"""Stream pinned Wiktextract JSONL and retain source-backed English candidate records."""

from __future__ import annotations

import argparse
from collections import Counter
from itertools import islice
import json
from pathlib import Path
import re
from typing import Iterator
from urllib.parse import quote

from external_records import atomic_output, normalize_headword, normalize_pos, open_data, targets, write_jsonl

SEMANTIC_LINKS = {
    "synonyms": "SYNONYM_OF",
    "antonyms": "ANTONYM_OF",
    "hypernyms": "HYPONYM_OF",
    "hyponyms": "HYPERNYM_OF",
    "meronyms": "HAS_MERONYM",
    "holonyms": "MERONYM_OF",
    "related": "RELATED_TO",
    "derived": "HAS_DERIVED_TERM_CANDIDATE",
}
ETYM_TEMPLATES = {
    "inh": "HAS_HISTORICAL_FORM",
    "der": "ETYMOLOGICALLY_DERIVED_FROM",
    "bor": "BORROWED_FROM",
    "bor+": "BORROWED_FROM",
    "lbor": "BORROWED_FROM",
    "slbor": "BORROWED_FROM",
    "ubor": "BORROWED_FROM",
    "obor": "BORROWED_FROM",
    "cog": "COGNATE_WITH",
    "root": "HAS_ETYMOLOGICAL_ROOT",
}
COMPONENT_TEMPLATES = {
    "affix", "af", "prefix", "pre", "suffix", "suf", "compound", "com", "surface analysis", "surf",
}
INFLECTION = {
    "plural", "comparative", "superlative", "past", "present", "participle", "gerund",
    "past-participle", "present-participle", "third-person", "past-tense",
}
VARIANT = {"alternative", "obsolete", "alternative-spelling", "pronunciation-spelling"}
REGISTERS = {
    "formal", "informal", "colloquial", "slang", "technical", "archaic", "obsolete", "dated",
    "literary", "offensive", "vulgar", "polite", "business", "law", "legal", "academic",
}
ENGLISH_LANGUAGE = re.compile(rb'"lang_code"\s*:\s*"en"')


def records_from_entry(entry: dict, version: str, line_number: int) -> Iterator[dict]:
    word = entry["word"]
    pos = entry["pos"]
    locator = f"line:{line_number}"
    base = {
        "headword": word, "part_of_speech": normalize_pos(pos), "source_id": "kaikki",
        "source_record_id": locator, "url": f"https://en.wiktionary.org/wiki/{quote(word.replace(' ', '_'), safe='')}#English",
        "version": version, "extraction_method": "wiktextract_jsonl", "verification_status": "source_attested",
        "etymology_number": entry.get("etymology_number"),
    }

    def relation(source: dict, kind: str, **fields) -> dict:
        return dict(source, kind="relation_candidate", relation_type=kind, **fields)

    def usage(source: dict, kind: str, expression: str, **details) -> dict:
        return dict(source, kind="usage_candidate", usage_type=kind, expression=expression, details=details)

    def linkage(source: dict, data: dict, scope: str) -> Iterator[dict]:
        for field, rel_type in SEMANTIC_LINKS.items():
            for item in data.get(field, []):
                if item.get("word"):
                    details = {key: item[key] for key in ("sense", "tags", "source", "alt", "topics") if key in item}
                    details.update(scope=scope, target_alignment="unreviewed")
                    yield relation(source, rel_type, target_headword=item["word"], details=details)

    for index, sense in enumerate(entry.get("senses", []), 1):
        sense_locator = f"{locator}:sense:{index}"
        local = dict(base, source_record_id=sense_locator, external_sense_id=f"kaikki:{version}:{sense_locator}")
        senses = sense.get("glosses", [])
        tags = sense.get("tags", [])
        yield dict(local, kind="sense_candidate", definition=senses[-1] if senses else None,
                   definitions=senses, tags=tags, wiktionary_sense_ids=sense.get("senseid", []),
                   topics=sense.get("topics", []), qualifiers=sense.get("qualifier"))
        yield from linkage(local, sense, "sense")
        if "form-of" in tags and set(tags) & INFLECTION:
            for item in sense.get("form_of", []):
                yield relation(local, "INFLECTION_OF", target_headword=item["word"],
                               target_part_of_speech=normalize_pos(pos), details={"tags": tags})
        for item in sense.get("alt_of", []):
            yield relation(local, "VARIANT_OF", target_headword=item["word"],
                           target_part_of_speech=normalize_pos(pos), details={"tags": tags})
        if "idiomatic" in tags and (" " in word or "-" in word):
            yield usage(local, "IDIOM", word, tags=tags)
        if "phrasal-verb" in tags:
            yield usage(local, "PHRASAL_VERB", word, tags=tags)
        for grammar_type, allowed in (
            ("COUNTABILITY", {"countable", "uncountable"}),
            ("TRANSITIVITY", {"transitive", "intransitive", "ambitransitive", "ditransitive"}),
            ("REGISTER", REGISTERS),
        ):
            for tag in sorted(allowed.intersection(tags)):
                yield usage(local, grammar_type, tag, tags=tags)

    yield from linkage(base, entry, "entry")
    for form in entry.get("forms", []):
        text, tags = form.get("form"), form.get("tags", [])
        if not text or text in {"-", "—", "?"} or "table-tags" in tags:
            continue
        if set(tags) & VARIANT:
            relation_type = "HAS_VARIANT_FORM"
        elif set(tags) & INFLECTION:
            relation_type = "HAS_INFLECTION"
        else:
            continue
        yield relation(base, relation_type, target_headword=text, details={"tags": tags, "source": form.get("source")})

    if entry.get("etymology_text"):
        yield relation(base, "ETYMOLOGY_NARRATIVE", details={"text": entry["etymology_text"]})
    seen: set[tuple[str, str]] = set()
    for template in entry.get("etymology_templates", []):
        name, args = template.get("name"), template.get("args", {})
        template_key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if template_key in seen:
            continue
        seen.add(template_key)
        details = {"template": name, "args": args, "scope": "wiktionary_etymology_section"}
        if name in COMPONENT_TEMPLATES:
            yield relation(base, "MORPHOLOGICAL_TEMPLATE", details=details)
        elif name in ETYM_TEMPLATES:
            language, form = (args.get("1"), args.get("2")) if name == "cog" else (args.get("2"), args.get("3"))
            yield relation(base, ETYM_TEMPLATES[name],
                           target_headword=form if form not in {None, "", "-"} else None,
                           details=dict(details, target_language=language,
                                        gloss=args.get("t") or args.get("5"),
                                        route_alignment="unreviewed"))


