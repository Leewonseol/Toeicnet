"""Retrieve bounded, provenance-bearing lexical evidence from a read-only SQLite snapshot."""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import islice
from pathlib import Path

from align_senses import pos_options
from review_common import normalized_lemma, normalized_pos, write_jsonl
from study_open_evidence import valid_context


PRIMARY_SOURCES = ("hackers_anki_user", "hackers_back")
EXTERNAL_SOURCES = frozenset({"oewn", "kaikki", "oanc", "ets", "toeic_kr"})
OFFICIAL_SOURCES = frozenset({"ets", "toeic_kr"})
ATTESTED = frozenset({"source_attested", "cross_verified", "corpus_attested"})
OLD_TAGS = frozenset({"archaic", "dated", "historical", "obsolete", "rare"})
ALIAS_EXCLUDED_TAGS = OLD_TAGS | {
    "abbreviation", "colloquial", "dialectal", "ellipsis", "eye-dialect", "informal",
    "initialism", "misspelling", "nonstandard", "pronunciation-spelling",
}
ALIAS_TYPES = frozenset({"INFLECTION_OF", "HAS_INFLECTION", "VARIANT_OF", "HAS_VARIANT_FORM"})
LEXICAL_POS = frozenset({
    "noun", "verb", "adjective", "adverb", "preposition", "pronoun", "conjunction",
    "determiner", "interjection", "numeral", "particle",
})
PARTICLE_ALTERNANTS = frozenset({
    "about", "across", "around", "at", "away", "back", "down", "for", "from", "in", "into",
    "off", "on", "onto", "out", "over", "through", "to", "up", "upon", "with",
})
SLASH_ALTERNANTS = re.compile(
    r"(?P<prefix>[a-z]+(?: [a-z]+)*) (?P<alternants>[a-z]+/[a-z]+|\([a-z]+/[a-z]+\))"
    r"(?P<suffix>(?: [a-z]+)*)"
)
MORPHOLOGY = ALIAS_TYPES | {
    "DERIVED_FROM", "DERIVATIONALLY_RELATED_TO", "HAS_DERIVED_TERM_CANDIDATE",
    "COMPOUND_COMPONENT_OF", "PARTICIPLE_OF", "MORPHOLOGICAL_TEMPLATE",
}
ETYMOLOGY = frozenset({
    "ETYMOLOGY_NARRATIVE", "HAS_HISTORICAL_FORM", "HAS_ETYMOLOGICAL_ROOT",
    "BORROWED_FROM", "ETYMOLOGICALLY_DERIVED_FROM", "COGNATE_WITH",
})
SEMANTICS = frozenset({
    "SYNONYM_OF", "ANTONYM_OF", "BELONGS_TO_SYNSET", "SIMILAR_TO", "HYPERNYM_OF",
    "HYPONYM_OF", "MERONYM_OF", "HAS_MERONYM", "RELATED_TO", "PERTAINYM_OF",
})
CHANNELS = ("senses", "morphology", "etymology", "semantics", "usage", "korean_candidates")
USAGE_ORDER = {
    "OFFICIAL_SAMPLE_ATTESTATION": 0, "PHRASE_ATTESTATION": 1, "COLLIGATION": 2, "COLLOCATION": 3,
    "COUNTABILITY": 4, "TRANSITIVITY": 4, "IDIOM": 4, "REGISTER": 4, "FREQUENCY": 5,
}


def object_json(value):
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def details_of(record):
    details = record.get("details")
    return details if isinstance(details, dict) else {}


def tags_of(record):
    tags = record.get("tags", [])
    embedded = details_of(record).get("tags", [])
    return frozenset(tag.casefold() for group in (tags, embedded) if isinstance(group, list)
                     for tag in group if isinstance(tag, str))


def korean_terms(gloss):
    if not isinstance(gloss, str):
        return frozenset()
    clean = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "", normalized_lemma(gloss))
    return frozenset(part.strip() for part in re.split(r"[,;/]|[~〜]", clean)
                     if re.search(r"[가-힣]", part))


def gloss_key(text):
    return re.sub(r"[^\w\s]|_", "", normalized_lemma(text)) if isinstance(text, str) else ""


def channel_for(kind, payload):
    if kind == "sense_candidate":
        definition = payload.get("definition")
        return "senses" if isinstance(definition, str) and definition.strip() else None
    if kind == "usage_candidate":
        return "usage"
    relation = payload.get("relation_type")
    if relation == "KOREAN_TRANSLATION_CANDIDATE":
        return "korean_candidates"
    if relation in ETYMOLOGY or (
        relation == "MORPHOLOGICAL_TEMPLATE"
        and details_of(payload).get("scope") == "wiktionary_etymology_section"
    ):
        return "etymology"
    if relation in MORPHOLOGY:
        return "morphology"
    if relation in SEMANTICS:
        return "semantics"
    return None


