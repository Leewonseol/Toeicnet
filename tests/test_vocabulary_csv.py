"""The learner CSV keeps the agreed 14 columns, Excel-safe encoding and `word — meaning` cells."""

import csv
import re
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "vocabulary/vocabulary.csv"
HEADER = ["DAY", "구분", "표제어", "품사", "뜻", "파생어", "합성어", "접두사", "접미사", "어근", "공통 어원", "동의어", "유의어", "사용 용법"]
WITH_MEANING = ("파생어", "합성어", "어근", "공통 어원", "동의어", "유의어", "사용 용법")
BANNED = re.compile(r"kaikki:|oewn-|anki_|item_id|logdice|pmi|\[\s*['\"]|\{['\"]|english_grade|pdf_status", re.I)


@unittest.skipUnless(PATH.exists(), "vocabulary.csv not built")
class VocabularyCsvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PATH.read_bytes()
        cls.rows = list(csv.DictReader(PATH.open(encoding="utf-8-sig", newline="")))

    def test_excel_safe_header_and_rows(self):
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(list(self.rows[0].keys()), HEADER)
        self.assertGreater(len(self.rows), 5000)
        self.assertEqual(len({r["표제어"].casefold() for r in self.rows}), len(self.rows))

    def test_every_related_word_has_a_meaning(self):
        for r in self.rows:
            self.assertTrue(r["뜻"].strip(), r["표제어"])
            for col in WITH_MEANING:
                for line in filter(None, r[col].split("\n")):
                    if line.startswith("문법: "):
                        continue
                    self.assertRegex(line, r"^.+ — \S", f"{r['표제어']} / {col}: {line}")
            for col in ("접두사", "접미사"):
                for line in filter(None, r[col].split("\n")):
                    self.assertRegex(line, r"^(\S+ : \S|\()", f"{r['표제어']} / {col}: {line}")

    def test_no_internal_metadata(self):
        for r in self.rows:
            for col, value in r.items():
                self.assertIsNone(BANNED.search(value), f"{r['표제어']} / {col}: {value[:80]}")


if __name__ == "__main__":
    unittest.main()
