"""Rebuild the source item table from the Anki extraction and record every audit finding.

Inputs are the four Anki deck extractions made by import_anki.py. The script does not
change source text. It adds a normalized headword, splits textbook relation notes such as
``turn off(↔turn on)`` into explicit source relations, marks exact duplicate notes and
splits Korean meanings into the line groups the deck stores (one line per sense group).
"""

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

DECKS = {"core": "anki_core", "basic": "anki_basic", "800": "anki_800", "900": "anki_900"}
RELATION = re.compile(r"\s*\(\s*(?P<mark>=|↔|<->)\s*(?P<other>[^()]+?)\s*\)\s*$")


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("’", "'")
    return " ".join(text.casefold().split())


def split_headword(raw):
    """Return (headword, relations) where relations come from the textbook's own (=x) or (↔x)."""
    match = RELATION.search(raw)
    if not match:
        return raw.strip(), []
    kind = "synonym" if match["mark"] == "=" else "antonym"
    others = [part.strip() for part in match["other"].split(",") if part.strip()]
    return raw[:match.start()].strip(), [{"relation": kind, "target": other} for other in others]


def build(paths):
    rows = []
    for deck, path in paths.items():
        for line in path.open(encoding="utf-8"):
            record = json.loads(line)
            headword, relations = split_headword(record["headword"])
            groups = [" ".join(part.split()) for part in record["original_korean_meaning"].splitlines()]
            rows.append({
                "item_id": f"{DECKS[deck]}:{record['anki_note_id']}",
                "deck": deck, "core": deck == "core", "day": record["day"],
                "raw_headword": record["headword"], "headword": headword, "normalized": normalize(headword),
                "korean_raw": record["original_korean_meaning"], "korean_groups": [g for g in groups if g],
                "textbook_relations": relations,
                "source_record_id": record["source_record_id"], "anki_note_id": record["anki_note_id"],
                "category": record["category"],
            })
    seen = {}
    for row in sorted(rows, key=lambda r: r["anki_note_id"]):
        key = (row["deck"], row["day"], row["normalized"], row["korean_raw"])
        row["duplicate_of"] = seen.get(key)
        seen.setdefault(key, row["item_id"])
    return rows


def audit(rows):
    active = [row for row in rows if not row["duplicate_of"]]
    by_word = defaultdict(list)
    for row in active:
        by_word[row["normalized"]].append(row)
    return {
        "rows": len(rows), "duplicate_rows": sum(1 for row in rows if row["duplicate_of"]),
        "active_items": len(active), "unique_headwords": len(by_word),
        "core_items": sum(row["core"] for row in active),
        "items_by_deck": dict(Counter(row["deck"] for row in active)),
        "items_by_deck_day": {deck: dict(sorted(Counter(r["day"] for r in active if r["deck"] == deck).items()))
                              for deck in DECKS},
        "duplicates_by_location": dict(Counter(f"{r['deck']}:DAY{r['day']:02d}" for r in rows if r["duplicate_of"])),
        "headwords_with_textbook_relations": sum(1 for row in active if row["textbook_relations"]),
        "same_headword_in_several_items": {
            word: [f"{r['deck']}:DAY{r['day']:02d}" for r in group] for word, group in sorted(by_word.items())
            if len(group) > 1
        },
        "multiword_items": sum(1 for row in active if " " in row["normalized"]),
        "korean_multi_group_items": sum(1 for row in active if len(row["korean_groups"]) > 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/intermediate"))
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--audit", type=Path, default=Path("data/rebuild/source_audit.json"))
    args = parser.parse_args()
    rows = build({deck: args.input_dir / f"anki-{deck}.jsonl" for deck in DECKS})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = audit(rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if not isinstance(value, dict)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
