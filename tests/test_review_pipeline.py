import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from align_senses import alignment_rows, pos_options
from analysis_review import analysis_records, checked_relation, relation_key
from review_common import checked_korean, write_jsonl


REVIEW_DATE = "2026-11-27"
CATALOG = {
    "cambridge": {"independence_group": "cambridge", "source_type": "learner_dictionary"},
    "oxford": {"independence_group": "oxford", "source_type": "learner_dictionary"},
    "oewn": {"independence_group": "wordnet", "source_type": "lexical_database"},
    "quizlet": {"independence_group": "quizlet", "source_type": "primary_material"},
    "oanc": {"independence_group": "oanc", "source_type": "corpus"},
}
URLS = {
    "cambridge": "https://dictionary.cambridge.org/dictionary/english/placeholder",
    "oxford": "https://www.oxfordlearnersdictionaries.com/definition/english/placeholder",
    "oewn": "https://en-word.net/lemma/placeholder",
    "quizlet": "https://quizlet.com/000000/placeholder",
    "oanc": "https://anc.org/",
}


def evidence(source_id, **fields):
    return {
        "source_id": source_id, "source_record_id": "test-only-locator",
        "verification_date": REVIEW_DATE, "url": URLS[source_id],
        "extraction_method": "test_fixture", "note": "Fixture only.",
        **fields,
    }


def definition_evidence(source_id):
    return evidence(source_id, matched_sense_key="test-sense", sense_match="matched")


def sense_record():
    return {
        "kind": "sense", "headword": "placeholder", "part_of_speech": "noun",
        "sense_key": "test-sense", "verification_date": REVIEW_DATE,
        "status": "cross_verified", "definition_origin": "paraphrase",
        "english_definition": "Test-only definition.",
        "definition_evidence": [definition_evidence("cambridge"), definition_evidence("oxford")],
        "occurrences": [{"source_id": "quizlet", "source_record_id": "test-position"}],
    }


def usage_record():
    return {
        "kind": "relation", "module": "lexical_usage", "relation_type": "HAS_COLLIGATION",
        "from": {"node_type": "SENSE", "headword": "placeholder", "part_of_speech": "NOUN",
                 "sense_key": "test-sense"},
        "to": {"node_type": "COLLIGATION", "key": "test-construction", "label": "Test construction"},
        "attributes": {"construction": "fixture", "toeic_official": False},
        "status": "source_attested", "verification_date": REVIEW_DATE,
        "evidence": [evidence("oxford", relation_match="matched")],
    }


