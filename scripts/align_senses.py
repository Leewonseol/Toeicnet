"""Queue exact headword and part-of-speech matches for sense and homonym review."""

import argparse
from collections import defaultdict
from pathlib import Path
import re

from review_common import jsonl_records, normalized_lemma, normalized_pos, text_field, write_jsonl


# Source labels for span types do not specify the grammatical class of the expression.
SPAN_LABELS = {"phrase", "phr", "idiom", "구", "숙어", "표현"}


def pos_options(value):
    if not isinstance(value, str):
        return []
    return list(dict.fromkeys(
        pos for label in re.split(r"\s+(?:or|and)\s+|[,;/·]", value, flags=re.IGNORECASE)
        if (pos := normalized_pos(label)) and pos not in SPAN_LABELS
    ))


def references_by_lemma(paths):
    references = defaultdict(list)
    for location, record in jsonl_records(paths):
        try:
            headword = text_field(record, "headword")
            positions = pos_options(record.get("part_of_speech"))
            reference = {
                "source_id": text_field(record, "source_id"),
                "source_record_id": text_field(record, "source_record_id"),
                "headword": headword,
                "part_of_speech": record.get("part_of_speech"),
                "part_of_speech_options": positions,
            }
        except ValueError as error:
            raise ValueError(f"{location}: {error}") from error
        for key in ("homonym_key", "day", "filename", "pdf_page", "printed_page", "original_korean_meaning"):
            if record.get(key) is not None:
                reference[key] = record[key]
        references[normalized_lemma(headword)].append(reference)
    return references


def alignment_rows(intake_paths, candidate_paths):
    references = references_by_lemma(intake_paths)
    matched_occurrences = set()
    for location, candidate in jsonl_records(candidate_paths):
        if candidate.get("kind") != "sense_candidate":
            continue
        try:
            lemma = normalized_lemma(text_field(candidate, "headword"))
            text_field(candidate, "source_id")
            text_field(candidate, "source_record_id")
            text_field(candidate, "external_sense_id")
        except ValueError as error:
            raise ValueError(f"{location}: {error}") from error
        pos = normalized_pos(candidate.get("part_of_speech"))
        if lemma not in references:
            continue
        matching = [
            item for item in references[lemma]
            if not item["part_of_speech_options"] or not pos or pos in item["part_of_speech_options"]
        ]
        if not matching:
            continue
        for item in matching:
            matched_occurrences.add((item["source_id"], item["source_record_id"]))
        homonyms = {item.get("homonym_key") for item in matching}
        if len(homonyms) > 1:
            basis = "homonym_review_required"
        elif not pos or any(not item["part_of_speech_options"] for item in matching):
            basis = "headword_only"
        else:
            basis = "headword_and_pos"
        yield {
            "kind": "sense_alignment_candidate",
            "basis": basis,
            "review_status": "pending",
            "candidate": candidate,
            "occurrences": matching,
        }
    for lemma in sorted(references):
        for item in references[lemma]:
            if (item["source_id"], item["source_record_id"]) in matched_occurrences:
                continue
            yield {
                "kind": "sense_alignment_missing",
                "basis": "no_exact_candidate",
                "review_status": "pending",
                "occurrence": item,
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="+", help="Normalized source occurrence JSONL files")
    parser.add_argument("--candidates", type=Path, nargs="+", required=True, help="External adapter JSONL files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        count = write_jsonl(args.output, alignment_rows(args.input, args.candidates))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Wrote {count} alignment worklist records to {args.output}")