class EvidenceRetriever:
    """Read candidates and established assertions without changing database state."""

    def __init__(self, connection):
        self.connection = connection
        self.sources = {row["source_id"]: dict(row) for row in self._query(
            """SELECT source_id, title, url, independence_group, license, version FROM sources"""
        )}
        self._pool = lru_cache(maxsize=128)(self._read_pool)
        self._evidence = lru_cache(maxsize=256)(self._read_evidence)
        self.aliases = self._index_aliases()

    def _query(self, statement, params=()):
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(statement, params)

    def targets(self, *, source_ids=PRIMARY_SOURCES, day=None):
        if not source_ids:
            raise ValueError("At least one target source is required")
        placeholders = ", ".join("?" for _ in source_ids)
        query = f"""
            SELECT o.occurrence_id, o.word_id, o.source_id, o.source_record_id, o.day, o.category,
                   o.original_korean_meaning, o.part_of_speech, o.entry_type, o.filename, o.pdf_page,
                   o.printed_page, o.verification_status, w.headword, w.normalized, w.homonym_key
            FROM occurrences o JOIN words w USING(word_id)
            WHERE o.source_id IN ({placeholders})
        """
        params = list(source_ids)
        if day is not None:
            query += " AND o.day = ?"
            params.append(day)
        query += " ORDER BY o.day, o.source_id, o.filename, o.pdf_page, o.source_record_id"
        for row in self._query(query, params):
            yield dict(row)

    def _source(self, source_id, record_id, version=None, url=None):
        source = self.sources[source_id]
        return {
            "source_id": source_id, "source_record_id": record_id, "source_title": source["title"],
            "source_version": version or source["version"], "source_license": source["license"],
            "independence_group": source["independence_group"], "url": url or source["url"],
        }

    def _read_evidence(self, object_type, object_id):
        rows = self._query("""
            SELECT evidence_id, source_id, url, source_record_id, version, extraction_method,
                   verification_date, note, properties_json
            FROM evidence WHERE object_type = ? AND object_id = ?
            ORDER BY source_id, source_record_id, evidence_id
        """, (object_type, object_id))
        return [{
            **self._source(row["source_id"], row["source_record_id"], row["version"], row["url"]),
            "evidence_ref": row["evidence_id"], "extraction_method": row["extraction_method"],
            "verification_date": row["verification_date"], "note": row["note"],
            **{
                key: value for key, value in object_json(row["properties_json"]).items()
                if key in {"sense_match", "relation_match", "assessment_kind", "matched_sense_key",
                           "external_sense_id", "item_locator"}
            },
        } for row in rows]

    def _index_aliases(self):
        index = defaultdict(list)
        for row in self._query("""
            SELECT e.edge_id, e.relation_type, e.status, l.normalized AS observed, r.normalized AS other,
                   l.word_id AS observed_word_id, r.word_id AS other_word_id, e.properties_json
            FROM edges e JOIN words l ON l.word_id = e.from_node_id
            JOIN words r ON r.word_id = e.to_node_id
            WHERE e.status IN ('source_attested', 'cross_verified')
              AND e.relation_type IN ('INFLECTION_OF', 'VARIANT_OF')
            ORDER BY e.edge_id
        """):
            attributes = object_json(row["properties_json"])
            features = attributes.get("features")
            pos = (
                {normalized_pos(key) for key in features} & LEXICAL_POS
                if isinstance(features, dict) else set()
            )
            proof = {
                "evidence_ref": row["edge_id"], "relation_type": row["relation_type"],
                "verification_status": row["status"],
                "evidence": self._evidence("edge", row["edge_id"]),
            }
            if proof["evidence"] and row["observed"] != row["other"]:
                index[row["observed"]].append((row["other"], pos, row["observed_word_id"], proof))
                if row["relation_type"] == "VARIANT_OF":
                    index[row["other"]].append((row["observed"], pos, row["other_word_id"], proof))
        # Use headword pairs explicitly stated in the source. Do not derive stems from strings.
        for row in self._query("""
            SELECT candidate_id, source_id, source_record_id, normalized_headword, payload_json
            FROM external_candidates
            WHERE source_id = 'kaikki' AND kind = 'relation_candidate'
              AND json_extract(payload_json, '$.relation_type')
                  IN ('INFLECTION_OF', 'HAS_INFLECTION', 'VARIANT_OF', 'HAS_VARIANT_FORM')
            ORDER BY candidate_id
        """):
            payload = object_json(row["payload_json"])
            relation = payload.get("relation_type")
            target = payload.get("target_headword")
            if payload.get("verification_status") not in ATTESTED or not isinstance(target, str):
                continue
            tags = tags_of(payload)
            if tags & ALIAS_EXCLUDED_TAGS:
                continue
            if relation == "VARIANT_OF" and not (tags & {
                "alternative", "alternative-form", "alternative-spelling", "british", "uk", "us",
                "american", "canadian", "australian", "standard",
            }):
                continue
            original = row["normalized_headword"]
            other = normalized_lemma(target)
            if not other or not original or original == other:
                continue
            if relation in {"INFLECTION_OF", "HAS_INFLECTION"}:
                observed, alternate = (original, other) if relation == "INFLECTION_OF" else (other, original)
                pairs = [(observed, alternate)]
            else:
                pairs = [(original, other), (other, original)]
            pos = set(pos_options(payload.get("part_of_speech")))
            proof = {
                **self._source(row["source_id"], row["source_record_id"], payload.get("version"), payload.get("url")),
                "evidence_ref": row["candidate_id"], "relation_type": relation,
                "verification_status": payload["verification_status"],
                "extraction_method": payload.get("extraction_method"), "tags": sorted(tags),
            }
            for observed, alternate in pairs:
                index[observed].append((alternate, pos, None, proof))
        return index

    def _read_pool(self, lemma):
        records = []
        for row in self._query("""
            SELECT candidate_id, kind, headword, source_id, source_record_id, payload_json
            FROM external_candidates WHERE normalized_headword = ?
            ORDER BY kind, source_id, source_record_id, candidate_id
        """, (lemma,)):
            if row["source_id"] not in EXTERNAL_SOURCES:
                continue
            payload = object_json(row["payload_json"])
            channel = channel_for(row["kind"], payload)
            if channel:
                fields = dict(row)
                del fields["payload_json"]
                records.append((fields, payload, channel))
        return records

    def _printed_alternants(self, target, lemma, target_pos):
        match = SLASH_ALTERNANTS.fullmatch(lemma)
        if match is None or target.get("verification_status") not in ATTESTED:
            return {}
        particles = match["alternants"].strip("()").split("/")
        if any(particle not in PARTICLE_ALTERNANTS for particle in particles):
            return {}
        forms = [f"{match['prefix']} {particle}{match['suffix']}" for particle in particles]
        if len(set(forms)) != 2:
            return {}
        proof = {
            **self._source(target["source_id"], target["source_record_id"]),
            "evidence_ref": target["occurrence_id"],
            "relation_type": "SOURCE_SHORTHAND_ALTERNANT",
            "original_surface": target["headword"],
            "verification_status": target["verification_status"],
        }
        # Require external lexical units for both explicitly written alternatives.
        for form in forms:
            if not any(
                channel == "senses"
                and normalized_pos(payload.get("part_of_speech")) in (target_pos or {"verb"})
                and not tags_of(payload) & {"form-of", "alt-of"}
                for _, payload, channel in self._pool(form)
            ):
                return {}
        return {form: [proof] for form in forms}

    def _reviewed(self, occurrence_id):
        query = """
            SELECT s.sense_id, s.part_of_speech, s.sense_key, s.preferred_display_language,
                   en.english_definition, en.status AS english_status, en.verification_date AS english_date,
                   ko.verified_korean_meaning, ko.status AS korean_status, ko.translation_uncertainty_reason
            FROM sense_occurrences so JOIN senses s USING(sense_id)
            JOIN english_definitions en USING(sense_id) JOIN korean_translations ko USING(sense_id)
            WHERE so.occurrence_id = ? AND en.status IN ('source_attested', 'cross_verified')
            ORDER BY s.sense_id
        """
        items = []
        for row in self._query(query, (occurrence_id,)):
            sid = row["sense_id"]
            evidence = self._evidence("english_definition", sid)
            items.append({
                **dict(row), "evidence_ref": sid, "definition_evidence": evidence,
                "english_definition_evidence": evidence,
                "korean_evidence": self._evidence("korean_translation", sid),
                "alignment_evidence": self._evidence("sense_alignment", sid),
                "evidence_groups": sorted({item["independence_group"] for item in evidence
                                           if item["independence_group"]}),
            })
        return items

    def _established(self, target, reviewed, limit):
        endpoint_ids = [target["word_id"], *(sense["sense_id"] for sense in reviewed)]
        slots = ",".join("?" for _ in endpoint_ids)
        query = f"""
            WITH selected(edge_id) AS (
                SELECT edge_id FROM edges WHERE from_node_id IN ({slots})
                UNION SELECT edge_id FROM edges WHERE to_node_id IN ({slots})
            )
            SELECT e.edge_id, e.relation_type, e.status, e.sense_id, e.properties_json,
                   n.label AS from_label, n.node_type AS from_type,
                   t.label AS to_label, t.node_type AS to_type
            FROM selected JOIN edges e USING(edge_id)
            JOIN nodes n ON n.node_id = e.from_node_id JOIN nodes t ON t.node_id = e.to_node_id
            WHERE e.relation_type <> 'HAS_SENSE' AND e.status IN ('source_attested', 'cross_verified', 'corpus_attested')
            ORDER BY e.status <> 'cross_verified', e.relation_type = 'BELONGS_TO_THEME',
                     e.relation_type, e.edge_id
            LIMIT ?
        """
        return [{
            **{key: row[key] for key in row.keys() if key != "properties_json"},
            "evidence_ref": row["edge_id"],
            "attributes": object_json(row["properties_json"]),
            "evidence": self._evidence("edge", row["edge_id"]),
        } for row in self._query(query, (*endpoint_ids, *endpoint_ids, limit))]

    def _candidate(self, row, payload, form, target_pos, aliases, korean_hit, position,
                   shared_alternant_synset=False):
        candidate_pos = normalized_pos(payload.get("part_of_speech"))
        tags = tags_of(payload)
        exact_pos = bool(target_pos and candidate_pos in target_pos)
        if not aliases:
            match = "exact_headword_and_pos" if exact_pos else "exact_headword"
        else:
            relation = aliases[0]["relation_type"]
            match = {
                "INFLECTION_OF": "source_attested_inflection",
                "HAS_INFLECTION": "source_attested_inflection",
                "SOURCE_SHORTHAND_ALTERNANT": "source_explicit_alternant",
            }.get(relation, "source_attested_variant")
        details = details_of(payload)
        compact = payload
        if isinstance(details.get("attestations"), list):
            compact = {**payload, "details": {
                **details, "attestations": [item for item in details["attestations"] if valid_context(item)][:2],
            }}
        result = {
            **self._source(row["source_id"], row["source_record_id"], payload.get("version"), payload.get("url")),
            "candidate_id": row["candidate_id"], "evidence_ref": row["candidate_id"],
            "kind": row["kind"], "headword": row["headword"], "part_of_speech": candidate_pos,
            "match_method": match, "match_basis": match, "matched_form": form,
            "alignment_status": "unreviewed", "payload": compact, "tags": sorted(tags),
            "external_sense_id": payload.get("external_sense_id"), "synset_id": payload.get("synset_id"),
            "extraction_method": payload.get("extraction_method"),
            "source_verification_status": payload.get("verification_status"),
            "rank_features": {
                "exact_form": not aliases, "exact_pos": exact_pos,
                "original_korean_spelling_anchor": bool(korean_hit),
                "korean_anchor_evidence_refs": sorted(korean_hit),
                "shared_alternant_synset": shared_alternant_synset,
                "historical_or_rare": bool(tags & OLD_TAGS),
                "form_reference": bool(tags & {"form-of", "alt-of"}),
                "source_order": position,
            },
        }
        if row["kind"] == "sense_candidate":
            result["definition"] = payload.get("definition")
        if aliases:
            result["alias_evidence"] = aliases
        return result

    def retrieve(self, target, *, per_channel=6):
        if per_channel < 1:
            raise ValueError("per_channel must be positive")
        lemma = target.get("normalized") or normalized_lemma(target["headword"])
        target_pos = set(pos_options(target.get("part_of_speech")))
        target_ko = korean_terms(target.get("original_korean_meaning"))
        aliases = defaultdict(list)
        for alternate, positions, word_id, proof in self.aliases.get(lemma, ()):
            if word_id and word_id != target.get("word_id"):
                continue
            if word_id is None and target.get("homonym_key"):
                continue
            if target_pos and positions and not target_pos.intersection(positions):
                continue
            if len(aliases[alternate]) < 2:
                aliases[alternate].append(proof)
        aliases.update(self._printed_alternants(target, lemma, target_pos))
        query_forms = [(lemma, []), *(sorted(aliases.items())[:12])]
        channels = {channel: [] for channel in CHANNELS}
        for form, proofs in query_forms:
            # Alias lookups serve lexical/morphological matching. They do not establish exact-form usage.
            for position, (row, payload, channel) in enumerate(self._pool(form)):
                term_pos = normalized_pos(payload.get("part_of_speech"))
                if target_pos and term_pos and term_pos not in target_pos:
                    continue
                if proofs and channel in {"usage", "korean_candidates"}:
                    continue
                channels[channel].append((row, payload, form, proofs, position))

        korean_clues = defaultdict(lambda: defaultdict(set))
        for row, payload, _, _, _ in channels["korean_candidates"]:
            target_gloss = payload.get("target_headword")
            if not target_ko.intersection(korean_terms(target_gloss)):
                continue
            label = gloss_key(details_of(payload).get("source_sense_label"))
            for value in (label, payload.get("external_sense_id")):
                if value:
                    korean_clues[row["source_id"]][value].add(row["candidate_id"])

        packet = {"target": dict(target)}
        baseline = [item for item in channels["senses"] if not item[3]][:per_channel]
        packet["baseline_senses"] = [
            self._candidate(row, payload, form, target_pos, proofs, (), position)
            for row, payload, form, proofs, position in baseline
        ]
        alternant_synsets = defaultdict(set)
        for row, payload, form, proofs, _ in channels["senses"]:
            synset_id = payload.get("synset_id")
            if synset_id and proofs and proofs[0]["relation_type"] == "SOURCE_SHORTHAND_ALTERNANT":
                alternant_synsets[(row["source_id"], synset_id)].add(form)
        for channel, entries in channels.items():
            scored = []
            for row, payload, form, proofs, position in entries:
                key = gloss_key(payload.get("definition"))
                korean_hit = set()
                if channel == "senses":
                    anchors = korean_clues.get(row["source_id"], {})
                    korean_hit.update(anchors.get(key, ()))
                    korean_hit.update(anchors.get(payload.get("external_sense_id"), ()))
                if channel == "korean_candidates" and target_ko.intersection(korean_terms(payload.get("target_headword"))):
                    korean_hit.add(row["candidate_id"])
                pos_rank = int(bool(normalized_pos(payload.get("part_of_speech")) in target_pos))
                tags = tags_of(payload)
                frequency = details_of(payload).get("frequency")
                shared_alternant_synset = channel == "senses" and len(alternant_synsets.get(
                    (row["source_id"], payload.get("synset_id")), ()
                )) > 1
                score = (
                    bool(proofs), -pos_rank, bool(tags & {"form-of", "alt-of"}), not korean_hit,
                    not shared_alternant_synset, bool(tags & OLD_TAGS),
                    USAGE_ORDER.get(payload.get("usage_type"), 9),
                    -frequency if type(frequency) is int else 0,
                    row["source_id"], row["source_record_id"], row["candidate_id"],
                )
                scored.append((score, korean_hit, row, payload, form, proofs, position,
                               shared_alternant_synset))
            scored.sort(key=lambda item: item[0])
            chosen = diversify_senses(scored, per_channel) if channel == "senses" else scored[:per_channel]
            packet[channel] = [
                self._candidate(row, payload, form, target_pos, proofs, hit, position, shared_synset)
                for _, hit, row, payload, form, proofs, position, shared_synset in chosen
            ]
        packet["match_counts"] = {channel: len(entries) for channel, entries in channels.items()}
        packet["reviewed"] = self._reviewed(target["occurrence_id"])
        packet["established"] = self._established(target, packet["reviewed"], per_channel)
        return packet


