"""Check that the Anki export applies review grades and independent Korean status."""

import csv
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from batch_rag_study import export_batch_study


class BatchStudyTest(unittest.TestCase):
    def test_grade_and_translation_are_preserved_in_anki_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "toeic.db"
            with closing(sqlite3.connect(database)) as db:
                db.executescript((ROOT / "scripts/schema.sql").read_text())
                db.executemany(
                    "INSERT INTO sources(source_id,title,independence_group) VALUES (?,?,?)",
                    [("hackers_anki_user", "Anki", "input"), ("cambridge", "Cambridge", "cambridge"),
                     ("oxford", "Oxford", "oxford"), ("oewn", "WordNet", "wordnet"),
                     ("kaikki", "Wiktionary", "wiktionary")],
                )
                db.executemany("INSERT INTO words VALUES (?,?,?,?)", [
                    ("known", "known", "known", ""), ("open", "open", "open", ""),
                ])
                db.execute("""
                    INSERT INTO occurrences(occurrence_id,word_id,source_id,source_record_id,day,
                                            verification_status,properties_json)
                    VALUES ('o1','known','hackers_anki_user','1',1,'source_attested','{}')
                """)
                db.execute("INSERT INTO senses VALUES ('s1','known','adjective','recognized','en')")
                db.execute("INSERT INTO sense_occurrences VALUES ('s1','o1')")
                db.execute("INSERT INTO english_definitions VALUES ('s1','Recognized.','cross_verified',NULL,'paraphrase')")
                db.execute("INSERT INTO korean_translations VALUES ('s1',NULL,'uncertain',NULL,NULL)")
                db.executemany("""
                    INSERT INTO evidence(evidence_id,object_type,object_id,source_id,
                                         extraction_method,properties_json)
                    VALUES (?,'english_definition','s1',?,'fixture','{"sense_match":"matched"}')
                """, [("e1", "cambridge"), ("e2", "oxford")])
                db.executemany("INSERT INTO external_candidates VALUES (?,?,?,?,?,?,?)", [
                    ("c1", "sense_candidate", "open", "oewn", "r1", "{}", "open"),
                    ("c2", "sense_candidate", "open", "kaikki", "r2:sense:1", '{"definition":"Available."}', "open"),
                    ("c3", "relation_candidate", "open", "kaikki", "r2:translation:2",
                     '{"relation_type":"KOREAN_TRANSLATION_CANDIDATE","target_headword":"사용 가능",'
                     '"details":{"source_sense_label":"available"}}', "open"),
                ])
                db.commit()

            def assessment(grade, definition, refs, *, aligned=True):
                return {
                    "target": {"occurrence_id": definition, "source_id": "hackers_anki_user", "day": 1,
                               "word_id": "open", "headword": "open", "part_of_speech": "adjective",
                               "original_korean_meaning": "교재 원뜻"},
                    "english": {"grade": grade, "definition": definition, "candidate_ids": refs,
                                "source_alignment": aligned},
                    "korean": {"status": "unverified", "meaning": "미검증 번역"},
                }

            independently_reviewed = assessment("B", "Available.", ["c1", "c2"])
            independently_reviewed["target"]["original_korean_meaning"] = "사용 가능"
            independently_reviewed["korean"] = {
                "status": "verified", "meaning": "사용 가능", "method": "dedicated_bilingual_review",
                "english_candidate_id": "c2", "candidate_ids": ["c3"],
            }
            records = [
                independently_reviewed,
                assessment("B", "Invalid promotion.", ["c1", "c1"]),
                assessment("C", "Not closed.", ["c1"]),
                assessment("C", "Unaligned.", ["c1"], aligned=False),
                assessment("D", "Review only.", ["c2"]),
            ]
            summary = export_batch_study(database, records, root / "notes", root / "anki", regenerate_original=False)
            self.assertEqual(summary["cards_by_grade"], {"A": 1, "B": 1, "C": 1})
            self.assertEqual(summary["occurrences_by_grade"]["B"], 2)
            file_b = (root / "anki" / "grade_b.tsv").read_text()
            entries = list(csv.reader(file_b.splitlines()[6:], delimiter="\t"))
            self.assertEqual(len(entries[0]), 3)
            self.assertIn("#tags column:3", file_b)
            self.assertIn("CC BY-SA 4.0", entries[0][1])
            self.assertIn("toeicnet::ko::verified", entries[0][2])
            self.assertIn("r2:translation:2", entries[0][1])
            self.assertIn("사용 가능", entries[0][1])
            file_c = (root / "anki" / "grade_c.tsv").read_text()
            self.assertIn("toeicnet::ko::unverified", file_c)
            self.assertNotIn("미검증 번역", file_b)
            self.assertNotIn("교재 원뜻", file_b)
            self.assertNotIn("Invalid promotion", file_b)
            self.assertFalse((root / "anki" / "grade_d.tsv").exists())


if __name__ == "__main__":
    unittest.main()
