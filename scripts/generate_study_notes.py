#!/usr/bin/env python3
"""Generate the three study parts and a 60-day evidence-backed study schedule."""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from study_open_evidence import CORPUS_TYPES, DICTIONARY_SOURCES, RELATIONS

from study_data import (
    BACK_SOURCE, CORE_SOURCES, ENGLISH_LABELS, KOREAN_LABELS, OPPOSITION_RELATIONS,
    RELATION_LABELS, StudyData, atomic_text, json_text, markdown, object_properties, path_label, study_edges,
)

CORE = "part01_core_words"
ETYMOLOGY = "part02_etymology_idioms"
SEMANTICS = "part03_synonym_theme"
EMPTY = "현재 근거가 확인된 학습 항목이 없습니다."
STATUS_LABELS = {
    "cross_verified": "교차 검증",
    "source_attested": "단일 출처 확인",
    "corpus_attested": "말뭉치 확인",
    "inferred": "추가 검증 필요",
    "disputed": "출처 간 불일치",
    "unverified": "미검증",
    "unavailable": "자료 접근 불가",
    "not_applicable": "해당 없음",
}


@dataclass(frozen=True)
class Category:
    directory: str
    title: str
    relations: frozenset[str]
    groups: frozenset[str] = frozenset()
    module: str | None = None
    idiom_class: str | None = None
    affix_type: str | None = None


def category(part, directory, title, relations, groups=(), **filters):
    if isinstance(relations, str):
        relations = (relations,)
    if isinstance(groups, str):
        groups = (groups,)
    return Category(
        f"{part}/{directory}", title, frozenset(relations), frozenset(groups), **filters,
    )


PREFIXES = category(ETYMOLOGY, "prefixes", "역사적 접두사", "HAS_ETYMOLOGICAL_AFFIX",
                    ("PREFIX", "ETYMOLOGICAL_AFFIX"), module="etymology", affix_type="prefix")
ROOTS = category(ETYMOLOGY, "roots", "역사적 어근", "HAS_ETYMOLOGICAL_ROOT", "ETYMOLOGICAL_ROOT")
IDIOM_CLASSES = (
    ("preposition", "prepositions", "전치사"),
    ("adverb", "adverbs", "부사"),
    ("verb", "verbs", "기본동사"),
    ("noun", "nouns", "기본명사"),
)
IDIOMS = tuple(
    category(ETYMOLOGY, f"idioms_{directory}", f"{label} 중심 숙어", "PARTICIPATES_IN_IDIOM",
             "IDIOM", idiom_class=key)
    for key, directory, label in IDIOM_CLASSES
)
IDIOMS_ALL = category(ETYMOLOGY, "idioms", "숙어", "PARTICIPATES_IN_IDIOM", "IDIOM")
PHRASAL_VERBS = category(ETYMOLOGY, "phrasal_verbs", "구동사", "PARTICIPATES_IN_PHRASAL_VERB", "PHRASAL_VERB")
SYNONYMS = category(SEMANTICS, "synonyms", "동의어", "SYNONYM_OF")
NEAR_SYNONYMS = category(SEMANTICS, "near_synonyms", "유의어", "NEAR_SYNONYM_OF")
ANTONYMS = category(SEMANTICS, "antonyms", "의미 대립", OPPOSITION_RELATIONS)
SEMANTIC_FIELDS = category(SEMANTICS, "semantic_fields", "의미장", "BELONGS_TO_SEMANTIC_FIELD", "SEMANTIC_FIELD")
THEMES = category(SEMANTICS, "themes", "테마", "BELONGS_TO_THEME", "THEME")
HIERARCHIES = category(SEMANTICS, "hierarchies", "보조 의미 관계", ("HYPERNYM_OF", "HYPONYM_OF", "MERONYM_OF"))
SEMANTIC_CATEGORIES = (THEMES, SEMANTIC_FIELDS, SYNONYMS, NEAR_SYNONYMS, ANTONYMS, HIERARCHIES)
CATEGORIES = (
    PREFIXES, ROOTS, *IDIOMS, IDIOMS_ALL, PHRASAL_VERBS, *SEMANTIC_CATEGORIES,
    category(ETYMOLOGY, "suffix_index", "접미사", ("HAS_SUFFIX", "HAS_ETYMOLOGICAL_AFFIX"),
             ("SUFFIX", "ETYMOLOGICAL_AFFIX"), affix_type="suffix"),
    category(ETYMOLOGY, "morphological_index/bases_stems", "어간과 어기", ("HAS_BASE", "HAS_STEM"), ("BASE", "STEM")),
    category(ETYMOLOGY, "morphological_index/components", "현대 형태소", ("HAS_MORPHEME", "HAS_ROOT", "HAS_PREFIX"),
             ("MORPHEME", "ROOT", "PREFIX"), module="morphology"),
    category(ETYMOLOGY, "morphological_index/derivations", "파생어", "DERIVED_FROM", ("WORD", "SENSE")),
    category(ETYMOLOGY, "morphological_index/inflections", "굴절형", ("INFLECTION_OF", "HAS_INFLECTIONAL_ENDING"),
             ("WORD", "INFLECTIONAL_ENDING")),
    category(ETYMOLOGY, "morphological_index/compounds", "합성어", "COMPOUND_COMPONENT_OF", "WORD"),
    category(ETYMOLOGY, "cognates", "동계어", "COGNATE_WITH"),
    category(CORE, "collocations", "콜로케이션", ("PARTICIPATES_IN_COLLOCATION", "COLLOCATES_WITH"), "COLLOCATION"),
    category(CORE, "colligations", "문법적 연어", "HAS_COLLIGATION", "COLLIGATION"),
    category(CORE, "verb_patterns", "동사 문형", "HAS_VERB_PATTERN", "GRAMMATICAL_PATTERN"),
)

