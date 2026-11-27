"""Exercise export policy and traceability with isolated database fixtures."""

import csv
import json
import re
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_network import export_network
from export_quizlet import write_decks
from generate_study_notes import generate_notes
from study_data import StudyData


class StudyOutputsTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.database = self.root / "study.db"
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript((Path(__file__).resolve().parents[1] / "scripts/schema.sql").read_text())
            db.executemany(
                "INSERT INTO sources(source_id,title,url,independence_group) VALUES (?,?,?,?)",
                [("quizlet_324678752", "Quizlet", "https://quizlet.com/324678752", "quizlet"),
                 ("hackers_back", "해커스", None, "hackers"),
                 ("cambridge", "Cambridge", "https://dictionary.cambridge.org/", "cambridge"),
                 ("oxford", "Oxford", "https://www.oxfordlearnersdictionaries.com/", "oxford")],
            )
            db.executemany(
                "INSERT INTO words VALUES (?,?,?,?)",
                [("w1", "sample", "sample", ""), ("w2", "partial", "partial", ""),
                 ("w3", "sample’s type", "sample's type", "")],
            )
            db.executemany(
                """
                INSERT INTO occurrences(occurrence_id,word_id,source_id,source_record_id,day,
                                        original_korean_meaning,verification_status,properties_json)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                [("o1", "w1", "quizlet_324678752", "row1", 1, "원문", "source_attested", "{}"),
                 ("o2", "w1", "hackers_back", "page1.1", 1, "별도 원문", "source_attested", "{}"),
                 ("o3", "w2", "quizlet_324678752", "row2", 2, "미검증 뜻", "source_attested", "{}")],
            )
            db.executemany(
                "INSERT INTO senses VALUES (?,?,?,?,?)",
                [("s1", "w1", "noun", "item", "en"),
                 ("s2", "w2", "adjective", "incomplete", "en"),
                 ("s3", "w3", "noun", "kind", "ko+en")],
            )
            db.execute("INSERT INTO sense_occurrences VALUES ('s1','o1')")
            db.executemany(
                "INSERT INTO english_definitions(sense_id,english_definition,status,verification_date) VALUES (?,?,?,?)",
                [("s1", "An item used for\tcomparison.\n", "cross_verified", "2026-11-27"),
                 ("s2", "A single-source gloss.", "source_attested", "2026-11-27"),
                 ("s3", "A category of sample.", "cross_verified", "2026-11-27")],
            )
            db.executemany(
                "INSERT INTO korean_translations VALUES (?,?,?,?,?)",
                [("s1", None, "uncertain", "문맥을 확인해야 함", "2026-11-27"),
                 ("s2", None, "unverified", None, "2026-11-27"),
                 ("s3", "표본 유형", "verified", None, "2026-11-27")],
            )
            db.executemany(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
                [("w1", "WORD", "sample", None, "w1", "unverified", "{}"),
                 ("s1", "SENSE", "sample", "s1", "w1", "cross_verified", "{}"),
                 ("p1", "PREFIX", "pre-", None, None, "source_attested", "{}"),
                 ("r1", "ETYMOLOGICAL_ROOT", "Root & Form", None, None, "source_attested", "{}"),
                 ("i1", "IDIOM", "sample’s type", None, None, "source_attested",
                  json.dumps({"definition_sense": {"headword": "sample’s type", "part_of_speech": "noun", "sense_key": "kind"}})),
                 ("t1", "THEME", "Test theme", None, None, "source_attested", "{}"),
                 ("fake", "COLLOCATION", "unsupported item", None, None, "unverified",
                  json.dumps({"english_definition_status": "cross_verified", "english_definition": "Unsupported."}))],
            )
            db.executemany(
                "INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
                [("e1", "w1", "p1", "HAS_ETYMOLOGICAL_AFFIX", None, "source_attested", '{"module":"etymology"}'),
                 ("e2", "w1", "r1", "HAS_ETYMOLOGICAL_ROOT", None, "source_attested", '{"module":"etymology"}'),
                 ("e3", "s1", "i1", "PARTICIPATES_IN_IDIOM", "s1", "source_attested", '{"idiom_category":"noun"}'),
                 ("e4", "s1", "t1", "BELONGS_TO_THEME", "s1", "source_attested", '{"module":"lexical_semantics"}'),
                 ("e5", "s1", "fake", "PARTICIPATES_IN_COLLOCATION", "s1", "source_attested", '{}')],
            )
            items = [
                ("edge", item, "cambridge") for item in ("e1", "e2", "e3", "e4", "e5")
            ] + [
                ("english_definition", item, source)
                for item in ("s1", "s3") for source in ("cambridge", "oxford")
            ] + [("english_definition", "s2", "cambridge")]
            db.executemany(
                """
                INSERT INTO evidence(evidence_id,object_type,object_id,source_id,url,source_record_id,
                                     extraction_method,verification_date,properties_json)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [(f"evidence{i}", object_type, object_id, source_id, None, f"rec{i}", "test fixture",
                  "2026-11-27", "{}") for i, (object_type, object_id, source_id) in enumerate(items)],
            )
            db.commit()
        self.data = StudyData(self.database)

    def test_decks_english_fallback_and_phrase_form(self):
        output = self.root / "cards"
        counts = write_decks(self.data, output)
        self.assertEqual(counts["bilingual"]["core_words"], 1)
        self.assertEqual(counts["english_definitions"]["idioms"], 1)
        self.assertEqual(counts["english_definitions"]["collocations"], 0)
        english_cards = (output / "english_definitions/core_words.tsv").read_text()
        self.assertEqual(english_cards, "sample (noun)\tAn item used for comparison.\n")
        bilingual_idioms = (output / "bilingual/idioms.tsv").read_text()
        self.assertEqual(bilingual_idioms, "sample’s type\t표본 유형 · A category of sample.\n")
        self.assertEqual((output / "bilingual/themes.tsv").read_text(), "sample (noun) · 확인된 테마\tTest theme\n")
        for deck in output.rglob("*.tsv"):
            for line in deck.read_text().splitlines():
                self.assertEqual(line.count("\t"), 1)

    def test_notes_use_attested_groups_and_sixty_days(self):
        output = self.root / "notes"
        count, groups = generate_notes(self.data, output)
        self.assertEqual(count, 2)
        self.assertGreaterEqual(groups, 4)
        schedule = (output / "schedule.md").read_text()
        self.assertEqual(len(re.findall(r"^### DAY \d{2}", schedule, re.M)), 60)
        self.assertIn("### DAY 11 어근과 숙어", schedule)
        self.assertIn("Root & Form", schedule)
        self.assertIn("기본명사 중심 숙어", schedule)
        notes = list((output / "part01_core_words").glob("word-*.md"))
        sample_note = next(path.read_text() for path in notes if path.name.startswith("word-sample-"))
        self.assertIn("별도 원문", sample_note)
        self.assertIn("한국어 뜻 불확실", sample_note)
        self.assertIn("영어 정의 교차 검증", sample_note)
        self.assertIn("Cambridge", sample_note)

    def test_network_and_vocabulary_preserve_links(self):
        output = self.root / "network"
        export_network(self.data, output)
        with (output / "vocabulary.csv").open(newline="") as stream:
            first = next(row for row in csv.DictReader(stream) if row["sense_id"] == "s1")
        self.assertEqual(json.loads(first["original_korean_meaning"]), ["원문"])
        self.assertEqual(json.loads(first["aligned_occurrence_ids"]), ["o1"])
        self.assertEqual(len(json.loads(first["occurrences"])), 2)
        self.assertEqual(len(json.loads(first["english_definition_sources"])), 2)
        root = ET.parse(output / "vocabulary.graphml").getroot()
        ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
        node_ids = {node.attrib["id"] for node in root.findall(".//g:node", ns)}
        for edge in root.findall(".//g:edge", ns):
            self.assertIn(edge.attrib["source"], node_ids)
            self.assertIn(edge.attrib["target"], node_ids)
        self.assertIn("Root &amp; Form", (output / "vocabulary.graphml").read_text())


if __name__ == "__main__":
    unittest.main()