def korean_translation_candidates(entry, version, line_number):
    """Preserve the translation group's own gloss and Korean form for later alignment."""
    word = entry["word"]
    page = quote(word.replace(" ", "_"), safe="")
    for index, translation in enumerate(entry.get("translations", []), 1):
        korean = translation.get("word")
        if (translation.get("code") or translation.get("lang_code")) != "ko" or not korean:
            continue
        yield {
            "kind": "relation_candidate", "headword": word,
            "part_of_speech": normalize_pos(entry["pos"]), "source_id": "kaikki",
            "source_record_id": f"line:{line_number}:translation:{index}",
            "url": f"https://en.wiktionary.org/wiki/{page}#English",
            "version": version, "extraction_method": "wiktextract_translation_group",
            "verification_status": "source_attested", "relation_type": "KOREAN_TRANSLATION_CANDIDATE",
            "target_headword": korean, "target_language": "ko",
            "details": {
                "source_sense_label": translation.get("sense"),
                "tags": translation.get("tags", []), "alternate": translation.get("alt"),
                "romanization": translation.get("roman"),
                "sense_alignment": "unreviewed", "korean_translation_status": "unverified",
            },
        }


def candidate_records(
    path: Path, wanted: set[str], version: str, stats: dict, *,
    max_lines: int | None = None, fast_language_filter: bool = False,
    korean_translations_only: bool = False,
) -> Iterator[dict]:
    entry_keys = Counter()
    sense_keys = Counter()
    matched = set()
    if not wanted:
        stats.update(targets=0, matched_targets=0, entries=0, inspected_lines=0, test_line_limit=max_lines,
                     selected_entry_keys={}, selected_sense_keys={})
        return
    line_number = 0
    parsed_lines = 0
    with open_data(path, "rb") as handle:
        for line_number, line in enumerate(islice(handle, max_lines), 1):
            if not line.strip():
                continue
            # A valid UTF-8 JSON English entry contains the language marker. Parse
            # any line with escapes that could also encode the ASCII key or value.
            if fast_language_filter and not ENGLISH_LANGUAGE.search(line) and b"\\u" not in line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid Wiktextract JSONL") from error
            parsed_lines += 1
            if item.get("lang_code") != "en" or not item.get("word") or not item.get("pos"):
                continue
            normalized = normalize_headword(item["word"])
            if normalized not in wanted:
                continue
            matched.add(normalized)
            entry_keys.update(item.keys())
            for sense in item.get("senses", []):
                sense_keys.update(sense.keys())
            if korean_translations_only:
                yield from korean_translation_candidates(item, version, line_number)
            else:
                yield from records_from_entry(item, version, line_number)
    stats.update(targets=len(wanted), matched_targets=len(matched), entries=entry_keys["word"],
                 inspected_lines=line_number, parsed_lines=parsed_lines, test_line_limit=max_lines,
                 fast_language_filter=fast_language_filter,
                 selected_entry_keys=dict(sorted(entry_keys.items())),
                 selected_sense_keys=dict(sorted(sense_keys.items())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Wiktextract JSONL or JSONL.GZ")
    parser.add_argument("--targets", action="append", required=True, type=Path, help="JSONL containing headword")
    parser.add_argument("--version", required=True, help="Pinned extraction version from the source catalog")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema-report", type=Path, help="Observed key counts in selected source entries")
    parser.add_argument("--max-lines", type=int, help="Limit for adapter QA only")
    parser.add_argument("--fast-language-filter", action="store_true",
                        help="Prefilter valid UTF-8 JSONL by language before full selected-record validation")
    parser.add_argument("--korean-translations-only", action="store_true",
                        help="Emit Korean translation groups as unaligned review candidates")
    args = parser.parse_args()
    if args.max_lines is not None and args.max_lines < 1:
        parser.error("--max-lines must be >=1 if provided")
    wanted = targets(args.targets)
    stats: dict = {}
    count = write_jsonl(args.output, candidate_records(args.input, wanted, args.version, stats,
                                                       max_lines=args.max_lines,
                                                       fast_language_filter=args.fast_language_filter,
                                                       korean_translations_only=args.korean_translations_only))
    if args.schema_report:
        with atomic_output(args.schema_report) as handle:
            handle.write(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    print(f"Wiktextract: {stats['matched_targets']}/{len(wanted)} target spellings, {count} candidate records, "
          f"{stats['inspected_lines']} dump lines inspected")


if __name__ == "__main__":
    main()
