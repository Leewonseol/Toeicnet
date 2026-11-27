import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from batch_rag_benchmark import evaluate_sample, select_sample
from review_common import write_jsonl


def occurrence(identifier, source="hackers_back", counts=None, existing=0):
    return {
        "occurrence_id": identifier, "source_id": source,
        "open_sense_candidates": counts or {}, "learner_cross_verified_senses": existing,
    }


class BatchRagBenchmarkTests(unittest.TestCase):
    def test_sample_is_order_independent_and_includes_both_sources(self):
        rows = [occurrence(str(i), "hackers_anki_user" if i % 2 else "hackers_back",
                           {"oewn": i % 5}, existing=i % 7 == 0) for i in range(400)]
        sample = select_sample(rows)
        self.assertEqual(sample, select_sample(reversed(rows)))
        self.assertEqual(len({row["occurrence_id"] for row in sample}), 100)
        self.assertEqual({row["source_id"] for row in sample}, {"hackers_anki_user", "hackers_back"})

    def test_positive_links_from_different_senses_cannot_establish_grade_b(self):
        target = occurrence("one")
        packet = {
            "target": target, "baseline_senses": ["wrong", "disease-W"],
            "senses": ["disease-W", "temperature-K", "wrong", "disease-K"],
            "english": {"grade": "B", "candidate_ids": ["disease-W", "temperature-K"]},
        }
        label = {
            "occurrence_id": "one", "reviewer": "test", "reason": "Two senses.",
            "expected_grade": "B", "matches": ["disease-W", "disease-K", "temperature-K"],
            "nonmatches": ["wrong"],
            "sense_groups": [["disease-W", "disease-K"], ["temperature-K"]],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.jsonl"
            write_jsonl(path, [label])
            result = evaluate_sample([packet], path)
        self.assertEqual(result["retrieval"]["baseline"]["1"]["candidate_recall"]["numerator"], 0)
        self.assertEqual(result["retrieval"]["reranked"]["1"]["candidate_recall"]["denominator"], 3)
        self.assertEqual(result["retrieval"]["reranked"]["1"]["candidate_recall"]["numerator"], 1)
        self.assertEqual(result["grade_B_precision"]["value"], 0)
        self.assertEqual(len(result["wrong_cross_sense_groups"]), 1)


if __name__ == "__main__":
    unittest.main()
