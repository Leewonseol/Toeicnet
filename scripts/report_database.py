"""Measure the current database snapshot without treating missing inputs as zero-sized sources."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from validate_database import coverage, validate

METRICS = {
    "고유 어휘": "SELECT COUNT(*) FROM words",
    "개별 의미": "SELECT COUNT(*) FROM senses",
    "개별 의미 미등록 어휘": "SELECT COUNT(*) FROM words w WHERE NOT EXISTS(SELECT 1 FROM senses s WHERE s.word_id=w.word_id)",
    "형태소": "SELECT COUNT(*) FROM morphemes",
    "접두사 집단": """SELECT COUNT(*) FROM nodes WHERE node_type='PREFIX'
                        OR (node_type='ETYMOLOGICAL_AFFIX' AND json_extract(properties_json,'$.affix_type')='prefix')""",
    "접미사 집단": """SELECT COUNT(*) FROM nodes WHERE node_type='SUFFIX'
                        OR (node_type='ETYMOLOGICAL_AFFIX' AND json_extract(properties_json,'$.affix_type')='suffix')""",
    "어근 집단": "SELECT COUNT(*) FROM nodes WHERE node_type IN ('ROOT','ETYMOLOGICAL_ROOT')",
    "파생 관계": "SELECT COUNT(*) FROM derivations",
    "굴절 관계": "SELECT COUNT(*) FROM inflections",
    "동계어 관계": "SELECT COUNT(*) FROM cognates",
    "동의 관계": "SELECT COUNT(*) FROM synonyms",
    "유의 관계": "SELECT COUNT(*) FROM near_synonyms",
    "반의 관계": "SELECT COUNT(*) FROM antonyms",
    "콜로케이션": "SELECT COUNT(*) FROM collocations",
    "문법적 연어": "SELECT COUNT(*) FROM colligations",
    "숙어": "SELECT COUNT(*) FROM idioms",
    "구동사": "SELECT COUNT(*) FROM phrasal_verbs",
    "문형": "SELECT COUNT(*) FROM verb_patterns",
    "의미장": "SELECT COUNT(*) FROM semantic_fields",
    "테마": "SELECT COUNT(*) FROM themes",
    "한국어 번역 불확실": "SELECT COUNT(*) FROM korean_translations WHERE status='uncertain'",
    "한국어 문맥 의존·부분 대응·정확한 대응어 미확인": """SELECT COUNT(*) FROM korean_translations
        WHERE status IN ('context_dependent','partial_equivalent','no_exact_equivalent')""",
    "영어 우선 출력": "SELECT COUNT(*) FROM senses WHERE preferred_display_language='en'",
    "영어 정의 미검증": "SELECT COUNT(*) FROM english_definitions WHERE status='unverified'",
    "외부 후보": "SELECT COUNT(*) FROM external_candidates",
}


def ratio(numerator, denominator):
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.2f}%)" if denominator else "산출 불가 (분모 0)"


def report(db, expected_pages):
    measured = coverage(db)
    counts = {label: db.execute(sql).fetchone()[0] for label, sql in METRICS.items()}
    errors = validate(db)
    yield "# SQLite 측정 결과"
    yield ""
    yield "| 원천 | 등록 출현 | 확인 DAY |"
    yield "| --- | ---: | ---: |"
    if measured["core_occurrences"]:
        yield f"| Quizlet 본 단어 | {measured['core_occurrences']} | {measured['core_days']} |"
    if measured["anki_occurrences"]:
        yield f"| Anki 본 단어 | {measured['anki_occurrences']} | {measured['anki_days']} |"
    yield f"| 해커스 뒷단어 | {measured['back_occurrences']} | {measured['back_days']} |"
    yield ""
    yield f"뒷단어 출현이 등록된 PDF 페이지는 {measured['back_pages_with_entries']}/{expected_pages}입니다."
    reviewed = measured["back_pages_image_reviewed"]
    if reviewed is not None:
        yield f"원본 이미지 대조가 완료된 페이지는 {reviewed}/{expected_pages}입니다."
    expected_items = measured["expected_quizlet_occurrences"]
    if measured["core_occurrences"] and expected_items is not None:
        yield f"Quizlet 화면과 대조한 예상 항목 수는 {expected_items:,}개입니다."
    yield "이 표의 수치는 SQLite 등록 건수입니다."
    yield ""
    yield "| 지표 | 수 |"
    yield "| --- | ---: |"
    for label, count in counts.items():
        yield f"| {label} | {count} |"
    yield ""
    for text, table, status in (
        ("영어 정의 교차 검증", "english_definitions", "cross_verified"),
        ("한국어 번역 검증", "korean_translations", "verified"),
    ):
        count = db.execute(f"SELECT COUNT(*) FROM {table} WHERE status=?", (status,)).fetchone()[0]
        yield f"- {text} {ratio(count, counts['개별 의미'])}"
    aligned = db.execute("SELECT COUNT(DISTINCT occurrence_id) FROM sense_occurrences").fetchone()[0]
    occurrence_count = sum(measured[f"{kind}_occurrences"] for kind in ("core", "anki", "back"))
    yield f"- 검토된 의미가 명시적으로 연결된 원천 출현 {ratio(aligned, occurrence_count)}"
    yield "- SQLite 검증 통과" if not errors else f"- SQLite 검증 실패 {errors}"
    yield ""
    yield "## 검증 상태별 분포"
    yield ""
    rows = db.execute("""
        SELECT object_type,status,COUNT(*) FROM verification_results
        GROUP BY object_type,status ORDER BY object_type,status
    """).fetchall()
    if rows:
        yield "| 유형 | 검증 상태 | 건수 |"
        yield "| --- | --- | ---: |"
        for object_type, status, count in rows:
            yield f"| {object_type} | {status} | {count} |"
    else:
        yield "의미, 원천 출현 또는 관계 검증 기록이 없습니다."
    yield ""
    yield "## 의미장·테마 미분류 어휘"
    yield ""
    rows = db.execute("""
        SELECT w.headword, w.homonym_key,
               EXISTS(SELECT 1 FROM senses s WHERE s.word_id=w.word_id)
        FROM words w
        WHERE NOT EXISTS(
            SELECT 1 FROM nodes n JOIN edges e ON e.from_node_id=n.node_id
            WHERE n.word_id=w.word_id AND e.relation_type IN ('BELONGS_TO_SEMANTIC_FIELD','BELONGS_TO_THEME')
                AND e.status IN ('cross_verified','source_attested','corpus_attested')
        )
        ORDER BY w.normalized,w.homonym_key
    """).fetchall()
    if rows:
        for headword, homonym_key, has_sense in rows:
            reason = "검증된 의미장·테마 관계 미등록" if has_sense else "의미 정렬 미완료"
            yield f"- {headword} {homonym_key} · {reason}"
    else:
        yield "현재 미분류 어휘가 등록되어 있지 않습니다."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output", type=Path, default=Path("reports/database.generated.md"))
    parser.add_argument("--config", type=Path, default=Path("config/analysis.yaml"))
    args = parser.parse_args()
    expected_pages = json.loads(args.config.read_text(encoding="utf-8"))["scope"]["back_pdf_pages"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        args.output.write_text("\n".join(report(db, expected_pages)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
