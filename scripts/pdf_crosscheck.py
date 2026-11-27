"""Cross-check OCR rows of the back-word PDFs against the Anki back-word decks.

Each page's DAY is taken from the majority DAY of its exactly matching Anki items; the
remaining rows are matched within that DAY by compact spelling similarity. Unmatched rows on
either side are written out for image review instead of being guessed.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

FIRST_DAY = {"해커스토익 뒷단어 데이 1-10(2).pdf": 1, "해커스 뒷단어 데이 11–15(1).pdf": 11, "해커스 뒷단어 16-30(1).pdf": 16}
LABEL = re.compile(r"^(phr|phe|ahr|pr|phi|adj|adv|ad|n|v)$", re.I)


def clean(text):
    """Cut the English entry at a POS badge read into the same line, and drop the rest."""
    tokens = text.split()
    for k, t in enumerate(tokens):
        if k and LABEL.match(t.strip("|[](){}.,:;")):
            tokens = tokens[:k]
            break
    return " ".join(tokens)


def compact(text):
    text = re.sub(r"\([^)]*\)", "", text or "")
    return re.sub(r"[^a-z]", "", text.casefold())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, default=Path("data/rebuild/pdf_ocr/pages.jsonl"))
    parser.add_argument("--items", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/rebuild/pdf_ocr"))
    parser.add_argument("--cutoff", type=float, default=0.8)
    args = parser.parse_args()
    pages = [json.loads(l) for l in args.pages.open(encoding="utf-8")]
    items = [json.loads(l) for l in args.items.open(encoding="utf-8")]
    back = [i for i in items if not i["core"] and not i["duplicate_of"]]
    by_key = defaultdict(list)
    for i in back:
        by_key[compact(i["headword"])].append(i)
    by_day = defaultdict(list)
    for i in back:
        by_day[i["day"]].append(i)

    matched, page_day = {}, {}
    rows_all = []
    for p in pages:
        # Each file holds its DAYs in order, four pages per DAY; on every page where the matched
        # items allow a check the majority DAY agreed with this position.
        page_day[(p["file"], p["pdf_page"])] = FIRST_DAY[p["file"]] + (p["pdf_page"] - 1) // 4
        for r in p["rows"]:
            r["english_raw"], r["english"] = r["english"], clean(r["english"])
            r["page_day"] = page_day[(p["file"], p["pdf_page"])]
            rows_all.append(r)
    # Pass 1: exact compact spelling in the page's DAY.
    for r in rows_all:
        cands = [i for i in by_key.get(compact(r["english"]), []) if i["day"] == r["page_day"] and i["item_id"] not in matched]
        if cands:
            matched[cands[0]["item_id"]] = (r, "exact", 1.0)
            r["match"] = cands[0]["item_id"]
    # Pass 1b: the OCR line starts with the item (trailing badge or gloss fragments read along).
    for r in rows_all:
        if r.get("match"):
            continue
        c = compact(r["english"])
        cands = sorted((i for i in by_day[r["page_day"]] if i["item_id"] not in matched and len(compact(i["headword"])) >= 4
                        and c.startswith(compact(i["headword"]))), key=lambda i: -len(compact(i["headword"])))
        if cands:
            matched[cands[0]["item_id"]] = (r, "prefix", 1.0)
            r["match"] = cands[0]["item_id"]
    # Pass 2: similar spelling within the DAY, best unclaimed item above the cutoff.
    for r in rows_all:
        if r.get("match") or r["page_day"] is None or len(compact(r["english"])) < 3:
            continue
        best = None
        for i in by_day[r["page_day"]]:
            if i["item_id"] in matched:
                continue
            score = SequenceMatcher(None, compact(r["english"]), compact(i["headword"])).ratio()
            if score >= args.cutoff and (best is None or score > best[0]):
                best = (score, i)
        if best:
            matched[best[1]["item_id"]] = (r, "similar", round(best[0], 3))
            r["match"] = best[1]["item_id"]

    # Pass 3: the item (5+ letters) occurs inside the OCR line, after leading checkbox noise.
    for r in rows_all:
        if r.get("match"):
            continue
        c = compact(r["english"])
        cands = sorted((i for i in by_day[r["page_day"]] if i["item_id"] not in matched and len(compact(i["headword"])) >= 5
                        and compact(i["headword"]) in c), key=lambda i: -len(compact(i["headword"])))
        if cands:
            matched[cands[0]["item_id"]] = (r, "contains", 1.0)
            r["match"] = cands[0]["item_id"]
    # Pass 4: drop leading 1-3 character noise tokens, then a looser similarity within the DAY.
    for r in rows_all:
        if r.get("match"):
            continue
        tokens = r["english"].split()
        while len(tokens) > 1 and len(re.sub(r"[^A-Za-z]", "", tokens[0])) <= 3 and not re.fullmatch(r"(a|an|be|by|in|on|at|to|up|of|go|do|it)", tokens[0], re.I):
            tokens = tokens[1:]
        c = compact(" ".join(tokens))
        if len(c) < 3:
            continue
        best = None
        for i in by_day[r["page_day"]]:
            if i["item_id"] in matched:
                continue
            score = SequenceMatcher(None, c, compact(i["headword"])).ratio()
            if score >= 0.7 and (best is None or score > best[0]):
                best = (score, i)
        if best:
            matched[best[1]["item_id"]] = (r, "similar_loose", round(best[0], 3))
            r["match"] = best[1]["item_id"]

    # Pass 5: Anki items still unmatched, searched in the second OCR reading of the same DAY.
    variant_path = args.pages.parent / "variant_lines.jsonl"
    if variant_path.exists():
        variants = defaultdict(list)
        for line in variant_path.open(encoding="utf-8"):
            v = json.loads(line)
            day = FIRST_DAY[v["file"]] + (v["pdf_page"] - 1) // 4
            for l in v["lines"]:
                tokens = clean(l["text"]).split()
                while len(tokens) > 1 and len(re.sub(r"[^A-Za-z]", "", tokens[0])) <= 2:
                    tokens = tokens[1:]
                variants[day].append((compact(" ".join(tokens)), v["file"], v["pdf_page"], l["y"], l["text"]))
        for i in back:
            if i["item_id"] in matched:
                continue
            key = compact(i["headword"])
            best = None
            for c, f, pg, y, text in variants[i["day"]]:
                if not c:
                    continue
                score = 1.0 if (len(key) >= 5 and key in c) else SequenceMatcher(None, c, key).ratio()
                if score >= 0.8 and (best is None or score > best[0]):
                    best = (score, {"file": f, "pdf_page": pg, "line": None, "english": text, "pos_label": None,
                                    "pos_fallback": None, "y": y})
            if best:
                matched[i["item_id"]] = (best[1], "variant_ocr", round(best[0], 3))

    out = args.output_dir
    with (out / "anki_pdf_matches.jsonl").open("w", encoding="utf-8") as h:
        for i in back:
            m = matched.get(i["item_id"])
            h.write(json.dumps({
                "item_id": i["item_id"], "headword": i["headword"], "deck": i["deck"], "day": i["day"],
                "pdf_match": None if not m else {"file": m[0]["file"], "pdf_page": m[0]["pdf_page"], "line": m[0]["line"], "y": m[0].get("y"),
                                                 "ocr_english": m[0]["english"], "method": m[1], "score": m[2],
                                                 "pos_label": m[0]["pos_label"], "pos_fallback": m[0].get("pos_fallback")},
            }, ensure_ascii=False) + "\n")
    unmatched_rows = [r for r in rows_all if not r.get("match")]
    with (out / "pdf_rows_unmatched.jsonl").open("w", encoding="utf-8") as h:
        for r in unmatched_rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "pdf_pages": len(pages), "ocr_rows": len(rows_all), "anki_back_items": len(back),
        "matched_exact": sum(1 for m in matched.values() if m[1] == "exact"),
        "matched_by_method": dict(Counter(m[1] for m in matched.values())),
        "anki_items_without_pdf_row": len(back) - len(matched),
        "ocr_rows_without_anki_item": len(unmatched_rows),
        "pages_without_day": [k for k, v in page_day.items() if v is None],
        "pages_per_day": dict(sorted(Counter(v for v in page_day.values() if v).items())),
        "pos_from_pdf": dict(Counter((m[0]["pos_label"] or m[0].get("pos_fallback") or "none") for m in matched.values())),
    }
    (out / "crosscheck_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
