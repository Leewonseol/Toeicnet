#!/usr/bin/env python3
"""Export a database snapshot as CSV, JSONL and GraphML."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from study_data import StudyData, atomic_text, json_text, object_properties

NODE_FIELDS = (
    "node_id", "node_type", "label", "sense_id", "word_id", "status",
    "properties_json", "evidence",
)
EDGE_FIELDS = (
    "edge_id", "from_node_id", "to_node_id", "relation_type", "sense_id", "status",
    "properties_json", "evidence",
)
ENGLISH_FIELDS = (
    "word_id", "sense_id", "headword", "part_of_speech", "english_definition",
    "english_definition_status", "english_definition_sources", "english_verification_date", "definition_origin",
)
KOREAN_FIELDS = (
    "word_id", "sense_id", "headword", "part_of_speech", "original_korean_meaning",
    "verified_korean_meaning", "korean_translation_status", "korean_translation_sources",
    "translation_uncertainty_reason", "korean_verification_date",
)
VOCABULARY_FIELDS = tuple(dict.fromkeys(ENGLISH_FIELDS + KOREAN_FIELDS)) + (
    "normalized", "homonym_key", "study_role", "preferred_display_language",
    "verification_date", "occurrences", "aligned_occurrence_ids",
)
ILLEGAL_XML = re.compile(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def vocabulary_rows(data):
    for word_id, word in data.words.items():
        occurrences = data.occurrences.get(word_id, [])
        for sense in data.word_senses.get(word_id) or [{}]:
            sense_id = sense.get("sense_id")
            aligned = {row["occurrence_id"] for row in data.sense_origins.get(sense_id, ())}
            # All occurrence glosses survive in occurrences, including as-yet unaligned glosses.
            glosses = list(dict.fromkeys(
                row["original_korean_meaning"] for row in occurrences
                if row.get("original_korean_meaning")
                and (sense_id is None or row["occurrence_id"] in aligned)
            ))
            yield {
                **word, **data.meaning(sense_id),
                "sense_id": sense_id,
                "part_of_speech": sense.get("part_of_speech"),
                "study_role": data.role(word_id),
                "occurrences": occurrences,
                "aligned_occurrence_ids": sorted(aligned),
                "original_korean_meaning": glosses,
            }


def graph_rows(data, object_type):
    records = data.nodes.values() if object_type == "node" else data.edges
    for record in records:
        yield {
            **record,
            "properties_json": object_properties(record),
            "evidence": data.graph_evidence(object_type, record),
        }


def scalar(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict, bool)):
        return json_text(value)
    return str(value)


def write_tabular(output, stem, fields, rows):
    with atomic_text(output / f"{stem}.csv", newline="") as csv_file:
        with atomic_text(output / f"{stem}.jsonl") as json_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                projected = {key: row.get(key) for key in fields}
                writer.writerow({key: scalar(value) for key, value in projected.items()})
                json_file.write(json_text(projected) + "\n")


def graphml_id(kind, identifier):
    return kind[0] + "_" + str(identifier).encode("utf-8").hex()


def write_graphml(output, data):
    fields_by_kind = {
        "node": NODE_FIELDS,
        "edge": EDGE_FIELDS,
    }
    with atomic_text(output / "vocabulary.graphml") as stream:
        stream.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        stream.write('<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n')
        for kind, fields in fields_by_kind.items():
            for field in fields:
                stream.write(f'  <key id="{kind}_{field}" for="{kind}" attr.name="{field}" attr.type="string"/>\n')
        stream.write('  <graph id="vocabulary" edgedefault="directed">\n')
        for kind, fields in fields_by_kind.items():
            for record in graph_rows(data, kind):
                element_id = quoteattr(graphml_id(kind, record[f"{kind}_id"]))
                attributes = f"id={element_id}"
                if kind == "edge":
                    source = quoteattr(graphml_id("node", record["from_node_id"]))
                    target = quoteattr(graphml_id("node", record["to_node_id"]))
                    attributes += f" source={source} target={target}"
                stream.write(f"    <{kind} {attributes}>\n")
                for field in fields:
                    value = record.get(field)
                    if value is None:
                        continue
                    value = escape(ILLEGAL_XML.sub("\ufffd", scalar(value)))
                    stream.write(f'      <data key="{kind}_{field}">{value}</data>\n')
                stream.write(f"    </{kind}>\n")
        stream.write("  </graph>\n</graphml>\n")


def export_network(data, output):
    write_tabular(output, "vocabulary", VOCABULARY_FIELDS, vocabulary_rows(data))
    write_tabular(
        output, "english_definitions", ENGLISH_FIELDS,
        (row for row in vocabulary_rows(data) if row["sense_id"] in data.english),
    )
    write_tabular(
        output, "korean_translations", KOREAN_FIELDS,
        (row for row in vocabulary_rows(data) if row["sense_id"] in data.korean),
    )
    write_tabular(output, "nodes", NODE_FIELDS, graph_rows(data, "node"))
    write_tabular(output, "edges", EDGE_FIELDS, graph_rows(data, "edge"))
    write_graphml(output, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    data = StudyData(args.db)
    export_network(data, args.output)
    print(f"{len(data.words)} words, {len(data.nodes)} nodes, {len(data.edges)} edges")


if __name__ == "__main__":
    main()
