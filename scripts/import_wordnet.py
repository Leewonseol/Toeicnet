"""Extract Open English WordNet 2025+ evidence without aligning it to textbook senses."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote
import xml.etree.ElementTree as ET

from external_records import normalize_headword, normalize_pos, open_data, targets, write_jsonl

SENSE_RELATIONS = {
    "antonym": "ANTONYM_OF",
    "derivation": "DERIVATIONALLY_RELATED_TO",
    "participle": "PARTICIPLE_OF",
    "pertainym": "PERTAINYM_OF",
    "similar": "SIMILAR_TO",
}
SYNSET_RELATIONS = {
    "hypernym": "HYPONYM_OF",
    "instance_hypernym": "INSTANCE_OF",
    "hyponym": "HYPERNYM_OF",
    "instance_hyponym": "HAS_INSTANCE",
    "mero_member": "HAS_MERONYM",
    "mero_part": "HAS_MERONYM",
    "mero_substance": "HAS_MERONYM",
    "holo_member": "MERONYM_OF",
    "holo_part": "MERONYM_OF",
    "holo_substance": "MERONYM_OF",
    "similar": "SIMILAR_TO",
}


@dataclass(frozen=True, slots=True)
class Sense:
    id: str
    lemma: str
    part_of_speech: str
    synset: str


def lexicon_records(path: Path) -> Iterator[ET.Element]:
    """Release complete lexicon items after each record and avoid building an XML tree."""
    with open_data(path, "rb") as handle:
        parents: list[ET.Element] = []
        for event, element in ET.iterparse(handle, events=("start", "end")):
            if event == "start":
                parents.append(element)
                if element.tag == "Lexicon":
                    yield element
                continue
            if len(parents) == 3 and parents[-2].tag == "Lexicon":
                yield element
                parents[-2].remove(element)
                element.clear()
            parents.pop()


def links(element: ET.Element, tag: str, mapping: dict[str, str]) -> list[tuple[str, str, str]]:
    return [
        (mapping[rel.attrib["relType"]], rel.attrib["target"], rel.attrib["relType"])
        for rel in element.findall(tag)
        if rel.get("relType") in mapping and "target" in rel.attrib
    ]


def candidate_records(path: Path, wanted: set[str], *, expansion: bool = True) -> Iterator[dict]:
    sense_index: dict[str, Sense] = {}
    synset_members: dict[str, list[str]] = defaultdict(list)
    focus: set[str] = set()
    selected: set[str] = set()
    sense_links: dict[str, list[tuple[str, str, str]]] = {}
    version = None

    for record in lexicon_records(path):
        if record.tag == "Lexicon":
            version = record.attrib["version"]
        if record.tag != "LexicalEntry":
            continue
        lemma = record.find("Lemma")
        if lemma is None:
            continue
        form = lemma.attrib["writtenForm"]
        pos = normalize_pos(lemma.attrib["partOfSpeech"])
        is_target = normalize_headword(form) in wanted
        for item in record.findall("Sense"):
            sense = Sense(item.attrib["id"], form, pos, item.attrib["synset"])
            sense_index[sense.id] = sense
            synset_members[sense.synset].append(sense.id)
            if is_target:
                focus.add(sense.id)
                relations = links(item, "SenseRelation", SENSE_RELATIONS)
                sense_links[sense.id] = relations
                if expansion:
                    selected.update(target for _, target, _ in relations)

    if version is None:
        raise ValueError(f"{path}: Lexicon version missing")
    selected.update(focus)
    if expansion:
        for sense_id in focus:
            selected.update(synset_members[sense_index[sense_id].synset])
    by_synset: dict[str, list[Sense]] = defaultdict(list)
    for sense_id in sorted(selected & sense_index.keys()):
        sense = sense_index[sense_id]
        by_synset[sense.synset].append(sense)

    def base(sense: Sense) -> dict:
        return {
            "headword": sense.lemma,
            "part_of_speech": sense.part_of_speech,
            "source_id": "oewn",
            "source_record_id": sense.id,
            "url": f"https://en-word.net/lemma/{quote(sense.lemma, safe='')}",
            "version": version,
            "extraction_method": "wordnet_lmf_xml",
            "verification_status": "source_attested",
            "external_sense_id": sense.id,
            "synset_id": sense.synset,
        }

    for record in lexicon_records(path):
        synset_id = record.get("id")
        if record.tag != "Synset" or synset_id not in by_synset:
            continue
        definitions = [
            item.text.strip() for item in record.findall("Definition")
            if item.text and item.text.strip()
        ]
        for sense in by_synset[synset_id]:
            item = base(sense)
            yield dict(item, kind="sense_candidate", definition=definitions[0] if definitions else None,
                       definitions=definitions, synset_ili=record.get("ili"), expansion=sense.id not in focus)
            for rel_type, target_id, original in sense_links.get(sense.id, []):
                target = sense_index.get(target_id)
                if target is None:
                    continue
                yield dict(item, kind="relation_candidate", relation_type=rel_type,
                           target_headword=target.lemma, target_part_of_speech=target.part_of_speech,
                           target_external_sense_id=target.id, target_synset_id=target.synset,
                           details={"wordnet_relation": original})
            if sense.id not in focus:
                continue
            yield dict(item, kind="relation_candidate", relation_type="BELONGS_TO_SYNSET",
                       target_synset_id=synset_id)
            for target_id in synset_members[synset_id]:
                if target_id == sense.id or target_id not in selected:
                    continue
                target = sense_index[target_id]
                yield dict(item, kind="relation_candidate", relation_type="SYNONYM_OF",
                           target_headword=target.lemma, target_part_of_speech=target.part_of_speech,
                           target_external_sense_id=target.id, target_synset_id=target.synset,
                           details={"basis": "shared synset", "substitutability": "unreviewed"})
            for rel_type, target_id, original in links(record, "SynsetRelation", SYNSET_RELATIONS):
                yield dict(item, kind="relation_candidate", relation_type=rel_type,
                           target_synset_id=target_id,
                           details={"wordnet_relation": original, "toeic_relevance": "unreviewed",
                                    "target_synset_headwords": sorted({
                                        sense_index[sid].lemma for sid in synset_members[target_id]
                                    })})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="OEWN LMF XML or XML.GZ")
    parser.add_argument("--targets", type=Path, required=True, action="append", help="JSONL containing headword")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-expansion", action="store_true")
    args = parser.parse_args()
    wanted = targets(args.targets)
    count = write_jsonl(args.output, candidate_records(args.input, wanted, expansion=not args.no_expansion))
    print(f"OEWN: {len(wanted)} target spellings, {count} candidate records")


if __name__ == "__main__":
    main()