# Content fields allowed in study notes. Technical processing metadata remains in the graph.
EXPLANATION_FIELDS = {
    "english_example": "영어 예문",
    "example": "영어 예문",
    "example_origin": "예문 유형",
    "context": "사용 문맥",
    "toeic_evidence": "TOEIC 확인 근거",
    "toeic_official": "공개 TOEIC 자료에서 확인",
    "study_rationale": "학습에 포함한 근거",
    "pattern": "문형",
    "construction": "문법 구조",
    "combination_type": "결합 유형",
    "argument_roles": "논항",
    "arguments": "논항",
    "origin_language": "기원 언어",
    "historical_form": "역사적 원형",
    "historical_gloss": "역사적 의미",
    "earlier_meaning": "이전 의미",
    "later_meaning": "이후 의미",
    "shared_origin": "공통 기원",
    "cognate_type": "동계 유형",
    "change_type": "변화 유형",
    "borrowing_path": "차용 경로",
    "variants": "변이형",
    "modern_function": "현대 기능",
    "base": "어기",
    "affix": "접사",
    "affixes": "접사",
    "inflection": "활용 정보",
    "features": "활용 정보",
    "part_of_speech_change": "품사 변화",
    "source_pos": "출발 품사",
    "target_pos": "도착 품사",
    "meaning_change": "의미 변화",
    "semantic_change": "의미 변화",
    "form_change": "형태 변화",
    "semantic_overlap": "공통 의미",
    "interchangeable_context": "대체 가능한 문맥",
    "non_interchangeable_context": "대체가 어려운 문맥",
    "register": "사용역",
    "countability": "가산성",
    "transitivity": "자·타동사",
    "particle": "불변화사",
    "base_verb": "기본동사",
    "separable": "분리 가능 여부",
    "separability": "분리 가능 여부",
    "pronoun_position": "대명사 목적어 위치",
}


def row_text(text):
    return markdown(text).replace("#", "\\#")


def source_links(evidence):
    links = {}
    for row in evidence:
        title = row_text(row.get("source_title") or row["source_id"])
        record = row.get("source_record_id")
        label = title + (" · " + row_text(record) if record else "")
        url = path_label(row.get("url") or row.get("source_url"))
        try:
            parsed = urlsplit(url)
            safe_url = quote(url, safe="/:?&=%#+,@~.-") if parsed.scheme in {"http", "https"} and parsed.netloc else ""
        except ValueError:
            safe_url = ""
        links[(label, safe_url)] = f"[{label}]({safe_url})" if safe_url else label
    return " · ".join(links.values())


