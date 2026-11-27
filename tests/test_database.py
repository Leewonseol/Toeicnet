"""Integration checks with isolated synthetic inputs."""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from build_database import build
from export_semantic_coverage import coverage_rows
from validate_database import coverage, source_coverage_complete, validate


def jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def citation(source_id, url, locator, **details):
    return {
        "source_id": source_id, "url": url, "source_record_id": locator,
        "verification_date": "2026-11-27", "extraction_method": "test",
        "note": "Synthetic test evidence", **details,
    }


class BuildDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.db = self.root / "toeic.db"
        self.config = self.root / "sources.json"
        catalog = {
            key: {"name": key, "independence_group": group, "source_type": kind}
            for key, group, kind in (
                ("quizlet_324678752", "hackers", "primary_material"),
                ("hackers_back", "hackers", "primary_material"),
                ("cambridge", "cmp", "learner_dictionary"),
                ("oxford", "oup", "learner_dictionary"),
                ("oewn", "oewn", "machine_lexicon"),
            )
        }
        self.config.write_text(json.dumps({"sources": catalog}))
        self.intake = jsonl(self.root / "intake.jsonl", [
            {"headword": "Sample", "source_id": "quizlet_324678752", "source_record_id": "1",
             "day": 1, "original_korean_meaning": "견본", "verification_status": "source_attested"},
            {"headword": "sample", "source_id": "hackers_back", "source_record_id": "2",
             "filename": "fixture.pdf", "pdf_page": 1, "day": 1},
            {"headword": "sample", "homonym_key": "test-homonym",
             "source_id": "hackers_back", "source_record_id": "3", "day": 1},
        ])
        self.candidates = jsonl(self.root / "candidates.jsonl", [{
            "kind": "sense_candidate", "headword": "outside", "source_id": "oewn",
            "source_record_id": "candidate-a",
        }])
        self.sense = {
            "kind": "sense", "headword": "sample", "part_of_speech": "noun", "sense_key": "item",
            "status": "cross_verified", "english_definition": "An item chosen for testing.",
            "definition_origin": "paraphrase", "verification_date": "2026-11-27",
            "definition_evidence": [
                citation("cambridge", "https://dictionary.cambridge.org/dictionary/english/sample",
                         "fixture-1", matched_sense_key="item", sense_match="matched"),
                citation("oxford", "https://www.oxfordlearnersdictionaries.com/definition/english/sample",
                         "fixture-2", matched_sense_key="item", sense_match="matched"),
            ],
            "occurrences": [{"source_id": "quizlet_324678752", "source_record_id": "1"}],
        }
        self.review = self.root / "review.jsonl"

    def test_build_links_duplicate_occurrences_and_keeps_candidate_outside_published_words(self):
        relation = {
            "kind": "relation", "module": "lexical_semantics", "relation_type": "BELONGS_TO_THEME",
            "from": {"node_type": "SENSE", "headword": "sample", "part_of_speech": "noun",
                     "sense_key": "item"},
            "to": {"node_type": "THEME", "key": "quality-test", "label": "Quality test"},
            "status": "source_attested", "verification_date": "2026-11-27",
            "evidence": [citation("oewn", "https://en-word.net/", "fixture-3", relation_match="matched")],
        }
        jsonl(self.review, [relation, self.sense])
        build(self.db, self.config, [self.intake], [self.candidates], [self.review])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(validate(db), [])
            self.assertEqual(coverage(db)["back_occurrences"], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM words").fetchone(), (2,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sense_occurrences").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM external_candidates").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM word_theme_relations").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT definition_origin FROM english_definitions").fetchone(),
                             ("paraphrase",))
            self.assertEqual(db.execute("SELECT status,verified_korean_meaning FROM korean_translations").fetchone(),
                             ("unverified", None))

    def test_invalid_review_does_not_replace_a_prior_database(self):
        build(self.db, self.config)
        prior = self.db.read_bytes()
        jsonl(self.review, [{**self.sense, "definition_evidence": self.sense["definition_evidence"][:1]}])
        with self.assertRaisesRegex(ValueError, "two independent"):
            build(self.db, self.config, [self.intake], review=[self.review])
        self.assertEqual(self.db.read_bytes(), prior)

    def test_candidates_do_not_count_as_learner_or_korean_verification(self):
        candidates = jsonl(self.candidates, [{
            "kind": "sense_candidate", "headword": "sample", "source_id": "oewn",
            "source_record_id": "open-meaning", "part_of_speech": "noun",
        }])
        jsonl(self.review, [self.sense])
        build(self.db, self.config, [self.intake], [candidates], [self.review])
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            rows = {row["source_record_id"]: row for row in coverage_rows(db, "quizlet")}
        self.assertEqual(rows["1"]["learner_cross_verified_senses"], 1)
        self.assertEqual(rows["1"]["korean_verified_senses"], 0)
        self.assertEqual(rows["2"]["meaning_evidence_state"], "open_candidates_pending_alignment")
        self.assertEqual(rows["2"]["open_sense_candidates"], {"oewn": 1})

    def test_anki_coverage_uses_own_manifest_and_full_pdf_review(self):
        measured = {
            "anki_manifest_complete": True, "anki_days": 30, "anki_occurrences": 1241,
            "expected_anki_occurrences": 1241, "back_days": 30, "back_pages_image_reviewed": 120,
            "ocr_manifest_complete": True, "intake_manifest_complete": False,
        }
        self.assertTrue(source_coverage_complete(measured, "anki"))
        self.assertFalse(source_coverage_complete(measured, "quizlet"))
        self.assertFalse(source_coverage_complete({**measured, "back_pages_image_reviewed": 119}, "anki"))
