"""Second OCR reading of the English column with other settings, used only to find Anki items
the first reading missed (threshold 170; PSM 6 and PSM 11). Lines keep their page and y."""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pdf_ocr_rows import FILES, render, tsv  # noqa: E402


def read(task):
    pdf, index = task
    gray = render(pdf, index, 300)
    W, H = gray.size
    bw = gray.point(lambda v: 255 if v > 170 else 0)
    crop = bw.crop((int(W * 0.05), int(H * 0.01), int(W * 0.62), int(H * 0.95)))
    lines = []
    for psm in (6, 11):
        for l in tsv(crop, "eng", psm):
            lines.append({"psm": psm, "text": l["text"], "y": round(l["y"] + H * 0.01)})
    return {"file": pdf.name, "pdf_page": index + 1, "lines": lines}


def main():
    import pypdfium2 as pdfium
    tasks = [(Path("sources/hackers") / name, i) for name in FILES
             for i in range(len(pdfium.PdfDocument(str(Path("sources/hackers") / name))))]
    with ProcessPoolExecutor(4) as pool, open("data/rebuild/pdf_ocr/variant_lines.jsonl", "w", encoding="utf-8") as out:
        for r in pool.map(read, tasks):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
