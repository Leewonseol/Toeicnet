"""The study page reads vocabulary.csv as its only data source and carries no data or credentials itself."""

import ast
import csv
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "vocabulary/study.html"
CSV_PATH = ROOT / "vocabulary/vocabulary.csv"
BUILDER = ROOT / "scripts/build_vocabulary_csv.py"
WORKFLOW = ROOT / ".github/workflows/study-page.yml"


def builder_header():
    for node in ast.parse(BUILDER.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "HEADER" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("HEADER not found in build_vocabulary_csv.py")


class StudyPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_page_reads_the_builder_columns(self):
        match = re.search(r"const HEADER = (\[[^\]]*\]);", self.html)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), builder_header())
        self.assertIn('fetch("vocabulary.csv"', self.html)

    def test_page_keeps_data_and_credentials_out(self):
        self.assertLess(len(self.html.encode("utf-8")), 120_000)
        for marker in ("ghp_", "github_pat_", "gho_", "Authorization", "access_token", "?token=",
                       "api.github.com", "raw.githubusercontent.com", "<script src", "@import"):
            self.assertNotIn(marker, self.html)
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', self.html)
        self.assertIsNotNone(csp)
        self.assertIn("default-src 'none'", csp.group(1))
        self.assertIn("connect-src 'self'", csp.group(1))
        self.assertNotIn("innerHTML", self.html)

    @unittest.skipUnless(CSV_PATH.exists(), "vocabulary.csv not built")
    def test_page_embeds_no_textbook_meanings(self):
        with CSV_PATH.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        leaked = [r["뜻"] for r in rows if len(r["뜻"]) >= 6 and r["뜻"] in self.html]
        self.assertEqual(leaked, [])

    def test_workflow_publishes_only_the_page(self):
        lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
        text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
        copies = re.findall(r"^\s*cp\s+(\S+)\s+(\S+)\s*$", text, re.M)
        self.assertEqual(copies, [("vocabulary/study.html", "_site/index.html")])
        self.assertIn("path: _site", text)
        self.assertNotRegex(text, r"vocabulary\.csv|vocabulary/\*|cp -r|rsync")


if __name__ == "__main__":
    unittest.main()
