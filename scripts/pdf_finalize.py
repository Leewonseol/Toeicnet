"""Combine the OCR cross-check with the page-image checks into one PDF status per Anki item.

Statuses: ocr_<method> (found by OCR), image_confirmed (seen on the page image where OCR failed),
struck_through (printed, crossed out by a hand-drawn pen line), not_found_in_pdf (looked for on
all four DAY pages and absent). PDF-only entries were read from the page images and are listed
with the page, the textbook gloss and the POS badge exactly as printed.
"""

import json
from collections import Counter
from pathlib import Path

D = Path("data/rebuild/pdf_ocr")
F1, F2, F3 = "해커스토익 뒷단어 데이 1-10(2).pdf", "해커스 뒷단어 데이 11–15(1).pdf", "해커스 뒷단어 16-30(1).pdf"

DAY11_P3 = ["except for", "exploration", "imaginable", "innovate", "interpretation", "licensed", "mechanical",
            "prediction", "prototype", "quantity", "remnant", "screen", "suspend", "technical", "unfavorable",
            "vulnerable to", "be carried out", "breakthrough", "by the time", "copyright", "custom-built", "customize",
            "disruption", "energy source", "expand into", "smoke detector"]
IMAGE = {(11, w): (F2, 3) for w in DAY11_P3}
IMAGE.update({(3, "as if"): (F1, 9), (13, "a loaf of"): (F2, 10), (13, "affair"): (F2, 10), (13, "aisle"): (F2, 10),
              (19, "coil"): (F3, 16), (26, "cluster"): (F3, 44), (6, "exhibit"): (F1, 23), (9, "so far"): (F1, 35),
              (28, "staircase"): (F3, 51)})
STRUCK = {(1, "necessity"): (F1, 3), (1, "relevant"): (F1, 3), (1, "versatile"): (F1, 4), (1, "preliminary"): (F1, 4)}
ABSENT = {(8, "diversify"), (8, "defiance")}
PDF_ONLY = [
    {"day": 8, "deck": "900", "file": F1, "pdf_page": 32, "headword": "nuisance", "pos_label": "n", "korean_textbook": "성가신 존재, 골칫거리"},
    {"day": 8, "deck": "900", "file": F1, "pdf_page": 32, "headword": "coincide with", "pos_label": "phr", "korean_textbook": "~와 동시에 일어나다, 일치하다"},
    {"day": 11, "deck": "800", "file": F2, "pdf_page": 2, "headword": "a series of", "pos_label": "phr", "korean_textbook": "일련의"},
    {"day": 11, "deck": "800", "file": F2, "pdf_page": 2, "headword": "check the manual", "pos_label": "phr", "korean_textbook": "사용 설명서를 참조하다"},
    {"day": 11, "deck": "800", "file": F2, "pdf_page": 2, "headword": "come up with", "pos_label": "phr", "korean_textbook": "생각해 내다, 떠올리다"},
    {"day": 11, "deck": "800", "file": F2, "pdf_page": 2, "headword": "enter a contest", "pos_label": "phr", "korean_textbook": "대회에 참가하다"},
    {"day": 11, "deck": "800", "file": F2, "pdf_page": 2, "headword": "give a demonstration of", "pos_label": "phr", "korean_textbook": "~을 보여주다, ~을 실연해 보이다"},
    {"day": 20, "deck": "800", "file": F3, "pdf_page": 19, "headword": "barely", "pos_label": "adv", "korean_textbook": "가까스로, 거의 ~하지 않는"},
    {"day": 26, "deck": "800", "file": F3, "pdf_page": 42, "headword": "alternate", "pos_label": "adj", "korean_textbook": "대신인, 교대의, 상호 간의"},
]


def main():
    rows = [json.loads(l) for l in (D / "anki_pdf_matches.jsonl").open(encoding="utf-8")]
    out = []
    for r in rows:
        key = (r["day"], r["headword"])
        m = r["pdf_match"]
        if m:
            status = f"ocr_{m['method']}"
            page = (m["file"], m["pdf_page"])
            pos, pos_method = (m["pos_label"], "badge_ocr") if m["pos_label"] else ((m["pos_fallback"], "badge_width_fallback") if m["pos_fallback"] else (None, None))
        elif key in STRUCK:
            status, page, pos, pos_method = "struck_through", STRUCK[key], None, None
        elif key in IMAGE:
            status, page, pos, pos_method = "image_confirmed", IMAGE[key], None, None
        elif key in ABSENT:
            status, page, pos, pos_method = "not_found_in_pdf", None, None, None
        else:
            raise SystemExit(f"unresolved item {key}")
        out.append({"item_id": r["item_id"], "headword": r["headword"], "deck": r["deck"], "day": r["day"],
                    "pdf_status": status, "pdf_file": page[0] if page else None, "pdf_page": page[1] if page else None,
                    "pdf_pos": pos, "pdf_pos_method": pos_method})
    with (D / "pdf_status.jsonl").open("w", encoding="utf-8") as h:
        for r in out:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (D / "pdf_only_items.jsonl").open("w", encoding="utf-8") as h:
        for r in PDF_ONLY:
            h.write(json.dumps({**r, "item_id": f"pdf_only:{r['day']:02d}:{r['headword']}", "read_by": "page image, model reading"}, ensure_ascii=False) + "\n")
    summary = {"anki_back_items": len(out), "status": dict(Counter(r["pdf_status"] for r in out)),
               "pdf_only_items": len(PDF_ONLY), "pdf_pos": dict(Counter(r["pdf_pos_method"] or "none" for r in out))}
    (D / "pdf_final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
