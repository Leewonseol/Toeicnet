"""Fix a reproducible 100-item sample: 50 core items over DAY 01-30 and 50 back-word items."""

import argparse
import hashlib
import json
from pathlib import Path


def rank(item_id):
    return hashlib.sha256(f"toeicnet-rebuild-v2:{item_id}".encode()).hexdigest()


def sample(rows):
    active = [row for row in rows if not row["duplicate_of"]]
    picked = []
    core = sorted((r for r in active if r["core"]), key=lambda r: rank(r["item_id"]))
    # Two core items per DAY for 20 DAYs and one for the remaining 10, in hash order.
    per_day = {}
    for row in core:
        per_day.setdefault(row["day"], []).append(row)
    order = sorted(per_day, key=lambda day: rank(f"day{day}"))
    for index, day in enumerate(order):
        picked += per_day[day][: 2 if index < 20 else 1]
    for deck, count in (("basic", 15), ("800", 20), ("900", 15)):
        rows_deck = sorted((r for r in active if r["deck"] == deck), key=lambda r: rank(r["item_id"]))
        picked += rows_deck[:count]
    return picked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/sample100.jsonl"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.items.open(encoding="utf-8")]
    picked = sample(rows)
    assert len(picked) == 100, len(picked)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in picked:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(sum(r["core"] for r in picked), "core,", sum(" " in r["normalized"] for r in picked), "multiword")


if __name__ == "__main__":
    main()