def cited(text, evidence):
    links = source_links(evidence)
    return f"{text} · {links}" if links else text


def meaning_lines(meaning):
    lines = []
    english_status = meaning.get("english_definition_status") or "unverified"
    korean_status = meaning.get("korean_translation_status") or "unverified"
    definition = meaning.get("english_definition")
    translation = meaning.get("verified_korean_meaning")
    english_label = ENGLISH_LABELS.get(english_status, english_status)
    korean_label = KOREAN_LABELS.get(korean_status, korean_status)
    verified_korean = korean_status == "verified" and bool(translation)
    if verified_korean:
        lines.append(cited(f"- {korean_label} · {row_text(translation)}", meaning.get("korean_translation_sources", ())))
    english_line = f"- {english_label}"
    if definition:
        english_line += " · " + row_text(definition)
    source_rows = meaning.get("english_definition_sources", ())
    if meaning.get("definition_origin") == "paraphrase":
        english_line += " · 의미를 재구성한 정의"
    lines.append(cited(english_line, source_rows))
    if english_status == "disputed":
        for source in source_rows:
            if note := source.get("note"):
                lines.append(cited("  - " + row_text(note), (source,)))
    if not verified_korean:
        reason = meaning.get("translation_uncertainty_reason")
        korean_line = f"- {korean_label}"
        if reason:
            korean_line += " · " + row_text(reason)
        lines.append(cited(korean_line, meaning.get("korean_translation_sources", ())))
    return lines


def explain(properties, *, indent=""):
    lines = []
    for field, label in EXPLANATION_FIELDS.items():
        value = properties.get(field)
        if value is not None and value != "":
            if isinstance(value, (list, dict)):
                value = json_text(value)
            lines.append(f"{indent}- {label} · {row_text(value)}")
    return lines


def sort_key(data, node_id):
    node = data.nodes[node_id]
    properties = object_properties(node)
    order = properties.get("study_order")
    if not isinstance(order, int):
        order = 1000000
    return order, path_label(data.node_label(node_id)).casefold(), node_id


def note_node_label(data, node_id):
    node = data.nodes[node_id]
    label = row_text(data.node_label(node_id))
    if node["node_type"] == "SENSE" and node.get("sense_id"):
        return label + " · " + row_text(node["sense_id"])
    return label


def grouped_edges(data, edges, spec):
    groups = defaultdict(list)
    for edge in edges:
        relation = edge["relation_type"]
        if relation not in spec.relations:
            continue
        properties = object_properties(edge)
        if spec.module is not None and properties.get("module") != spec.module:
            continue
        source, target = edge["from_node_id"], edge["to_node_id"]
        if relation == "COMPOUND_COMPONENT_OF":
            order = (target, source)
        elif relation in {"DERIVED_FROM", "INFLECTION_OF"}:
            order = (target, source)
        elif relation == "HAS_INFLECTIONAL_ENDING":
            order = (target, source)
        else:
            order = (target, source) if spec.groups else (source, target)
        primary = next((node_id for node_id in order if data.nodes[node_id]["node_type"] in spec.groups), order[0])
        primary_node = data.nodes[primary]
        primary_attributes = object_properties(primary_node)
        if spec.affix_type is not None:
            kind = primary_node["node_type"]
            affix = primary_attributes.get("affix_type") or properties.get("affix_type")
            if kind.casefold() != spec.affix_type and affix != spec.affix_type:
                continue
        if spec.idiom_class is not None:
            classification = properties.get("idiom_category") or primary_attributes.get("idiom_category")
            if classification != spec.idiom_class:
                continue
        members = [data.node_word(node_id) for node_id in (source, target)]
        if all(word_id is None or data.role(word_id) == "extension" for word_id in members):
            continue
        groups[primary].append(edge)
    return {node_id: groups[node_id] for node_id in sorted(groups, key=lambda item: sort_key(data, item))}


def edge_lines(data, edge):
    from_id, to_id = edge["from_node_id"], edge["to_node_id"]
    relation = edge["relation_type"]
    status = STATUS_LABELS.get(edge["status"], edge["status"])
    line = (
        f"- {RELATION_LABELS.get(relation, relation)} · {note_node_label(data, from_id)}"
        f" → {note_node_label(data, to_id)} · {status}"
    )
    evidence = data.graph_evidence("edge", edge)
    return [cited(line, evidence), *explain(object_properties(edge), indent="  ")]


