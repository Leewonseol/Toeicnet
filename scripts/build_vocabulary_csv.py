"""Build the single learner CSV vocabulary/vocabulary.csv from the existing rebuild-v2 analysis.

No new analysis is done. Every related word or expression is written as `word — meaning`:
textbook words carry their textbook gloss; other words carry the English definition of the
aligned WordNet sense (same synset) or Wiktionary's gloss of the source word. A relation with
no available meaning is left out of the learner file and recorded in the internal coverage file.
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rebuild_evidence import Lexicon, normalize  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/rebuild"
HEADER = ["DAY", "구분", "표제어", "품사", "뜻", "파생어", "합성어", "접두사", "접미사", "어근", "공통 어원", "동의어", "유의어", "사용 용법"]
DECK = {"core": "본 단어", "basic": "기초", "800": "800점", "900": "900점"}
DECK_ORDER = {"core": 0, "basic": 1, "800": 2, "900": 3}
POS_KO = {"noun": "명사", "verb": "동사", "adjective": "형용사", "adverb": "부사", "phrase": "구", "preposition": "전치사",
          "conjunction": "접속사", "interjection": "감탄사", "pronoun": "대명사", "n": "명사", "v": "동사", "adj": "형용사",
          "adv": "부사", "phr": "구", "prep": "전치사", "conj": "접속사", "int": "감탄사"}
# Curated learner glosses for the productive English affixes the morphology rules accept
# (meaning or function only; written for this project, see reports/vocabulary_csv_report.md).
AFFIX = {
    "re-": "다시", "pre-": "미리, 앞서", "un-": "부정, 반대", "in-": "부정(않은)", "im-": "부정(않은)", "il-": "부정(않은)",
    "ir-": "부정(않은)", "dis-": "부정, 반대, 분리", "mis-": "잘못", "over-": "지나치게, 위로", "under-": "부족하게, 아래로",
    "inter-": "서로, 사이에", "down-": "아래로, 줄여서", "up-": "위로", "out-": "밖으로, ~보다 더", "co-": "함께",
    "non-": "아닌, 비(非)-", "sub-": "아래, 하위", "super-": "위, 초과", "trans-": "가로질러, 옮겨", "anti-": "반대, 대항",
    "self-": "스스로, 자기", "multi-": "여러", "-ment": "행위·결과를 나타내는 명사 형성", "-ion": "행위·상태를 나타내는 명사 형성",
    "-tion": "행위·상태를 나타내는 명사 형성", "-ation": "행위·결과를 나타내는 명사 형성", "-er": "행위자·도구를 나타내는 명사 형성",
    "-or": "행위자를 나타내는 명사 형성", "-ly": "부사 형성(~하게)", "-ness": "성질·상태를 나타내는 명사 형성",
    "-ity": "성질·상태를 나타내는 명사 형성", "-able": "~할 수 있는", "-ible": "~할 수 있는", "-al": "~의, ~에 관한(형용사) / 행위(명사)",
    "-ic": "~의, ~적인", "-ive": "~하는 성질의", "-ful": "~이 가득한", "-less": "~이 없는", "-ize": "~화하다(동사 형성)",
    "-ise": "~화하다(동사 형성)", "-ify": "~하게 하다(동사 형성)", "-ing": "동작·과정 / ~하는", "-ed": "~된, ~한(과거분사형 형용사)",
    "-en": "~하게 하다(동사 형성)", "-ent": "~하는(형용사) / ~하는 사람", "-ant": "~하는(형용사) / ~하는 사람",
    "-ance": "행위·상태를 나타내는 명사 형성", "-ence": "행위·상태를 나타내는 명사 형성", "-ship": "신분·관계·자격",
    "-hood": "상태·시기·집단", "-free": "~이 없는", "-wise": "~의 방식으로, ~에 관해", "-ward": "~쪽으로", "-y": "~의 성질이 있는",
    "-ous": "~이 많은, ~의 성질의", "-ary": "~에 관한 / ~하는 곳·사람", "-ery": "장소·행위·집합", "-ist": "~하는 사람, 전문가",
    "-ee": "~을 받는 사람", "-age": "행위·결과·요금·집합", "-ure": "행위·결과", "-ism": "주의, 행위", "-ish": "~스러운, 약간 ~한",
    "-like": "~ 같은",
}
TAG_NOTE = {"transitive": "타동사", "intransitive": "자동사", "countable": "가산명사", "uncountable": "불가산명사",
            "plural": "복수형으로 씀", "usually plural": "보통 복수형", "plural-only": "복수형으로만 씀", "formal": "격식체",
            "informal": "비격식체", "colloquial": "구어체", "slang": "속어", "ditransitive": "목적어 두 개를 취함",
            "not-comparable": "비교급 없음", "attributive": "명사 앞에서만 씀", "predicative": "서술적으로만 씀",
            "US": "미국식", "UK": "영국식", "British": "영국식", "business": "비즈니스 용어", "law": "법률 용어",
            "finance": "금융 용어", "with-to": "to와 함께 씀", "with-of": "of와 함께 씀"}
CAP = 6
REC_POS = {"adj": "adjective", "adv": "adverb", "prep": "preposition", "conj": "conjunction", "intj": "interjection"}


def ko_short(groups):
    """One-line textbook gloss for a related word (all sense groups, '; ' separated)."""
    return "; ".join(g for g in groups if g)


def clean_etymon(form):
    return re.sub(r"#.*$", "", form or "").strip()


def main():
    lex = Lexicon()
    rows = [json.loads(l) for l in (DATA / "full_v31r.jsonl").open(encoding="utf-8")]
    pdf = {r["item_id"]: r for r in map(json.loads, (DATA / "pdf_ocr/pdf_status.jsonl").open(encoding="utf-8"))}
    pdf_only = [json.loads(l) for l in (DATA / "pdf_ocr/pdf_only_items.jsonl").open(encoding="utf-8")]

    # Textbook gloss of every textbook word, for related-word meanings.
    gloss = {}
    for r in rows:
        gloss.setdefault(normalize(r["headword"]), ko_short(r["korean"]))
    for x in pdf_only:
        gloss.setdefault(normalize(x["headword"]), x["korean_textbook"])

    def textbook(word):
        g = gloss.get(normalize(word))
        return f"{word} — {g}" if g else None

    # Group items by headword: one learner row per headword.
    groups = defaultdict(list)
    for r in rows:
        groups[normalize(r["headword"])].append(r)
    order = []
    for key, items in groups.items():
        first = min(items, key=lambda r: (r["day"], DECK_ORDER[r["deck"]], r["item_id"]))
        order.append((first["day"], DECK_ORDER[first["deck"]], first["item_id"], key))

    # A morphology record from a homograph with another part of speech (apply ← apple + -y) is
    # dropped when the word has a Wiktionary entry in the item's own part of speech.

    def morphology_of(r):
        m = r["morphology"]
        if not m or m["type"] == "multiword" or r["english_grade"] in ("B", "C"):
            return m
        rec_pos = REC_POS.get(m["source"].split(":")[2], m["source"].split(":")[2])
        item_pos = set(r["pos"])
        p = pdf.get(r["item_id"], {}).get("pdf_pos")
        if p:
            item_pos.add(REC_POS.get(p, {"n": "noun", "v": "verb", "phr": "phrase"}.get(p, p)))
        if rec_pos in item_pos:
            return m
        own = {REC_POS.get(rec["record_id"].split(":")[2], rec["record_id"].split(":")[2])
               for rec in lex.kaikki.get(normalize(r["headword"]), [])}
        return None if own & item_pos else m

    for r in rows:
        r["morphology"] = morphology_of(r)
    # Derivational families (modern English) from morphology segments.
    base_of, family = {}, defaultdict(set)
    compounds = defaultdict(set)
    for r in rows:
        m = r["morphology"]
        if not m or m["type"] == "multiword":
            continue
        free = [s for s in m["segments"] if not (s.startswith("-") or s.endswith("-"))]
        if m["type"] == "derivation" and free:
            base_of[normalize(r["headword"])] = normalize(free[0])
            family[normalize(free[0])].add(normalize(r["headword"]))
        if m["type"] == "compound":
            for part in free:
                compounds[normalize(part)].add(normalize(r["headword"]))
    # Historical common origin: shared PIE root recorded by Wiktionary (kept apart from derivation).
    # Grouped by recorded root *and* source family, so a broad root does not join, e.g., a Latin
    # borrowing with a Germanic word; the family is used only for grouping, never shown.
    by_root = defaultdict(set)
    for r in rows:
        if r["etymology"] and r["etymology"].get("root"):
            by_root[(r["etymology"]["root"], r["etymology"]["family"])].add(normalize(r["headword"]))
    # Textbook multiword expressions that contain a single-word headword.
    usage_expr = defaultdict(list)
    for key in groups:
        if " " in key:
            for w in set(key.split()):
                usage_expr[w].append(key)

    out, coverage = [], []
    for _, _, _, key in sorted(order):
        items = sorted(groups[key], key=lambda r: (r["day"], DECK_ORDER[r["deck"]]))
        main = items[0]
        word = main["headword"]
        cov = {"표제어": word}

        days = sorted({r["day"] for r in items})
        decks = []
        for r in items:
            if DECK[r["deck"]] not in decks:
                decks.append(DECK[r["deck"]])
        # POS: the PDF's printed badge; else the POS of the aligned dictionary sense (grade B/C);
        # else the POS inferred from the Korean gloss, replaced by Wiktionary's only POS for the
        # word when the inferred one does not exist for it (주로 → adverb, not noun).
        pos = []
        wk = {REC_POS.get(rec["record_id"].split(":")[2], rec["record_id"].split(":")[2])
              for rec in lex.kaikki.get(key, [])} - {"name", "proper", "phrase"}
        for r in items:
            p = pdf.get(r["item_id"], {}).get("pdf_pos")
            if p:
                labels = [POS_KO.get(p, p)]
            elif r["english_grade"] in ("B", "C") and r["english"]:
                labels = [POS_KO.get(r["english"][0]["pos"], r["english"][0]["pos"])]
            elif " " not in key and len(wk) == 1 and not set(r["pos"]) & wk:
                labels = [POS_KO.get(next(iter(wk)), next(iter(wk)))]
            else:
                labels = [POS_KO.get(x, x) for x in r["pos"]]
            for l in labels:
                if l and l not in pos:
                    pos.append(l)

        meaning = []
        for r in items:
            lines = [g for g in r["korean"] if g]
            prefix = f"[{DECK[r['deck']]} DAY {r['day']:02d}] " if len(items) > 1 else ""
            meaning.append(prefix + " / ".join(lines))
        best = next((r for r in items if r["english_grade"] in ("B", "C") and r["english"]), None)
        if best and best["korean_status"] != "verified":
            e = best["english"][0]
            definition = e["wn_definition"] if best["english_grade"] == "B" and e["wn_definition"] else (e["kk_gloss"] or e["wn_definition"])
            if definition:
                meaning.append(f"영어 정의: {definition}")

        # Derivatives: textbook words in the same modern derivational family.
        fam = set(family.get(key, set())) | ({base_of[key]} if key in base_of else set())
        if key in base_of:
            fam |= family.get(base_of[key], set())
        fam.discard(key)
        deriv = [t for t in (textbook(groups[w][0]["headword"]) for w in sorted(fam) if w in groups) if t][:CAP]
        cov["파생어"] = "present" if deriv else ("no_textbook_meaning" if fam else "none_found")

        comp_words = set(compounds.get(key, set()))
        m = main["morphology"]
        if m and m["type"] == "compound":
            comp_words |= {normalize(s) for s in m["segments"]}
        comp_words.discard(key)
        comp = [t for t in (textbook(groups[w][0]["headword"]) for w in sorted(comp_words) if w in groups) if t][:CAP]
        cov["합성어"] = "present" if comp else ("no_textbook_meaning" if comp_words else "none_found")

        prefixes, suffixes = [], []
        if m and m["type"] in ("derivation", "combining_forms"):
            for s in m["segments"]:
                if s.endswith("-") and s in AFFIX:
                    prefixes.append(f"{s} : {AFFIX[s]}")
                elif s.startswith("-") and s in AFFIX:
                    suffixes.append(f"{s} : {AFFIX[s]}")
            if prefixes or suffixes:
                bases = [s for s in m["segments"] if not (s.startswith("-") or s.endswith("-"))]
                if bases:
                    line = f"({' + '.join(m['segments'])})"
                    (suffixes if suffixes else prefixes).append(line)
        cov["접두사"] = "present" if prefixes else "none_found"
        cov["접미사"] = "present" if suffixes else "none_found"

        # Source word and its meaning as recorded by Wiktionary (no language or path shown).
        root = ""
        e = main["etymology"]
        if e and e["family"] != "English formation" and e.get("etymon"):
            for ent in lex.etymology(word):
                if ent["record_id"] != e["source"]:
                    continue
                for name, a in ent["templates"]:
                    if str(a.get("2")) == e["language"] and str(a.get("3")) == e["etymon"]:
                        g = a.get("5") or a.get("t") or a.get("gloss")
                        if g:
                            first = re.split(r"[;]", g)[0].strip()
                            root = f"{clean_etymon(e['etymon'])} — {first}"
                        break
                break
        cov["어근"] = "present" if root else ("no_gloss" if e and e.get("etymon") else "none_found")

        common = []
        if e and e.get("root"):
            others = sorted(by_root[(e["root"], e["family"])] - {key} - fam)
            common = [t for t in (textbook(groups[w][0]["headword"]) for w in others) if t][:CAP]
        cov["공통 어원"] = "present" if common else "none_found"

        # Synonyms: same WordNet synset as the aligned sense (B), plus the textbook's own (=) notes.
        syn, near = [], []
        for x in main.get("textbook_relations") or []:
            if x["relation"] == "synonym":
                syn.append(textbook(x["target"]) or f"{x['target']} — 교재 표기 동의어")
        b = next((r for r in items if r["english_grade"] == "B"), None)
        if b:
            sense = next((s for s in lex.wn_senses(word) if s["sense_id"] == b["english"][0]["wn_sense"]), None)
            if sense:
                # Same synset = same sense: show that sense's definition, not the word's textbook
                # gloss, which may describe another sense (comply ~ follow ≠ 따라가다).
                for s in sense["synonyms"]:
                    syn.append(f"{s} — {sense['definition']}")
                # Near-synonyms: WordNet 'similar' links of the aligned sense that are textbook words.
                for kind, target in sense["relations"]:
                    if kind == "similar" and normalize(target) in groups:
                        near.append(textbook(target))
        # Wiktionary synonyms of the aligned sense that are textbook words (near-synonyms).
        kkid = next((e2["kk_sense"] for r in items for e2 in r["english"] if e2["kk_sense"]), None)
        kk_sense = None
        if kkid:
            lemma = main.get("kk_lemma") or word
            kk_sense = next((s for s in lex.kk_senses(lemma) if s.get("id") == kkid), None)
            if kk_sense:
                for s in kk_sense.get("synonyms", []):
                    if s and normalize(s) in groups and normalize(s) != key:
                        t = textbook(s)
                        if t and t not in syn:
                            near.append(t)
        syn = list(dict.fromkeys(syn))[:CAP]
        syn_words = {line.split(" — ")[0] for line in syn}
        near = [n for n in dict.fromkeys(near) if n.split(" — ")[0] not in syn_words][:CAP]
        cov["동의어"] = "present" if syn else ("not_aligned" if not b else "none_found")
        cov["유의어"] = "present" if near else "none_found"

        usage = [t for t in (textbook(groups[w][0]["headword"]) for w in sorted(usage_expr.get(key, []))) if t][:CAP]
        if kk_sense:
            notes = [TAG_NOTE[t] for t in kk_sense.get("tags", []) if t in TAG_NOTE]
            if notes:
                usage.append("문법: " + ", ".join(dict.fromkeys(notes)))
        cov["사용 용법"] = "present" if usage else "none_found"

        out.append([", ".join(f"{d:02d}" for d in days), ", ".join(decks), word, ", ".join(pos), "\n".join(meaning),
                    "\n".join(deriv), "\n".join(comp), "\n".join(prefixes), "\n".join(suffixes), root,
                    "\n".join(common), "\n".join(syn), "\n".join(near), "\n".join(usage)])
        coverage.append(cov)

    for x in pdf_only:
        out.append([f"{x['day']:02d}", DECK[x["deck"]], x["headword"], POS_KO.get(x["pos_label"], x["pos_label"]),
                    x["korean_textbook"], "", "", "", "", "", "", "", "", ""])
        coverage.append({"표제어": x["headword"], **{h: "not_analyzed_pdf_only" for h in HEADER[5:]}})
    out.sort(key=lambda r: (int(r[0].split(",")[0]), min(DECK_ORDER[k] for k, v in DECK.items() if v in r[1].split(", "))))

    path = ROOT / "vocabulary/vocabulary.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.writer(h, quoting=csv.QUOTE_MINIMAL)
        w.writerow(HEADER)
        w.writerows(out)
    internal = ROOT / "vocabulary/internal/vocabulary_coverage.csv"
    internal.parent.mkdir(parents=True, exist_ok=True)
    with internal.open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["표제어"] + HEADER[5:])
        w.writeheader()
        w.writerows(coverage)
    problems = []
    for r in out:
        for i, h in enumerate(HEADER):
            if h in ("파생어", "합성어", "공통 어원", "동의어", "유의어", "사용 용법", "어근"):
                for line in filter(None, r[i].split("\n")):
                    if not line.startswith("문법: ") and not re.match(r"^.+ — \S.*$", line):
                        problems.append((r[2], h, line))
            if h in ("접두사", "접미사"):
                for line in filter(None, r[i].split("\n")):
                    if not (re.match(r"^\S+ : \S.*$", line) or line.startswith("(")):
                        problems.append((r[2], h, line))
            if re.search(r"[\[{]['\"]|kaikki:|oewn-|anki_", r[i]):
                problems.append((r[2], h, "internal identifier or object"))
    if problems:
        raise SystemExit(f"{len(problems)} cells break the word — meaning format, e.g. {problems[:5]}")
    filled = {h: sum(1 for r in out if r[i]) for i, h in enumerate(HEADER)}
    print(json.dumps({"rows": len(out), "filled": filled}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
