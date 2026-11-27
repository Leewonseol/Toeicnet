"""Check SQLite invariants and distinguish structural integrity from source coverage."""
import argparse
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def validate(db):
    errors = []
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        errors.append("SQLite integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        errors.append("Foreign key check failed")
    for object_type, table, key in (
        ("node", "nodes", "node_id"), ("edge", "edges", "edge_id"),
        ("occurrence", "occurrences", "occurrence_id"), ("sense_alignment", "senses", "sense_id"),
        ("english_definition", "english_definitions", "sense_id"),
        ("korean_translation", "korean_translations", "sense_id"),
    ):
        count = db.execute(
            f"""SELECT COUNT(*) FROM evidence ev LEFT JOIN {table} obj ON ev.object_id=obj.{key}
                WHERE ev.object_type=? AND obj.{key} IS NULL""", (object_type,),
        ).fetchone()[0]
        if count:
            errors.append(f"{count} orphan evidence records for {object_type}")
    checks = {
        "A sense lacks one of its verification rows": """
            SELECT 1 FROM senses s LEFT JOIN english_definitions en USING(sense_id)
            LEFT JOIN korean_translations ko USING(sense_id)
            WHERE en.sense_id IS NULL OR ko.sense_id IS NULL""",
        "A verified Korean translation lacks explicit bilingual evidence": """
            SELECT 1 FROM korean_translations ko WHERE status='verified' AND (
                verified_korean_meaning IS NULL OR NOT EXISTS(
                    SELECT 1 FROM evidence ev WHERE ev.object_type='korean_translation'
                    AND ev.object_id=ko.sense_id AND json_extract(ev.properties_json,'$.sense_match')='matched'
                    AND json_extract(ev.properties_json,'$.assessment_kind') IN
                        ('bilingual_dictionary','korean_usage','bilingual_semantic_review')))""",
        "An unverified Korean translation was stored as verified": """
            SELECT 1 FROM korean_translations
            WHERE status<>'verified' AND verified_korean_meaning IS NOT NULL""",
        "A cross-verified English definition lacks two independent matched learner dictionaries": """
            SELECT 1 FROM english_definitions en WHERE status='cross_verified' AND (
                SELECT COUNT(DISTINCT s.independence_group) FROM evidence ev JOIN sources s USING(source_id)
                WHERE ev.object_type='english_definition' AND ev.object_id=en.sense_id
                    AND ev.source_id IN ('cambridge','oxford','longman','collins','britannica')
                    AND json_extract(ev.properties_json,'$.sense_match')='matched') < 2""",
        "An attested relation has no evidence": """
            SELECT 1 FROM edges e WHERE status IN ('cross_verified','source_attested','corpus_attested')
            AND NOT EXISTS(SELECT 1 FROM evidence ev WHERE ev.object_type='edge' AND ev.object_id=e.edge_id)""",
        "A source occurrence has no provenance": """
            SELECT 1 FROM occurrences o
            WHERE NOT EXISTS(SELECT 1 FROM evidence ev WHERE ev.object_type='occurrence' AND ev.object_id=o.occurrence_id)""",
        "A word or sense is missing from the graph": """
            SELECT word_id FROM words WHERE word_id NOT IN (SELECT node_id FROM nodes WHERE node_type='WORD')
            UNION ALL
            SELECT sense_id FROM senses WHERE sense_id NOT IN (SELECT node_id FROM nodes WHERE node_type='SENSE')""",
    }
    for message, sql in checks.items():
        if db.execute(sql).fetchone():
            errors.append(message)
    return errors


def coverage(db):
    values = {}
    for name, source in (("core", "quizlet_324678752"), ("anki", "hackers_anki_user"), ("back", "hackers_back")):
        count, days = db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT day) FROM occurrences WHERE source_id=?", (source,),
        ).fetchone()
        values[f"{name}_occurrences"] = count
        values[f"{name}_days"] = days
    values["back_pages_with_entries"] = db.execute(
        """SELECT COUNT(*) FROM (
            SELECT DISTINCT filename,pdf_page FROM occurrences
            WHERE source_id='hackers_back' AND filename IS NOT NULL AND pdf_page IS NOT NULL)""",
    ).fetchone()[0]
    row = db.execute("SELECT payload_json FROM pipeline_state WHERE stage='normalized_intake'").fetchone()
    intake_manifest = json.loads(row[0]) if row else {}
    configured = db.execute("""
        SELECT json_extract(metadata_json,'$.expected_items') FROM sources
        WHERE source_id='quizlet_324678752'
    """).fetchone()
    values["expected_quizlet_occurrences"] = configured[0] if configured else None
    values["back_pages_image_reviewed"] = intake_manifest.get("reviewed_image_pages")
    values["intake_manifest_complete"] = intake_manifest.get("complete_intake", False)
    return values


def validate_tsv(directory):
    errors = []
    for path in sorted(directory.rglob("*.tsv")):
        with path.open(encoding="utf-8", newline="") as stream:
            for line_no, row in enumerate(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE), 1):
                if len(row) != 2 or not all(row) or any("\x00" in field for field in row):
                    errors.append(f"{path}:{line_no}: Expected two nonempty UTF-8 fields")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--quizlet-output", type=Path)
    parser.add_argument("--require-coverage", action="store_true",
                        help="Require the matching normalized manifest, exact Quizlet count and full PDF/image coverage")
    args = parser.parse_args()
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        errors = validate(db)
        measured = coverage(db)
    if args.quizlet_output:
        errors.extend(validate_tsv(args.quizlet_output))
    integrity_passed = not errors
    if args.require_coverage and (
        not measured["intake_manifest_complete"]
        or measured["core_occurrences"] != measured["expected_quizlet_occurrences"]
        or measured["core_days"] != 30 or measured["back_days"] != 30
        or measured["back_pages_image_reviewed"] != 120
    ):
        errors.append("Count-matched Quizlet and/or full image-reviewed Hackers DAY 01–30 coverage is missing")
    print(json.dumps({
        "passed": not errors, "integrity_passed": integrity_passed,
        "errors": errors, "coverage": measured,
    }, ensure_ascii=False))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