def node_extra_lines(data, node):
    properties = object_properties(node)
    meaning = data.node_meaning(node)
    has_status = meaning.get("english_definition_status") or meaning.get("korean_translation_status")
    if node.get("sense_id") or has_status:
        lines = meaning_lines(meaning)
    else:
        lines = []
    lines += explain(properties)
    if sources := source_links(data.graph_evidence("node", node)):
        lines.append(f"- 근거 자료 · {sources}")
    return lines


def write_markdown(path, lines):
    with atomic_text(path) as stream:
        stream.write("\n".join(lines).rstrip() + "\n")


def render_category(data, output, spec, groups):
    lines = [f"# {spec.title}", "", f"근거를 확인한 학습 집단 {len(groups)}개", ""]
    if not groups:
        lines.append(EMPTY)
    for node_id, edges in groups.items():
        node = data.nodes[node_id]
        lines += [f"## {note_node_label(data, node_id)}", ""]
        lines += node_extra_lines(data, node)
        companion_nodes = set()
        for edge in edges:
            lines += edge_lines(data, edge)
            companion_nodes.update({edge["from_node_id"], edge["to_node_id"]} - {node_id})
        for companion in sorted(companion_nodes, key=lambda item: sort_key(data, item)):
            related = data.nodes[companion]
            if related["node_type"] != "SENSE":
                continue
            lines += ["", f"### {note_node_label(data, companion)}", ""]
            lines += node_extra_lines(data, related)
        lines.append("")
    write_markdown(output / spec.directory / "README.md", lines)


def occurrence_line(data, occurrence):
    source = data.sources.get(occurrence["source_id"], {})
    parts = [row_text(source.get("title") or occurrence["source_id"])]
    if occurrence.get("day"):
        day = occurrence["day"]
        parts.append(f"DAY {day:02}" if isinstance(day, int) else f"DAY {row_text(day)}")
    for field, label in (
        ("category", ""), ("filename", ""), ("pdf_page", "PDF "), ("printed_page", "교재 "),
        ("source_record_id", "레코드 "), ("part_of_speech", "품사 "), ("entry_type", "유형 "),
        ("original_korean_meaning", "교재 원문 "),
    ):
        if occurrence.get(field) is not None and occurrence[field] != "":
            parts.append(label + row_text(occurrence[field]))
    if status := occurrence.get("verification_status"):
        parts.append(STATUS_LABELS.get(status, row_text(status)))
    return cited("- " + " · ".join(parts), data.citations("occurrence", occurrence["occurrence_id"]))


def core_filename(word_id, headword):
    slug = re.sub(r"[^a-z0-9]+", "-", headword.casefold()).strip("-")[:64]
    digest = hashlib.sha256(word_id.encode()).hexdigest()[:20]
    return f"word-{slug or 'entry'}-{digest}.md"


def open_source_citation(data, item):
    source = data.sources.get(item["source_id"], {})
    title = item.get("source_title") or item["source_id"]
    stamp = " · ".join(filter(None, (str(title), item["source_id"], str(item.get("version") or ""))))
    return [{
        "source_title": stamp, "source_id": item["source_id"],
        "source_record_id": item["source_record_id"], "url": item.get("url"),
        "source_url": source.get("url"),
    }]


def detail_label(item, *, tag=False):
    pos = item.get("part_of_speech")
    return " · " + ("자동 품사 태그 " if tag else "출처 품사 ") + row_text(pos) if pos else ""


def cite_open(data, text, item):
    if license_name := item.get("source_license"):
        text += " · 이용 조건 " + row_text(license_name)
    return cited(text, open_source_citation(data, item))


def excerpt(attestation):
    start = attestation["start"] - attestation["context_start"]
    end = attestation["end"] - attestation["context_start"]
    context = attestation["context"]
    left = max(0, start - 60)
    right = min(len(context), end + 88)
    return ("…" if left else "") + path_label(context[left:right]) + ("…" if right < len(context) else "")


