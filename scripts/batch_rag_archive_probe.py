"""Look up unresolved exact forms and conservative alternates in cached open archives."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from align_senses import pos_options
from batch_rag_retrieval import EvidenceRetriever, SLASH_ALTERNANTS
from export_semantic_coverage import coverage_rows
from external_records import atomic_output
from import_wiktextract import candidate_records as wiktionary_records
from import_wordnet import candidate_records as wordnet_records
from review_common import normalized_lemma, normalized_pos, write_jsonl


MISS = "no_exact_open_candidate_pending_review"
DEFAULT_ARCHIVES = {
    "oewn": Path("data/external/english-wordnet-2025.xml.gz"),
    "kaikki": Path("data/external/raw-wiktextract-data.jsonl.gz"),
}


def lookup_forms(target, source_aliases):
    """Generate lookups while preserving how each alternate was proposed."""
    lemma = target["normalized"]
    yield lemma, "source_spelling"
    if "-" in lemma:
        yield lemma.replace("-", ""), "hyphenation_probe"
        yield lemma.replace("-", " "), "hyphenation_probe"
    if match := SLASH_ALTERNANTS.fullmatch(lemma):
        for alternate in match["alternants"].strip("()").split("/"):
            yield f"{match['prefix']} {alternate}", "printed_alternant_probe"
    target_pos = set(pos_options(target.get("part_of_speech")))
    for alternate, positions, word_id, proof in source_aliases:
        if word_id and word_id != target["word_id"]:
            continue
        if word_id is None and target.get("homonym_key"):
            continue
        if target_pos and positions and not target_pos.intersection(positions):
            continue
        yield alternate, f"documented_{proof['relation_type'].casefold()}"


def probe(db, source, archive, output_dir):
    misses = {row["occurrence_id"] for row in coverage_rows(db, "anki") if row["meaning_evidence_state"] == MISS}
    retriever = EvidenceRetriever(db)
    queries = defaultdict(dict)
    for target in retriever.targets():
        identifier = target["occurrence_id"]
        if identifier not in misses:
            continue
        for alternate, basis in lookup_forms(target, retriever.aliases.get(target["normalized"], ())):
            if not alternate.strip():
                continue
            lemma = normalized_lemma(alternate)
            if identifier in queries[lemma]:
                queries[lemma][identifier][1].add(basis)
            else:
                queries[lemma][identifier] = (target, {basis})

    source_record = retriever.sources[source]
    stats = {}
    stream = (
        wordnet_records(archive, set(queries), expansion=False) if source == "oewn"
        else wiktionary_records(archive, set(queries), source_record["version"], stats, fast_language_filter=True)
    )
    matched = defaultdict(set)
    counts = Counter()

    def records():
        for candidate in stream:
            if candidate["kind"] != "sense_candidate" or not candidate.get("definition"):
                continue
            lemma = normalized_lemma(candidate["headword"])
            part = normalized_pos(candidate.get("part_of_speech"))
            imported = db.execute("""
                SELECT candidate_id FROM external_candidates
                WHERE normalized_headword=? AND source_id=? AND kind='sense_candidate' AND source_record_id=?
            """, (lemma, source, candidate["source_record_id"])).fetchone()
            for identifier, (target, bases) in queries.get(lemma, {}).items():
                positions = pos_options(target.get("part_of_speech"))
                kind = "known" if imported else "new"
                if positions and part not in positions:
                    counts[f"{kind}_incompatible_pos"] += 1
                    continue
                scope = "exact" if "source_spelling" in bases else "alternate"
                status = f"{kind}_{scope}"
                counts[status] += 1
                matched[status].add(identifier)
                yield {
                    "occurrence_id": identifier,
                    "headword": target["headword"],
                    "matched_form": candidate["headword"],
                    "lookup_basis": sorted(bases),
                    "part_of_speech_match": "compatible" if positions else "unspecified_source_pos",
                    "existing_candidate_id": imported[0] if imported else None,
                    "grade": "D",
                    "review_status": "pending_sense_and_form_alignment",
                    "record": candidate,
                }

    count = write_jsonl(output_dir / f"{source}.archive_candidates.jsonl", records())
    report = {
        "source_id": source, "source_version": source_record["version"], "archive": archive.name,
        "source_occurrences": len(misses), "query_spelling_count": len(queries),
        "candidate_observation_count": count, "observation_counts": dict(counts),
        "distinct_occurrence_counts": {key: len(ids) for key, ids in matched.items()},
    }
    if stats.get("inspected_lines") is not None:
        report["inspected_lines"] = stats["inspected_lines"]
    with atomic_output(output_dir / f"{source}.archive_summary.json") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--source", choices=DEFAULT_ARCHIVES, required=True)
    parser.add_argument("--archive", type=Path, help="Pinned archive for the selected source")
    parser.add_argument("--output", type=Path, default=Path("data/intermediate/batch_rag/archive"))
    args = parser.parse_args()
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        report = probe(db, args.source, args.archive or DEFAULT_ARCHIVES[args.source], args.output)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
