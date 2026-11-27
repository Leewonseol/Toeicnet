"""Validate accepted Quizlet and image-reviewed OCR records for database intake."""

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from import_quizlet import SOURCE_ID as QUIZLET_ID
from intake_common import (
    ENTRY_FIELDS, ENTRY_TYPES, HACKERS_PDF_ALIASES, HACKERS_PDFS, PAGE_FIELDS, read_csv, read_jsonl,
    sha256_file, write_json, write_jsonl,
)


HACKERS_ID = "hackers_back"


def positive_integer(raw, field, where, minimum=1):
    if isinstance(raw, bool) or not str(raw).isdecimal() or int(raw) < minimum:
        raise ValueError(f"{where}: invalid {field} {raw!r}")
    return int(raw)


def load_json(path):
    with path.open(encoding="utf-8-sig") as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return result


def accepted_quizlet(intake, manifest_path):
    manifest = load_json(manifest_path)
    if manifest.get("source_id") != QUIZLET_ID or manifest.get("count_matches") is not True:
        raise ValueError(f"{manifest_path}: no count-matched import for Quizlet set 324678752")
    if manifest.get("output_records_sha256") != sha256_file(intake):
        raise ValueError(f"{intake}: records do not match the accepted Quizlet import")
    count = positive_integer(manifest.get("expected_count"), "expected_count", manifest_path)
    if not manifest.get("count_evidence") or count != manifest.get("extracted_count"):
        raise ValueError(f"{manifest_path}: expected count and its provenance are inconsistent")
    records = list(read_jsonl(intake))
    if len(records) != count or any(
        rec.get("source_id") != QUIZLET_ID
        or rec.get("source_sha256") != manifest.get("sha256")
        or rec.get("verification_status") != "source_attested"
        for rec in records
    ):
        raise ValueError(f"{intake}: source identity, checksum or record count does not match the accepted import")
    return records


def review_pages(ocr_dir, pages_path, allow_partial=False, snapshot=False):
    prefix = "snapshot." if snapshot else ""
    manifest = load_json(ocr_dir / f"{prefix}manifest.json")
    if manifest.get("source_id") != HACKERS_ID:
        raise ValueError(f"{ocr_dir}: invalid OCR source")
    if not allow_partial and not manifest.get("ready_for_full_image_review"):
        raise ValueError(f"{ocr_dir}: OCR must be complete for all three source PDFs")
    files = manifest.get("files", {})
    requested_files = {}
    for filename, file in files.items():
        requested = file.get("requested_filename", filename)
        valid_filenames = (requested, *HACKERS_PDF_ALIASES.get(requested, ()))
        if (requested not in HACKERS_PDFS or requested in requested_files
                or unicodedata.normalize("NFC", filename) not in valid_filenames):
            raise ValueError(f"{ocr_dir}: unexpected or duplicate source filename {filename}")
        requested_files[requested] = filename
    if set(requested_files) != set(HACKERS_PDFS):
        raise ValueError(f"{ocr_dir}: one or more source files are missing from the manifest")
    candidate_pages = {
        (row["filename"], int(row["pdf_page"])): row
        for row in read_csv(ocr_dir / f"{prefix}candidates.pages.csv", PAGE_FIELDS)
    }
    expected_pages = {
        (requested_files[requested], page)
        for requested, (_, _, page_count) in HACKERS_PDFS.items()
        for page in range(1, page_count + 1)
    }
    if (not allow_partial and set(candidate_pages) != expected_pages) or set(candidate_pages) - expected_pages:
        raise ValueError(f"{ocr_dir}: expected {len(expected_pages)} OCR page records")
    verified_pages = expected_pages & set(candidate_pages)
    pages = {}
    seen_days = set()
    for row in read_csv(pages_path, PAGE_FIELDS):
        filename = row["filename"]
        pdf_page = positive_integer(row["pdf_page"], "pdf_page", pages_path)
        key = (filename, pdf_page)
        where = f"{filename} PDF page {pdf_page}"
        if key not in verified_pages or key in pages:
            raise ValueError(f"{where}: unexpected or duplicate review record")
        candidate = candidate_pages[key]
        if any(row[field] != candidate[field] for field in ("source_sha256", "image_path", "ocr_path")):
            raise ValueError(f"{where}: review does not match the OCR checkpoint")
        if files[filename].get("sha256") != row["source_sha256"]:
            raise ValueError(f"{where}: review checksum does not match the OCR source")
        for field in ("image_path", "ocr_path"):
            path = (ocr_dir / row[field]).resolve()
            if not path.is_relative_to(ocr_dir.resolve()) or not path.is_file():
                raise ValueError(f"{where}: missing or invalid {field}")
        if row["review_status"] != "image_reviewed":
            raise ValueError(f"{where}: image review has not been confirmed")
        day = positive_integer(row["day"], "day", where)
        first_day, last_day, _ = HACKERS_PDFS[files[filename].get("requested_filename", filename)]
        if not first_day <= day <= last_day:
            raise ValueError(f"{where}: DAY {day} is outside the source's configured range")
        seen_days.add(day)
        printed_page = row["printed_page"].strip()
        reviewed_entries = positive_integer(row["reviewed_entries"], "reviewed_entries", where, minimum=0)
        if (not printed_page or not reviewed_entries) and not row["review_note"].strip():
            raise ValueError(f"{where}: document unavailable print pagination or a page without entries")
        pages[key] = {
            **row, "pdf_page": pdf_page, "day": day,
            "printed_page": positive_integer(printed_page, "printed_page", where) if printed_page else None,
            "reviewed_entries": reviewed_entries,
        }
    if not pages:
        raise ValueError(f"{pages_path}: no pages have image review")
    if not allow_partial and set(pages) != expected_pages:
        missing = sorted(expected_pages - set(pages))
        raise ValueError(f"{pages_path}: {len(missing)} pages lack image review; first missing: {missing[0]}")
    expected_days = set(range(min(value[0] for value in HACKERS_PDFS.values()),
                              max(value[1] for value in HACKERS_PDFS.values()) + 1))
    if not allow_partial and (missing_days := sorted(expected_days - seen_days)):
        raise ValueError(f"{pages_path}: DAYS lacking reviewed pages: {missing_days}")
    return pages