def open_evidence_lines(data, preview):
    lines = []
    if preview.definitions or preview.relations:
        lines += ["", "## 공개 사전의 참고 자료", "",
                  "공개 사전에 수록된 자료입니다. 교재의 뜻과 개별 의미 간 대응은 미검토 상태입니다.", ""]
        for source_id in DICTIONARY_SOURCES:
            definitions = preview.definitions.get(source_id, [])
            relation_count = preview.counts[source_id, "relation"]
            if not definitions and not relation_count:
                continue
            source = data.sources.get(source_id, {})
            lines += [
                f"### {row_text(source.get('title') or source_id)}", "",
                f"원문 정의 후보 {preview.counts[source_id, 'definition']:,}건 중 {len(definitions)}건을 표시합니다.",
                "",
            ]
            for item in definitions:
                definition = path_label(item["definition"])
                if len(definition) > 220:
                    definition = definition[:217].rstrip() + "…"
                text = "- 원문 정의" + detail_label(item) + " · " + row_text(definition)
                if item["tags"]:
                    text += " · 출처 태그 " + row_text(", ".join(map(str, item["tags"])))
                if item.get("qualifiers"):
                    text += " · 출처 한정 정보 " + row_text(item["qualifiers"])
                lines.append(cite_open(data, text, item))
            if relation_count:
                shown = [(relation, items[0]) for relation, items in preview.relations.items()
                         if relation[0] == source_id and items]
                lines += ["", f"사전 관계 후보 {relation_count:,}건 중 {len(shown)}건을 표시합니다.", ""]
                for relation, item in sorted(shown):
                    text = f"- {RELATIONS[relation]}{detail_label(item)} · {row_text(item['target'])}"
                    if item.get("external_sense_id") and item.get("target_external_sense_id"):
                        text += (
                            " · 원천 의미 " + row_text(item["external_sense_id"])
                            + " → " + row_text(item["target_external_sense_id"])
                        )
                    details = item.get("details")
                    if isinstance(details, dict):
                        if lang := details.get("target_language"):
                            text += " · 언어 코드 " + row_text(lang)
                        if tags := details.get("tags"):
                            text += " · 태그 " + row_text(", ".join(map(str, tags)))
                    lines.append(cite_open(data, text, item))
            lines.append("")
    if preview.corpus:
        lines += [
            "", "## OANC 일반 영어 사용례", "",
            f"문서와 위치가 확인된 말뭉치 레코드 {preview.counts['oanc', 'usage']:,}건 중 "
            f"{len(preview.corpus)}건을 표시합니다. 품사 태그와 인접 결합은 자동 분석 결과입니다.", "",
        ]
        for corpus_type, label in CORPUS_TYPES.items():
            if not (items := preview.corpus.get(corpus_type)):
                continue
            item = items[0]
            attestation = item["attestation"]
            text = f"- {label} · {row_text(item['expression'])}{detail_label(item, tag=True)}"
            if document_limit := item.get("test_document_limit"):
                text += f" · 최대 {document_limit:,}문서 범위"
            text += (
                f" · {item['frequency']:,}회 · 발췌 “{row_text(excerpt(attestation))}”"
                f" · {row_text(attestation['document'])} 문자 {attestation['start']}–{attestation['end']}"
            )
            lines.append(cite_open(data, text, item))
    if preview.official:
        lines += [
            "", "## 공식 TOEIC 공개 샘플 사용례", "",
            f"공개 샘플 출현 {preview.counts['toeic', 'usage']:,}건 중 {len(preview.official)}건을 표시합니다.", "",
        ]
        for item in preview.official:
            text = f"- {row_text(item['expression'])}{detail_label(item)} · {row_text(item['item_locator'])}"
            lines.append(cite_open(data, text, item))
    return lines


