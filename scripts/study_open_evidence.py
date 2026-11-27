"""Select compact, provenance-bearing previews from the external evidence view."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

DICTIONARY_SOURCES = ("oewn", "kaikki")
OFFICIAL_SOURCES = ("ets", "toeic_kr")
DEFINITION_LIMIT = 2
OLDER_USAGE_TAGS = frozenset({"archaic", "dated", "historical", "obsolete"})
RELATIONS = {
    ("oewn", "SYNONYM_OF"): "WordNet의 동일 Synset",
    ("kaikki", "HAS_HISTORICAL_FORM"): "Wiktionary 어원 항목의 역사적 형태",
    ("kaikki", "HAS_INFLECTION"): "Wiktionary의 활용형",
}
CORPUS_TYPES = {
    "PHRASE_ATTESTATION": "표현 출현",
    "FREQUENCY": "표제어·품사 태그 출현",
    "COLLIGATION": "인접 문법 패턴 후보",
    "COLLOCATION": "인접 어휘 결합 후보",
}


@dataclass
class ExternalPreview:
    counts: Counter = field(default_factory=Counter)
    definitions: dict = field(default_factory=lambda: defaultdict(list))
    relations: dict = field(default_factory=lambda: defaultdict(list))
    corpus: dict = field(default_factory=lambda: defaultdict(list))
    official: list = field(default_factory=list)


def keep_example(container, item, key, limit):
    container.append(item)
    container.sort(key=key)
    del container[limit:]


def record_order(item):
    return item["source_record_id"], item["candidate_id"]


def dictionary_order(item):
    return bool(OLDER_USAGE_TAGS.intersection(item["tags"])), *record_order(item)


def corpus_order(item):
    return (-item["frequency"], *record_order(item))


def valid_context(attestation):
    if not isinstance(attestation, dict):
        return False
    document = attestation.get("document")
    context = attestation.get("context")
    surface = attestation.get("surface")
    if not all(isinstance(value, str) and value for value in (document, context, surface)):
        return False
    start = attestation.get("start")
    end = attestation.get("end")
    offset = attestation.get("context_start")
    if not all(isinstance(value, int) for value in (start, end, offset)):
        return False
    return offset <= start < end and context[start - offset:end - offset] == surface


def matching_records(connection, core_sources):
    """Stream only preview-eligible records for primary learning words."""
    placeholders = ", ".join("?" for _ in core_sources)
    statement = f"""
        SELECT *
        FROM external_lexical_evidence e
        WHERE (
            (e.kind = 'sense_candidate' AND e.source_id IN ('oewn', 'kaikki'))
            OR (e.kind = 'relation_candidate' AND (
                (e.source_id = 'oewn' AND json_extract(e.payload_json, '$.relation_type') = 'SYNONYM_OF')
                OR (e.source_id = 'kaikki' AND json_extract(e.payload_json, '$.relation_type')
                    IN ('HAS_HISTORICAL_FORM', 'HAS_INFLECTION'))
            ))
            OR (e.kind = 'usage_candidate' AND e.source_id IN ('oanc', 'ets', 'toeic_kr'))
        )
        AND EXISTS (
            SELECT 1 FROM occurrences o
            WHERE o.word_id = e.word_id AND o.source_id IN ({placeholders})
        )
    """
    return connection.execute(statement, sorted(core_sources))


def load_open_evidence(connection, core_sources):
    previews = defaultdict(ExternalPreview)
    available = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE name = 'external_lexical_evidence' AND type = 'view'"
    ).fetchone()
    if not available:
        return previews
    for raw in matching_records(connection, core_sources):
        row = dict(raw)
        payload = json.loads(row.pop("payload_json"))
        if not isinstance(payload, dict):
            continue
        source_id = row["source_id"]
        source_version = payload.get("version") or row["source_version"]
        item = {
            **row,
            "version": source_version,
            "url": payload.get("url"),
            "part_of_speech": payload.get("part_of_speech"),
        }
        preview = previews[row["word_id"]]
        if row["kind"] == "sense_candidate":
            definition = payload.get("definition")
            if isinstance(definition, str) and definition.strip():
                preview.counts[source_id, "definition"] += 1
                tags = payload.get("tags")
                if not isinstance(tags, list):
                    tags = []
                keep_example(preview.definitions[source_id], {
                    **item, "definition": definition, "tags": tags,
                    "qualifiers": payload.get("qualifiers"),
                }, dictionary_order, DEFINITION_LIMIT)
            continue
        if row["kind"] == "relation_candidate":
            relation = (source_id, payload.get("relation_type"))
            target = payload.get("target_headword")
            if relation not in RELATIONS or not isinstance(target, str) or not target.strip():
                continue
            if relation == ("oewn", "SYNONYM_OF") and not (
                payload.get("external_sense_id") and payload.get("target_external_sense_id")
            ):
                continue
            preview.counts[source_id, "relation"] += 1
            keep_example(preview.relations[relation], {
                **item,
                "target": target,
                "external_sense_id": payload.get("external_sense_id"),
                "target_external_sense_id": payload.get("target_external_sense_id"),
                "details": payload.get("details", {}),
            }, record_order, 1)
            continue
        details = payload.get("details")
        expression = payload.get("expression")
        if not isinstance(details, dict) or not isinstance(expression, str) or not expression.strip():
            continue
        if source_id == "oanc":
            corpus_type = payload.get("usage_type")
            frequency = details.get("frequency")
            if (
                corpus_type not in CORPUS_TYPES or payload.get("verification_status") != "corpus_attested"
                or not isinstance(frequency, int) or frequency <= 0
            ):
                continue
            attestations = details.get("attestations")
            if not isinstance(attestations, list):
                continue
            example = next((example for example in attestations if valid_context(example)), None)
            if example is None:
                continue
            preview.counts[source_id, "usage"] += 1
            keep_example(preview.corpus[corpus_type], {
                **item, "expression": expression, "frequency": frequency, "attestation": example,
                "test_document_limit": details.get("test_document_limit"),
            }, corpus_order, 1)
        elif (
            source_id in OFFICIAL_SOURCES and details.get("toeic_evidence") is True
            and isinstance(details.get("item_locator"), str) and details["item_locator"].strip()
        ):
            preview.counts["toeic", "usage"] += 1
            keep_example(preview.official, {
                **item, "expression": expression, "item_locator": details["item_locator"],
            }, record_order, 2)
    return previews
