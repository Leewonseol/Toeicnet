"""Exercise source-grounded retrieval without network calls."""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from batch_rag_retrieval import EvidenceRetriever
from review_common import normalized_lemma


class EvidenceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript((SCRIPTS / "schema.sql").read_text(encoding="utf-8"))
        self.db.executemany(
            "INSERT INTO sources(source_id,title,independence_group,license,version) VALUES(?,?,?,?,?)",
            [("hackers_back", "PDF", "local_input", None, None),
             ("oewn", "WordNet", "globalwordnet", "CC BY", "2025"),
             ("kaikki", "Kaikki", "wiktionary", "CC BY-SA", "snapshot"),
             ("gcide", "GCIDE", "gcide", "GPL-3.0-or-later", "0.54")],
        )

    def occurrence(self, word, pos, korean, key):
        normalized = normalized_lemma(word)
        self.db.execute("INSERT OR IGNORE INTO words VALUES(?,?,?,?)", (word, word, normalized, ""))
        self.db.execute("""
            INSERT INTO occurrences(occurrence_id,word_id,source_id,source_record_id,day,
              original_korean_meaning,part_of_speech,verification_status,properties_json)
            VALUES(?,?, 'hackers_back',?,1,?,?,'source_attested','{}')
        """, (key, word, key, korean, pos))

    def candidate(self, key, word, definition=None, pos="noun", source="oewn", **extras):
        kind = "sense_candidate" if definition else "relation_candidate"
        payload = {
            "kind": kind, "headword": word, "source_id": source, "source_record_id": key,
            "part_of_speech": pos, "external_sense_id": key,
            "extraction_method": "fixture", "verification_status": "source_attested",
            **extras,
        }
        if definition is not None:
            payload["definition"] = definition
        self.db.execute("INSERT INTO external_candidates VALUES(?,?,?,?,?,?,?)", (
            key, kind, word, source, key, json.dumps(payload), normalized_lemma(word),
        ))

    def packets(self, limit=6):
        retriever = EvidenceRetriever(self.db)
        return {target["occurrence_id"]: retriever.retrieve(target, per_channel=limit)
                for target in retriever.targets()}

    def test_gcide_lineage_reaches_the_verifier(self):
        from batch_rag_verify import ASSESSMENT_FIELDS, adjudicate_english
        self.occurrence("apply", "verb", "지원하다", "apply-page")
        self.candidate("wn", "apply", "Ask for something formally.", pos="verb")
        self.candidate("gw", "apply", "To make a formal request for something.", pos="verb", source="gcide",
                       lineage="wordnet", derived_from=["globalwordnet", "oewn", "wordnet"])
        self.candidate("gb", "apply", "To submit a written request.", pos="verb", source="gcide",
                       lineage="webster1913", derived_from=["webster1913"])
        packet = self.packets()["apply-page"]
        senses = {row["source_record_id"]: row for row in packet["senses"]}
        self.assertEqual({senses[key]["source_id"] for key in senses}, {"oewn", "gcide"})
        case = {"case_key": "k", "part_of_speech": "verb", "original_korean_meaning": "지원하다"}

        def judge(*keys):
            decision = {"case_key": "k", "verdict": "equivalent",
                        "candidate_ids": [senses[key]["candidate_id"] for key in keys],
                        "definition": "To request formally.", "reason": "Same sense.",
                        "assessment": {field: "Considered." for field in ASSESSMENT_FIELDS}}
            return adjudicate_english(packet["senses"], case=case, decision=decision)["grade"]

        self.assertEqual(judge("wn", "gw"), "D")
        self.assertEqual(judge("wn", "gb"), "B")

    def test_korean_spelling_clue_reranks_without_verifying_a_sense(self):
        self.occurrence("claim", "noun", "주장, 요구", "claim-page")
        self.candidate("a", "claim", "A request for compensation.", source="kaikki")
        self.candidate("b", "claim", "An assertion.", source="kaikki")
        self.candidate("c", "claim", "To assert something.", pos="verb")
        self.candidate("translation", "claim", source="kaikki",
                       relation_type="KOREAN_TRANSLATION_CANDIDATE", external_sense_id="b",
                       target_headword="주장", details={"source_sense_label": "an assertion"})
        result = self.packets(limit=1)["claim-page"]
        self.assertEqual([row["candidate_id"] for row in result["baseline_senses"]], ["a"])
        self.assertEqual([row["candidate_id"] for row in result["senses"]], ["b"])
        self.assertEqual(result["senses"][0]["rank_features"]["korean_anchor_evidence_refs"], ["translation"])
        self.assertEqual(result["senses"][0]["alignment_status"], "unreviewed")
        self.assertEqual(result["match_counts"]["senses"], 2)
        self.assertEqual(result["reviewed"], [])

    def test_expansion_requires_attested_forms_and_compatible_pos(self):
        self.occurrence("criteria", "noun", "기준", "criteria-page")
        self.candidate("lemma", "criterion", "A standard for judgment.")
        self.candidate("wrong-pos", "criterion", "An incompatible meaning.", pos="verb")
        self.candidate("fake-stem", "criteri", "Unrelated.")
        self.candidate("link", "criterion", source="kaikki", relation_type="HAS_INFLECTION",
                       target_headword="criteria", details={"tags": ["plural"]})
        result = self.packets()["criteria-page"]
        self.assertEqual(result["baseline_senses"], [])
        self.assertEqual([row["candidate_id"] for row in result["senses"]], ["lemma"])
        self.assertEqual(result["senses"][0]["match_method"], "source_attested_inflection")
        self.assertEqual(result["senses"][0]["alias_evidence"][0]["evidence_ref"], "link")

    def test_slash_alternants_keep_whole_phrase_and_share_synset_as_clue(self):
        self.occurrence("fill out/in", "phrase", "기입하다", "form-page")
        self.occurrence("go up/down", "phrase", "이동하다", "direction-page")
        self.candidate("a-unrelated", "fill in", "Substitute for someone.", pos="verb", synset_id="s2")
        self.candidate("b-form", "fill in", "Enter required information.", pos="verb", synset_id="s1")
        self.candidate("c-form", "fill out", "Enter required information.", pos="verb", synset_id="s1")
        self.candidate("noise", "fill", "Make full.", pos="verb")
        self.candidate("one-alternate", "go up", "Move upward.", pos="verb")
        results = self.packets(limit=2)
        candidates = results["form-page"]["senses"]
        self.assertEqual([row["candidate_id"] for row in candidates], ["b-form", "c-form"])
        self.assertTrue(all(row["rank_features"]["shared_alternant_synset"] for row in candidates))
        self.assertTrue(all(row["match_method"] == "source_explicit_alternant" for row in candidates))
        self.assertEqual(candidates[0]["alias_evidence"][0]["evidence_ref"], "form-page")
        self.assertEqual(results["direction-page"]["senses"], [])

    def test_reviewed_meaning_applies_only_to_explicit_occurrence_anchor(self):
        self.occurrence("bank", "noun", "은행", "finance-page")
        self.occurrence("bank", "noun", "둑", "river-page")
        self.db.execute("INSERT INTO senses VALUES('finance-sense','bank','noun','banking','en')")
        self.db.execute("""INSERT INTO english_definitions VALUES(
            'finance-sense','An institution providing financial services.','cross_verified','2026-11-27','paraphrase'
        )""")
        self.db.execute("INSERT INTO korean_translations VALUES('finance-sense',NULL,'unverified',NULL,'2026-11-27')")
        self.db.execute("INSERT INTO sense_occurrences VALUES('finance-sense','finance-page')")
        results = self.packets()
        self.assertEqual(results["finance-page"]["reviewed"][0]["english_status"], "cross_verified")
        self.assertEqual(results["river-page"]["reviewed"], [])


if __name__ == "__main__":
    unittest.main()
