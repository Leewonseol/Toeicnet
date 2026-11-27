"""Check the boundary between native WordNet records and study claims."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_wordnet_relations import database_records, export, resolve
from import_wordnet import candidate_records

WN_LMF = """<LexicalResource><Lexicon version="test">
 <LexicalEntry><Lemma writtenForm="alpha" partOfSpeech="n"/>
  <Sense id="a1" synset="x"><SenseRelation relType="antonym" target="c1"/></Sense>
  <Sense id="a2" synset="y"/>
 </LexicalEntry>
 <LexicalEntry><Lemma writtenForm="beta" partOfSpeech="n"/><Sense id="b1" synset="x"/></LexicalEntry>
 <LexicalEntry><Lemma writtenForm="gamma" partOfSpeech="n"/><Sense id="c1" synset="z"/></LexicalEntry>
 <Synset id="x" ili="i1"><Definition>A shared meaning.</Definition>
  <SynsetRelation relType="hypernym" target="y"/>
 </Synset>
 <Synset id="y" ili="i2"><Definition>A separate meaning.</Definition></Synset>
 <Synset id="z" ili="i3"><Definition>An opposite meaning.</Definition></Synset>
</Lexicon></LexicalResource>"""


class WordnetExportTest(unittest.TestCase):
    def fixtures(self, folder, expansion=True):
        path = folder / "fixture.xml"
        path.write_text(WN_LMF, encoding="utf-8")
        return list(candidate_records(path, {"alpha", "beta"}, expansion=expansion))

    def test_exact_senses_and_native_relation_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            senses, synsets, links = resolve(self.fixtures(Path(temporary)))
        self.assertEqual({row["native_sense_id"] for row in senses if row["headword"] == "alpha"}, {"a1", "a2"})
        self.assertEqual({row["native_synset_id"] for row in synsets}, {"x", "y", "z"})
        hypernyms = [row for row in links if row["native_relation_type"] == "hypernym"]
        self.assertEqual(len(hypernyms), 1)
        self.assertEqual((hypernyms[0]["from_native_id"], hypernyms[0]["to_native_id"]), ("x", "y"))
        self.assertEqual(hypernyms[0]["relation_type"], "HYPONYM_OF")
        self.assertEqual(hypernyms[0]["anchor_native_sense_ids"], ["a1", "b1"])
        self.assertEqual(hypernyms[0]["from_node_type"], "synset")
        antonym = next(row for row in links if row["native_relation_type"] == "antonym")
        self.assertEqual((antonym["from_native_id"], antonym["to_native_id"]), ("a1", "c1"))
        co_membership = next(row for row in links if row["basis"] == "shared_synset_membership")
        self.assertEqual(co_membership["relation_type"], "SHARES_SYNSET_WITH")
        self.assertEqual(co_membership["candidate_relation_type"], "SYNONYM_OF")
        self.assertIsNone(co_membership["native_relation_type"])
        self.assertEqual(co_membership["substitutability"], "unreviewed")
        self.assertEqual(sum(row["relation_type"] == "BELONGS_TO_SYNSET" for row in links), len(senses))

    def test_database_mode_can_keep_exact_endpoint_without_its_local_sense_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            rows = self.fixtures(folder, expansion=False)
            with sqlite3.connect(folder / "fixture.db") as db:
                db.execute("CREATE TABLE external_candidates(source_id TEXT, payload_json TEXT)")
                db.executemany("INSERT INTO external_candidates VALUES (?,?)",
                               [(row["source_id"], json.dumps(row)) for row in rows])
                db.execute("INSERT INTO external_candidates VALUES (?,?)", ("kaikki", "not queried"))
            summary = export(database_records(folder / "fixture.db"), folder / "output")
            outfile = folder / "output" / "relations.jsonl"
            rels = [json.loads(line) for line in outfile.read_text(encoding="utf-8").splitlines()]
            antonym = next(row for row in rels if row["native_relation_type"] == "antonym")
            self.assertEqual(antonym["to_native_id"], "c1")
            self.assertFalse(antonym["to_record_available"])
            self.assertEqual(summary["workbook_sense_assignments"], 0)
            self.assertEqual(summary["connections_without_target_sense_record"], 1)
            notice = (folder / "output" / "ATTRIBUTION.txt").read_text(encoding="utf-8")
            self.assertIn("Princeton University", notice)
            self.assertIn("creativecommons.org/licenses/by/4.0", notice)

    def test_invalid_sense_join_does_not_infer_an_endpoint_from_spelling(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows = self.fixtures(Path(temporary))
        altered = [
            dict(row, target_synset_id="x") if row.get("relation_type") == "ANTONYM_OF" else row
            for row in rows
        ]
        with self.assertRaisesRegex(ValueError, "Conflicting synset IDs"):
            resolve(altered)


if __name__ == "__main__":
    unittest.main()
