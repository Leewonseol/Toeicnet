"""Import a user-authorized export of the specified Quizlet set."""

import argparse
import csv
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from intake_common import ENTRY_TYPES, sha256_file, write_json, write_jsonl


SOURCE_ID = "quizlet_324678752"
SOURCE_URL = "https://quizlet.com/kr/324678752/"
HEADER_ALIASES = {
    "headword": ("headword", "term", "word", "표제어", "영어"),
    "meaning": ("original_korean_meaning", "definition", "meaning", "정의", "뜻", "한국어"),
    "part_of_speech": ("part_of_speech", "pos", "품사"),
    "entry_type": ("entry_type", "type", "유형"),
    "day": ("day", "학습일"),
    "category": ("category", "분류"),
    "homonym_key": ("homonym_key",),
    "source_record_id": ("source_record_id", "card_id"),
}
HEADER_KEYS = {label: key for key, aliases in HEADER_ALIASES.items() for label in aliases}


def delimiter_for(path, requested):
    if requested:
        return {"tab": "\t", "comma": ","}[requested]
    if path.suffix.casefold() == ".tsv":
        return "\t"
    if path.suffix.casefold() == ".csv":
        return ","
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
    try:
        return csv.Sniffer().sniff(sample, delimiters="\t,").delimiter
    except csv.Error as error:
        raise ValueError("TXT must be tab- or comma-delimited. Set --delimiter if needed.") from error


def parse_day(raw):
    value = raw.strip().casefold().removeprefix("day").strip()
    if not value:
        return None
    if not value.isdecimal() or not 1 <= int(value) <= 30:
        raise ValueError(f"invalid DAY {raw!r}")
    return int(value)


def detect_header(row, header_mode):
    mapped = [HEADER_KEYS.get(column.strip().casefold()) for column in row]
    detected = "headword" in mapped and "meaning" in mapped
    if header_mode == "no" or (header_mode == "auto" and not detected):
        return None
    if not detected:
        raise ValueError("header must contain headword/term and definition/meaning columns")
    recognized = [key for key in mapped if key is not None]
    if len(set(recognized)) != len(recognized):
        raise ValueError("header contains duplicate columns for a recognized field")
    return {key: index for index, key in enumerate(mapped) if key is not None}


def read_export(path, delimiter, header_mode):
    has_header = False
    entries = []
    ids = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        rows = (row for row in reader if row and any(value.strip() for value in row))
        first = next(rows, None)
        if first is None:
            raise ValueError("export has no source records")
        fields = detect_header(first, header_mode)
        has_header = fields is not None

        def data_rows():
            if not has_header:
                yield first
            yield from rows

        if fields is None:
            fields = {"headword": 0, "meaning": 1}
        row_width = len(first) if has_header else 2
        for ordinal, row in enumerate(data_rows(), 1):
            if len(row) != row_width:
                raise ValueError(f"line {reader.line_num}: expected {row_width} columns")

            def field(name, default=""):
                return row[fields[name]] if name in fields else default

            headword = field("headword").strip()
            if not headword or any(c in headword for c in "\r\n\x00\t"):
                raise ValueError(f"line {reader.line_num}: invalid headword")
            sense_type = field("entry_type").strip().casefold()
            if sense_type and sense_type not in ENTRY_TYPES:
                raise ValueError(f"line {reader.line_num}: unsupported entry_type {sense_type!r}")
            record_id = field("source_record_id").strip() or str(ordinal)
            if record_id in ids:
                raise ValueError(f"line {reader.line_num}: repeated occurrence ID {record_id!r}")
            ids.add(record_id)
            entries.append({
                "headword": headword,
                "original_korean_meaning": field("meaning") or None,
                "part_of_speech": field("part_of_speech").strip() or None,
                "entry_type": sense_type or None,
                "day": parse_day(field("day")),
                "category": field("category").strip() or None,
                "source_id": SOURCE_ID,
                "source_record_id": record_id,
                "source_record_ordinal": ordinal,
                "source_line_end": reader.line_num,
                "filename": path.name,
                "pdf_page": None,
                "printed_page": None,
                "verification_status": "source_attested",
                "extraction_method": "quizlet_export_import",
                "homonym_key": field("homonym_key").strip() or None,
            })
    return entries, has_header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Quizlet set 324678752 export (.tsv/.csv/.txt)")
    parser.add_argument("--expected-count", type=int, required=True, help="count independently observed for set 324678752")
    parser.add_argument("--count-evidence", required=True, help="where the set count was observed, including date where known")
    parser.add_argument("--delimiter", choices=("tab", "comma"))
    parser.add_argument("--header", choices=("auto", "yes", "no"), default="auto")
    parser.add_argument("--output", type=Path, default=Path("data/intermediate/quizlet.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("data/intermediate/quizlet-manifest.json"))
    args = parser.parse_args()
    if args.expected_count <= 0 or not args.count_evidence.strip():
        parser.error("a positive expected count and count evidence are required")
    if len({path.resolve() for path in (args.input, args.output, args.manifest)}) != 3:
        parser.error("input, output, and manifest must be separate files")
    try:
        checksum = sha256_file(args.input)
        delimiter = delimiter_for(args.input, args.delimiter)
        entries, has_header = read_export(args.input, delimiter, args.header)
        if sha256_file(args.input) != checksum:
            raise ValueError("source file changed during import")
        count = len(entries)
        day_counts = Counter(entry["day"] for entry in entries if entry["day"] is not None)
        matched = count == args.expected_count
        manifest = {
            "source_id": SOURCE_ID,
            "url": SOURCE_URL,
            "filename": args.input.name,
            "sha256": checksum,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "header": has_header,
            "expected_count": args.expected_count,
            "count_evidence": args.count_evidence.strip(),
            "extracted_count": count,
            "unique_headword_count": len({
                unicodedata.normalize("NFC", entry["headword"]).casefold() for entry in entries
            }),
            "count_matches": matched,
            "days": dict(sorted(day_counts.items())),
            "unknown_day_count": count - sum(day_counts.values()),
            "day_coverage_complete": set(day_counts) == set(range(1, 31)) and sum(day_counts.values()) == count,
            "output_records_sha256": None,
        }
        if matched:
            for entry in entries:
                entry["source_sha256"] = checksum
            write_jsonl(args.output, entries)
            manifest["output_records_sha256"] = sha256_file(args.output)
        write_json(args.manifest, manifest)
        if not matched:
            raise ValueError(f"expected {args.expected_count} cards, parsed {count}; intake was not accepted")
    except (OSError, ValueError, csv.Error) as error:
        print(f"Quizlet import: {error}", file=sys.stderr)
        return 1
    print(f"Imported {count} cards; {manifest['unknown_day_count']} without a source DAY label.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
