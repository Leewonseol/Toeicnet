"""Re-read pages whose first OCR found few rows (small or faint scans) at 500 dpi with an Otsu
threshold and a wide English-column crop; lines are appended to variant_lines.jsonl."""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from pdf_ocr_rows import render, tsv  # noqa: E402


def otsu(values):
    hist = np.bincount(values.ravel(), minlength=256).astype(float)
    total, best, threshold = hist.sum(), 0, 128
    sum_all, sum_b, w_b = (np.arange(256) * hist).sum(), 0.0, 0.0
    for t in range(256):
        w_b += hist[t]
        if not w_b or w_b == total:
            continue
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / (total - w_b)
        between = w_b * (total - w_b) * (m_b - m_f) ** 2
        if between > best:
            best, threshold = between, t
    return threshold


def read(task):
    pdf, index = task
    gray = render(pdf, index, 500)
    W, H = gray.size
    t = otsu(np.asarray(gray))
    bw = gray.point(lambda v: 255 if v > t else 0)
    lines = []
    for x0, x1 in ((0.05, 0.62), (0.15, 0.75)):
        crop = bw.crop((int(W * x0), int(H * 0.05), int(W * x1), int(H * 0.97)))
        for psm in (4, 6):
            for l in tsv(crop, "eng", psm):
                lines.append({"psm": psm, "text": l["text"], "y": round(l["y"] + H * 0.05), "crop": [x0, x1]})
    return {"file": pdf.name, "pdf_page": index + 1, "lines": lines, "threshold": t}


def main():
    pages = [json.loads(l) for l in open("data/rebuild/pdf_ocr/pages.jsonl", encoding="utf-8")]
    tasks = [(Path("sources/hackers") / p["file"], p["pdf_page"] - 1) for p in pages if len(p["rows"]) < 28]
    with ProcessPoolExecutor(4) as pool, open("data/rebuild/pdf_ocr/variant_lines.jsonl", "a", encoding="utf-8") as out:
        for r in pool.map(read, tasks):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(r["file"][-12:], r["pdf_page"], len(r["lines"]), r["threshold"])


if __name__ == "__main__":
    main()
