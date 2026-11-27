"""Export native WordNet senses, synsets and precisely located source connections."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from external_records import atomic_output, read_jsonl, write_jsonl

SOURCE = "oewn"
SOURCE_URL = "https://en-word.net/downloads"
SOURCE_RIGHTS = "https://github.com/globalwordnet/english-wordnet/blob/main/LICENSE.md"
PRINCETON_RIGHTS = "https://github.com/globalwordnet/english-wordnet/blob/main/WNDB_License.txt"
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

PRINCETON_NOTICE = """Permission to use, copy, modify and distribute this software and
database and its documentation for any purpose and without fee or
royalty is hereby granted, provided that you agree to comply with
the following copyright notice and statements, including the disclaimer,
and that the same appear on ALL copies of the software, database and
documentation, including modifications that you make for internal
use or for distribution.

WordNet 3.1 Copyright 2011 by Princeton University.  All rights reserved.

THIS SOFTWARE AND DATABASE IS PROVIDED "AS IS" AND PRINCETON
UNIVERSITY MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PRINCETON
UNIVERSITY MAKES NO REPRESENTATIONS OR WARRANTIES OF MERCHANT-
ABILITY OR FITNESS FOR ANY PARTICULAR PURPOSE OR THAT THE USE
OF THE LICENSED SOFTWARE, DATABASE OR DOCUMENTATION WILL NOT
INFRINGE ANY THIRD PARTY PATENTS, COPYRIGHTS, TRADEMARKS OR
OTHER RIGHTS.

