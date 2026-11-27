import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from batch_rag_verify import ALIGNMENT_RESULTS, ASSESSMENT_FIELDS, adjudicate_english, adjudicate_korean


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

    def _learner(self, source_id, group, record_id, definition):
        return {
            "candidate_id": source_id, "source_id": source_id, "independence_group": group,
            "source_record_id": record_id, "part_of_speech": "noun", "definition": definition,
        }

    def test_collins_and_merriam_webster_reach_a(self):
        collins = self._learner("collins", "harpercollins", "collins:period:1", "A length of time.")
        webster = self._learner("merriam_webster", "merriam_webster", "mw:period:1", "A portion of time.")
        decision = {**self.decision, "candidate_ids": ["collins", "merriam_webster"]}
        judged = adjudicate_english([collins, webster], case=self.case, decision=decision)
        self.assertEqual((judged["grade"], judged["source_combination"]), ("A", "learner×2"))
        self.assertEqual(judged["alignment_result"], "equivalent")

    def test_same_lineage_outlets_are_not_independent(self):
        webster = self._learner("merriam_webster", "merriam_webster", "mw:period:1", "A portion of time.")
        britannica = self._learner("britannica", "merriam_webster", "brit:period:1", "An amount of time.")
        decision = {**self.decision, "candidate_ids": ["merriam_webster", "britannica"]}
        judged = adjudicate_english([webster, britannica], case=self.case, decision=decision)
        self.assertEqual(judged["grade"], "D")

    def test_mixed_tier_keeps_a_and_b_definitions(self):
        webster = self._learner("merriam_webster", "merriam_webster", "mw:period:1", "A portion of time.")
        decision = {**self.decision, "candidate_ids": ["merriam_webster", "n"]}
        judged = adjudicate_english([webster, self.wordnet], case=self.case, decision=decision)
        self.assertEqual((judged["grade"], judged["status"]), ("C", "source_attested"))
        self.assertEqual(judged["source_combination"], "learner×1+open×1")

    def test_seven_way_alignment_results(self):
        for label in ALIGNMENT_RESULTS:
            with self.subTest(label=label):
                decision = {**self.decision, "verdict": label}
                if label != "equivalent":
                    decision["definition"] = None
                judged = adjudicate_english([self.wiktionary, self.wordnet], case=self.case, decision=decision)
                self.assertEqual(judged["alignment_result"], label)
                self.assertEqual(judged["grade"], "B" if label == "equivalent" else "D")
        legacy = adjudicate_english([self.wiktionary, self.wordnet], case=self.case,
                                    decision={**self.decision, "verdict": "partial", "definition": None})
        self.assertEqual((legacy["grade"], legacy["alignment_result"]), ("D", "partially_equivalent"))
        with self.assertRaisesRegex(ValueError, "Unmatched decisions"):
            adjudicate_english([self.wiktionary, self.wordnet], case=self.case,
                               decision={**self.decision, "verdict": "broader"})


if __name__ == "__main__":
    unittest.main()
