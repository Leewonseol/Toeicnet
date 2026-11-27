"""Build SQLite atomically from source transcription, evidence candidates, and reviewed assertions."""
import argparse
import hashlib
import json
import sqlite3
import tempfile
import unicodedata
from pathlib import Path

from analysis_review import checked_relation, relation_key
from review_common import checked_korean, load_catalog, normalized_lemma

SCHEMA = Path(__file__).with_name("schema.sql")
ROOT = SCHEMA.parent.parent
ATTESTED = {"source_attested", "corpus_attested", "cross_verified"}
STATUSES = ATTESTED | {"inferred", "disputed", "unverified", "unavailable", "not_applicable"}
SEMANTIC_PEERS = {
    "SYNONYM_OF", "NEAR_SYNONYM_OF", "ANTONYM_OF", "COMPLEMENTARY_TO",
    "GRADABLE_OPPOSITE_OF", "CONVERSE_OF", "REVERSIVE_OF", "CONTEXTUAL_OPPOSITE_OF",
}

NODE_TYPES = {
    "WORD", "SENSE", "MORPHEME", "ROOT", "BASE", "STEM", "PREFIX", "SUFFIX",
    "INFLECTIONAL_ENDING", "HISTORICAL_FORM", "ETYMOLOGICAL_ROOT", "COLLOCATION",
    "COLLIGATION", "IDIOM", "PHRASAL_VERB", "GRAMMATICAL_PATTERN", "SYNSET",
    "SEMANTIC_FIELD", "THEME", "SOURCE", "ORIGIN_LANGUAGE", "SEMANTIC_CHANGE",
    "ARGUMENT_STRUCTURE", "COUNTABILITY", "TRANSITIVITY", "REGISTER", "ETYMOLOGICAL_AFFIX",
}


