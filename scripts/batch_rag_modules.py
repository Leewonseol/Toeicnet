"""Retrieve module evidence for workbook occurrences without promoting unaligned claims."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from align_senses import pos_options
from analysis_review import RELATIONS
from review_common import normalized_pos, write_jsonl
from study_open_evidence import OFFICIAL_SOURCES, CORPUS_TYPES, valid_context

MODULES = tuple(RELATIONS)
MORPHOLOGY = {
    "HAS_INFLECTION", "INFLECTION_OF", "HAS_VARIANT_FORM", "VARIANT_OF",
    "HAS_DERIVED_TERM_CANDIDATE", "DERIVATIONALLY_RELATED_TO", "PARTICIPLE_OF",
    "MORPHOLOGICAL_TEMPLATE",
}
ETYMOLOGY = {
    "BORROWED_FROM", "COGNATE_WITH", "ETYMOLOGICALLY_DERIVED_FROM",
    "ETYMOLOGY_NARRATIVE", "HAS_ETYMOLOGICAL_ROOT", "HAS_HISTORICAL_FORM",
}
SEMANTICS = {
    "ANTONYM_OF", "BELONGS_TO_SYNSET", "HAS_MERONYM", "HYPERNYM_OF",
    "HYPONYM_OF", "MERONYM_OF", "PERTAINYM_OF", "RELATED_TO", "SIMILAR_TO", "SYNONYM_OF",
}
DICTIONARY_RELATIONS = MORPHOLOGY | ETYMOLOGY | SEMANTICS
DICTIONARY_USAGE = {"COUNTABILITY", "IDIOM", "PHRASAL_VERB", "REGISTER", "TRANSITIVITY"}
REVIEW_MODULE = {
    "morphology": "Check grammatical function and direction against the modern base or form. A derivation linkage or etymology template alone is not a modern decomposition.",
    "etymology": "Check the historical form, language and borrowing route against the relevant historical source and homonym.",
    "lexical_semantics": "Align both word senses and compare contextual substitution. A synset or shared theme alone does not establish it.",
    "lexical_usage": "Read the context and align the intended sense before deciding collocation, grammar or register. A TOEIC sample has its own document scope.",
}
CANDIDATE_RANK = {
    "official_sample_observation": 1,
    "corpus_context_observation": 2,
    "open_dictionary_usage": 3,
    "open_morphology": 3,
    "open_historical_evidence": 3,
    "open_semantic_relation": 3,
    "native_synset_membership": 4,
}
ATTESTED_STATUSES = {"cross_verified", "source_attested", "corpus_attested"}


def occurrence_index(connection):
    result = {}
    by_lemma = defaultdict(list)
    by_word = defaultdict(list)
    for oid, wid, lemma, part_of_speech, source_id, locator in connection.execute("""
        SELECT o.occurrence_id, o.word_id, w.normalized, o.part_of_speech, o.source_id, o.source_record_id
        FROM occurrences o JOIN words w USING (word_id)
        ORDER BY o.occurrence_id
    """):
        result[oid] = (frozenset(pos_options(part_of_speech)), source_id, locator)
        by_lemma[lemma].append(oid)
        by_word[wid].append(oid)
    return result, by_lemma, by_word


def registered_evidence(connection, occurrences, by_word):
    by_sense = defaultdict(list)
    for sense_id, occurrence_id in connection.execute("SELECT sense_id, occurrence_id FROM sense_occurrences"):
        by_sense[sense_id].append(occurrence_id)

    provenance = defaultdict(list)
    for eid, edge_id, sid, locator, version, url, method, date, group, properties in connection.execute("""
        SELECT v.evidence_id, v.object_id, v.source_id, v.source_record_id,
               COALESCE(v.version, s.version), v.url, v.extraction_method,
               v.verification_date, s.independence_group, v.properties_json
        FROM evidence v JOIN sources s USING (source_id)
        WHERE v.object_type='edge'
        ORDER BY v.object_id, v.source_id, v.evidence_id
    """):
        metadata = json.loads(properties)
        provenance[edge_id].append({
            "evidence_id": eid, "source_id": sid, "source_record_id": locator,
            "version": version, "url": url, "extraction_method": method,
            "verification_date": date, "independence_group": group,
            "relation_match": metadata.get("relation_match"),
            "item_locator": metadata.get("item_locator"),
        })

    selected = defaultdict(list)
    for row in connection.execute("""
        SELECT e.edge_id, e.relation_type, e.status, json_extract(e.properties_json,'$.module'),
               a.word_id, a.sense_id, a.label, b.word_id, b.sense_id, b.label
        FROM edges e JOIN nodes a ON a.node_id=e.from_node_id JOIN nodes b ON b.node_id=e.to_node_id
        WHERE e.relation_type <> 'HAS_SENSE' ORDER BY e.edge_id
    """):
        edge_id, relation, status, module, from_word, from_sense, from_label, to_word, to_sense, to_label = row
        if module not in RELATIONS or relation not in RELATIONS[module]:
            continue
        evidence = provenance[edge_id]
        matched = [reference for reference in evidence if reference["relation_match"] == "matched"]
        groups = {reference["independence_group"] for reference in matched if reference["independence_group"]}
        if status == "cross_verified" and len(groups) < 2:
            status = "unverified"
        elif status == "corpus_attested" and not any(reference["source_id"] == "oanc" for reference in matched):
            status = "unverified"
        elif status == "source_attested" and not matched:
            status = "unverified"
        theme = relation == "BELONGS_TO_THEME"
        item = {
            "evidence_kind": "registered_theme" if theme else "registered_relation",
            "edge_id": edge_id, "status": status, "relation_type": relation,
            "from_label": from_label, "to_label": to_label, "provenance": evidence,
        }
        paired = (
            (from_word, from_sense, "from"),
            (to_word, to_sense, "to"),
        )
        added = set()
        for word, sense, direction in paired:
            for oid in (by_sense[sense] if sense else by_word[word]):
                if oid in added:
                    continue
                if theme:
                    _, origin, locator = occurrences[oid]
                    if not any(ref["source_id"] == origin and ref["source_record_id"] == locator for ref in matched):
                        continue
                selected[oid, module].append({
                    **item, "scope": "occurrence_sense" if sense else "word",
                    "anchor_sense_id": sense, "direction": direction,
                })
                added.add(oid)
    return selected


def source_candidate(source, payload, anchor_lemma):
    relation = payload.get("relation_type")
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        return None
    if source in {"oewn", "kaikki"} and relation in DICTIONARY_RELATIONS:
        if relation in MORPHOLOGY:
            module, kind = "morphology", "open_morphology"
        elif relation in ETYMOLOGY and source == "kaikki":
            module, kind = "etymology", "open_historical_evidence"
        elif relation in SEMANTICS:
            module, kind = "lexical_semantics", "open_semantic_relation"
            if source == "oewn" and relation in {"BELONGS_TO_SYNSET", "SYNONYM_OF"}:
                if not (payload.get("external_sense_id") and payload.get("target_synset_id")):
                    return None
                if relation == "SYNONYM_OF" and not payload.get("target_external_sense_id"):
                    return None
                kind = "native_synset_membership"
        else:
            return None
        return module, kind, relation, {
            "target_headword": payload.get("target_headword"),
            "target_external_sense_id": payload.get("target_external_sense_id"),
            "external_sense_id": payload.get("external_sense_id"),
            "synset_id": payload.get("synset_id"),
            "target_synset_id": payload.get("target_synset_id"),
            "etymology_number": payload.get("etymology_number"),
            "origin_language": details.get("target_language"),
            "template": details.get("template"),
            "tags": details.get("tags"),
        }

    usage = payload.get("usage_type")
    if source == "kaikki" and usage in DICTIONARY_USAGE and payload.get("external_sense_id"):
        return "lexical_usage", "open_dictionary_usage", usage, {
            "expression": payload.get("expression"),
            "external_sense_id": payload["external_sense_id"],
            "tags": details.get("tags"),
        }
    if source in OFFICIAL_SOURCES and usage == "OFFICIAL_SAMPLE_ATTESTATION":
        locator = details.get("item_locator")
        if (
            payload.get("verification_status") == "source_attested"
            and details.get("official_material_type") == "official_sample"
            and details.get("toeic_evidence") is True
            and isinstance(locator, str) and locator.strip()
        ):
            return "lexical_usage", "official_sample_observation", usage, {
                "item_locator": locator,
                "section_role": details.get("section_role"),
                "expression": payload.get("expression"),
                "official_material_type": "official_sample",
            }
    if source == "oanc" and usage in CORPUS_TYPES and payload.get("verification_status") == "corpus_attested":
        frequency = details.get("frequency")
        if type(frequency) is not int or frequency < 1:
            return None
        attestations = details.get("attestations")
        if not isinstance(attestations, list):
            return None
        observed = next((record for record in attestations if valid_context(record)), None)
        if observed:
            return "lexical_usage", "corpus_context_observation", usage, {
                "expression": payload.get("expression") or anchor_lemma,
                "frequency": frequency,
                "corpus_document": observed["document"],
                "start": observed["start"], "end": observed["end"],
                "analysis_scope": details.get("analysis_scope"),
                "test_document_limit": details.get("test_document_limit"),
            }
    return None


def candidate_order(item):
    return (
        CANDIDATE_RANK[item["evidence_kind"]],
        item["pos_match"] != "headword_and_pos",
        -(item.get("frequency") or 0),
        item["source_id"], item["relation_type"], item["candidate_id"],
    )


def source_candidates(connection, occurrences, by_lemma):
    counts = defaultdict(Counter)
    candidates = defaultdict(dict)
    seen_other_pos = defaultdict(set)
    for cid, lemma, source, locator, version, group, raw in connection.execute("""
        SELECT c.candidate_id, c.normalized_headword, c.source_id, c.source_record_id,
               s.version, s.independence_group, c.payload_json
        FROM external_candidates c JOIN sources s USING (source_id)
        WHERE c.kind IN ('relation_candidate','usage_candidate')
          AND c.source_id IN ('oewn','kaikki','oanc','ets','toeic_kr')
    """):
        if lemma not in by_lemma:
            continue
        payload = json.loads(raw)
        selected = source_candidate(source, payload, lemma)
        if selected is None:
            continue
        module, kind, relation, fields = selected
        pos = normalized_pos(payload.get("part_of_speech"))
        for oid in by_lemma[lemma]:
            positions, _, _ = occurrences[oid]
            group_key = oid, module
            if positions and pos and pos not in positions:
                seen_other_pos[group_key].add(pos)
                continue
            counts[group_key][kind] += 1
            reference = {
                "evidence_kind": kind, "candidate_id": cid, "source_id": source,
                "source_record_id": locator, "version": payload.get("version") or version,
                "url": payload.get("url"), "independence_group": group,
                "extraction_method": payload.get("extraction_method"),
                "verification_date": payload.get("verification_date"),
                "recorded_source_status": payload.get("verification_status"),
                "relation_type": relation, "part_of_speech": pos,
                "pos_match": "headword_and_pos" if positions and pos else "headword_only",
                "workbook_alignment": "pending", **fields,
            }
            # Preserve a representative for each source, evidence type, and relation.
            slot = source, kind, relation
            prior = candidates[group_key].get(slot)
            if prior is None or candidate_order(reference) < candidate_order(prior):
                candidates[group_key][slot] = reference
    return counts, candidates, seen_other_pos


def module_decision(module, registered, counts, candidates, other_pos, limit):
    conflicts = [item for item in registered if item["status"] == "disputed"]
    confirmed = [
        item for item in registered
        if item["evidence_kind"] == "registered_relation" and item["status"] in ATTESTED_STATUSES
    ]
    pending = [item for item in registered if item["status"] not in ATTESTED_STATUSES | {"disputed"}]
    themes = [item for item in registered if item["evidence_kind"] == "registered_theme" and item["status"] in ATTESTED_STATUSES]
    observed = sum(counts[kind] for kind in ("corpus_context_observation", "official_sample_observation"))
    if conflicts:
        classification = "disagreement_review"
    elif confirmed:
        classification = "registered_relation_attested"
    elif observed:
        classification = "source_context_attested"
    elif candidates or pending:
        classification = "candidate_review"
    elif themes:
        classification = "theme_attested"
    elif other_pos:
        classification = "part_of_speech_review"
    else:
        classification = "needs_evidence"

    # Keep at least one open reference alongside registered records when room permits.
    selected = [*conflicts, *confirmed, *pending, *themes]
    ordered = sorted(candidates.values(), key=candidate_order)
    reviewed_limit = limit - 1 if ordered and selected and limit > 1 else limit
    evidence = selected[:reviewed_limit]
    evidence.extend(ordered[:limit - len(evidence)])
    return {
        "classification": classification,
        "next_review": REVIEW_MODULE[module],
        "registered_counts": {
            "attested_relations": len(confirmed), "disputed_relations": len(conflicts),
            "pending_relations": len(pending), "attested_themes": len(themes),
        },
        "source_candidate_counts": dict(sorted(counts.items())),
        "other_candidate_parts_of_speech": sorted(other_pos),
        "evidence": evidence,
    }


def load_module_evidence(connection, *, max_evidence=6):
    """Return four provenance-bearing module assessments for every intake occurrence."""
    if type(max_evidence) is not int or max_evidence < 1:
        raise ValueError("max_evidence must be a positive integer")
    occurrences, by_lemma, by_word = occurrence_index(connection)
    registered = registered_evidence(connection, occurrences, by_word)
    counts, candidates, other_pos = source_candidates(connection, occurrences, by_lemma)
    return {
        oid: {
            module: module_decision(
                module, registered.get((oid, module), ()), counts.get((oid, module), Counter()),
                candidates.get((oid, module), {}), other_pos.get((oid, module), ()), max_evidence,
            )
            for module in MODULES
        }
        for oid in occurrences
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-evidence", default=6, type=int)
    args = parser.parse_args()
    if args.output.resolve() == args.database.resolve():
        parser.error("output must differ from the input database")
    if args.max_evidence < 1:
        parser.error("--max-evidence must be at least 1")
    with closing(sqlite3.connect(f"{args.database.resolve().as_uri()}?mode=ro", uri=True)) as db:
        assessments = load_module_evidence(db, max_evidence=args.max_evidence)
    count = write_jsonl(args.output, (
        {"occurrence_id": oid, "modules": result} for oid, result in assessments.items()
    ))
    print(f"Prepared four module assessments for {count} occurrences")


if __name__ == "__main__":
    main()
