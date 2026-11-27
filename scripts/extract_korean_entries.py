"""Collect Wiktionary Korean-language entries for the Korean terms used in the textbook glosses.

They give the part of speech of a Korean term and its English glosses. They come from the
same Wiktionary project as the English entries, so they select senses and support Korean
review but never count as a second, independent English definition source.
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rebuild_evidence import korean_terms  # noqa: E402


def variants(term):
    term = re.sub(r"^(~[을를이가에게의와과으로로]*|~)\s*", "", term).strip()
    out = {term}
    rules = ((r"적인$", "적"), (r"한$", "하다"), (r"히$", "하다"), (r"하게$", "하다"), (r"의$", ""),
             (r"([가-힣])인$", r"\1"), (r"된$", "되다"), (r"는$", "다"), (r"하는$", "하다"), (r"스러운$", "스럽다"))
    for pattern, repl in rules:
        if re.search(pattern, term):
            out.add(re.sub(pattern, repl, term))
    return {t for t in out if t}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--input", type=Path, default=Path("data/external/raw-wiktextract-data.jsonl.gz"))
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/kaikki_korean.jsonl"))
    args = parser.parse_args()
    wanted = set()
    for line in args.items.open(encoding="utf-8"):
        row = json.loads(line)
        for group in row["korean_groups"]:
            for term in korean_terms(group):
                wanted |= variants(term)
    count = 0
    with gzip.open(args.input, "rt", encoding="utf-8") as handle, args.output.open("w", encoding="utf-8") as out:
        for line in handle:
            if '"lang_code": "ko"' not in line:
                continue
            record = json.loads(line)
            if record.get("lang_code") != "ko" or record.get("word") not in wanted:
                continue
            senses = [{"gloss": (s.get("glosses") or [""])[-1], "tags": s.get("tags", [])} for s in record.get("senses", [])]
            out.write(json.dumps({"word": record["word"], "pos": record.get("pos"), "senses": senses,
                                  "record_id": f"kaikki-ko:{record['word']}:{record.get('pos')}:{count}"},
                                 ensure_ascii=False) + "\n")
            count += 1
    print(len(wanted), "Korean terms wanted;", count, "Korean entries found")


if __name__ == "__main__":
    main()