def canonical(value):
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def stable(prefix, *parts):
    digest = hashlib.sha256(packed(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def read_rows(path):
    with path.open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield line_no, json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_no}: {error.msg}") from error


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Builder:
    def __init__(self, connection):
        self.db = connection
        self.reviewed_senses = {}

    def node(self, node_id, node_type, label, *, sense_id=None, word_id=None,
             status="unverified", properties=None):
        self.db.execute("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)",
                        (node_id, node_type, label, sense_id, word_id, status, packed(properties or {})))
        current = self.db.execute(
            "SELECT node_type,label,sense_id,word_id,properties_json FROM nodes WHERE node_id=?",
            (node_id,),
        ).fetchone()
        if tuple(current) != (node_type, label, sense_id, word_id, packed(properties or {})):
            raise ValueError(f"Conflicting node data for {node_id}")
        return node_id

    def sources(self, config, manifest=None):
        if isinstance(config, dict):
            config = config.get("sources", config)
        if isinstance(config, list):
            config = {item.get("source_id", item.get("id")): item for item in config}
        downloads = {}
        if manifest:
            receipts = manifest.get("downloads", manifest.get("datasets", manifest)) if isinstance(manifest, dict) else manifest
            if isinstance(receipts, list):
                downloads = {item["source_id"]: item for item in receipts}
            elif isinstance(receipts, dict):
                downloads = receipts
        for source_id, item in sorted(config.items()):
            receipt = downloads.get(source_id) or {}
            source_url = item.get("url") or item.get("homepage")
            title = item.get("title") or item.get("name") or source_id
            license_name = item.get("license")
            if not isinstance(license_name, (str, type(None))):
                license_name = packed(license_name)
            version = receipt.get("version") or item.get("version")
            if version is not None:
                version = str(version)
            self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (
                source_id, title, source_url, item.get("independence_group"),
                license_name, version, packed({**item, "download_receipt": receipt}),
            ))
            self.node(stable("source", source_id), "SOURCE", title,
                      properties={"source_id": source_id, "url": source_url, "version": version})

    def evidence(self, object_type, object_id, records):
        for record in records:
            source_id = record["source_id"]
            record_id = str(record.get("source_record_id") or "").strip()
            method = str(record.get("extraction_method") or "").strip()
            if not record_id or not method:
                raise ValueError(f"Missing record locator or extraction method for {object_id}")
            source = self.db.execute("SELECT url,version FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if not source:
                raise ValueError(f"Unknown evidence source: {source_id}")
            evidence_id = stable("ev", object_type, object_id, source_id, record_id, record)
            self.db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                evidence_id, object_type, object_id, source_id, record.get("url") or source[0], record_id,
                record.get("version") or source[1], method, record.get("verification_date"),
                record.get("note"), packed(record),
            ))

    def word(self, record):
        headword = record["headword"].strip()
        normalized = normalized_lemma(headword)
        if not normalized:
            raise ValueError("Empty headword")
        homonym_key = str(record.get("homonym_key") or "")
        word_id = stable("w", normalized, homonym_key)
        self.db.execute("INSERT OR IGNORE INTO words VALUES (?,?,?,?)",
                        (word_id, headword, normalized, homonym_key))
        title = self.db.execute("SELECT headword FROM words WHERE word_id=?", (word_id,)).fetchone()[0]
        self.node(word_id, "WORD", title, word_id=word_id, properties={"homonym_key": homonym_key})
        return word_id

    def occurrence(self, record):
        status = record.get("verification_status", "unverified")
        if status not in STATUSES:
            raise ValueError(f"Invalid occurrence status: {status}")
        source_id = record["source_id"]
        source_record_id = str(record["source_record_id"]).strip()
        if not source_record_id:
            raise ValueError("Empty source record ID")
        word_id = self.word(record)
        occurrence_id = stable("occ", source_id, source_record_id)
        self.db.execute("INSERT INTO occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            occurrence_id, word_id, source_id, source_record_id, record.get("day"),
            record.get("category"), record.get("original_korean_meaning"),
            record.get("part_of_speech"), record.get("entry_type"), record.get("filename"),
            record.get("pdf_page"), record.get("printed_page"), status, packed(record),
        ))
        self.evidence("occurrence", occurrence_id, [{
            **record, "extraction_method": record.get("extraction_method", "source_import"),
        }])

    def candidate(self, record):
        if record["kind"] not in {"sense_candidate", "relation_candidate", "usage_candidate"}:
            raise ValueError(f"Unknown candidate kind: {record['kind']}")
        locator = str(record.get("source_record_id") or "").strip()
        if not locator or not record.get("headword"):
            raise ValueError("Candidate requires a headword and a source record ID")
        candidate_id = stable("candidate", record)
        self.db.execute("INSERT OR IGNORE INTO external_candidates VALUES (?,?,?,?,?,?)", (
            candidate_id, record["kind"], record["headword"], record["source_id"], locator, packed(record),
        ))

    def edge(self, start, end, kind, status, *, sense_id=None, properties=None, evidence=()):
        if status not in STATUSES or (status in ATTESTED and not evidence and kind != "HAS_SENSE"):
            raise ValueError(f"Invalid or unsupported relation status for {kind}: {status}")
        edge_id = stable("edge", start, end, kind, sense_id)
        self.db.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", (
            edge_id, start, end, kind, sense_id, status, packed(properties or {}),
        ))
        self.evidence("edge", edge_id, evidence)

    def sense(self, record):
        word_id = self.word(record)
        pos = canonical(record["part_of_speech"])
        key = record["sense_key"]
        if not pos or not key:
            raise ValueError("Sense must have part of speech and a sense key")
        sense_id = stable("sense", word_id, pos, key)
        en_status = record["status"]
        ko_status = record["korean_status"]
        definition = record.get("english_definition")
        translation = record.get("verified_korean_meaning")
        definition_evidence = record.get("definition_evidence", [])
        translation_evidence = record.get("korean_evidence", [])
        display = record["preferred_display_language"]
        self.db.execute("INSERT INTO senses VALUES (?,?,?,?,?)", (sense_id, word_id, pos, key, display))
        self.db.execute("INSERT INTO english_definitions VALUES (?,?,?,?,?)", (
            sense_id, definition, en_status, record.get("verification_date"), record.get("definition_origin"),
        ))
        self.db.execute("INSERT INTO korean_translations VALUES (?,?,?,?,?)", (
            sense_id, translation, ko_status, record.get("translation_uncertainty_reason"),
            record.get("verification_date"),
        ))
        self.evidence("english_definition", sense_id, definition_evidence)
        self.evidence("korean_translation", sense_id, translation_evidence)
        self.evidence("sense_alignment", sense_id, record.get("alignment_evidence", []))
        for origin in record.get("occurrences", []):
            occurrence_id = stable("occ", origin["source_id"], str(origin["source_record_id"]))
            match = self.db.execute("SELECT word_id FROM occurrences WHERE occurrence_id=?",
                                    (occurrence_id,)).fetchone()
            if match is None or match[0] != word_id:
                raise ValueError(f"Sense occurrence is missing or belongs to another word: {origin}")
            self.db.execute("INSERT INTO sense_occurrences VALUES (?,?)", (sense_id, occurrence_id))
        title = self.db.execute("SELECT headword FROM words WHERE word_id=?", (word_id,)).fetchone()[0]
        self.node(sense_id, "SENSE", title, sense_id=sense_id, word_id=word_id,
                  status=en_status, properties={"sense_key": key, "part_of_speech": pos})
        self.edge(word_id, sense_id, "HAS_SENSE", en_status, sense_id=sense_id,
                  properties={"verification_date": record.get("verification_date")}, evidence=definition_evidence)
        self.reviewed_senses[(word_id, pos, key)] = sense_id

    def endpoint(self, record):
        kind = record["node_type"]
        if kind not in NODE_TYPES:
            raise ValueError(f"Unknown node type: {kind}")
        if kind == "WORD":
            return self.word(record), None
        if kind == "SENSE":
            word_id = self.word(record)
            key = (word_id, canonical(record["part_of_speech"]), record["sense_key"])
            if key not in self.reviewed_senses:
                raise ValueError(f"Relation references an unreviewed sense: {key}")
            sense_id = self.reviewed_senses[key]
            return sense_id, sense_id
        if kind == "SOURCE":
            node_id = stable("source", record["key"])
            if not self.db.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone():
                raise ValueError(f"Unknown source: {record['key']}")
            return node_id, None
        if not record.get("key") or not record.get("label"):
            raise ValueError(f"{kind} endpoint requires key and label")
        node_id = stable("node", kind, record["key"])
        return self.node(node_id, kind, record["label"], properties=record.get("attributes")), None

    def relation(self, record):
        kind = record["relation_type"]
        left, left_sense = self.endpoint(record["from"])
        right, right_sense = self.endpoint(record["to"])
        if kind in SEMANTIC_PEERS and (not left_sense or not right_sense):
            raise ValueError(f"Semantic peer relation {kind} must connect two senses")
        evidence = record.get("evidence", [])
        self.edge(left, right, kind, record["status"], sense_id=left_sense or right_sense,
                  properties={**record.get("attributes", {}), "module": record["module"],
                              "verification_date": record.get("verification_date")}, evidence=evidence)
        for node_id in (left, right):
            self.evidence("node", node_id, evidence)