def accepted_ocr(ocr_dir, pages_path, entries_path, allow_partial=False, snapshot=False):
    pages = review_pages(ocr_dir, pages_path, allow_partial, snapshot)
    counts = Counter()
    positions = set()
    records = []
    for row in read_csv(entries_path, ENTRY_FIELDS):
        filename = row["filename"]
        pdf_page = positive_integer(row["pdf_page"], "pdf_page", entries_path)
        where = f"{filename} PDF page {pdf_page}"
        page = pages.get((filename, pdf_page))
        if page is None or row["source_sha256"] != page["source_sha256"]:
            raise ValueError(f"{where}: entry does not refer to the reviewed source page")
        index = positive_integer(row["entry_index"], "entry_index", where)
        source_record_id = f"{filename}:{pdf_page}:{index}"
        if source_record_id in positions:
            raise ValueError(f"{where}: duplicate image entry index {index}")
        positions.add(source_record_id)
        if row["entry_type"] not in ENTRY_TYPES:
            raise ValueError(f"{where} entry {index}: choose a reviewed entry_type from {sorted(ENTRY_TYPES)}")
        confidence = row["ocr_confidence"].strip()
        if confidence:
            confidence = float(confidence)
            if not 0 <= confidence <= 100:
                raise ValueError(f"{where} entry {index}: invalid OCR confidence")
        records.append({
            "headword": row["headword"],
            "original_korean_meaning": row["original_korean_meaning"] or None,
            "part_of_speech": row["part_of_speech"].strip() or None,
            "entry_type": row["entry_type"],
            "day": page["day"],
            "category": row["category"].strip() or None,
            "source_id": HACKERS_ID,
            "source_record_id": source_record_id,
            "filename": filename,
            "source_sha256": row["source_sha256"],
            "pdf_page": pdf_page,
            "printed_page": page["printed_page"],
            "verification_status": "source_attested",
            "extraction_method": "bilingual_ocr_image_review",
            "homonym_key": row["homonym_key"].strip() or None,
            "review_status": "image_reviewed",
            "ocr_image_path": page["image_path"],
            "ocr_text_path": page["ocr_path"],
            "ocr_bbox": row["ocr_bbox"].strip() or None,
            "ocr_confidence": confidence if confidence != "" else None,
            "ocr_page_review_note": page["review_note"].strip() or None,
            "ocr_entry_review_note": row["review_note"].strip() or None,
        })
        counts[(filename, pdf_page)] += 1
    for page, info in pages.items():
        if counts[page] != info["reviewed_entries"]:
            raise ValueError(f"{page}: {info['reviewed_entries']} entries declared, {counts[page]} accepted")
    return records, len(pages)


