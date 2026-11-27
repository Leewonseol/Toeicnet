"""Report reviewed and pending meaning evidence for every source occurrence."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from align_senses import pos_options
from intake_common import write_csv, write_json
from review_common import normalized_lemma, normalized_pos, write_jsonl

FIELDS = (
    "occurrence_id", "source_id", "source_record_id", "day", "filename", "pdf_page",
    "headword", "part_of_speech", "original_korean_meaning", "reviewed_senses",
    "learner_cross_verified_senses", "korean_verified_senses", "open_sense_candidates",
    "open_korean_translation_candidates", "meaning_evidence_state",
)


def coverage_rows(db, core_source):
    source_ids = ({"anki": "hackers_anki_user", "quizlet": "quizlet_324678752"}[core_source], "hackers_back")
    possible = defaultdict(Counter)
    for headword, source, pos in db.execute("""
        SELECT headword,source_id,json_extract(payload_json,'$.part_of_speech')
        FROM external_candidates WHERE kind='sense_candidate' AND source_id IN ('oewn','kaikki')
    """):
        possible[normalized_lemma(headword)][(source, normalized_pos(pos))] += 1
    bilingual = defaultdict(Counter)
    for headword, pos in db.execute("""
        SELECT headword,json_extract(payload_json,'$.part_of_speech')
        FROM external_candidates WHERE kind='relation_candidate' AND source_id='kaikki'
        AND json_extract(payload_json,'$.relation_type')='KOREAN_TRANSLATION_CANDIDATE'
    """):
        bilingual[normalized_lemma(headword)][normalized_pos(pos)] += 1

    for row in db.execute("""
        SELECT o.occurrence_id,o.source_id,o.source_record_id,o.day,o.filename,o.pdf_page,
               COALESCE(json_extract(o.properties_json,'$.original_headword'),w.headword) AS headword,
               o.part_of_speech,o.original_korean_meaning,
               COUNT(so.sense_id) AS reviewed_senses,
               COUNT(CASE WHEN en.status='cross_verified' THEN 1 END) AS learner_cross_verified_senses,
               COUNT(CASE WHEN ko.status='verified' THEN 1 END) AS korean_verified_senses
        FROM occurrences o JOIN words w ON o.word_id=w.word_id
        LEFT JOIN sense_occurrences so ON so.occurrence_id=o.occurrence_id
        LEFT JOIN english_definitions en ON en.sense_id=so.sense_id
        LEFT JOIN korean_translations ko ON ko.sense_id=so.sense_id
        WHERE o.source_id IN (?,?)
        GROUP BY o.occurrence_id
        ORDER BY o.source_id,o.day,o.filename,o.pdf_page,o.source_record_id
    """, source_ids):
        record = dict(row)
        source_pos = pos_options(record["part_of_speech"])
        lemma = normalized_lemma(record["headword"])
        candidates = Counter()
        for (source, pos), count in possible[lemma].items():
            if not source_pos or not pos or pos in source_pos:
                candidates[source] += count
        korean_candidates = sum(
            count for pos, count in bilingual[lemma].items()
            if not source_pos or not pos or pos in source_pos
        )
        if record["learner_cross_verified_senses"]:
            state = "learner_cross_verified_sense_linked"
        elif record["reviewed_senses"]:
            state = "reviewed_sense_linked"
        elif candidates:
            state = "open_candidates_pending_alignment"
        else:
            state = "no_exact_open_candidate_pending_review"
        yield {
            **record, "open_sense_candidates": dict(candidates), "meaning_evidence_state": state,
            "open_korean_translation_candidates": korean_candidates,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--core-source", choices=("anki", "quizlet"), default="anki")
    args = parser.parse_args()
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = list(coverage_rows(db, args.core_source))
    state_counts = Counter(row["meaning_evidence_state"] for row in rows)
    summary = {
        "source_occurrences": len(rows),
        "occurrences_with_linked_english_verification": sum(bool(row["learner_cross_verified_senses"]) for row in rows),
        "occurrences_with_linked_korean_verification": sum(bool(row["korean_verified_senses"]) for row in rows),
        "occurrences_with_open_korean_candidates": sum(bool(row["open_korean_translation_candidates"]) for row in rows),
        "occurrence_meaning_evidence_states": dict(state_counts),
    }
    write_jsonl(args.output_dir / "semantic_coverage.jsonl", rows)
    write_csv(args.output_dir / "semantic_coverage.csv", FIELDS, (
        {**row, "open_sense_candidates": json.dumps(row["open_sense_candidates"], sort_keys=True)}
        for row in rows
    ))
    write_json(args.output_dir / "semantic_coverage_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
