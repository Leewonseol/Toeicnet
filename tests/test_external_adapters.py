"""Checks for candidate scope, evidence direction and annotated corpus counts."""

import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from download_datasets import checksum, download
from import_corpus import association, sentence_tokens
from import_wiktextract import candidate_records as wiktextract_candidates
from import_wordnet import candidate_records as wordnet_candidates


class ExternalAdaptersTest(unittest.TestCase):
    def test_wordnet_relations_keep_sense_ids_and_semantic_direction(self):
        fixture = """<LexicalResource><Lexicon version="test">
        <LexicalEntry><Lemma writtenForm="worda" partOfSpeech="n"/>
          <Sense id="s1" synset="x"><SenseRelation relType="antonym" target="s3"/></Sense>
        </LexicalEntry>
        <LexicalEntry><Lemma writtenForm="wordb" partOfSpeech="n"/><Sense id="s2" synset="x"/></LexicalEntry>
        <LexicalEntry><Lemma writtenForm="wordc" partOfSpeech="n"/><Sense id="s3" synset="y"/></LexicalEntry>
        <Synset id="x" ili="i1"><Definition>First meaning.</Definition>
          <SynsetRelation relType="hypernym" target="y"/>
        </Synset><Synset id="y"><Definition>Second meaning.</Definition></Synset>
        </Lexicon></LexicalResource>"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.xml.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write(fixture)
            rows = list(wordnet_candidates(path, {"worda"}))
        synonyms = [row for row in rows if row.get("relation_type") == "SYNONYM_OF"]
        self.assertEqual([(row["external_sense_id"], row["target_external_sense_id"]) for row in synonyms],
                         [("s1", "s2")])
        self.assertEqual(synonyms[0]["details"]["substitutability"], "unreviewed")
        self.assertTrue(any(row.get("relation_type") == "HYPONYM_OF" and row["target_synset_id"] == "y"
                            for row in rows))
        self.assertEqual({row["headword"] for row in rows if row.get("expansion")}, {"wordb", "wordc"})

    def test_wiktextract_filters_english_and_keeps_narrative_distinct_from_templates(self):
        english = {
            "word": "worda", "pos": "noun", "lang_code": "en",
            "senses": [{"glosses": ["An item."], "tags": ["countable"]}],
            "forms": [{"form": "wordae", "tags": ["plural"]}, {"form": "wordaa", "tags": ["alternative"]}],
            "etymology_text": "A test narrative with no automatic segmentation.",
            "etymology_templates": [{"name": "surf", "args": {"1": "en", "2": "word", "3": "-a"}}],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.jsonl"
            rows = [json.dumps(dict(english, lang_code="la")),
                    json.dumps(english).replace('"en"', r'"\u0065n"')]
            path.write_text("\n".join(rows), encoding="utf-8")
            stats = {}
            rows = list(wiktextract_candidates(path, {"worda"}, "test", stats))
            fast_stats = {}
            fast_rows = list(wiktextract_candidates(path, {"worda"}, "test", fast_stats, fast_language_filter=True))
        self.assertEqual(stats["entries"], 1)
        self.assertEqual(rows, fast_rows)
        self.assertEqual({row.get("relation_type") for row in rows if row["kind"] == "relation_candidate"},
                         {"HAS_INFLECTION", "HAS_VARIANT_FORM", "ETYMOLOGY_NARRATIVE", "MORPHOLOGICAL_TEMPLATE"})
        self.assertEqual(next(row for row in rows if row["kind"] == "sense_candidate")["external_sense_id"],
                         "kaikki:test:line:2:sense:1")

    def test_oanc_aligns_unicode_char_offsets_to_sentence_boundaries(self):
        hepple = b"""<graph xmlns="http://www.xces.org/ns/GrAF/1.0/">
        <region xml:id="r1" anchors="0 1"/><node xml:id="n1"><link targets="r1"/></node>
        <a label="tok" ref="n1"><fs><f name="base" value="x"/><f name="msd" value="NN"/></fs></a>
        <region xml:id="r2" anchors="2 5"/><node xml:id="n2"><link targets="r2"/></node>
        <a label="tok" ref="n2"><fs><f name="base" value="get"/><f name="msd" value="VBD"/></fs></a>
        </graph>"""
        sentences = b"""<graph xmlns="http://www.xces.org/ns/GrAF/1.0/">
        <region xml:id="s1" anchors="0 5"/><node xml:id="sn1"><link targets="s1"/></node>
        <a label="s" ref="sn1"/>
        </graph>"""
        segments = list(sentence_tokens("é got.", hepple, sentences))
        self.assertEqual([(token.lemma, token.pos) for token in segments[0][2]], [("x", "noun"), ("get", "verb")])
        self.assertEqual(association(5, 10, 10, 100)["logdice"], 13.0)

    def test_wiktextract_korean_translation_preserves_source_gloss_without_alignment(self):
        entry = {
            "word": "sample", "pos": "noun", "lang_code": "en",
            "translations": [
                {"code": "de", "word": "Probe"},
                {"code": "ko", "word": "견본", "sense": "an item selected for testing"},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "entry.jsonl"
            path.write_text(json.dumps(entry), encoding="utf-8")
            rows = list(wiktextract_candidates(path, {"sample"}, "test", {}, korean_translations_only=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_record_id"], "line:1:translation:2")
        self.assertEqual(rows[0]["target_headword"], "견본")
        self.assertEqual(rows[0]["details"]["source_sense_label"], "an item selected for testing")
        self.assertEqual(rows[0]["details"]["korean_translation_status"], "unverified")

    def test_adoption_requires_pinned_or_recorded_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            file = directory / "fixture.gz"
            file.write_bytes(b"fixture")
            config = {"download_allowed": True, "download_url": "https://example.org/fixture.gz",
                      "version": "test", "license": "test-fixture"}
            with self.assertRaisesRegex(ValueError, "checksum"):
                download("fixture", config, directory, None)
            result = download("fixture", dict(config, sha256=checksum(file)), directory, None)
            self.assertEqual(result["size_bytes"], 7)


if __name__ == "__main__":
    unittest.main()
