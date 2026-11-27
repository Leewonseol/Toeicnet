import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from batch_rag_verify import ASSESSMENT_FIELDS, adjudicate_english, near_duplicate
from import_gcide import candidate_records

FIXTURE = """<p><ent>Apply</ent><br/
<hw>Ap*ply"</hw> <pr>(x)</pr>, <pos>v. t.</pos> <vmorph>[<pos>imp. &
p. p.</pos> <conjf>Applied</conjf>.]</vmorph> <ety>[OF. <ets>aplier</ets>, fr. L. <ets>applicare</ets>.]</ety>
<sn>1.</sn> <def>To lay or place; to put or adjust.</def><br/
[<source>1913 Webster</source>]</p>

<p><q>He said, and the sword his throat <qex>applied</qex>.</q><br/
[<source>1913 Webster</source>]</p>

<p><sn>2.</sn> <mark>[Obs.]</mark> <def>To visit.</def><br/
[<source>1913 Webster</source>]</p>

<p><pos>v. i.</pos> <sn>3.</sn> <def>To make a formal request for something.</def><br/
[<source>WordNet 1.5</source>]</p>

<p><ent>Other</ent><br/
<hw>Oth"er</hw>, <pos>a.</pos> <def>Different.</def><br/
[<source>PJC</source>]</p>
"""


class GcideTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        Path(self.folder.name, "CIDE.A").write_text(FIXTURE, encoding="latin-1")
        self.rows = list(candidate_records(Path(self.folder.name), {"apply"}, version="test"))

    def tearDown(self):
        self.folder.cleanup()

    def test_definitions_keep_pos_lineage_and_usage_marks(self):
        self.assertEqual([row["definition"] for row in self.rows], [
            "To lay or place; to put or adjust.", "To visit.", "To make a formal request for something."])
        first, obsolete, wordnet = self.rows
        # The verb-morphology <pos> labels must not replace the entry's part of speech.
        self.assertEqual((first["part_of_speech"], first["tags"]), ("verb", ["transitive"]))
        self.assertEqual(first["etymology_text"], "[OF. aplier, fr. L. applicare.]")
        self.assertIn("obsolete", obsolete["tags"])
        self.assertEqual((wordnet["lineage"], wordnet["tags"]), ("wordnet", ["intransitive"]))
        self.assertIn("globalwordnet", wordnet["derived_from"])
        self.assertEqual(first["lineage"], "webster1913")
        self.assertEqual(len({row["source_record_id"] for row in self.rows}), 3)

    def _candidate(self, row, candidate_id):
        return {**row, "candidate_id": candidate_id, "independence_group": "gcide", "payload": row}

    def test_wordnet_derived_gcide_sense_is_not_a_second_source(self):
        gcide = self._candidate(self.rows[2], "g")
        wordnet = {"candidate_id": "n", "source_id": "oewn", "independence_group": "globalwordnet",
                   "source_record_id": "oewn-apply-v-2", "part_of_speech": "verb",
                   "definition": "Ask for something formally, in writing or in person."}
        case = {"case_key": "k", "part_of_speech": "verb", "original_korean_meaning": "지원하다"}
        decision = {"case_key": "k", "verdict": "equivalent", "candidate_ids": ["g", "n"],
                    "definition": "To make a formal request.", "reason": "Same request sense.",
                    "assessment": {field: "Considered." for field in ASSESSMENT_FIELDS}}
        rejected = adjudicate_english([gcide, wordnet], case=case, decision=decision)
        self.assertEqual((rejected["grade"], rejected["review_reason"]),
                         ("D", "Independence of cited definitions is unresolved."))
        webster = self._candidate({**self.rows[0], "definition": "To submit a request in a formal way."}, "w")
        decision["candidate_ids"] = ["w", "n"]
        judged = adjudicate_english([webster, wordnet], case=case, decision=decision)
        self.assertEqual((judged["grade"], judged["source_combination"]), ("B", "open×2"))

    def test_near_duplicate_wording_is_one_source(self):
        self.assertTrue(near_duplicate("That which is required; an essential condition.",
                                       "That which is required; an essential condition"))
        self.assertTrue(near_duplicate("To gain, usually by one's own exertions; to get as one's own.",
                                       "To get, usually by one's own exertions; to gain as one's own."))
        self.assertFalse(near_duplicate("A length of time.", "An interval with a known length."))


if __name__ == "__main__":
    unittest.main()
