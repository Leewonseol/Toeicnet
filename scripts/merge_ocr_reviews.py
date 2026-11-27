"""Merge page-level image review checkpoints into the OCR review CSVs."""
import argparse
from collections import defaultdict
from pathlib import Path

from intake_common import ENTRY_FIELDS, ENTRY_TYPES, PAGE_FIELDS, read_csv, read_jsonl, write_csv
from normalize import positive_integer
from review_common import normalized_lemma


def page_key(row):
    return row["filename"], positive_integer(row["pdf_page"], "pdf_page", row["filename"])


def merge(ocr_dir, base_pages, base_entries, batches):
    reference = {}
    for row in read_csv(ocr_dir / "candidates.pages.csv", PAGE_FIELDS):
        key = page_key(row)
        if key in reference:
            raise ValueError(f"{key}: duplicate OCR page")
        reference[key] = row

    raw_entries = defaultdict(list)
    for row in read_csv(ocr_dir / "candidates.entries.csv", ENTRY_FIELDS):
        raw_entries[(*page_key(row), normalized_lemma(row["headword"]))].append(row)

    pages = {}
    for row in read_csv(base_pages, PAGE_FIELDS):
        key = page_key(row)
        if key in pages:
            raise ValueError(f"{key}: duplicate base review page")
        pages[key] = row

    entries = defaultdict(list)
    for row in read_csv(base_entries, ENTRY_FIELDS):
        key = page_key(row)
        if key not in pages:
            raise ValueError(f"{key}: base entry has no page review")
        entries[key].append(row)

    for path in batches:
        for row in read_jsonl(path):
            key = page_key(row)
            if key in pages or key not in reference:
                raise ValueError(f"{path}: duplicate or unknown review page {key}")
            checkpoint = reference[key]
            day = positive_integer(row["day"], "day", key)
            printed = row.get("printed_page")
            note = str(row.get("page_note") or "")
            if printed is not None:
                printed = positive_integer(printed, "printed_page", key)
            if not isinstance(row["entries"], list) or (not row["entries"] and not note):
                raise ValueError(f"{path}: expected reviewed entries or a documented empty page for {key}")
            if printed is None and not note:
                raise ValueError(f"{path}: missing print page for {key} must be explained")
            pages[key] = {
                **checkpoint, "day": day, "printed_page": printed, "reviewed_entries": len(row["entries"]),
                "review_status": "image_reviewed", "review_note": note,
            }
            for number, item in enumerate(row["entries"], 1):
                headword = item.get("headword")
                if not isinstance(headword, str) or not normalized_lemma(headword):
                    raise ValueError(f"{key}:{number}: expected a nonempty headword")
                if item.get("entry_type") not in ENTRY_TYPES:
                    raise ValueError(f"{key}:{number}: unsupported entry type")
                matches = raw_entries[(*key, normalized_lemma(headword))]
                exact = matches[0] if len(matches) == 1 else {}
                entries[key].append({
                    "filename": key[0], "source_sha256": checkpoint["source_sha256"],
                    "pdf_page": key[1], "entry_index": number,
                    "headword": headword, "original_korean_meaning": item.get("original_korean_meaning"),
                    "part_of_speech": item.get("part_of_speech"), "entry_type": item["entry_type"],
                    "category": item.get("category"), "homonym_key": item.get("homonym_key"),
                    "ocr_bbox": exact.get("ocr_bbox"), "ocr_confidence": exact.get("ocr_confidence"),
                    "review_note": item.get("note"),
                })

    page_rows = [pages[key] for key in sorted(pages)]
    entry_rows = [row for key in sorted(entries) for row in entries[key]]
    return page_rows, entry_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batches", nargs="+", type=Path)
    parser.add_argument("--ocr-dir", required=True, type=Path)
    parser.add_argument("--base-pages", required=True, type=Path)
    parser.add_argument("--base-entries", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        pages, entries = merge(args.ocr_dir, args.base_pages, args.base_entries, args.batches)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    write_csv(args.output_dir / "reviewed.pages.csv", PAGE_FIELDS, pages)
    write_csv(args.output_dir / "reviewed.entries.csv", ENTRY_FIELDS, entries)
    print(f"{len(pages)} image-reviewed pages, {len(entries)} occurrences")


if __name__ == "__main__":
    main()
