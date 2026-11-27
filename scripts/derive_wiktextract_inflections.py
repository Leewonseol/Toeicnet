"""Connect source headwords using explicit reciprocal Wiktextract inflection records."""
import argparse
from collections import defaultdict
from pathlib import Path

from align_senses import references_by_lemma
from analysis_review import checked_relation
from review_common import date_field, jsonl_records, load_catalog, normalized_lemma, normalized_pos, write_jsonl

INFLECTION_FEATURES = frozenset({
    "plural", "singular", "past", "past-participle", "present-participle", "present",
    "third-person", "first-person", "second-person", "gerund", "comparative",
    "superlative", "participle", "preterite", "indicative", "subjunctive",
})


def supports_pos(occurrences, pos):
    return any(
        not occurrence["part_of_speech_options"] or pos in occurrence["part_of_speech_options"]
        for occurrence in occurrences
    )


def form_of_relations(input_paths, candidate_paths, catalog, date):
    vocabulary = references_by_lemma(input_paths)
    forward = defaultdict(list)
    reverse = defaultdict(list)
    for _, row in jsonl_records(candidate_paths):
        if row.get("source_id") != "kaikki" or row.get("kind") != "relation_candidate":
            continue
        relation = row.get("relation_type")
        if relation not in {"HAS_INFLECTION", "INFLECTION_OF"}:
            continue
        source = normalized_lemma(row["headword"])
        target = normalized_lemma(row.get("target_headword") or "")
        pos = normalized_pos(row.get("part_of_speech"))
        if not pos or source == target or source not in vocabulary or target not in vocabulary:
            continue
        if not supports_pos(vocabulary[source], pos) or not supports_pos(vocabulary[target], pos):
            continue
        if relation == "HAS_INFLECTION":
            forward[target, source, pos].append(row)
        elif normalized_pos(row.get("target_part_of_speech")) == pos:
            reverse[source, target, pos].append(row)

    pairs = defaultdict(dict)
    for form, base, pos in sorted(forward.keys() & reverse.keys()):
        attested = []
        features = set()
        for base_entry in forward[form, base, pos]:
            for inflected_entry in reverse[form, base, pos]:
                if base_entry.get("version") != inflected_entry.get("version"):
                    continue
                listed = set(base_entry.get("details", {}).get("tags", []))
                derived = set(inflected_entry.get("details", {}).get("tags", []))
                if "form-of" not in derived:
                    continue
                agreed_features = listed & derived & INFLECTION_FEATURES
                if agreed_features:
                    attested.extend((base_entry, inflected_entry))
                    features.update(agreed_features)
        if features:
            pairs[form, base][pos] = (features, attested)

    for (form, base), forms in sorted(pairs.items()):
        evidence = {}
        features_by_pos = {}
        for pos, (features, records) in forms.items():
            features_by_pos[pos] = sorted(features)
            for row in records:
                evidence[row["source_record_id"], row["url"]] = {
                    "source_id": "kaikki", "source_record_id": row["source_record_id"],
                    "url": row["url"], "version": row["version"],
                    "extraction_method": "reciprocal_wiktextract_inflection",
                    "verification_date": date, "relation_match": "matched",
                    "note": "같은 릴리스의 굴절형 목록과 form-of 표기를 대조했다.",
                    "native_relation": row["relation_type"],
                    "native_tags": row.get("details", {}).get("tags", []),
                }
        yield checked_relation({
            "kind": "relation", "module": "morphology", "relation_type": "INFLECTION_OF",
            "from": {"node_type": "WORD", "headword": vocabulary[form][0]["headword"]},
            "to": {"node_type": "WORD", "headword": vocabulary[base][0]["headword"]},
            "status": "source_attested", "verification_date": date,
            "attributes": {"features": features_by_pos, "scope": "english_form_only"},
            "evidence": list(evidence.values()),
        }, catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--candidates", nargs="+", type=Path, required=True)
    parser.add_argument("--catalog", default=Path("config/sources.yaml"), type=Path)
    parser.add_argument("--verification-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    date = date_field({"verification_date": args.verification_date})
    count = write_jsonl(args.output, form_of_relations(
        args.inputs, args.candidates, load_catalog(args.catalog), date,
    ))
    print(f"{count} source-attested form relations")


if __name__ == "__main__":
    main()
