"""Shared source-intake fields and file helpers."""

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path


HACKERS_PDFS = {
    "해커스토익 뒷단어 데이 1-10(2)(2).pdf": (1, 10, 40),
    "해커스 뒷단어 데이 11–15(1)(2).pdf": (11, 15, 20),
    "해커스 뒷단어 16-30(1)(2).pdf": (16, 30, 60),
}
HACKERS_PDF_ALIASES = {
    "해커스토익 뒷단어 데이 1-10(2)(2).pdf": ("해커스토익 뒷단어 데이 1-10(2).pdf",),
    "해커스 뒷단어 데이 11–15(1)(2).pdf": ("해커스 뒷단어 데이 11–15(1).pdf",),
    "해커스 뒷단어 16-30(1)(2).pdf": ("해커스 뒷단어 16-30(1).pdf",),
}

PAGE_FIELDS = (
    "filename", "source_sha256", "pdf_page", "day", "printed_page",
    "reviewed_entries", "review_status", "review_note", "image_path", "ocr_path",
)
ENTRY_FIELDS = (
    "filename", "source_sha256", "pdf_page", "entry_index", "headword",
    "original_korean_meaning", "part_of_speech", "entry_type", "category",
    "homonym_key", "ocr_bbox", "ocr_confidence", "review_note",
)
ENTRY_TYPES = {"word", "compound", "idiom", "phrasal_verb", "phrase"}


def sha256_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _atomic_write(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            write(handle)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, obj):
    def dump(handle):
        json.dump(obj, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")

    _atomic_write(path, dump)


def write_jsonl(path, records):
    def dump(handle):
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")

    _atomic_write(path, dump)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: JSON object required")
            yield record


def write_csv(path, fieldnames, records):
    def dump(handle):
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    _atomic_write(path, dump)


def read_csv(path, fields):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        fieldnames = reader.fieldnames or []
        if len(set(fieldnames)) != len(fieldnames) or set(fields) - set(fieldnames):
            raise ValueError(f"{path}: invalid CSV header; expected {', '.join(fields)}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{reader.line_num}: wrong number of fields")
            yield row