def normalize_records(records):
    seen = set()
    for record in records:
        position = (record.get("source_id"), record.get("source_record_id"))
        if not all(position) or position in seen:
            raise ValueError(f"missing or duplicate source occurrence: {position}")
        seen.add(position)
        original = record.get("headword")
        if not isinstance(original, str) or any(char in original for char in "\x00\r\n\t"):
            raise ValueError(f"{position}: invalid source headword")
        normalized = " ".join(unicodedata.normalize("NFC", original).split())
        if not normalized:
            raise ValueError(f"{position}: empty headword")
        day = record.get("day")
        if day is not None and (type(day) is not int or not 1 <= day <= 30):
            raise ValueError(f"{position}: invalid DAY {day!r}")
        yield {
            **record, "headword": normalized, "original_headword": original,
            "headword_key": unicodedata.normalize("NFKC", normalized).replace("’", "'").casefold(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quizlet", type=Path, default=Path("data/intermediate/quizlet.jsonl"))
    parser.add_argument("--quizlet-manifest", type=Path, default=Path("data/intermediate/quizlet-manifest.json"))
    parser.add_argument("--ocr-dir", type=Path, default=Path("data/intermediate/ocr"))
    parser.add_argument("--reviewed-pages", type=Path, default=Path("data/intermediate/ocr/reviewed.pages.csv"))
    parser.add_argument("--reviewed-entries", type=Path, default=Path("data/intermediate/ocr/reviewed.entries.csv"))
    parser.add_argument("--allow-partial-ocr-review", action="store_true",
                        help="accept only recorded, image-reviewed pages from incomplete OCR coverage")
    parser.add_argument("--ocr-snapshot", action="store_true",
                        help="use the snapshot.* cache inventory produced by extract_ocr.py --cached-only")
    parser.add_argument("--only", choices=("quizlet", "ocr"), help="explicitly normalize only one intake")
    parser.add_argument("--output", type=Path, default=Path("data/intermediate/normalized.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("data/intermediate/normalized-manifest.json"))
    args = parser.parse_args()
    prefix = "snapshot." if args.ocr_snapshot else ""
    input_files = [args.quizlet, args.quizlet_manifest, args.reviewed_pages, args.reviewed_entries,
                   args.ocr_dir / f"{prefix}manifest.json", args.ocr_dir / f"{prefix}candidates.pages.csv"]
    inputs = {path.resolve() for path in input_files}
    if args.output.resolve() == args.manifest.resolve() or inputs & {args.output.resolve(), args.manifest.resolve()}:
        parser.error("output and manifest must be separate from every input")
    try:
        records = []
        image_pages = 0
        if args.only != "ocr":
            records.extend(accepted_quizlet(args.quizlet, args.quizlet_manifest))
        if args.only != "quizlet":
            ocr, image_pages = accepted_ocr(
                args.ocr_dir, args.reviewed_pages, args.reviewed_entries,
                args.allow_partial_ocr_review, args.ocr_snapshot,
            )
            records.extend(ocr)
        normalized = list(normalize_records(records))
        write_jsonl(args.output, normalized)
        by_source = Counter(row["source_id"] for row in normalized)
        expected_pages = sum(value[2] for value in HACKERS_PDFS.values())
        expected_pages = sum(value[2] for value in HACKERS_PDFS.values())
        write_json(args.manifest, {
            "normalized_at": datetime.now(timezone.utc).isoformat(),
            "output_records_sha256": sha256_file(args.output),
            "source_counts": dict(by_source),
            "expected_image_pages": expected_pages,
            "reviewed_image_pages": image_pages,
            "unknown_day_occurrences": sum(row["day"] is None for row in normalized),
            "complete_intake": set(by_source) == {HACKERS_ID, QUIZLET_ID} and image_pages == expected_pages,
        })
    except (OSError, ValueError, csv.Error) as error:
        print(f"Normalization: {error}", file=sys.stderr)
        return 1
    print(f"Normalized {len(normalized)} occurrences; {image_pages} image-reviewed pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
