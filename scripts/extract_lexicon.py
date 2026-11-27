"""Collect complete WordNet, Wiktextract and GCIDE records for the rebuilt source headwords.

The output keeps each source record whole, with its own identifier, so later analysis
cites records instead of re-deriving them. Wiktextract is read in two passes: the first
collects entries spelled like a target and the lemmas their ``form_of`` points to, the
second collects those lemmas.
"""

import argparse
import gzip
import json
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from import_gcide import candidate_records as gcide_records  # noqa: E402

POS = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).replace("’", "'").casefold().split())


def targets(path):
    words = set()
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        if row["duplicate_of"]:
            continue
        words.add(row["normalized"])
        words.update(normalize(rel["target"]) for rel in row["textbook_relations"])
    return words


def wordnet(path, wanted):
    """Return {lemma: [sense...]} with synset gloss, lexfile, members and relations."""
    entries, synsets, sense_lemma, entry_lemma = defaultdict(list), {}, {}, {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag == "LexicalEntry":
                lemma = element.find("Lemma")
                form = lemma.get("writtenForm")
                entry_lemma[element.get("id")] = form
                for sense in element.findall("Sense"):
                    sense_lemma[sense.get("id")] = form
                    if normalize(form) in wanted:
                        entries[normalize(form)].append({
                            "sense_id": sense.get("id"), "lemma": form, "pos": POS.get(lemma.get("partOfSpeech")),
                            "synset": sense.get("synset"),
                            "relations": [(rel.get("relType"), rel.get("target")) for rel in sense.findall("SenseRelation")],
                        })
                element.clear()
            elif element.tag == "Synset":
                synsets[element.get("id")] = {
                    "lexfile": element.get("lexfile"), "members": element.get("members", "").split(),
                    "definition": " ".join((element.findtext("Definition") or "").split()),
                    "examples": [" ".join((ex.text or "").split()) for ex in element.findall("Example")][:3],
                    "relations": [(rel.get("relType"), rel.get("target")) for rel in element.findall("SynsetRelation")],
                }
                element.clear()
    member_lemma = entry_lemma
    for senses in entries.values():
        for sense in senses:
            synset = synsets[sense["synset"]]
            sense.update(definition=synset["definition"], examples=synset["examples"], lexfile=synset["lexfile"],
                         synonyms=sorted({member_lemma.get(m, m) for m in synset["members"]} - {sense["lemma"]}),
                         synset_relations=synset["relations"])
            sense["relations"] = [(kind, sense_lemma.get(target, target)) for kind, target in sense["relations"]]
            sense["hypernyms"] = [synsets[target]["definition"] for kind, target in synset["relations"]
                                  if kind == "hypernym" and target in synsets][:2]
    return entries


def wiktextract_pass(path, wanted):
    found, lemmas = [], set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if '"lang_code": "en"' not in line:
                continue
            record = json.loads(line)
            if record.get("lang_code") != "en" or normalize(record.get("word", "")) not in wanted:
                continue
            found.append(record)
            for sense in record.get("senses", []):
                for item in sense.get("form_of", []) + sense.get("alt_of", []):
                    if item.get("word"):
                        lemmas.add(normalize(item["word"]))
    return found, lemmas


KEEP = ("word", "pos", "etymology_number", "etymology_text", "etymology_templates", "head_templates",
        "forms", "senses", "derived", "related", "synonyms", "antonyms", "translations", "hyphenation")


def compact(record, index):
    kept = {key: record[key] for key in KEEP if key in record}
    kept["record_id"] = f"kaikki:{normalize(record['word'])}:{record.get('pos')}:{record.get('etymology_number', 0)}:{index}"
    kept["translations"] = [t for t in record.get("translations", []) if t.get("lang_code") == "ko"]
    for sense in kept.get("senses", []):
        sense["translations"] = [t for t in sense.get("translations", []) if t.get("lang_code") == "ko"]
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--external", type=Path, default=Path("data/external"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/rebuild"))
    parser.add_argument("--only", choices=("wordnet", "kaikki", "gcide"), action="append")
    args = parser.parse_args()
    wanted = targets(args.items)
    only = set(args.only or ("wordnet", "kaikki", "gcide"))
    if "wordnet" in only:
        senses = wordnet(args.external / "english-wordnet-2025.xml.gz", wanted)
        (args.output_dir / "wordnet_targets.json").write_text(json.dumps(senses, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wordnet lemmas", len(senses), "senses", sum(map(len, senses.values())))
    if "gcide" in only:
        rows = list(gcide_records(args.external / "gcide-0.54.tar.xz", wanted, version="0.54"))
        with (args.output_dir / "gcide_targets.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("gcide definitions", len(rows))
    if "kaikki" in only:
        path = args.external / "raw-wiktextract-data.jsonl.gz"
        first, lemmas = wiktextract_pass(path, wanted)
        extra = lemmas - wanted
        second, _ = wiktextract_pass(path, extra) if extra else ([], set())
        with (args.output_dir / "kaikki_targets.jsonl").open("w", encoding="utf-8") as handle:
            for index, record in enumerate(first + second):
                row = compact(record, index)
                row["lookup"] = "lemma_of_target" if normalize(record["word"]) in extra else "target"
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("kaikki records", len(first), "lemma records", len(second))


if __name__ == "__main__":
    main()