class ReviewPipelineTests(unittest.TestCase):
    def test_definition_approval_does_not_approve_korean(self):
        original = sense_record()
        output = checked_korean(original, CATALOG)
        self.assertEqual(output["status"], "cross_verified")
        self.assertEqual(output["korean_status"], "unverified")
        self.assertEqual(output["preferred_display_language"], "en")
        self.assertEqual(output["occurrences"], original["occurrences"])

    def test_definition_requires_independent_learner_dictionaries(self):
        record = sense_record()
        record["definition_evidence"][1] = definition_evidence("oewn")
        with self.assertRaisesRegex(ValueError, "two independent learner dictionaries"):
            checked_korean(record, CATALOG)
        record = sense_record()
        shared = {**CATALOG, "oxford": {"independence_group": "cambridge"}}
        with self.assertRaisesRegex(ValueError, "two independent learner dictionaries"):
            checked_korean(record, shared)

    def test_uncertain_translation_retains_english_definition(self):
        record = sense_record()
        record["korean_status"] = "partial_equivalent"
        record["translation_uncertainty_reason"] = "Test-only review reason."
        record["korean_evidence"] = [
            evidence("quizlet", matched_sense_key="test-sense", sense_match="matched",
                     assessment_kind="bilingual_semantic_review")
        ]
        result = checked_korean(record, CATALOG)
        self.assertIsNone(result["verified_korean_meaning"])
        self.assertEqual(result["preferred_display_language"], "en")
        self.assertEqual(result["korean_status"], "partial_equivalent")
        record["verified_korean_meaning"] = "검사용"
        with self.assertRaisesRegex(ValueError, "outside verified_korean_meaning"):
            checked_korean(record, CATALOG)

    def test_translation_requires_separate_assessment(self):
        record = sense_record()
        record["korean_status"] = "verified"
        record["verified_korean_meaning"] = "검사용"
        with self.assertRaisesRegex(ValueError, "explicit bilingual"):
            checked_korean(record, CATALOG)
        record["korean_evidence"] = [
            evidence("quizlet", matched_sense_key="test-sense", sense_match="matched",
                     assessment_kind="bilingual_semantic_review")
        ]
        self.assertEqual(checked_korean(record, CATALOG)["preferred_display_language"], "ko+en")

    def test_english_and_korean_use_distinct_review_notes(self):
        record = sense_record()
        record["definition_evidence"][1]["matched_sense_key"] = "other-sense"
        with self.assertRaisesRegex(ValueError, "matched_sense_key"):
            checked_korean(record, CATALOG)

    def test_usage_does_not_mistag_official_toeic(self):
        record = usage_record()
        checked = checked_relation(record, CATALOG)
        self.assertEqual(relation_key(checked)[0], "HAS_COLLIGATION")
        self.assertEqual(checked["from"]["part_of_speech"], "noun")
        record["attributes"]["toeic_official"] = True
        with self.assertRaisesRegex(ValueError, "official item locator"):
            checked_relation(record, CATALOG)

    def test_batch_module_candidates_remain_pending(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.jsonl"
            candidate = {"kind": "usage_candidate", "usage_type": "COLLOCATION",
                         "headword": "placeholder", "verification_status": "corpus_attested"}
            write_jsonl(path, [candidate, usage_record()])
            review = list(analysis_records([path], "lexical_usage", CATALOG, for_review=True))
            self.assertEqual([item["kind"] for item in review], ["usage_candidate", "relation"])
            self.assertEqual(review[0]["review_status"], "pending")
            self.assertEqual(len(list(analysis_records([path], "lexical_usage", CATALOG, for_review=False))), 1)

    def test_alignment_preserves_homonym_ambiguity_and_misses(self):
        with TemporaryDirectory() as temporary:
            intake = Path(temporary) / "intake.jsonl"
            candidates = Path(temporary) / "candidates.jsonl"
            write_jsonl(intake, [
                {"headword": "Placeholder", "source_id": "quizlet", "source_record_id": "1",
                 "part_of_speech": "n.", "homonym_key": "sense-one"},
                {"headword": "placeholder", "source_id": "quizlet", "source_record_id": "2",
                 "part_of_speech": "명사", "homonym_key": "sense-two"},
                {"headword": "placeholder", "source_id": "quizlet", "source_record_id": "3",
                 "part_of_speech": "verb"},
            ])
            candidate = {
                "kind": "sense_candidate", "headword": "placeholder", "part_of_speech": "noun",
                "source_id": "oewn", "source_record_id": "source-sense", "external_sense_id": "source-sense",
            }
            candidates.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            rows = list(alignment_rows([intake], [candidates]))
            self.assertEqual(rows[0]["basis"], "homonym_review_required")
            self.assertEqual(len(rows[0]["occurrences"]), 2)
            self.assertEqual(rows[1]["occurrence"]["source_record_id"], "3")
            self.assertEqual(rows[1]["basis"], "no_exact_candidate")

    def test_alignment_accepts_multiple_source_parts_of_speech(self):
        self.assertEqual(pos_options("n.; verb/형용사"), ["noun", "verb", "adjective"])
        self.assertEqual(pos_options("noun, adj or noun"), ["noun", "adjective"])
        self.assertEqual(pos_options("phrase"), [])
        self.assertEqual(pos_options("phrase; noun"), ["noun"])

    def test_jsonl_install_is_atomic_on_failed_review(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "reviewed.jsonl"
            path.write_text("previous\n", encoding="utf-8")

            def interrupted_rows():
                yield {"kind": "reviewed"}
                raise ValueError("stopped")

            with self.assertRaisesRegex(ValueError, "stopped"):
                write_jsonl(path, interrupted_rows())
            self.assertEqual(path.read_text(encoding="utf-8"), "previous\n")


if __name__ == "__main__":
    unittest.main()