def render_core(data, output, approved_ids):
    destination = output / CORE
    filenames = {}
    lines = ["# PART 1 핵심 표제어", ""]
    for word_id, word in data.words.items():
        if data.role(word_id) != "core":
            continue
        title = row_text(word["headword"])
        if word["homonym_key"]:
            title += " · " + row_text(word["homonym_key"])
        filename = core_filename(word_id, word["headword"])
        filenames[word_id] = filename
        lines.append(f"- [{title}]({filename})")
        note = [f"# {title}", "", f"어휘 식별자 `{word_id}`", "", "## 원천 출현 위치", ""]
        note += [occurrence_line(data, item) for item in data.occurrences[word_id]]
        note += ["", "## 개별 의미", ""]
        senses = data.word_senses.get(word_id, ())
        if not senses:
            note += ["개별 의미 정렬을 기다리고 있습니다."]
        for sense in senses:
            sense_id = sense["sense_id"]
            note += [f"### {row_text(sense['part_of_speech'])} · {row_text(sense_id)}", ""]
            note += meaning_lines(data.meaning(sense_id))
            aligned = {row["occurrence_id"] for row in data.sense_origins.get(sense_id, ())}
            note += [
                occurrence_line(data, item) for item in data.occurrences[word_id]
                if item["occurrence_id"] in aligned
            ]
            note.append("")
        if preview := data.open_evidence.get(word_id):
            note += open_evidence_lines(data, preview)
        note += ["", "## 형태·어원·의미·용법 연결", ""]
        edges = [
            edge for edge in data.word_edges(word_id)
            if edge["edge_id"] in approved_ids and edge["relation_type"] in RELATION_LABELS
        ]
        if not edges:
            note.append(EMPTY)
        for edge in sorted(edges, key=lambda item: (item["relation_type"], item["edge_id"])):
            note += edge_lines(data, edge)
        write_markdown(destination / filename, note)
    if not filenames:
        lines.append(EMPTY)
    core_previews = [data.open_evidence[word_id] for word_id in filenames if word_id in data.open_evidence]
    if core_previews:
        dictionary_count = sum(bool(preview.definitions) for preview in core_previews)
        corpus_count = sum(bool(preview.corpus) for preview in core_previews)
        official_count = sum(bool(preview.official) for preview in core_previews)
        lines += [
            "", "## 참고 자료가 있는 핵심 어휘", "",
            f"- 공개 사전 정의 후보가 있는 어휘 {dictionary_count:,}개",
            f"- OANC 문서와 위치가 확인된 어휘 {corpus_count:,}개",
            f"- 공식 TOEIC 공개 샘플에서 표현을 확인한 어휘 {official_count:,}개",
        ]
    lines += ["", "## 결합 표현과 문형", ""]
    for spec in CATEGORIES:
        if spec.directory.startswith(CORE + "/"):
            relative = spec.directory.removeprefix(CORE + "/")
            lines.append(f"- [{spec.title}]({relative}/README.md)")
    write_markdown(destination / "README.md", lines)
    return filenames


def schedule_groups(data, catalogs, specs, *, prefer_non_etymological=frozenset()):
    items = []
    for spec in specs:
        for structured, edges in catalogs[spec].items():
            members = set()
            for edge in edges:
                for field in ("from_node_id", "to_node_id"):
                    word_id = data.node_word(edge[field])
                    if word_id and data.role(word_id) != "extension":
                        members.add(word_id)
            edge_orders = [
                value for edge in edges if isinstance(value := object_properties(edge).get("study_order"), int)
            ]
            node_rank, label, node_id = sort_key(data, structured)
            rank = min([node_rank, *edge_orders])
            priority = bool(prefer_non_etymological and members and members <= prefer_non_etymological)
            items.append((spec, structured, members, (priority, rank, label, node_id)))
    return sorted(items, key=lambda item: item[3])


