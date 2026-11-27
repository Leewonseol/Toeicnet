"""Tests for Anki package selection, local provenance and card multiplicity."""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from import_anki import resolve_day
from intake_common import read_jsonl, sha256_file


class AnkiIntakeTests(unittest.TestCase):
    def fixture(self, root, *, modern=False):
        collection = root / "collection.sqlite"
        fields = [{"ord": 0, "name": "English"}, {"ord": 1, "name": "Korean"}]
        name = "Example::DAY 07"
        with closing(sqlite3.connect(collection)) as db, db:
            db.create_collation("unicase", lambda left, right: (left > right) - (left < right))
            db.executescript("""
                CREATE TABLE col(ver INTEGER, models TEXT, decks TEXT);
                CREATE TABLE notes(id INTEGER, guid TEXT, tags TEXT, flds TEXT, mid INTEGER);
                CREATE TABLE cards(id INTEGER, nid INTEGER, did INTEGER, odid INTEGER);
                INSERT INTO cards VALUES (21,11,9,0),(22,11,8,9);
            """)
            db.execute("INSERT INTO notes VALUES(?,?,?,?,?)",
                       (11, "g11", " DAY_07 ", "adjust\x1f<b>조정하다</b><br>[sound:example.mp3]적응하다", 3))
            db.execute("INSERT INTO col VALUES(?,?,?)", (18 if modern else 11,
                       json.dumps({"3": {"name": "Vocab", "flds": fields}}), json.dumps({"9": {"name": name}})))
            if modern:
                db.executescript("""
                    CREATE TABLE fields(ntid INTEGER, ord INTEGER, name TEXT COLLATE unicase,
                                        PRIMARY KEY(ntid,ord)) WITHOUT ROWID;
                    CREATE TABLE decks(id INTEGER, name TEXT COLLATE unicase);
                    CREATE TABLE notetypes(id INTEGER, name TEXT COLLATE unicase);
                    INSERT INTO fields VALUES(3,0,'English'),(3,1,'Korean');
                    INSERT INTO notetypes VALUES(3,'Vocab');
                """)
                db.execute("INSERT INTO decks VALUES(?,?)", (9, name.replace("::", "\x1f")))
        package = root / "example.apkg"
        with ZipFile(package, "w") as out:
            if modern:
                data = subprocess.run(["zstd", "--quiet", "--stdout", str(collection)],
                                      check=True, capture_output=True).stdout
                out.writestr("collection.anki21b", data)
                out.writestr("collection.anki2", "Compatibility stub")
            else:
                out.write(collection, "collection.anki2")
            out.writestr("../../ignored", "media")
        return package

    def run_script(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPTS / "import_anki.py"), *map(str, arguments)],
                              capture_output=True, text=True)

    def test_zip_preserves_note_and_card_ids_and_ignores_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.fixture(root)
            archive = root / "example.zip"
            with ZipFile(archive, "w") as out:
                out.write(package, "folder/example.apkg")
                out.writestr("../stray.txt", "ignore")
            result = self.run_script(archive, "--inspect")
            self.assertEqual(result.returncode, 0, result.stderr)
            inspected = json.loads(result.stdout)
            self.assertEqual((inspected["note_count"], inspected["card_count"]), (1, 2))
            output, manifest = root / "out.jsonl", root / "manifest.json"
            result = self.run_script(archive, "--model-id", 3, "--headword-field", "English", "--meaning-field",
                                     "Korean", "--deck-prefix", "Example", "--expected-count", 1,
                                     "--output", output, "--manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = list(read_jsonl(output))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["anki_card_ids"], [21, 22])
            self.assertEqual(records[0]["original_korean_meaning"], "조정하다\n적응하다")
            self.assertEqual((records[0]["source_id"], records[0]["day"]), ("hackers_anki_user", 7))
            self.assertEqual(json.loads(manifest.read_text())["output_records_sha256"], sha256_file(output))
            self.assertFalse((root / "stray.txt").exists())

    @unittest.skipUnless(shutil.which("zstd"), "Zstandard CLI required")
    def test_selects_modern_collection_over_legacy_stub(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.fixture(Path(temporary), modern=True)
            result = self.run_script(package, "--inspect")
            self.assertEqual(result.returncode, 0, result.stderr)
            inspected = json.loads(result.stdout)
            self.assertEqual(inspected["schema_version"], 18)
            self.assertEqual(inspected["decks"][0]["explicit_day_labels"], [7])

    def test_conflicting_day_labels_require_review(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            resolve_day("Example::DAY 07", " DAY_08 ")
        self.assertIsNone(resolve_day("Example::2021-08-21", ""))


if __name__ == "__main__":
    unittest.main()
