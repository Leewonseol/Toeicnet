#!/usr/bin/env python3
"""Regenerate local study notes and grade-aware Anki text imports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from generate_study_notes import CORE, core_filename, generate_notes, write_markdown
from study_data import CORE_SOURCES, KOREAN_LABELS, StudyData, atomic_text, markdown, path_label


GRADE_LABEL = {
    "A": "독립 학습자 영영사전 2종 이상",
    "B": "독립 공개 어휘 자료 2종 이상",
    "C": "단일 출처",
    "D": "추가 검토 필요",
    "E": "근거 미확보",
}
MODULE_LABEL = {
    "morphology": "형태론",
    "etymology": "어원론",
    "lexical_semantics": "어휘 의미론",
    "lexical_usage": "어휘 결합 및 용법",
}
ORIGIN_LABEL = {
    "paraphrase": "검증 근거를 바탕으로 재작성한 영어 정의",
    "llm_original_definition": "검색 근거를 바탕으로 모델이 재작성한 영어 정의",
    "open_source_gloss": "공개 사전 영어 정의",
}
OPEN_LICENSE = {
    "oewn": ("https://creativecommons.org/licenses/by/4.0/", "Open English WordNet Community · Princeton WordNet"),
    "kaikki": ("https://creativecommons.org/licenses/by-sa/4.0/", "영어 Wiktionary 기여자 · Kaikki/Wiktextract"),
}
SUPPLEMENT = "batch_rag"
INDEX_LINK = f"- [Batch RAG 검증 등급별 학습 노트]({SUPPLEMENT}/README.md)"


@dataclass
class Card:
    headword: str
    word_id: str
    pos: str
    definition: str
    grade: str
    korean_status: str
    korean: str = ""
    definition_origin: str = ""
    sense_id: str = ""
    candidate_ids: tuple = ()
    occurrences: dict = field(default_factory=dict)
    references: tuple = ()
    korean_reference: dict | None = None

    @property
    def identifier(self):
        value = json.dumps((self.word_id, self.pos, self.definition.casefold()), ensure_ascii=False)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def established_cards(db):
    """Read the already validated A meanings without replacing their review records."""
    cards = {}
    query = """
        SELECT s.sense_id,s.word_id,w.headword,s.part_of_speech,
               en.english_definition,en.definition_origin,
               ko.status AS korean_status,ko.verified_korean_meaning,
               o.occurrence_id,o.source_id,o.day
        FROM english_definitions en JOIN senses s USING(sense_id) JOIN words w USING(word_id)
        JOIN sense_occurrences so USING(sense_id) JOIN occurrences o USING(occurrence_id)
        LEFT JOIN korean_translations ko USING(sense_id)
        WHERE en.status='cross_verified'
        ORDER BY s.sense_id,o.occurrence_id
    """
    for row in db.execute(query):
        definition = path_label(row["english_definition"])
        if not definition:
            continue
        sense_id = row["sense_id"]
        if sense_id not in cards:
            status = row["korean_status"] or "unverified"
            cards[sense_id] = Card(
                row["headword"], row["word_id"], row["part_of_speech"], definition, "A", status,
                path_label(row["verified_korean_meaning"]) if status == "verified" else "",
                row["definition_origin"] or "기존 검증 정의",
                sense_id=sense_id,
            )
        cards[sense_id].occurrences[row["occurrence_id"]] = (row["source_id"], row["day"])
    return cards


def read_references(db, ids, *, definitions=False):
    references = defaultdict(list)
    if definitions:
        query = """
            SELECT ev.object_id AS ref_id,ev.source_id,ev.url,ev.source_record_id,
                   COALESCE(ev.version,s.version) AS version,s.title,s.license
            FROM evidence ev JOIN sources s USING(source_id)
            WHERE ev.object_type='english_definition' AND ev.object_id IN ({})
            ORDER BY s.source_id,ev.source_record_id,ev.evidence_id
        """
    else:
        query = """
            SELECT e.candidate_id AS ref_id,e.source_id,e.source_record_id,s.title,s.license,
                   COALESCE(json_extract(e.payload_json,'$.url'),s.url) AS url,
                   COALESCE(json_extract(e.payload_json,'$.version'),s.version) AS version
            FROM external_candidates e JOIN sources s USING(source_id)
            WHERE e.kind='sense_candidate' AND e.candidate_id IN ({})
            ORDER BY e.source_id,e.source_record_id
        """
    ids = sorted(set(ids))
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        for row in db.execute(query.format(",".join("?" for _ in batch)), batch):
            item = {key: row[key] for key in ("source_id", "source_record_id", "title", "url", "version", "license")}
            if item not in references[row["ref_id"]]:
                references[row["ref_id"]].append(item)
    return references


def reviewed_korean(db, card, target, review):
    """Use bilingual review only when its exact sense and Korean record are present."""
    ids = review.get("candidate_ids") or []
    sense_id = review.get("english_candidate_id")
    meaning = path_label(review.get("meaning"))
    if (
        review.get("status") != "verified" or review.get("method") != "dedicated_bilingual_review"
        or len(ids) != 1 or sense_id not in card.candidate_ids or not meaning
        or meaning != path_label(target.get("original_korean_meaning"))
    ):
        return None
    evidence = db.execute("""
        SELECT k.source_id,k.source_record_id,e.source_record_id AS sense_record_id,s.title,
               COALESCE(json_extract(k.payload_json,'$.url'),s.url) AS url,
               COALESCE(json_extract(k.payload_json,'$.version'),s.version) AS version,s.license,
               json_extract(k.payload_json,'$.target_headword') AS korean_form,
               json_extract(k.payload_json,'$.details.source_sense_label') AS sense_label,
               json_extract(e.payload_json,'$.definition') AS gloss
        FROM external_candidates k JOIN sources s USING(source_id)
        JOIN external_candidates e ON e.source_id=k.source_id
        WHERE k.candidate_id=? AND e.candidate_id=? AND k.source_id='kaikki'
          AND k.kind='relation_candidate' AND e.kind='sense_candidate'
          AND json_extract(k.payload_json,'$.relation_type')='KOREAN_TRANSLATION_CANDIDATE'
    """, (ids[0], sense_id)).fetchone()
    if not evidence or meaning != path_label(evidence["korean_form"]):
        return None
    english_label = path_label(evidence["sense_label"]).casefold().rstrip(" .:;")
    if not english_label or english_label != path_label(evidence["gloss"]).casefold().rstrip(" .:;"):
        return None
    entry, separator, _ = evidence["source_record_id"].partition(":translation:")
    if not separator or not evidence["sense_record_id"].startswith(entry + ":sense:"):
        return None
    return meaning, dict(evidence)


def collect_cards(db, assessments):
    known = established_cards(db)
    signed = read_references(db, known, definitions=True)
    cards = {}
    for sense_id, card in known.items():
        card.references = tuple(signed[sense_id])
        # Established sense IDs are retained even when their definition strings coincide.
        cards[card.word_id, card.pos, card.definition.casefold(), sense_id] = card

    open_cards = {}
    verified_definitions = {(card.word_id, card.pos, card.definition.casefold()) for card in known.values()}
    for assessment in assessments:
        target = assessment["target"]
        en = assessment["english"]
        grade = en["grade"]
        if grade not in ("B", "C") or en.get("source_alignment") is not True:
            continue
        definition = path_label(en.get("definition"))
        candidates = tuple(sorted(set(en.get("candidate_ids") or ())))
        if not definition or not candidates:
            continue
        pos = target.get("part_of_speech") or ""
        key = (target["word_id"], pos, definition.casefold())
        if key in verified_definitions:
            continue
        card = open_cards.get(key)
        if card is None or grade < card.grade:
            previous = card.occurrences if card else {}
            status = assessment.get("korean", {}).get("status") or "unverified"
            card = Card(
                target["headword"], target["word_id"], pos, definition, grade,
                "unverified" if status == "verified" else status,
                definition_origin=path_label(en.get("definition_origin") or "공개 어휘 자료"),
                candidate_ids=candidates, occurrences=previous,
            )
            open_cards[key] = card
        card.occurrences[target["occurrence_id"]] = (target["source_id"], target.get("day"))
        if reviewed := reviewed_korean(db, card, target, assessment.get("korean") or {}):
            card.korean, card.korean_reference = reviewed
            card.korean_status = "verified"

    evidence = read_references(db, (key for card in open_cards.values() for key in card.candidate_ids))
    groups = {
        row["source_id"]: row["independence_group"]
        for row in db.execute("SELECT source_id,independence_group FROM sources")
    }
    for key, card in open_cards.items():
        refs = tuple(item for candidate in card.candidate_ids for item in evidence[candidate])
        groups_seen = {groups[item["source_id"]] for item in refs if item["source_id"] in OPEN_LICENSE}
        groups_seen.discard(None)
        if len(groups_seen) >= (2 if card.grade == "B" else 1):
            card.references = refs
            cards[key] = card
    return sorted(cards.values(), key=lambda row: (row.headword.casefold(), row.pos, row.grade, row.sense_id, row.identifier))


def source_line(reference, *, links):
    name = reference["title"]
    additions = [reference.get(key) for key in ("version", "source_record_id")]
    if own := OPEN_LICENSE.get(reference["source_id"]):
        license_url, contributors = own
        license_name = "CC BY-SA 4.0" if reference["source_id"] == "kaikki" else "CC BY 4.0"
        additions += [contributors, f"[{license_name}]({license_url})" if links else f"{license_name} {license_url}"]
    details = " · ".join(str(item) for item in additions if item)
    url = reference.get("url") or ""
    if url and urlsplit(url).scheme in ("http", "https"):
        if links:
            return f"{markdown(name)} · {details} [원문]({url})" if details else f"[{markdown(name)}]({url})"
        return f"{name} · {details} · {url}" if details else f"{name} · {url}"
    return f"{markdown(name) if links else name} · {details}" if details else name


def stable_prompts(cards):
    siblings = defaultdict(list)
    for card in cards:
        siblings[card.headword.casefold(), card.pos].append(card)
    for group in siblings.values():
        for index, card in enumerate(group, 1):
            prompt = f"{card.headword} ({card.pos})" if card.pos else card.headword
            if len(group) > 1:
                prompt += f" · 의미 {index}"
            yield card, prompt


def anki_tags(card):
    korean_tag = "verified" if card.korean else (
        "awaiting_review" if card.korean_status == "verified" else card.korean_status
    )
    sense_key = card.sense_id or card.identifier
    tags = {"toeicnet", f"toeicnet::rag::{card.grade}", f"toeicnet::ko::{korean_tag}",
            f"toeicnet::sense::{sense_key}"}
    for source, day in card.occurrences.values():
        role = "core" if source in CORE_SOURCES else "back"
        tags.add(f"toeicnet::{role}")
        if day is not None:
            tags.add(f"toeicnet::day::{day:02d}")
    return " ".join(sorted(tags))


def write_anki(anki_path, grade, cards):
    path = anki_path / f"grade_{grade.lower()}.tsv"
    with atomic_text(path, newline="") as stream:
        stream.write(
            "#separator:Tab\n#html:false\n#notetype:Basic\n"
            f"#deck:Toeicnet::Batch RAG::Grade {grade}\n"
            "#tags column:3\n#columns:Front\tBack\tTags\n"
        )
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for card, prompt in cards:
            answer_parts = [card.definition, f"등급 {grade} · {GRADE_LABEL[grade]}"]
            if card.korean:
                answer_parts.insert(0, card.korean)
            else:
                answer_parts.append("검증된 한국어 뜻 없음")
            answer_parts.append(ORIGIN_LABEL.get(card.definition_origin, card.definition_origin))
            answer_parts.extend(dict.fromkeys(source_line(item, links=False) for item in card.references))
            if card.korean_reference:
                answer_parts.append("한국어 뜻 근거 · " + source_line(card.korean_reference, links=False))
            writer.writerow((path_label(prompt), " | ".join(map(path_label, answer_parts)), anki_tags(card)))
    return path


def write_grade_notes(path, grade, cards, notes_path):
    lines = [f"# {grade}등급 · {GRADE_LABEL[grade]}", "", f"학습 의미 {len(cards):,}개", ""]
    for card, prompt in cards:
        lines += [f"## {markdown(prompt)}", "", f"- 영어 정의 · {markdown(card.definition)}"]
        if card.korean:
            lines.append(f"- 검증된 한국어 뜻 · {markdown(card.korean)}")
        else:
            status = card.korean_status if card.korean_status != "verified" else "unverified"
            lines.append(f"- {KOREAN_LABELS.get(status, KOREAN_LABELS['unverified'])} · 영어 정의 제공")
        if card.definition_origin:
            origin = ORIGIN_LABEL.get(card.definition_origin, card.definition_origin)
            lines.append(f"- 정의 출처 유형 · {markdown(origin)}")
        lines.extend(f"- {ref}" for ref in dict.fromkeys(source_line(item, links=True) for item in card.references))
        if card.korean_reference:
            lines.append(f"- 한국어 뜻 근거 · {source_line(card.korean_reference, links=True)}")
        filename = core_filename(card.word_id, card.headword)
        if any(source in CORE_SOURCES for source, _ in card.occurrences.values()) and (
            notes_path / CORE / filename
        ).exists():
            lines.append(f"- [핵심 표제어 노트](../{CORE}/{filename})")
        lines.append("")
    write_markdown(path, lines)


def write_module_index(path, assessments):
    counts = defaultdict(Counter)
    for assessment in assessments:
        for module, result in assessment.get("modules", {}).items():
            counts[module][result["classification"]] += 1
    lines = [
        "# 언어학 모듈 근거 현황", "",
        "분류별 원천 출현 수입니다. 확인된 관계는 기존 PART 1~3의 학습 노트에 있습니다.", "",
        "| 모듈 | 근거 분류 | 원천 출현 |",
        "| --- | --- | ---: |",
    ]
    for module, label in MODULE_LABEL.items():
        for status, count in sorted(counts[module].items()):
            lines.append(f"| {label} | `{status}` | {count:,} |")
    write_markdown(path, lines)


def export_batch_study(db_path, assessments, notes_path, anki_path, *, regenerate_original=True):
    """Read assessment records and export disposable local study artifacts."""
    assessments = list(assessments)
    if regenerate_original:
        generate_notes(StudyData(db_path, include_open_evidence=True), notes_path)
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        cards = collect_cards(db, assessments)
    by_grade = defaultdict(list)
    for card, prompt in stable_prompts(cards):
        by_grade[card.grade].append((card, prompt))
    occurrence_counts = Counter(item["english"]["grade"] for item in assessments)
    card_counts = {grade: len(by_grade[grade]) for grade in ("A", "B", "C")}
    supplemental = notes_path / SUPPLEMENT
    index = [
        "# Batch RAG 검증 등급별 학습 노트", "",
        "| 등급 | 확인 기준 | 처리한 원천 출현 | 학습 의미 |",
        "| --- | --- | ---: | ---: |",
    ]
    anki_index = [
        "# Anki 가져오기", "",
        "UTF-8 탭 구분 파일을 Anki로 가져오면 앞면·뒷면을 Basic 카드 필드에 연결하고 태그와 덱을 적용합니다.",
        "태그에서 검증 등급과 원천 DAY를 확인할 수 있습니다.", "",
    ]
    for grade, label in GRADE_LABEL.items():
        name = f"grade_{grade.lower()}.md"
        link = f"[{grade}]({name})" if grade in card_counts else grade
        index.append(f"| {link} | {label} | {occurrence_counts[grade]:,} | {card_counts.get(grade, 0):,} |")
        if grade in card_counts:
            write_grade_notes(supplemental / name, grade, by_grade[grade], notes_path)
            tsv = write_anki(anki_path, grade, by_grade[grade])
            anki_index.append(f"- {grade}등급 · {card_counts[grade]:,}장 [{tsv.name}]({tsv.name})")
    index += [
        "", "한국어 뜻은 독립 검증된 경우에 표시합니다. C등급 정의는 단일 출처임을 확인하고 학습할 수 있습니다.",
        "D·E등급은 검토 대기 자료에 포함됩니다. A등급 학습 의미에는 DB에 연결된 기존 검증 의미를 포함합니다.",
        "", "[네 가지 언어학 모듈의 근거 현황](modules.md)",
    ]
    write_markdown(supplemental / "README.md", index)
    write_module_index(supplemental / "modules.md", assessments)
    master = notes_path / "README.md"
    if master.exists():
        original = master.read_text(encoding="utf-8")
        if INDEX_LINK not in original:
            with atomic_text(master) as stream:
                stream.write(original.rstrip() + "\n\n" + INDEX_LINK + "\n")
    anki_index += [
        "", "확인된 한국어 뜻을 카드에 넣고, 그 외 카드에는 영어 정의와 근거를 표시합니다.",
        "공개 어휘 자료는 각 카드의 출처와 판본에 표시합니다. 원천 교재와 대조하여 만든 출력은 로컬 학습 자료입니다.",
        "", "[Anki 텍스트 가져오기 도움말](https://docs.ankiweb.net/importing/text-files.html)",
    ]
    write_markdown(anki_path / "README.md", anki_index)
    return {"occurrences_by_grade": {grade: occurrence_counts[grade] for grade in GRADE_LABEL},
            "cards_by_grade": card_counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--assessments", type=Path, required=True)
    parser.add_argument("--notes", type=Path, default=Path("notes"))
    parser.add_argument("--anki-output", type=Path, default=Path("exports/anki"))
    args = parser.parse_args()
    with args.assessments.open(encoding="utf-8") as stream:
        result = export_batch_study(args.db, (json.loads(line) for line in stream if line.strip()), args.notes, args.anki_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
