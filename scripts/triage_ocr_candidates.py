"""Build a private, pending OCR review queue using same-DAY Anki back entries."""

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from intake_common import ENTRY_FIELDS, PAGE_FIELDS, read_csv, read_jsonl, sha256_file, write_json, write_jsonl


BACK_SECTIONS = {"02.토익기초단어", "03.800점", "04.900점"}
DEFAULT_OCR = Path("data/intermediate/ocr_fast")


def spelling(value):
    normalized = unicodedata.normalize("NFKC", value).replace("’", "'").casefold()
    return " ".join(normalized.split())


def read_page_index(manifest_path):
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest["source_id"] != "hackers_back":
        raise ValueError("Unexpected OCR source in manifest")
    pages = {}
    for filename, info in manifest["files"].items():
        first_day, last_day = info["day_range"]
        four_pages_per_day = info["expected_pages"] == 4 * (last_day - first_day + 1)
        for page in info["pages"]:
            if not 1 <= page <= info["expected_pages"]:
                raise ValueError(f"Out-of-range OCR page: {filename}, {page}")
            inferred_day = first_day + (page - 1) // 4 if four_pages_per_day else None
            pages[filename, page] = (info["sha256"], inferred_day)
    if len(pages) != manifest["ocr_pages"]:
        raise ValueError("OCR manifest page count and page inventory differ")
    return pages


def source_page(row, pages):
    key = row["filename"], int(row["pdf_page"])
    if key not in pages or pages[key][0] != row["source_sha256"]:
        raise ValueError(f"Review/candidate does not match OCR checkpoint: {key}")
    return key


def index_anki(path):
    index = defaultdict(list)
    for entry in read_jsonl(path):
        parts = (entry.get("category") or "").split("::")
        if entry.get("source_id") != "hackers_anki_user" or len(parts) < 2 or parts[1] not in BACK_SECTIONS:
            continue
        day, headword = entry.get("day"), entry.get("headword")
        if type(day) is int and 1 <= day <= 30 and headword:
            index[day, spelling(headword)].append({
                "source_record_id": entry["source_record_id"], "headword": headword,
                "category": entry["category"],
            })
    return index


def triage(ocr_dir, anki_path):
    manifest_path = ocr_dir / "manifest.json"
    reviewed_path = ocr_dir / "reviewed.pages.csv"
    candidates_path = ocr_dir / "candidates.entries.csv"
    inputs = (manifest_path, reviewed_path, candidates_path, anki_path)
    fingerprints = [sha256_file(path) for path in inputs]
    pages = read_page_index(manifest_path)
    reviewed = set()
    inference_conflicts = set()
    for row in read_csv(reviewed_path, PAGE_FIELDS):
        if row["review_status"] != "image_reviewed":
            continue
        key = source_page(row, pages)
        reviewed.add(key)
        inferred_day = pages[key][1]
        if inferred_day is not None and inferred_day != int(row["day"]):
            inference_conflicts.add(key[0])

    back = index_anki(anki_path)
    queue = []
    pages_with_candidates = set()
    counts = Counter(dict.fromkeys(
        ("one_exact_spelling", "multiple_exact_spellings", "no_exact_spelling", "day_inference_unavailable"), 0
    ))
    for row in read_csv(candidates_path, ENTRY_FIELDS):
        key = source_page(row, pages)
        if key in reviewed:
            continue
        filename, page = key
        input_checksum, inferred_day = pages[key]
        if filename in inference_conflicts:
            inferred_day = None
        hits = back.get((inferred_day, spelling(row["headword"])), [])
        if inferred_day is None:
            clue = "day_inference_unavailable"
        elif not hits:
            clue = "no_exact_spelling"
        else:
            clue = "one_exact_spelling" if len(hits) == 1 else "multiple_exact_spellings"
        pages_with_candidates.add(key)
        counts[clue] += 1
        queue.append({
            "filename": filename, "source_sha256": input_checksum, "pdf_page": page,
            "ocr_entry_index": int(row["entry_index"]), "ocr_headword": row["headword"],
            "ocr_original_korean_meaning": row["original_korean_meaning"],
            "ocr_part_of_speech": row["part_of_speech"] or None,
            "ocr_category_candidate": row["category"] or None, "ocr_bbox": row["ocr_bbox"] or None,
            "ocr_confidence": float(row["ocr_confidence"]) if row["ocr_confidence"] else None,
            "inferred_day": inferred_day,
            "inferred_day_method": "four_pages_per_day" if inferred_day is not None else None,
            "anki_spelling_clue": clue, "anki_back_matches": hits,
            "review_status": "pending", "verification_status": "unverified",
        })

    queue.sort(key=lambda row: (row["filename"], row["pdf_page"], row["ocr_entry_index"]))
    pending = sorted(pages.keys() - reviewed)
    if any(sha256_file(path) != digest for path, digest in zip(inputs, fingerprints, strict=True)):
        raise ValueError("OCR or Anki input changed during queue generation")
    summary = {
        "review_status": "pending",
        "ocr_pages": len(pages), "image_reviewed_pages_excluded": len(reviewed),
        "unreviewed_pages": len(pending),
        "unreviewed_pages_with_candidates": len(pages_with_candidates),
        "unreviewed_pages_without_candidates": [
            {"filename": filename, "pdf_page": page}
            for filename, page in pending if (filename, page) not in pages_with_candidates
        ],
        "files_with_day_inference_conflicts": sorted(inference_conflicts),
        "anki_back_entries_indexed": sum(map(len, back.values())),
        "pending_ocr_candidates": len(queue), "anki_spelling_clues": dict(sorted(counts.items())),
        "input_sha256": {path.name: digest for path, digest in zip(inputs, fingerprints, strict=True)},
    }
    return queue, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR)
    parser.add_argument("--anki", type=Path, default=Path("data/intermediate/anki.jsonl"))
    args = parser.parse_args()
    output = args.ocr_dir / "anki-pending-review.jsonl"
    summary_path = args.ocr_dir / "anki-pending-review-summary.json"
    if args.anki.resolve() in {output.resolve(), summary_path.resolve()}:
        parser.error("Anki input and queue outputs must be separate files")
    try:
        queue, summary = triage(args.ocr_dir, args.anki)
        write_jsonl(output, queue)
        summary["output_sha256"] = sha256_file(output)
        write_json(summary_path, summary)
    except (KeyError, OSError, ValueError, csv.Error) as error:
        print(f"OCR review queue: {error}", file=sys.stderr)
        return 1
    print(f"Pending OCR candidates: {len(queue)} across {summary['unreviewed_pages']} unreviewed pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