def day_groups(groups, days):
    # Keep each group intact. Use the early days when fewer groups than days are available.
    days_used = min(len(groups), days)
    result = [[] for _ in range(days)]
    for position, group in enumerate(groups):
        result[position * days_used // len(groups)].append(group)
    return result


def schedule_item(data, spec, node_id, members, core_files):
    word_labels = []
    for word_id in sorted(members, key=lambda item: (data.role(item) != "core", data.words[item]["normalized"], item)):
        label = row_text(data.words[word_id]["headword"])
        if filename := core_files.get(word_id):
            label = f"[{label}]({CORE}/{filename})"
        word_labels.append(label)
    text = f"- {note_node_label(data, node_id)} · [{spec.title}]({spec.directory}/README.md)"
    if word_labels:
        text += " · " + ", ".join(word_labels)
    return text


def render_schedule(data, output, catalogs, core_files):
    prefixes = schedule_groups(data, catalogs, (PREFIXES,))
    roots = schedule_groups(data, catalogs, (ROOTS,))
    etymological_words = frozenset(member for _, _, members, _ in prefixes + roots for member in members)
    idioms = schedule_groups(data, catalogs, IDIOMS)
    semantics = schedule_groups(data, catalogs, SEMANTIC_CATEGORIES, prefer_non_etymological=etymological_words)
    part2_groups = day_groups(prefixes, 10) + day_groups(roots, 30)
    part2_idioms = day_groups(idioms, 40)
    lines = [
        "# 60일 학습 일정", "",
        "보카바이블 B권의 학습 원리를 적용한 자체 일정입니다. 각 날짜의 학습 항목은 데이터베이스의 출처 확인 상태를 반영합니다.", "",
        "## PART 2 어원과 숙어 · 40일", "",
    ]
    for day, (groups, usage) in enumerate(zip(part2_groups, part2_idioms), start=1):
        label = "접두사" if day <= 10 else "어근"
        heading = "접두사와 숙어" if day <= 10 else "어근과 숙어"
        lines += [f"### DAY {day:02} {heading}", ""]
        for spec, node_id, members, _ in groups + usage:
            lines.append(schedule_item(data, spec, node_id, members, core_files))
        if not groups:
            lines.append(f"- {label} · {EMPTY}")
        if not usage:
            lines.append(f"- 숙어 · {EMPTY}")
        lines.append("")
    lines += ["## PART 3 동의어와 테마 · 20일", ""]
    for day, groups in enumerate(day_groups(semantics, 20), start=1):
        lines += [f"### DAY {day:02} 의미 관계와 테마", ""]
        for spec, node_id, members, _ in groups:
            lines.append(schedule_item(data, spec, node_id, members, core_files))
        if not groups:
            lines.append(EMPTY)
        lines.append("")
    write_markdown(output / "schedule.md", lines)


def generate_notes(data, output):
    approved = list(study_edges(data))
    catalogs = {spec: grouped_edges(data, approved, spec) for spec in CATEGORIES}
    core_files = render_core(data, output, {edge["edge_id"] for edge in approved})
    for spec, groups in catalogs.items():
        render_category(data, output, spec, groups)
    render_schedule(data, output, catalogs, core_files)
    back_words = sum(
        any(item["source_id"] == BACK_SOURCE for item in rows) for rows in data.occurrences.values()
    )
    core_occurrences = sum(
        item["source_id"] in CORE_SOURCES for rows in data.occurrences.values() for item in rows
    )
    lines = [
        "# 어휘 학습 노트", "",
        f"- 본 단어 {len(core_files)}개 · 출현 {core_occurrences}건 [PART 1]({CORE}/README.md)",
        f"- 뒷단어 {back_words}개 · 본 단어와 중복될 수 있습니다.",
        "- [PART 2 어원과 숙어](part02_etymology_idioms/README.md)",
        "- [PART 3 동의어와 테마](part03_synonym_theme/README.md)",
        "- [60일 학습 일정](schedule.md)",
    ]
    if not core_files or not back_words:
        lines += ["", "원천 어휘 확보 현황에 따라 일부 학습 경로가 비어 있습니다."]
    write_markdown(output / "README.md", lines)
    for part, title in ((ETYMOLOGY, "PART 2 어원과 숙어"), (SEMANTICS, "PART 3 동의어와 테마")):
        index = [f"# {title}", ""]
        for spec in CATEGORIES:
            if spec.directory.startswith(part + "/"):
                relative = spec.directory.removeprefix(part + "/")
                index.append(f"- {spec.title} · {len(catalogs[spec])}개 집단 [학습 노트]({relative}/README.md)")
        write_markdown(output / part / "README.md", index)
    return len(core_files), sum(map(len, catalogs.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output", type=Path, default=Path("notes"))
    args = parser.parse_args()
    core, groups = generate_notes(StudyData(args.db, include_open_evidence=True), args.output)
    print(f"{core} core notes, {groups} study groups, 60 scheduled days")


if __name__ == "__main__":
    main()