def diversify_senses(scored, limit):
    """Leave room for additional sources at the same form rank."""
    selected = []
    for alias_rank in (False, True):
        selected_at_rank = []
        deferred = []
        source_counts = Counter()
        remaining = limit - len(selected)
        if remaining <= 0:
            break
        cap = max(1, remaining // 2)
        for row in scored:
            if row[0][0] != alias_rank:
                continue
            source_id = row[2]["source_id"]
            if source_counts[source_id] < cap:
                selected_at_rank.append(row)
                source_counts[source_id] += 1
            else:
                deferred.append(row)
        selected.extend((selected_at_rank + deferred)[:remaining])
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-channel", type=int, default=6)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--day", type=int, choices=range(1, 31))
    parser.add_argument("--source", action="append", choices=PRIMARY_SOURCES)
    args = parser.parse_args()
    if args.per_channel < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--per-channel and --limit must be positive")
    if args.output.resolve() == args.db.resolve():
        parser.error("output cannot be the input database")
    try:
        with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            retriever = EvidenceRetriever(connection)
            targets = retriever.targets(source_ids=args.source or PRIMARY_SOURCES, day=args.day)
            if args.limit is not None:
                targets = islice(targets, args.limit)
            count = write_jsonl(args.output, (
                retriever.retrieve(target, per_channel=args.per_channel) for target in targets
            ))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(f"Retrieved evidence for {count} occurrences.")


if __name__ == "__main__":
    main()
