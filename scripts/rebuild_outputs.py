"""Turn the rule-v3 analysis into study cards, PART 1-3 notes, a review queue and aggregates.

Cards and notes contain textbook Korean glosses, so they are written under data/ and notes/
(both git-ignored). The aggregate JSON holds counts and accuracy only.
"""

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

LICENSE = {
    "wn": "Open English WordNet 2025 (CC BY 4.0)",
    "kk": "English Wiktionary via Wiktextract 2026-10-01 (CC BY-SA 4.0)",
}
GRADE_LABEL = {"B": "공개 사전 2종 교차 검증", "C": "단일 출처 확인"}
REVIEWED = "model_reviewed_pair"


def definition(row):
    """Grade B: WordNet definition of the aligned sense; grade C: the single source's gloss."""
    first = row["english"][0]
    if row["english_grade"] == "B" and first["wn_definition"]:
        return first["wn_definition"], LICENSE["wn"] + " · " + LICENSE["kk"]
    if first.get("kk_gloss"):
        return first["kk_gloss"], LICENSE["kk"]
    return first.get("wn_definition"), LICENSE["wn"]


def card(row):
    text, attribution = definition(row)
    if not text:
        return None
    pos = "/".join(row["pos"])
    korean = " / ".join(row["korean"])
    lines = []
    if row["korean_status"] == "verified":
        lines.append(f"<b>{html.escape(korean)}</b> <small>(한국어 뜻 검증)</small>")
        lines.append(html.escape(text))
    else:
        # The English definition comes first when the Korean gloss is not independently verified.
        lines.append(f"<b>{html.escape(text)}</b>")
        lines.append(f"<small>교재 뜻(미검증): {html.escape(korean)}</small>")
    ety, morph, sem, use = row["etymology"], row["morphology"], row["semantics"], row["usage"]
    if morph and morph["type"] != "multiword":
        lines.append("형태: " + html.escape(" + ".join(morph["segments"])))
    if ety:
        bits = [ety["family"]]
        if ety.get("etymon"):
            bits.append(f"{ety['language']} {ety['etymon']}")
        if ety.get("root"):
            bits.append("어근 " + ety["root"])
        lines.append("어원: " + html.escape(" · ".join(bits)))
    if row["english_grade"] == "B":
        if sem["synonyms"]:
            lines.append("동의어(같은 의미): " + html.escape(", ".join(sem["synonyms"][:5])))
        if sem["antonyms"]:
            lines.append("반의어: " + html.escape(", ".join(sem["antonyms"])))
    if use["collocations"]:
        lines.append("OANC 결합: " + html.escape(", ".join(c["expression"] for c in use["collocations"][:3])))
    how = " · 의미 짝 모델 검토(사람 미검수)" if row["method"] == REVIEWED else ""
    lines.append(f"<small>등급 {row['english_grade']} · {GRADE_LABEL[row['english_grade']]}{how} · {html.escape(attribution)}</small>")
    tags = ["toeicnet_v2", f"grade_{row['english_grade']}", row["deck"], f"day{row['day']:02d}",
            "ko_verified" if row["korean_status"] == "verified" else "ko_unverified"]
    front = f"{html.escape(row['headword'])} <small>{pos}</small>"
    return front, "<br>".join(lines), " ".join(tags)


def write_tsv(path, deck, cards):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"#separator:tab\n#html:true\n#deck:{deck}\n#tags column:3\n")
        for front, back, tags in cards:
            handle.write(f"{front}\t{back}\t{tags}\n")


