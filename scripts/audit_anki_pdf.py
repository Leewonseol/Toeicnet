"""Compare Anki deck categories with image-reviewed PDF rows by exact DAY and headword."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from import_anki import SOURCE_ID as ANKI_ID
from intake_common import read_jsonl, sha256_file, write_json
from normalize import HACKERS_ID, normalize_records


ANKI_CORE = "01.빈출단어"
ANKI_BACK = {
    "02.토익기초단어": "basic",
    "03.800점": "800",
    "04.900점": "900",
}
PDF_GROUPS = {
    "토익 기초 단어": "basic",
    "800점 완성 단어": "800",
    "900점 완성 단어": "900",
}


def load_anki(path):
    rows = []
    for row in normalize_records(read_jsonl(path)):
        if row["source_id"] != ANKI_ID:
            raise ValueError(f"{path}: expected records from the Anki importer")
        components = row["category"].split("::")
        day = row["day"]
        if len(components) < 2 or day is None or components[-1] != f"DAY{day:02d}":
            raise ValueError(f"{path}: category and explicit DAY must agree")
        deck = components[-2]
        if deck not in ANKI_BACK and deck != ANKI_CORE:
            raise ValueError(f"{path}: unsupported deck category")
        rows.append({**row, "deck_category": deck, "audit_category": ANKI_BACK.get(deck)})
    if not rows:
        raise ValueError(f"{path}: expected at least one Anki row")
    return rows


def load_pdf(path):
    rows = []
    for row in read_jsonl(path):
        if row["source_id"] != HACKERS_ID or row.get("review_status") != "image_reviewed":
            continue
        kind = (row.get("category") or "").split(" / ", 1)[0]
        if kind not in PDF_GROUPS or not row.get("day") or not row.get("headword_key"):
            raise ValueError(f"{path}: each image-reviewed row needs a known category, DAY, and headword key")
        rows.append({**row, "audit_category": PDF_GROUPS[kind]})
    if not rows:
        raise ValueError(f"{path}: expected at least one image-reviewed PDF row")
    return rows


def count_overlap(pdf_rows, anki_rows, fields):
    pdf_counts = Counter(tuple(row[field] for field in fields) for row in pdf_rows)
    anki_counts = Counter(tuple(row[field] for field in fields) for row in anki_rows)
    common = pdf_counts.keys() & anki_counts.keys()
    return {
        "pdf_distinct": len(pdf_counts),
        "anki_distinct": len(anki_counts),
        "shared_distinct": len(common),
        "pdf_rows_with_match": sum(pdf_counts[key] for key in common),
        "anki_rows_with_match": sum(anki_counts[key] for key in common),
        "paired_rows": sum((pdf_counts & anki_counts).values()),
        "pdf_only_distinct": len(pdf_counts.keys() - anki_counts.keys()),
        "anki_only_distinct": len(anki_counts.keys() - pdf_counts.keys()),
    }


def audit(anki_path, pdf_path):
    anki = load_anki(anki_path)
    pdf = load_pdf(pdf_path)
    days = sorted({row["day"] for row in pdf})
    pdf_pages = {(row["filename"], row["pdf_page"]) for row in pdf}
    anki_back = [row for row in anki if row["audit_category"] is not None]
    anki_core = [row for row in anki if row["deck_category"] == ANKI_CORE]
    back_reviewed_days = [row for row in anki_back if row["day"] in days]
    core_reviewed_days = [row for row in anki_core if row["day"] in days]

    exact = ("day", "headword_key")
    category_exact = (*exact, "audit_category")
    result = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {str(path): sha256_file(path) for path in (anki_path, pdf_path)},
        "comparison": {
            "scope": "image-reviewed PDF rows only",
            "primary_key": "DAY and exact normalized headword",
            "normalization": "Unicode normalization, whitespace, apostrophe and case only",
            "fuzzy_matching": False,
            "pdf_reviewed_pages": len(pdf_pages),
            "pdf_reviewed_rows": len(pdf),
            "reviewed_days": days,
            "unreviewed_days": sorted(set(range(1, 31)) - set(days)),
            "anki_total_rows": len(anki),
            "anki_core_rows": len(anki_core),
            "anki_back_rows": len(anki_back),
            "anki_back_rows_on_reviewed_days": len(back_reviewed_days),
            "anki_deck_group_counts": dict(sorted(Counter(row["deck_category"] for row in anki).items())),
        },
        "same_day_exact": count_overlap(pdf, back_reviewed_days, exact),
        "same_day_raw_exact": count_overlap(pdf, back_reviewed_days, ("day", "original_headword")),
        "same_day_same_group_exact": count_overlap(pdf, back_reviewed_days, category_exact),
        "core_pdf_cross_check_same_day_exact": count_overlap(pdf, core_reviewed_days, exact),
        "per_day": [],
        "per_group": [],
    }
    for day in days:
        pdf_day = [row for row in pdf if row["day"] == day]
        anki_day = [row for row in back_reviewed_days if row["day"] == day]
        result["per_day"].append({
            "day": day,
            "pdf_reviewed_pages": len({(row["filename"], row["pdf_page"]) for row in pdf_day}),
            "pdf_rows": len(pdf_day),
            "anki_back_rows": len(anki_day),
            "same_day_exact": count_overlap(pdf_day, anki_day, exact),
            "same_day_same_group_exact": count_overlap(pdf_day, anki_day, category_exact),
        })
    for group in PDF_GROUPS.values():
        pdf_group = [row for row in pdf if row["audit_category"] == group]
        anki_group = [row for row in back_reviewed_days if row["audit_category"] == group]
        result["per_group"].append({
            "group": group,
            "pdf_rows": len(pdf_group),
            "anki_back_rows": len(anki_group),
            "same_day_same_group_exact": count_overlap(pdf_group, anki_group, category_exact),
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anki", type=Path, help="Full Anki import JSONL with deck categories")
    parser.add_argument("pdf", type=Path, help="Normalized JSONL containing image-reviewed PDF rows")
    parser.add_argument("--output", type=Path, required=True, help="Aggregate results JSON")
    args = parser.parse_args()
    try:
        result = audit(args.anki, args.pdf)
        if args.output.resolve() in {args.anki.resolve(), args.pdf.resolve()}:
            raise ValueError("Output must be different from both inputs")
        write_json(args.output, result)
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    compared = result["comparison"]["pdf_reviewed_rows"]
    matched = result["same_day_exact"]["pdf_rows_with_match"]
    print(f"Matched {matched}/{compared} image-reviewed PDF rows")


if __name__ == "__main__":
    main()
