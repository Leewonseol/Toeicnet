"""Rules of the rebuild-v2 analysis that the sample evaluation depends on."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebuild_analyze import _collocation_ok, _pieces, family, korean_forms, korean_pos  # noqa: E402
from rebuild_sources import build, split_headword  # noqa: E402


class RebuildRulesTest(unittest.TestCase):
    def test_textbook_relation_notes_are_split_not_lost(self):
        self.assertEqual(split_headword("turn off(↔turn on)"), ("turn off", [{"relation": "antonym", "target": "turn on"}]))
        self.assertEqual(split_headword("a variety of (= various)"), ("a variety of", [{"relation": "synonym", "target": "various"}]))
        self.assertEqual(split_headword("provided(that)"), ("provided(that)", []))

    def test_korean_endings(self):
        self.assertEqual(korean_pos("보호하다"), "verb")
        self.assertEqual(korean_pos("훌륭한, 탁월한"), "adjective")
        self.assertEqual(korean_pos("한계, 제한"), "noun")
        self.assertEqual(korean_pos("정확히"), "adverb")
        self.assertIn("편안하다", korean_forms("편안한"))
        self.assertIn("정확하게", korean_forms("정확히"))
        self.assertIn("면세", korean_forms("면세의"))

    def test_morphology_templates_and_families(self):
        self.assertEqual(_pieces("ety", {"1": "en", "2": ":af", "3": "state", "4": "-ment"}), ["state", "-ment"])
        self.assertEqual(_pieces("suf", {"1": "en", "2": "excel", "3": "ent"}), ["excel", "-ent"])
        self.assertIsNone(_pieces("affix", {"1": "la", "2": "prō-", "3": "tegō"}))
        self.assertEqual(family("la-med"), "Latinate")
        self.assertEqual(family("frk"), "Germanic")
        self.assertEqual(family("enm"), "English formation")

    def test_collocation_filter_drops_names_and_acronyms(self):
        def row(expression, surfaces, documents):
            return {"expression": expression, "details": {"attestations": [
                {"surface": s, "document": d} for s, d in zip(surfaces, documents)]}}
        self.assertTrue(_collocation_ok(row("interest rate", ["interest rates", "interest rate"], ["a", "b"]), "interest"))
        self.assertFalse(_collocation_ok(row("doj inspector", ["DOJ inspector", "DOJ inspectors"], ["a", "b"]), "inspector"))
        self.assertFalse(_collocation_ok(row("rice meeting", ["Rice meeting", "meeting Rice"], ["a", "a"]), "meeting"))
        self.assertFalse(_collocation_ok(row("more efficient", ["more efficient", "more efficient"], ["a", "b"]), "efficient"))
        self.assertFalse(_collocation_ok(row("weekly standard", ["Weekly Standard", "Weekly Standard"], ["a", "b"]), "weekly"))


if __name__ == "__main__":
    unittest.main()
