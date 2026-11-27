import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from batch_rag_verify import ASSESSMENT_FIELDS, adjudicate_english, adjudicate_korean


class AdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.case = {"case_key": "example", "part_of_speech": "noun", "original_korean_meaning": "기간"}
        self.wiktionary = {
            "candidate_id": "w", "source_id": "kaikki", "independence_group": "wiktionary",
            "source_record_id": "line:21:sense:1", "part_of_speech": "noun",
            "definition": "A specified length of time.", "match_method": "exact_headword_and_pos",
        }
        self.wordnet = {
            "candidate_id": "n", "source_id": "oewn", "independence_group": "globalwordnet",
            "source_record_id": "oewn-example-01", "part_of_speech": "noun",
            "definition": "An interval with a known length.",
        }
        self.decision = {
            "case_key": "example", "verdict": "match", "candidate_ids": ["w", "n"],
            "definition": "A measured interval of time.", "reason": "Both senses specify the span.",
            "assessment": {field: "Evidence was considered." for field in ASSESSMENT_FIELDS},
        }

    def test_open_sources_do_not_change_a(self):
        candidates = [self.wiktionary, self.wordnet]
        self.assertEqual(adjudicate_english(candidates, case=self.case)["grade"], "D")
        judged = adjudicate_english(candidates, case=self.case, decision=self.decision)
        self.assertEqual((judged["grade"], judged["status"]), ("B", "open_cross_verified"))
        self.assertEqual(adjudicate_korean(decision=self.decision)["status"], "unverified")

    def test_identical_or_reused_wording_does_not_establish_independence(self):
        repeated = {**self.wordnet, "definition": self.wiktionary["definition"]}
        reused = {**self.wordnet, "derived_from": "wiktionary"}
        for record in (repeated, reused):
            with self.subTest(record=record):
                result = adjudicate_english([self.wiktionary, record], case=self.case, decision=self.decision)
                self.assertEqual(result["grade"], "D")
                self.assertFalse(result["source_alignment"])

    def test_rejects_unsupported_candidate_id_and_ineligible_corpus(self):
        corpus = {**self.wordnet, "source_id": "oanc", "kind": "usage_candidate"}
        with self.assertRaisesRegex(ValueError, "unavailable or ineligible sense ID"):
            adjudicate_english([self.wiktionary, corpus], case=self.case, decision=self.decision)

    def test_phrase_span_label_is_not_a_pos_conflict(self):
        judged = adjudicate_english([self.wiktionary, self.wordnet],
                                    case={**self.case, "part_of_speech": "phr"}, decision=self.decision)
        self.assertEqual(judged["grade"], "B")

    def test_preserves_independently_reviewed_korean(self):
        row = {"sense_id": "sense", "english_status": "cross_verified", "english_definition": "Example",
               "korean_status": "context_dependent", "translation_uncertainty_reason": "Multiple contexts."}
        en = adjudicate_english([], case=self.case, established=[row])
        ko = adjudicate_korean(established=[row])
        self.assertEqual(en["grade"], "A")
        self.assertEqual(ko["status"], "context_dependent")
        self.assertIsNone(ko["meaning"])

    def test_bilingual_anchor_is_not_automatic_korean_verification(self):
        bilingual = {
            "candidate_id": "translation", "source_id": "kaikki", "source_record_id": "line:21:translation:4",
            "part_of_speech": "noun", "payload": {
                "relation_type": "KOREAN_TRANSLATION_CANDIDATE", "target_headword": "기간",
                "details": {"source_sense_label": "A specified length of time"},
            },
        }
        en = adjudicate_english([self.wiktionary], case=self.case, korean_candidates=[bilingual])
        self.assertEqual(en["grade"], "D")
        self.assertEqual(adjudicate_korean(candidates=[bilingual], english=en)["status"], "unverified")
        reviewed = {**self.decision, "korean": {"status": "verified", "candidate_id": "translation",
                    "sense_candidate_id": "w", "meaning": "기간", "reason": "Exact linked bilingual gloss."}}
        reviewed["candidate_ids"] = ["w"]
        en = adjudicate_english([self.wiktionary], case=self.case, decision=reviewed)
        ko = adjudicate_korean(candidates=[bilingual], decision=reviewed,
                               english=en, english_candidates=[self.wiktionary], case=self.case)
        self.assertEqual((ko["status"], ko["meaning"]), ("verified", "기간"))


if __name__ == "__main__":
    unittest.main()
