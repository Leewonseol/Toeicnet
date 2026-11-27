"""Shared validation for lexical review records and auditable JSONL output."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata
from urllib.parse import urlparse


DEFINITION_SOURCES = {
    "cambridge": "dictionary.cambridge.org",
    "oxford": "oxfordlearnersdictionaries.com",
    "longman": "ldoceonline.com",
    "collins": "collinsdictionary.com",
    "britannica": "britannica.com",
}
STATUSES = frozenset({
    "cross_verified", "source_attested", "corpus_attested", "inferred",
    "disputed", "unverified", "unavailable", "not_applicable",
})
KOREAN_STATUSES = frozenset({
    "verified", "context_dependent", "partial_equivalent", "uncertain",
    "no_exact_equivalent", "unverified",
})
REVIEWED_KOREAN_METHODS = frozenset({
    "bilingual_dictionary", "korean_usage", "bilingual_semantic_review",
})
POS_ALIASES = {
    "n": "noun", "명": "noun", "명사": "noun",
    "v": "verb", "동": "verb", "동사": "verb",
    "vi": "verb", "vt": "verb", "자동사": "verb", "타동사": "verb",
    "adj": "adjective", "형": "adjective", "형용사": "adjective",
    "adv": "adverb", "부": "adverb", "부사": "adverb",
    "prep": "preposition", "전": "preposition", "전치사": "preposition",
    "conj": "conjunction", "접": "conjunction", "접속사": "conjunction",
    "pron": "pronoun", "대명사": "pronoun",
    "det": "determiner", "한정사": "determiner",
    "interj": "interjection", "intj": "interjection", "감탄사": "interjection",
}


def object_field(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def text_field(record, name, *, optional=False):
    value = record.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def enum_field(record, name, allowed):
    value = text_field(record, name)
    if value not in allowed:
        raise ValueError(f"{name} {value!r} must be one of {', '.join(sorted(allowed))}")
    return value


def date_field(record, name="verification_date"):
    value = text_field(record, name)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)")
    date.fromisoformat(value)
    return value


def normalized_lemma(headword):
    text = unicodedata.normalize("NFKC", headword).replace("’", "'")
    return " ".join(text.split()).casefold()


def normalized_pos(value):
    if not isinstance(value, str):
        return None
    pos = value.strip().strip(".").casefold()
    return POS_ALIASES.get(pos, pos) if pos and pos not in {"unknown", "unspecified"} else None


def reviewed_pos(record):
    value = normalized_pos(text_field(record, "part_of_speech"))
    if not value:
        raise ValueError("reviewed sense requires a known part_of_speech")
    return value


def jsonl_records(paths):
    for path in paths:
        with Path(path).open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                location = f"{path}:{line_number}"
                try:
                    record = object_field(json.loads(line), "record")
                except ValueError as error:
                    raise ValueError(f"{location}: {error}") from error
                yield location, record


def at_location(location, handler, *args):
    try:
        return handler(*args)
    except ValueError as error:
        raise ValueError(f"{location}: {error}") from error


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", encoding="utf-8",
            newline="\n", mode="w", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            count = 0
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                count += 1
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return count


def load_catalog(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    try:
        catalog = json.loads(content)
    except json.JSONDecodeError:
        import yaml
        catalog = yaml.safe_load(content)
    return object_field(object_field(catalog, "catalog").get("sources"), "sources")


def checked_evidence(record, field, catalog, *, sense_key=None):
    items = record.get(field, [])
    if not isinstance(items, list):
        raise ValueError(f"{field} must be a list")
    evidence = []
    seen = set()
    for item in items:
        item = dict(object_field(item, field))
        source_id = text_field(item, "source_id")
        if source_id not in catalog:
            raise ValueError(f"{field}: source_id {source_id!r} is absent from the catalog")
        source_group = text_field(catalog[source_id], "independence_group")
        item["independence_group"] = source_group
        item["source_record_id"] = text_field(item, "source_record_id")
        item["extraction_method"] = text_field(item, "extraction_method")
        item["verification_date"] = date_field(item)
        source_type = catalog[source_id].get("source_type")
        local = source_type == "primary_material" and item.get("url") is None
        url = urlparse(text_field(item, "url")) if not local else None
        if url is not None and (
            url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password
        ):
            raise ValueError(f"{field}: expected a public HTTP(S) evidence URL")
        approved_host = DEFINITION_SOURCES.get(source_id)
        if approved_host and (url is None or url.hostname.removeprefix("www.") != approved_host):
            raise ValueError(f"{field}: {source_id} evidence must be hosted at {approved_host}")
        allowed_hosts = catalog[source_id].get("allowed_hosts", [])
        if url is not None and allowed_hosts and url.hostname not in allowed_hosts:
            raise ValueError(f"{field}: {url.hostname!r} is not a catalog host for {source_id}")
        item["url"] = url.geturl() if url is not None else None
        if sense_key is not None:
            if item.get("matched_sense_key") != sense_key:
                raise ValueError(f"{field}: matched_sense_key must equal {sense_key!r}")
            enum_field(item, "sense_match", {"matched", "disagrees", "uncertain"})
            item["note"] = text_field(item, "note")
        identity = (source_id, item["source_record_id"], item["url"])
        if identity in seen:
            raise ValueError(f"{field}: duplicate evidence {identity!r}")
        seen.add(identity)
        evidence.append(item)
    return evidence


def checked_sense_identity(record):
    fields = ("headword", "sense_key")
    item = {field: text_field(record, field) for field in fields}
    item["part_of_speech"] = reviewed_pos(record)
    item["homonym_key"] = text_field(record, "homonym_key", optional=True)
    return item


def sense_identity(record):
    item = checked_sense_identity(record)
    return (
        normalized_lemma(item["headword"]), item["part_of_speech"],
        item["homonym_key"], item["sense_key"],
    )


def lexicon_group(evidence):
    return {
        entry["independence_group"]
        for entry in evidence
        if entry["source_id"] in DEFINITION_SOURCES and entry["sense_match"] == "matched"
    }


def checked_english(record, catalog):
    result = checked_sense_identity(record)
    status = enum_field(record, "status", STATUSES)
    definition = text_field(record, "english_definition", optional=True)
    evidence = checked_evidence(record, "definition_evidence", catalog, sense_key=result["sense_key"])
    matching = [item for item in evidence if item["sense_match"] == "matched"]
    origin = text_field(record, "definition_origin", optional=True)
    if origin is not None and origin not in {"paraphrase", "open_source"}:
        raise ValueError("definition_origin must be paraphrase or open_source")
    if status == "corpus_attested":
        raise ValueError("corpus_attested is reserved for usage observations")
    if status in {"cross_verified", "source_attested"} and (not definition or not matching):
        raise ValueError(f"{status} requires a definition and matching sense evidence")
    if status == "cross_verified":
        if len(lexicon_group(evidence)) < 2:
            raise ValueError("cross_verified requires two independent learner dictionaries for the sense")
        if any(item["sense_match"] == "disagrees" for item in evidence):
            raise ValueError("cross_verified conflicts with an unresolved dictionary disagreement")
    if status == "disputed":
        if len({item["independence_group"] for item in evidence}) < 2 or not any(
            item["sense_match"] == "disagrees" for item in evidence
        ):
            raise ValueError("disputed requires independently sourced sense evidence and disagreement")
    if definition and (status == "cross_verified" or any(
        item["source_id"] in DEFINITION_SOURCES for item in evidence
    )) and origin != "paraphrase":
        raise ValueError("learner-dictionary-based definitions must be recorded as paraphrases")
    if status in {"unavailable", "not_applicable"} and definition:
        raise ValueError(f"{status} cannot carry a definition")
    result.update(
        kind="sense", status=status, english_definition=definition, definition_origin=origin,
        definition_evidence=evidence, verification_date=date_field(record),
    )
    occurrences = record.get("occurrences", [])
    if not isinstance(occurrences, list):
        raise ValueError("occurrences must be a list")
    result["occurrences"] = [
        {
            "source_id": text_field(object_field(anchor, "occurrence"), "source_id"),
            "source_record_id": text_field(anchor, "source_record_id"),
        }
        for anchor in occurrences
    ]
    occurrence_ids = {(item["source_id"], item["source_record_id"]) for item in result["occurrences"]}
    if len(occurrence_ids) != len(occurrences):
        raise ValueError("occurrences must not contain duplicate source positions")
    if "alignment_evidence" in record:
        result["alignment_evidence"] = checked_evidence(
            record, "alignment_evidence", catalog, sense_key=result["sense_key"],
        )
        for item in result["alignment_evidence"]:
            text_field(item, "external_sense_id")
    if "original_korean_meaning" in record:
        result["original_korean_meaning"] = text_field(record, "original_korean_meaning", optional=True)
    return result


def checked_korean(record, catalog):
    result = checked_english(record, catalog)
    status = record.get("korean_status", "unverified")
    if status not in KOREAN_STATUSES:
        raise ValueError("unknown korean_status")
    translation = text_field(record, "verified_korean_meaning", optional=True)
    reason = text_field(record, "translation_uncertainty_reason", optional=True)
    evidence = checked_evidence(record, "korean_evidence", catalog, sense_key=result["sense_key"])
    if status == "verified" and not translation:
        raise ValueError("verified Korean translation requires verified_korean_meaning")
    if status != "verified" and translation is not None:
        raise ValueError("store unverified or uncertain Korean meanings outside verified_korean_meaning")
    if status != "unverified":
        if not any(
            item.get("assessment_kind") in REVIEWED_KOREAN_METHODS
            and item["sense_match"] == "matched"
            for item in evidence
        ):
            raise ValueError("Korean status requires an explicit bilingual or Korean-usage assessment")
        if status != "verified" and not reason:
            raise ValueError("qualified Korean status requires translation_uncertainty_reason")
    result.update(
        korean_status=status, verified_korean_meaning=translation, korean_evidence=evidence,
        translation_uncertainty_reason=reason,
        preferred_display_language="ko+en" if (
            status == "verified" and result["status"] == "cross_verified"
        ) else "en",
    )
    return result


def review_cli(handler, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input", type=Path, nargs="+", help="Reviewed sense JSONL files")
    parser.add_argument("--catalog", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalog = load_catalog(args.catalog)
        seen = set()

        def records():
            for location, original in jsonl_records(args.input):
                if original.get("kind") != "sense":
                    raise ValueError(f"{location}: expected a reviewed sense record")
                record = at_location(location, handler, original, catalog)
                identity = sense_identity(record)
                if identity in seen:
                    raise ValueError(f"{location}: duplicate reviewed sense {identity!r}")
                seen.add(identity)
                yield record

        count = write_jsonl(args.output, records())
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Wrote {count} reviewed senses to {args.output}")
