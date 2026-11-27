"""Load the extracted lexicon records and give each source item its candidate evidence.

Every candidate carries a stable reference (WordNet sense ID, Wiktextract record and sense
index, GCIDE record ID) so that a reviewed decision can cite exactly what supports it.
"""

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

DATA = Path("data/rebuild")
OLD_TAGS = {"obsolete", "archaic", "historical", "dated", "rare"}
POS_ALIASES = {"adj": "adjective", "adv": "adverb", "noun": "noun", "verb": "verb", "phrase": "phrase",
               "prep": "preposition", "prep_phrase": "phrase", "conj": "conjunction", "intj": "interjection",
               "name": "proper", "num": "numeral", "pron": "pronoun", "det": "determiner", "particle": "particle"}


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text or "").replace("’", "'").casefold().split())


class Lexicon:
    def __init__(self, directory=DATA):
        self.wordnet = json.loads((directory / "wordnet_targets.json").read_text(encoding="utf-8"))
        self.kaikki = defaultdict(list)
        for line in (directory / "kaikki_targets.jsonl").open(encoding="utf-8"):
            record = json.loads(line)
            self.kaikki[normalize(record["word"])].append(record)
        self.gcide = defaultdict(list)
        for line in (directory / "gcide_targets.jsonl").open(encoding="utf-8"):
            record = json.loads(line)
            self.gcide[normalize(record["headword"])].append(record)

    def wn_senses(self, word):
        return self.wordnet.get(normalize(word), [])

    def kk_senses(self, word):
        """Flatten Wiktextract senses with a stable ID and the entry's Korean translation table."""
        rows = []
        for record in self.kaikki.get(normalize(word), []):
            pos = POS_ALIASES.get(record.get("pos"), record.get("pos"))
            table = record.get("translations", [])
            for index, sense in enumerate(record.get("senses", [])):
                glosses = sense.get("glosses") or sense.get("raw_glosses") or []
                if not glosses:
                    continue
                tags = set(sense.get("tags", []))
                rows.append({
                    "id": f"{record['record_id']}:s{index}", "pos": pos, "gloss": glosses[-1],
                    "tags": sorted(tags), "old": bool(tags & OLD_TAGS),
                    "form_of": [item.get("word") for item in sense.get("form_of", []) + sense.get("alt_of", [])],
                    "ko": sorted({t.get("word") for t in sense.get("translations", []) if t.get("word")}),
                    "synonyms": [s.get("word") for s in sense.get("synonyms", [])][:6],
                    "antonyms": [s.get("word") for s in sense.get("antonyms", [])][:6],
                    "examples": [e.get("text") for e in sense.get("examples", []) if e.get("text")][:2],
                    "record_id": record["record_id"], "senseid": sense.get("senseid"),
                })
            for item in table:
                if item.get("word"):
                    rows.append({"id": f"{record['record_id']}:t", "pos": pos, "table_sense": item.get("sense"),
                                 "ko_word": item["word"], "record_id": record["record_id"], "kind": "translation"})
        return rows

    def etymology(self, word):
        out = []
        for record in self.kaikki.get(normalize(word), []):
            if record.get("etymology_text") or record.get("etymology_templates"):
                out.append({
                    "record_id": record["record_id"], "pos": POS_ALIASES.get(record.get("pos"), record.get("pos")),
                    "text": record.get("etymology_text"),
                    "templates": [(t.get("name"), {k: v for k, v in (t.get("args") or {}).items()})
                                  for t in record.get("etymology_templates", [])],
                })
        return out

    def gc_senses(self, word):
        return self.gcide.get(normalize(word), [])


def korean_terms(text):
    """Split a Korean textbook gloss into comparable terms, dropping parenthesized scope notes."""
    text = re.sub(r"\([^)]*\)", " ", text or "")
    text = text.replace("~", " ")
    parts = re.split(r"[,;/·:]|\s{2,}", text)
    return [" ".join(part.split()) for part in parts if part.strip()]