The name of Princeton University or Princeton may not be used in
advertising or publicity pertaining to distribution of the software
and/or database.  Title to copyright in this software, database and
any associated documentation shall at all times remain with
Princeton University and LICENSEE agrees to preserve same.
"""

SenseKey = tuple[str, str]
RelationKey = tuple[str, str, str, str, str, str]


def database_records(path: Path) -> Iterator[dict]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        for (payload,) in db.execute(
            "SELECT payload_json FROM external_candidates WHERE source_id = ?", (SOURCE,),
        ):
            yield json.loads(payload)


def packed(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def node_id(version: str, node_type: str, native_id: str) -> str:
    return f"{SOURCE}:{version}:{node_type}:{native_id}"


def sense_key(row: dict) -> SenseKey:
    try:
        version, identifier = row["version"], row["external_sense_id"]
        if not isinstance(version, str) or not version or not isinstance(identifier, str) or not identifier:
            raise ValueError
        return version, identifier
    except (KeyError, ValueError) as error:
        raise ValueError("WordNet records require a native sense identifier and source version") from error


def add_sense(index: dict[SenseKey, dict], row: dict) -> None:
    key = sense_key(row)
    if not row.get("synset_id") or not row.get("headword"):
        raise ValueError(f"Missing synset or headword for WordNet sense {key}")
    previous = index.get(key)
    if previous is None:
        index[key] = row
    elif dict(previous, expansion=False) != dict(row, expansion=False):
        raise ValueError(f"Conflicting native WordNet sense records for {key}")
    elif previous.get("expansion") and not row.get("expansion"):
        index[key] = row


def connection(row: dict) -> tuple[RelationKey, str, str | None, str]:
    version, anchor = sense_key(row)
    source_synset = row.get("synset_id")
    target_sense = row.get("target_external_sense_id")
    target_synset = row.get("target_synset_id")
    relation = row["relation_type"]
    details = row.get("details") or {}
    native_relation = details.get("wordnet_relation")
    if not source_synset:
        raise ValueError(f"Missing source synset for WordNet relation anchored at {anchor}")
    if relation == "BELONGS_TO_SYNSET":
        if target_sense or target_synset != source_synset:
            raise ValueError(f"Conflicting native synset membership for {anchor}")
        return (version, "sense", anchor, relation, "synset", target_synset), "sense_synset_attribute", None, anchor
    if relation == "SYNONYM_OF" and details.get("basis") == "shared synset":
        if not target_sense or target_synset != source_synset:
            raise ValueError(f"Invalid shared-synset candidate for {anchor}")
        return (version, "sense", anchor, relation, "sense", target_sense), "shared_synset_membership", None, anchor
    if not native_relation:
        raise ValueError(f"Missing explicit WordNet relation type for {anchor}: {relation}")
    if target_sense:
        return (version, "sense", anchor, relation, "sense", target_sense), "native_sense_relation", native_relation, anchor
    if target_synset:
        return (version, "synset", source_synset, relation, "synset", target_synset), "native_synset_relation", native_relation, anchor
    raise ValueError(f"Missing native WordNet endpoint for {anchor}: {relation}")


def resolve(records: Iterable[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    senses: dict[SenseKey, dict] = {}
    relations = defaultdict(set)
    anchored_synsets: set[SenseKey] = set()
    target_labels: dict[SenseKey, set[str]] = defaultdict(set)
    declared_sense_synsets: dict[SenseKey, set[str]] = defaultdict(set)
    anchor_urls: dict[SenseKey, set[str]] = defaultdict(set)
    for row in records:
        if row.get("source_id") != SOURCE:
            continue
        if row.get("kind") == "sense_candidate":
            add_sense(senses, row)
            continue
        if row.get("kind") != "relation_candidate":
            continue
        key, basis, raw_type, anchor = connection(row)
        relations[key, basis, raw_type].add(anchor)
        version = key[0]
        source_synset = row["synset_id"]
        anchored_synsets.add((version, source_synset))
        declared_sense_synsets[version, anchor].add(source_synset)
        if url := row.get("url"):
            anchor_urls[version, anchor].add(url)
        if synset := row.get("target_synset_id"):
            labels = (row.get("details") or {}).get("target_synset_headwords", [])
            target_labels[version, synset].update(labels)
            if target := row.get("target_external_sense_id"):
                declared_sense_synsets[version, target].add(synset)

    synset_candidates: dict[SenseKey, list[dict]] = defaultdict(list)
    sense_rows = []
    for (version, identifier), row in sorted(senses.items()):
        synset = row["synset_id"]
        declared_sense_synsets[version, identifier].add(synset)
        if url := row.get("url"):
            anchor_urls[version, identifier].add(url)
        synset_candidates[version, synset].append(row)
        key = (version, "sense", identifier, "BELONGS_TO_SYNSET", "synset", synset)
        relations[key, "sense_synset_attribute", None].add(identifier)
        sense_rows.append({
            **row, "record_type": "native_sense", "node_id": node_id(version, "sense", identifier),
            "native_sense_id": identifier, "native_synset_id": synset,
            "synset_node_id": node_id(version, "synset", synset),
        })
    for key, declarations in declared_sense_synsets.items():
        if len(declarations) != 1:
            raise ValueError(f"Conflicting synset IDs for native WordNet sense {key}")

    synset_rows = []
    synset_keys = synset_candidates.keys() | anchored_synsets | target_labels.keys()
    for version, synset in sorted(synset_keys):
        members = synset_candidates.get((version, synset), [])
        ili = sorted({member["synset_ili"] for member in members if member.get("synset_ili")})
        if len(ili) > 1:
            raise ValueError(f"Conflicting ILI identifiers for native WordNet synset {(version, synset)}")
        definitions = sorted({
            definition for member in members
            for definition in (member.get("definitions") or [member.get("definition")]) if definition
        })
        synset_rows.append({
            "record_type": "native_synset", "source_id": SOURCE, "version": version,
            "node_id": node_id(version, "synset", synset), "native_synset_id": synset,
            "ili": ili[0] if ili else None, "available_definitions": definitions,
            "available_native_sense_ids": [member["external_sense_id"] for member in members],
            "available_member_headwords": sorted({member["headword"] for member in members}),
            "source_index_member_headwords": sorted(target_labels.get((version, synset), set())),
            "source_urls": sorted({member["url"] for member in members if member.get("url")}),
        })

    relation_rows = []
    for (key, basis, raw_type), anchors in sorted(relations.items()):
        version, source_type, start, relation, target_type, end = key
        shares_synset = basis == "shared_synset_membership"
        relation_id = hashlib.sha256(packed((key, basis, raw_type)).encode()).hexdigest()
        relation_rows.append({
            "record_type": "source_connection", "relation_id": f"{SOURCE}:{version}:relation:{relation_id}",
            "source_id": SOURCE, "version": version,
            "relation_type": "SHARES_SYNSET_WITH" if shares_synset else relation,
            "candidate_relation_type": relation,
            "native_relation_type": raw_type, "basis": basis,
            "from_node_type": source_type, "from_native_id": start,
            "from_node_id": node_id(version, source_type, start),
            "from_record_available": source_type == "synset" or (version, start) in senses,
            "to_node_type": target_type, "to_native_id": end,
            "to_node_id": node_id(version, target_type, end),
            "to_record_available": target_type == "synset" or (version, end) in senses,
            "anchor_native_sense_ids": sorted(anchors),
            "source_urls": sorted({
                url for anchor in anchors for url in anchor_urls.get((version, anchor), set())
            }),
            "status": "source_attested", "substitutability": "unreviewed" if shares_synset else None,
        })
    return sense_rows, synset_rows, relation_rows


def export(records: Iterable[dict], output: Path) -> dict:
    senses, synsets, relations = resolve(records)
    if not senses:
        raise ValueError("No native WordNet sense records were found in the input")
    counts = {
        "native_sense_count": write_jsonl(output / "senses.jsonl", senses),
        "native_synset_count": write_jsonl(output / "synsets.jsonl", synsets),
        "connection_count": write_jsonl(output / "relations.jsonl", relations),
        "connections_by_basis": dict(Counter(row["basis"] for row in relations)),
        "connections_by_type": dict(Counter(row["relation_type"] for row in relations)),
        "connections_without_target_sense_record": sum(not row["to_record_available"] for row in relations),
    }
    versions = sorted({row["version"] for row in senses})
    with atomic_output(output / "ATTRIBUTION.txt") as handle:
        handle.write(
            f"Open English WordNet {', '.join(versions)}\n"
            "Copyright (c) 2019-present, The Open English WordNet Team.\n"
            "Based in part on the Princeton University WordNet database.\n"
            f"{SOURCE_URL}\n{SOURCE_RIGHTS}\n{LICENSE_URL}\n{PRINCETON_RIGHTS}\n\n"
            "Changes: selected source records, grouped duplicate synset edges and marked shared membership.\n\n"
            + PRINCETON_NOTICE
        )
    summary = {
        **counts, "source_id": SOURCE, "source_versions": versions, "source_url": SOURCE_URL,
        "license": LICENSE, "license_url": LICENSE_URL, "source_rights_notice": SOURCE_RIGHTS,
        "princeton_rights_notice": PRINCETON_RIGHTS, "attribution_file": "ATTRIBUTION.txt",
        "workbook_sense_assignments": 0,
        "shared_synset_scope": "Shared membership only. Contextual substitutability remains unreviewed.",
    }
    with atomic_output(output / "summary.json") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--db", type=Path, help="Read the external candidates from a SQLite database")
    inputs.add_argument("--input", action="append", type=Path, help="WordNet candidate JSONL or JSONL.GZ")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = database_records(args.db) if args.db else (row for path in args.input for row in read_jsonl(path))
    try:
        result = export(records, args.output_dir)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    print(f"WordNet source export: {result['native_sense_count']} senses, {result['native_synset_count']} synsets, "
          f"{result['connection_count']} connections")


if __name__ == "__main__":
    main()