def notes(rows, directory):
    directory.mkdir(parents=True, exist_ok=True)
    verified = [r for r in rows if r["english_grade"] in ("B", "C")]
    core = sorted((r for r in verified if r["core"]), key=lambda r: (r["day"], r["headword"].casefold()))
    part1 = ["# PART 1. CORE WORDS (검증 항목)", "",
             f"본 단어 1,241건 중 영어 정의가 B·C등급으로 확인된 {len(core)}건. 한국어 뜻이 검증되지 않은 항목은 영어 정의를 먼저 적었다.", ""]
    day = None
    for r in core:
        if r["day"] != day:
            day = r["day"]
            part1 += ["", f"## DAY {day:02d}", ""]
        text, _ = definition(r)
        ko = " / ".join(r["korean"])
        head = f"- **{r['headword']}** ({'/'.join(r['pos'])}, {r['english_grade']})"
        body = f"{ko} — {text}" if r["korean_status"] == "verified" else f"{text} [교재 뜻 미검증: {ko}]"
        extra = []
        if r["morphology"] and r["morphology"]["type"] != "multiword":
            extra.append("형태 " + " + ".join(r["morphology"]["segments"]))
        if r["etymology"]:
            extra.append("어원 " + r["etymology"]["family"] + (f" {r['etymology']['etymon']}" if r["etymology"].get("etymon") else ""))
        if r["english_grade"] == "B" and r["semantics"]["antonyms"]:
            extra.append("반의어 " + ", ".join(r["semantics"]["antonyms"]))
        part1.append(head + ": " + body + (" · " + " · ".join(extra) if extra else ""))
    (directory / "PART1_core_words.md").write_text("\n".join(part1) + "\n", encoding="utf-8")

    # PART 2: etymological families by attested PIE root, then by derivational affix.
    by_root, by_affix = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["etymology"] and r["etymology"].get("root"):
            by_root[r["etymology"]["root"]].append(r)
        morph = r["morphology"]
        if morph and morph["type"] == "derivation":
            for seg in morph["segments"]:
                if seg.startswith("-") or seg.endswith("-"):
                    by_affix[seg].append(r)
    part2 = ["# PART 2. ETYMOLOGY (어원·접사 집단)", "",
             "어근은 Wiktionary 어원 템플릿의 인도유럽 조어 어근이 기록된 경우만, 접사는 현대 영어의 생산적 접사로 분석된 경우만 묶었다. "
             "본 단어와 뒷단어를 같은 집단에서 함께 복습한다. 영어 정의 등급은 괄호에 표시했다.", "", "## 어근 집단 (2개 이상)", ""]
    for root, group in sorted(by_root.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(group) < 2:
            continue
        words = ", ".join(f"{g['headword']}{'*' if g['core'] else ''}({g['english_grade']})" for g in sorted(group, key=lambda g: g["headword"]))
        part2.append(f"- **{root}** {len(group)}개: {words}")
    part2 += ["", "## 접두사·접미사 집단", "", "`*`는 본 단어.", ""]
    for affix, group in sorted(by_affix.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        words = ", ".join(f"{g['headword']}{'*' if g['core'] else ''}" for g in sorted(group, key=lambda g: g["headword"]))
        part2.append(f"- **{affix}** {len(group)}개: {words}")
    (directory / "PART2_etymology.md").write_text("\n".join(part2) + "\n", encoding="utf-8")

    # PART 3: semantic fields from the WordNet lexicographer file of the aligned sense (grade B).
    by_field = defaultdict(list)
    for r in rows:
        if r["english_grade"] == "B":
            for field in r["semantics"]["fields"]:
                by_field[field].append(r)
    part3 = ["# PART 3. SYNONYM / THEME (의미장)", "",
             "B등급에서 정렬된 WordNet 의미의 의미장(lexicographer file)으로 묶었다. 동의어는 같은 Synset의 구성원이며 교재 의미와 같은 개별 의미에서만 가져왔다.", ""]
    for field, group in sorted(by_field.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        part3 += ["", f"## {field} ({len(group)})", ""]
        for g in sorted(group, key=lambda g: g["headword"]):
            syn = ", ".join(g["semantics"]["synonyms"][:4])
            ant = ", ".join(g["semantics"]["antonyms"])
            part3.append(f"- {g['headword']}{'*' if g['core'] else ''}" + (f" — 동의어: {syn}" if syn else "") + (f" · 반의어: {ant}" if ant else ""))
    (directory / "PART3_semantic_fields.md").write_text("\n".join(part3) + "\n", encoding="utf-8")
    return by_root, by_affix, by_field


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=Path("data/rebuild/full_v3.jsonl"))
    parser.add_argument("--cards", type=Path, default=Path("data/rebuild/cards"))
    parser.add_argument("--notes", type=Path, default=Path("notes/rebuild_v2"))
    parser.add_argument("--summary", type=Path, default=Path("reports/rebuild_v2_summary.json"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.analysis.open(encoding="utf-8")]
    decks = defaultdict(list)
    for row in rows:
        if row["english_grade"] in ("B", "C"):
            made = card(row)
            if made:
                tier = row["english_grade"] + ("_reviewed" if row["method"] == REVIEWED else "")
                decks[("core" if row["core"] else "back", tier)].append(made)
    for (scope, grade), cards in decks.items():
        write_tsv(args.cards / f"{scope}_grade_{grade}.tsv", f"Toeicnet v2::{scope}::Grade {grade}", cards)
    queue = [{"item_id": r["item_id"], "headword": r["headword"], "grade": r["english_grade"], "reason": r["method"],
              "proposed_pairs": r["proposed_pairs"]} for r in rows if r["english_grade"] in ("D", "E")]
    with (args.cards.parent / "review_queue.jsonl").open("w", encoding="utf-8") as handle:
        for row in queue:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    by_root, by_affix, by_field = notes(rows, args.notes)
    families = Counter(r["etymology"]["family"] for r in rows if r["etymology"])
    summary = {
        "items": len(rows), "core_items": sum(r["core"] for r in rows),
        "english_grades": dict(Counter(r["english_grade"] for r in rows)),
        "english_grades_core": dict(Counter(r["english_grade"] for r in rows if r["core"])),
        "grade_B_by_method": dict(Counter(r["method"] for r in rows if r["english_grade"] == "B")),
        "korean_verified": sum(r["korean_status"] == "verified" for r in rows),
        "korean_verified_core": sum(r["korean_status"] == "verified" for r in rows if r["core"]),
        "cards": {f"{s}_{g}": len(c) for (s, g), c in sorted(decks.items())},
        "review_queue": len(queue),
        "morphology_analyzed": sum(1 for r in rows if r["morphology"] and r["morphology"]["type"] != "multiword"),
        "morphology_types": dict(Counter(r["morphology"]["type"] for r in rows if r["morphology"])),
        "etymology_analyzed": sum(1 for r in rows if r["etymology"]),
        "etymology_families": dict(families.most_common()),
        "roots_with_2plus_items": sum(1 for g in by_root.values() if len(g) >= 2),
        "items_in_root_groups": sum(len(g) for g in by_root.values() if len(g) >= 2),
        "affix_groups": {a: len(g) for a, g in sorted(by_affix.items(), key=lambda kv: -len(kv[1]))},
        "semantic_fields_grade_B": {f: len(g) for f, g in sorted(by_field.items(), key=lambda kv: -len(kv[1]))},
        "items_with_oanc_collocations": sum(1 for r in rows if r["usage"]["collocations"]),
        "items_with_oanc_frequency": sum(1 for r in rows if r["usage"]["oanc_frequency"]),
        "textbook_relations": sum(len(r["textbook_relations"]) for r in rows),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, dict) or k in ("cards", "english_grades", "etymology_families", "morphology_types")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
