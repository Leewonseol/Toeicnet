"""Select a candidate type without changing its corpus evidence status."""

import argparse
from pathlib import Path

from external_records import read_jsonl, write_jsonl


def export_usage(usage_type: str) -> None:
    parser = argparse.ArgumentParser(description=f"Filter corpus JSONL for {usage_type} candidates.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = write_jsonl(args.output, (
        record for record in read_jsonl(args.input)
        if record.get("source_id") == "oanc" and record.get("usage_type") == usage_type
    ))
    print(f"{usage_type}: {count} records")
