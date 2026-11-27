"""Regression checks for source count, occurrence provenance, and OCR review gates."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_ocr import candidate_entries, expected_files, pair_sparse_columns
from intake_common import ENTRY_FIELDS, PAGE_FIELDS, read_jsonl, write_csv, write_json
import normalize


class SourceIntakeTests(unittest.TestCase):
    def run_script(self, name, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *map(str, arguments)],
            capture_output=True, text=True,
        )

    def test_quizlet_count_gate_and_duplicate_headword_occurrences(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "export.csv"
            intake = root / "quizlet.jsonl"
            manifest = root / "quizlet-manifest.json"
            normalized = root / "normalized.jsonl"
            normalized_manifest = root / "normalized-manifest.json"
            source.write_text(
                'term,definition,day,type\nCarry over,"계속하다, 이월하다",DAY 01,phrasal_verb\n'
                "carry over,이월되다,,phrasal_verb\n", encoding="utf-8"
            )
            command = [
                source, "--count-evidence", "count in isolated test fixture",
                "--output", intake, "--manifest", manifest, "--expected-count",
            ]
            result = self.run_script("import_quizlet.py", *command, "3")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(intake.exists())
            self.assertFalse(json.loads(manifest.read_text())["count_matches"])
            result = self.run_script("import_quizlet.py", *command, "2")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_script(
                "normalize.py", "--only", "quizlet", "--quizlet", intake,
                "--quizlet-manifest", manifest, "--output", normalized,
                "--manifest", normalized_manifest,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            records = list(read_jsonl(normalized))
            self.assertEqual(len({record["source_record_id"] for record in records}), 2)
            self.assertEqual({record["headword_key"] for record in records}, {"carry over"})
            self.assertEqual(records[0]["original_korean_meaning"], "계속하다, 이월하다")
            self.assertEqual([record["day"] for record in records], [1, None])
            self.assertFalse(json.loads(normalized_manifest.read_text())["complete_intake"])
            with intake.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "do not match"):
                normalize.accepted_quizlet(intake, manifest)

    def test_ocr_reports_missing_inputs_without_accepting_empty_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_script("extract_ocr.py", "--source-dir", root / "pdfs", "--output-dir", root / "ocr")
            self.assertEqual(result.returncode, 1, result.stderr)
            manifest = json.loads((root / "ocr" / "manifest.json").read_text())
            self.assertEqual(manifest["expected_pages"], 120)
            self.assertEqual(manifest["ocr_pages"], 0)
            self.assertFalse(manifest["ready_for_full_image_review"])
            self.assertEqual(len(manifest["files"]), 3)

    def test_original_drive_filenames_match_requested_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "해커스토익 뒷단어 데이 1-10(2).pdf"
            original.touch()
            requested = "해커스토익 뒷단어 데이 1-10(2)(2).pdf"
            self.assertEqual(expected_files(root), {requested: original})
            (root / requested).touch()
            with self.assertRaisesRegex(ValueError, "multiple source files"):
                expected_files(root)

    def test_sparse_ocr_pairs_columns_by_page_geometry(self):
        lines = [(f"O word{letter}", (100, row * 40, 50, 20), 80, 1000)
                 for row, letter in enumerate("abcde", start=1)]
        lines.extend([("phr 교재 어휘", (270, 80, 90, 19), 91, 1000),
                      ("다른 줄", (270, 105, 90, 19), 91, 1000)])
        self.assertEqual(
            [line[0] for line in pair_sparse_columns(lines)], ["wordb phr 교재 어휘"]
        )

    def test_ocr_candidates_need_page_review_and_count_agreement(self):
        with tempfile.TemporaryDirectory() as temp:
            ocr = Path(temp)
            for name in ("image.png", "ocr.txt"):
                (ocr / name).touch()
            filename = "source.pdf"
            checksum = "abc"
            pages = [{
                "filename": filename, "source_sha256": checksum, "pdf_page": 1,
                "day": 1, "printed_page": 14, "reviewed_entries": "",
                "review_status": "pending", "review_note": "", "image_path": "image.png",
                "ocr_path": "ocr.txt",
            }]
            write_csv(ocr / "candidates.pages.csv", PAGE_FIELDS, pages)
            write_json(ocr / "manifest.json", {
                "source_id": "hackers_back", "ready_for_full_image_review": True,
                "files": {filename: {"sha256": checksum}},
            })
            entries = candidate_entries(
                [("signal (n.) 신호", (1, 2, 3, 4), 85.0, 300)], filename, checksum, 1
            )
            self.assertEqual(entries[0]["part_of_speech"], "noun")
            self.assertEqual(entries[0]["entry_type"], "")
            entries[0]["entry_type"] = "word"
            reviewed_entries = ocr / "reviewed.entries.csv"
            reviewed_pages = ocr / "reviewed.pages.csv"
            write_csv(reviewed_entries, ENTRY_FIELDS, entries)
            write_csv(reviewed_pages, PAGE_FIELDS, pages)
            with patch.object(normalize, "HACKERS_PDFS", {filename: (1, 1, 1)}):
                with self.assertRaisesRegex(ValueError, "review has not been confirmed"):
                    normalize.accepted_ocr(ocr, reviewed_pages, reviewed_entries)
                pages[0].update(review_status="image_reviewed", reviewed_entries=2)
                write_csv(reviewed_pages, PAGE_FIELDS, pages)
                with self.assertRaisesRegex(ValueError, "2 entries declared, 1 accepted"):
                    normalize.accepted_ocr(ocr, reviewed_pages, reviewed_entries)
                pages[0]["reviewed_entries"] = 1
                write_csv(reviewed_pages, PAGE_FIELDS, pages)
                records, page_count = normalize.accepted_ocr(ocr, reviewed_pages, reviewed_entries)
                write_csv(ocr / "snapshot.candidates.pages.csv", PAGE_FIELDS, pages)
                write_json(ocr / "snapshot.manifest.json", {
                    "source_id": "hackers_back", "ready_for_full_image_review": False,
                    "files": {filename: {"sha256": checksum}},
                })
                with self.assertRaisesRegex(ValueError, "OCR must be complete"):
                    normalize.accepted_ocr(ocr, reviewed_pages, reviewed_entries, snapshot=True)
                self.assertEqual(normalize.accepted_ocr(
                    ocr, reviewed_pages, reviewed_entries, allow_partial=True, snapshot=True
                ), (records, page_count))
            self.assertEqual(page_count, 1)
            self.assertEqual(records[0]["source_record_id"], "source.pdf:1:1")
            self.assertEqual(records[0]["printed_page"], 14)
            self.assertEqual(records[0]["original_korean_meaning"], "신호")


if __name__ == "__main__":
    unittest.main()
