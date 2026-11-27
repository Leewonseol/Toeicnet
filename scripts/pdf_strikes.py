"""Find hand-drawn pen strokes across printed lines (struck-through entries) on the PDF pages.

A stroke is a near-black run (grey < 70) at least 15% of the page width long in one pixel row,
inside the word-list area; consecutive rows form one stroke band. Printed rules and badges are
grey, so they do not qualify. Bands are cropped for visual reading.
"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from pdf_ocr_rows import FILES, render  # noqa: E402


def longest_run(row):
    best = cur = 0
    for v in row:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def bands(task):
    pdf, index = task
    g = np.asarray(render(pdf, index, 100))
    H, W = g.shape
    dark = g < 70
    rows = []
    for y in range(int(H * 0.08), int(H * 0.95)):
        # allow small gaps inside a pen stroke by closing 3-pixel holes
        r = dark[y, int(W * 0.08):int(W * 0.92)].copy()
        for shift in (1, 2, 3):
            r[:-shift] |= dark[y, int(W * 0.08) + shift:int(W * 0.92)]
        if longest_run(r) > W * 0.15:
            rows.append(y)
    found, start = [], None
    for y in rows:
        if start is None or y - prev > 3:
            if start is not None:
                found.append((start, prev))
            start = y
        prev = y
    if start is not None:
        found.append((start, prev))
    return {"file": pdf.name, "pdf_page": index + 1, "day": FILES[pdf.name] + index // 4,
            "bands_100dpi": [[int(a), int(b)] for a, b in found]}


def main():
    import pypdfium2 as pdfium
    tasks = [(Path("sources/hackers") / n, i) for n in FILES for i in range(len(pdfium.PdfDocument(str(Path("sources/hackers") / n))))]
    with ProcessPoolExecutor(4) as pool, open("data/rebuild/pdf_ocr/strikes.jsonl", "w", encoding="utf-8") as out:
        for r in pool.map(bands, tasks):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
