"""Shared read-only projections for study notes, cards and network exports."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing, contextmanager
from pathlib import Path

from review_common import normalized_lemma, normalized_pos
from study_open_evidence import load_open_evidence

CORE_SOURCES = {"quizlet_324678752", "hackers_anki_user"}
BACK_SOURCE = "hackers_back"
ATTESTED = frozenset({"cross_verified", "source_attested", "corpus_attested"})
ENGLISH_LABELS = {
    "cross_verified": "영어 정의 교차 검증",
    "source_attested": "영어 정의 단일 출처 확인",
    "corpus_attested": "영어 사용례 말뭉치 확인",
    "inferred": "영어 정의 추가 검증 필요",
    "disputed": "영어 정의 출처 간 불일치",
    "unverified": "영어 정의 미검증",
    "unavailable": "영어 정의 자료 접근 불가",
    "not_applicable": "영어 정의 해당 없음",
}
KOREAN_LABELS = {
    "verified": "한국어 뜻 검증 완료",
    "context_dependent": "문맥에 따라 번역이 달라짐",
    "partial_equivalent": "한국어 뜻이 영어 의미의 일부를 전달",
    "uncertain": "한국어 뜻 불확실",
    "no_exact_equivalent": "한국어 대응어 확인 불가",
    "unverified": "한국어 뜻 미검증",
}


def records(connection, query, parameters=()):
    return [dict(row) for row in connection.execute(query, parameters)]


def index(rows, key):
    return {row[key]: row for row in rows}


def group(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return result


def object_properties(record):
    try:
        value = json.loads(record.get("properties_json") or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def atomic_text(path, *, newline=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline=newline, dir=path.parent, delete=False
    )
    temporary = Path(stream.name)
    try:
        with stream:
            yield stream
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def path_label(text):
    return " ".join(str(text or "").split())


def markdown(text):
    value = path_label(text)
    return "".join("\\" + char if char in "\\`*_{}[]<>|" else char for char in value)


def answer(meaning, *, english_only=False):
    """Use independently verified Korean or cross-verified English for cards."""
    definition = path_label(meaning.get("english_definition"))
    translation = path_label(meaning.get("verified_korean_meaning"))
    english_status = meaning.get("english_definition_status")
    korean_status = meaning.get("korean_translation_status")
    if english_only:
        return definition if english_status == "cross_verified" else ""
    if korean_status == "verified" and translation:
        if english_status == "cross_verified" and definition:
            return f"{translation} · {definition}"
        if english_status == "source_attested" and definition:
            return f"{translation} · {definition} [영어 정의 단일 출처]"
        return translation
    return definition if english_status == "cross_verified" else ""


class StudyData:
    def __init__(self, path, *, include_open_evidence=False):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            self.words = index(records(connection, "SELECT * FROM words ORDER BY normalized, word_id"), "word_id")
            self.senses = index(records(connection, "SELECT * FROM senses ORDER BY sense_id"), "sense_id")
            self.occurrences = group(
                records(connection, "SELECT * FROM occurrences ORDER BY source_id, day, filename, pdf_page, occurrence_id"),
                "word_id",
            )
            self.sense_origins = group(records(connection, "SELECT * FROM sense_occurrences ORDER BY occurrence_id"), "sense_id")
            self.english = index(records(connection, "SELECT * FROM english_definitions"), "sense_id")
            self.korean = index(records(connection, "SELECT * FROM korean_translations"), "sense_id")
            self.sources = index(records(connection, "SELECT * FROM sources ORDER BY source_id"), "source_id")
            self.evidence = defaultdict(list)
            for row in records(connection, "SELECT * FROM evidence ORDER BY source_id, evidence_id"):
                self.evidence[row["object_type"], row["object_id"]].append(row)
            self.nodes = index(records(connection, "SELECT * FROM nodes ORDER BY label, node_id"), "node_id")
            self.edges = records(connection, "SELECT * FROM edges ORDER BY relation_type, from_node_id, to_node_id, edge_id")
            self.open_evidence = load_open_evidence(connection, CORE_SOURCES) if include_open_evidence else {}
        self.word_senses = group(self.senses.values(), "word_id")
        self.homonyms = group(self.words.values(), "normalized")
        self.sense_keys = {}
        for sense_id, sense in self.senses.items():
            word = self.words[sense["word_id"]]
            key = (word["normalized"], word["homonym_key"], sense["part_of_speech"], sense["sense_key"])
            self.sense_keys[key] = sense_id
        self.edges_from = group(self.edges, "from_node_id")
        self.edges_to = group(self.edges, "to_node_id")
        self.word_nodes = group(self.nodes.values(), "word_id")
        self.sense_nodes = group(self.nodes.values(), "sense_id")

    def role(self, word_id):
        sources = {item["source_id"] for item in self.occurrences.get(word_id, ())}
        if CORE_SOURCES & sources:
            return "core"
        if BACK_SOURCE in sources:
            return "back"
        return "extension"

    def citations(self, object_type, object_id):
        citations = []
        for row in self.evidence.get((object_type, object_id), ()):
            source = self.sources.get(row["source_id"], {})
            citations.append({
                **row,
                "source_title": source.get("title"),
                "source_url": source.get("url"),
                "independence_group": source.get("independence_group"),
                "source_license": source.get("license"),
            })
        return citations

    def meaning(self, sense_id):
        english = self.english.get(sense_id, {})
        korean = self.korean.get(sense_id, {})
        english_status = english.get("status") or "unverified"
        korean_status = korean.get("status") or "unverified"
        return {
            "english_definition": english.get("english_definition"),
            "definition_origin": english.get("definition_origin"),
            "english_definition_status": english_status,
            "english_definition_sources": self.citations("english_definition", sense_id),
            "english_verification_date": english.get("verification_date"),
            "verified_korean_meaning": korean.get("verified_korean_meaning"),
            "korean_translation_status": korean_status,
            "korean_translation_sources": self.citations("korean_translation", sense_id),
            "translation_uncertainty_reason": korean.get("translation_uncertainty_reason"),
            "korean_verification_date": korean.get("verification_date"),
            "preferred_display_language": self.senses.get(sense_id, {}).get("preferred_display_language"),
            "verification_date": max(
                filter(None, (english.get("verification_date"), korean.get("verification_date"))),
                default=None,
            ),
        }

    def node_object(self, node):
        if node["node_type"] == "WORD":
            return node.get("word_id")
        if node["node_type"] == "SENSE":
            return node.get("sense_id")
        return None

    def graph_evidence(self, object_type, record):
        object_id = record[f"{object_type}_id"]
        citations = self.citations(object_type, object_id)
        if object_type == "node" and not citations:
            underlying_id = self.node_object(record)
            if underlying_id:
                underlying_type = record["node_type"].lower()
                citations = self.citations(underlying_type, underlying_id)
                if underlying_type == "sense" and not citations:
                    citations = self.citations("english_definition", underlying_id)
        return citations

    def node_meaning(self, node):
        sense_id = node.get("sense_id")
        reference = object_properties(node).get("definition_sense")
        if not sense_id and isinstance(reference, dict):
            headword = normalized_lemma(path_label(reference.get("headword")))
            homonym = reference.get("homonym_key") or ""
            part_of_speech = normalized_pos(reference.get("part_of_speech"))
            sense_key = reference.get("sense_key")
            if isinstance(homonym, str) and isinstance(sense_key, str):
                sense_id = self.sense_keys.get((headword, homonym, part_of_speech, sense_key))
        return self.meaning(sense_id) if sense_id else {}

    def node_word(self, node_id):
        node = self.nodes[node_id]
        if node["node_type"] == "WORD":
            return node.get("word_id")
        if node["node_type"] == "SENSE":
            return node.get("word_id") or self.senses.get(node.get("sense_id"), {}).get("word_id")
        return None

    def node_label(self, node_id):
        node = self.nodes[node_id]
        if node["node_type"] == "SENSE":
            sense = self.senses.get(node.get("sense_id"), {})
            word = self.words.get(sense.get("word_id"), {})
            label = word.get("headword") or node["label"]
            pos = sense.get("part_of_speech")
            return f"{label} ({pos})" if pos else label
        return node["label"]

    def word_edges(self, word_id):
        node_ids = {node["node_id"] for node in self.word_nodes.get(word_id, ())}
        for sense in self.word_senses.get(word_id, ()):
            node_ids.update(node["node_id"] for node in self.sense_nodes.get(sense["sense_id"], ()))
        edges = {}
        for node_id in sorted(node_ids):
            for edge in self.edges_from.get(node_id, []) + self.edges_to.get(node_id, []):
                edges[edge["edge_id"]] = edge
        return edges.values()


RELATION_LABELS = {
    "HAS_MORPHEME": "형태소",
    "HAS_ROOT": "현대 어근",
    "HAS_BASE": "어기",
    "HAS_STEM": "어간",
    "HAS_PREFIX": "접두사",
    "HAS_SUFFIX": "접미사",
    "HAS_INFLECTIONAL_ENDING": "굴절어미",
    "DERIVED_FROM": "파생",
    "INFLECTION_OF": "굴절",
    "COMPOUND_COMPONENT_OF": "합성어 구성 요소",
    "ETYMOLOGICALLY_DERIVED_FROM": "역사적 파생",
    "HAS_ETYMOLOGICAL_ROOT": "역사적 어근",
    "HAS_HISTORICAL_FORM": "역사적 원형",
    "HAS_ETYMOLOGICAL_AFFIX": "역사적 접사",
    "HAS_ORIGIN_LANGUAGE": "기원 언어",
    "VARIANT_OF": "변이형",
    "COGNATE_WITH": "동계어",
    "BORROWED_FROM": "차용",
    "HAS_SEMANTIC_CHANGE": "의미 변화",
    "SYNONYM_OF": "동의어",
    "NEAR_SYNONYM_OF": "유의어",
    "ANTONYM_OF": "반의어",
    "COMPLEMENTARY_TO": "상보적 대립",
    "GRADABLE_OPPOSITE_OF": "정도적 대립",
    "CONVERSE_OF": "관계적 대립",
    "REVERSIVE_OF": "역행적 대립",
    "CONTEXTUAL_OPPOSITE_OF": "문맥상 대립",
    "HYPERNYM_OF": "상위어 관계",
    "HYPONYM_OF": "하위어 관계",
    "MERONYM_OF": "부분·전체 관계",
    "BELONGS_TO_SYNSET": "WordNet Synset",
    "BELONGS_TO_SEMANTIC_FIELD": "의미장",
    "BELONGS_TO_THEME": "테마",
    "COLLOCATES_WITH": "콜로케이션 결합",
    "PARTICIPATES_IN_COLLOCATION": "콜로케이션",
    "HAS_COLLIGATION": "문법적 연어",
    "PARTICIPATES_IN_IDIOM": "숙어",
    "PARTICIPATES_IN_PHRASAL_VERB": "구동사",
    "HAS_VERB_PATTERN": "동사 문형",
    "HAS_ARGUMENT_STRUCTURE": "논항 구조",
    "HAS_COUNTABILITY": "가산성",
    "HAS_TRANSITIVITY": "자·타동사",
    "HAS_REGISTER": "사용역",
}
OPPOSITION_RELATIONS = frozenset({
    "ANTONYM_OF", "COMPLEMENTARY_TO", "GRADABLE_OPPOSITE_OF", "CONVERSE_OF",
    "REVERSIVE_OF", "CONTEXTUAL_OPPOSITE_OF",
})


def study_edges(data):
    for edge in data.edges:
        if edge["status"] in ATTESTED and data.graph_evidence("edge", edge):
            yield edge


def node_type(data, node_id):
    return data.nodes[node_id]["node_type"]
