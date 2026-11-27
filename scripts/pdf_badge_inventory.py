"""Count printed entries per page by their POS badges and list badges with no matched Anki item.

Every printed entry carries one grey POS badge. A badge whose line has no matched Anki item is a
PDF entry that still needs reading (a PDF-only entry, a struck-through entry, or an OCR miss).
"""

import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from pdf_ocr_rows import FILES, find_badge, render  # noqa: E402


def badges(task):
    pdf, index = task
    g = np.asarray(render(pdf, index, 300))
    H, W = g.shape
    a = (g > 120) & (g < 215)
    hits = []
    for y in range(int(H * 0.04), int(H * 0.95), 6):
        box = find_badge(a, y - 15, y + 15, int(W * 0.40), int(W * 0.72))
        if box and box[1] - box[0] <= W * 0.04:
            hits.append((y, box))
    centers, group = [], []
    for y, box in hits:
        if group and y - group[-1][0] > 12:
            centers.append(group)
            group = []
        group.append((y, box))
    if group:
        centers.append(group)
    out = []
    for grp in centers:
        if len(grp) >= 3:  # a badge is ~35-45 px tall: several 6 px steps
            ys = [y for y, _ in grp]
            out.append({"y": int(np.mean(ys)), "x": [int(np.median([b[0] for _, b in grp])), int(np.median([b[1] for _, b in grp]))]})
    return {"file": pdf.name, "pdf_page": index + 1, "badges": out}


def main():
    import pypdfium2 as pdfium
    tasks = [(Path("sources/hackers") / n, i) for n in FILES for i in range(len(pdfium.PdfDocument(str(Path("sources/hackers") / n))))]
    with ProcessPoolExecutor(4) as pool:
        pages = list(pool.map(badges, tasks))
    matches = [json.loads(l) for l in open("data/rebuild/pdf_ocr/anki_pdf_matches.jsonl", encoding="utf-8")]
    ys = defaultdict(list)
    for m in matches:
        if m["pdf_match"] and m["pdf_match"].get("y") is not None:
            ys[(m["pdf_match"]["file"], m["pdf_match"]["pdf_page"])].append(m["pdf_match"]["y"])
    total, open_badges = 0, []
    for p in pages:
        total += len(p["badges"])
        for b in p["badges"]:
            if not any(abs(b["y"] - y) < 30 for y in ys[(p["file"], p["pdf_page"])]):
                open_badges.append({"file": p["file"], "pdf_page": p["pdf_page"], "day": FILES[p["file"]] + (p["pdf_page"] - 1) // 4, **b})
    Path("data/rebuild/pdf_ocr/badge_inventory.json").write_text(json.dumps({"pages": pages, "open_badges": open_badges}, ensure_ascii=False))
    print("badges", total, "pages", len(pages), "badges without matched item", len(open_badges))


if __name__ == "__main__":
    main()