def load_input(builder, category, paths, handler):
    for path in paths:
        count = 0
        for line_no, row in read_rows(path):
            try:
                handler(row)
            except (KeyError, ValueError, TypeError, sqlite3.Error) as error:
                raise ValueError(f"{path}:{line_no}: {error}") from error
            count += 1
        builder.db.execute("INSERT INTO run_input VALUES (?,?,?,?)",
                           (category, path.name, hash_file(path), count))


def build(output, config, intake=(), candidates=(), review=(), manifest=None,
          intake_manifest=None, anki_manifest=None):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".toeic-build-", dir=output.parent) as work_dir:
        temporary_db = Path(work_dir) / output.name
        db = sqlite3.connect(temporary_db)
        try:
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            with db:
                builder = Builder(db)
                catalog = load_catalog(config)
                builder.sources(catalog,
                                json.loads(manifest.read_text(encoding="utf-8")) if manifest else None)
                load_input(builder, "intake", intake, builder.occurrence)
                for stage, manifest_path in (("normalized_intake", intake_manifest), ("anki_intake", anki_manifest)):
                    if not manifest_path:
                        continue
                    state = json.loads(manifest_path.read_text(encoding="utf-8"))
                    digest = state.get("output_records_sha256")
                    matching_input = db.execute(
                        "SELECT 1 FROM run_input WHERE input_kind='intake' AND sha256=?", (digest,),
                    ).fetchone()
                    if not matching_input:
                        raise ValueError(f"{manifest_path}: intake manifest does not match any loaded JSONL")
                    db.execute("INSERT INTO pipeline_state VALUES (?,?)", (stage, packed(state)))
                load_input(builder, "candidate", candidates, builder.candidate)
                review_relations = []
                relation_keys = set()

                def import_review(record):
                    if record["kind"] == "sense":
                        checked = checked_korean(record, catalog)
                        builder.sense(checked)
                    elif record["kind"] == "relation":
                        checked = checked_relation(record, catalog)
                        key = relation_key(checked)
                        if key in relation_keys:
                            raise ValueError(f"Duplicate reviewed relation: {key}")
                        relation_keys.add(key)
                        review_relations.append(checked)
                    else:
                        raise ValueError(f"Unknown review record kind: {record['kind']}")

                load_input(builder, "review", review, import_review)
                for relation in review_relations:
                    builder.relation(relation)
                if db.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Foreign key check failed")
        finally:
            db.close()
        temporary_db.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/toeic.db")
    parser.add_argument("--config", type=Path, default=ROOT / "config/sources.yaml")
    parser.add_argument("--intake", type=Path, action="append", default=[])
    parser.add_argument("--candidates", type=Path, action="append", default=[])
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--intake-manifest", type=Path)
    parser.add_argument("--anki-manifest", type=Path)
    options = parser.parse_args()
    build(options.output, options.config, options.intake, options.candidates,
          options.review, options.manifest, options.intake_manifest, options.anki_manifest)
    print(options.output)


if __name__ == "__main__":
    main()
