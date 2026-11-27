"""OCR the back-word PDFs into rows of (English entry, POS label, Korean gloss) with page coordinates.

Pages are rendered at 300 dpi with PDFium and read by Tesseract (kor+eng, PSM 6) as word boxes.
Words are grouped into printed lines; a line splits at the first POS label (phr, n, v, adj, adv,
prep, conj) into the English entry on the left and the Korean gloss on the right. Raw word boxes
are kept so every row can be traced back to the page image.
"""

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

POS_LABEL = re.compile(r"^(phr|n|v|adj|adv|prep|conj|pron|int)$")
FILES = {
    "해커스토익 뒷단어 데이 1-10(2).pdf": 1,
    "해커스 뒷단어 데이 11–15(1).pdf": 11,
    "해커스 뒷단어 16-30(1).pdf": 16,
}


def render(pdf, index, dpi):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(str(pdf))[index].render(scale=dpi / 72, grayscale=True).to_pil()


def tsv(image, lang, psm, extra=()):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    out = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--psm", str(psm), *extra, "tsv"],
                         input=buffer.getvalue(), capture_output=True, check=True).stdout.decode("utf-8")
    words = [r for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE)
             if r["level"] == "5" and r["text"].strip()]
    grouped = {}
    for w in words:
        grouped.setdefault((w["block_num"], w["par_num"], w["line_num"]), []).append(w)
    lines = []
    for ws in grouped.values():
        ws.sort(key=lambda w: int(w["left"]))
        top = min(int(w["top"]) for w in ws)
        bottom = max(int(w["top"]) + int(w["height"]) for w in ws)
        lines.append({"y": (top + bottom) / 2, "text": " ".join(w["text"] for w in ws),
                      "conf": sum(float(w["conf"]) for w in ws) / len(ws)})
    return sorted(lines, key=lambda l: l["y"])


def find_badge(a, y0, y1, x_lo, x_hi):
    """First mid-grey filled box right of the English entry on one printed line."""
    import numpy as np
    band = a[y0:y1, x_lo:x_hi]
    if band.size == 0:
        return None
    xs = np.where(band.mean(axis=0) > 0.45)[0]
    if not len(xs):
        return None
    runs, start, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - prev > 8:
            runs.append((start, prev + 1))
            start = x
        prev = x
    runs.append((start, prev + 1))
    for a0, a1 in runs:
        if a1 - a0 >= 15:
            return int(x_lo + a0), int(x_lo + a1)
    return None


def read_badge(gray, box, y0, y1):
    """Badges in these scans are grey boxes with dark letters; read them as a single word."""
    from PIL import ImageOps
    crop = gray.crop((box[0] + 2, y0 - 4, box[1] - 2, y1 + 4)).point(lambda v: 0 if v < 110 else 255)
    crop = ImageOps.expand(crop.resize((crop.width * 3, crop.height * 3)), border=30, fill=255)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    text = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "8", "-c",
                           "tessedit_char_whitelist=phrnvadjeoctis"], input=buffer.getvalue(),
                          capture_output=True).stdout.decode().strip().lower()
    fixes = {"phe": "phr", "pr": "phr", "ph": "phr", "phy": "phr", "pht": "phr", "ad": "adj", "adi": "adj", "aj": "adj",
             "av": "adv", "ady": "adv", "rn": "n", "nn": "n", "vv": "v", "prey": "prep", "conj": "conj"}
    label = fixes.get(text, text)
    if not POS_LABEL.match(label or ""):
        label = None
    return label, text, box[1] - box[0]


def page_rows(task):
    pdf, index, dpi, first_day = task
    import numpy as np
    gray = render(pdf, index, dpi)
    W, H = gray.size
    bw = gray.point(lambda v: 255 if v > 150 else 0)
    g = np.asarray(gray)
    a = (g > 120) & (g < 215)  # mid-grey badge fill
    top, bottom = int(H * 0.08), int(H * 0.95)
    left = int(W * 0.10)
    eng = tsv(bw.crop((left, top, int(W * 0.53), bottom)), "eng", 4)
    header = " ".join(l["text"] for l in tsv(bw.crop((0, 0, W, int(H * 0.16))), "kor+eng", 6))
    rows = []
    for n, line in enumerate(eng):
        text = line["text"]
        margin = ""
        m = re.match(r"^\s*(LC|RC|Lc|Re|Part\s*\d[\s,]*\d?)\s+(.*)$", text)
        if m:
            margin, text = m.group(1), m.group(2)
        text = re.sub(r"^(?:[□口ㅁ0OoQqDdCcaGUu_\-—.,'`|\[\]()©@¢‘’“”]+\s+)", "", text)
        text = re.sub(r"\s+(?:phr?|phi|phe|ad[jiv]?|n|v|[_\-—~.»«|=]+)$", "", text).strip(" _—-.|~=")
        if not re.search(r"[A-Za-z]{2,}", text) or re.search(r"hackers|토익|daily|quiz", text, re.I):
            continue
        y = int(line["y"] + top)
        y0, y1 = y - 18, y + 18
        box = find_badge(a, y0, y1, int(W * 0.40), int(W * 0.72))
        label, raw, width = read_badge(gray, box, y0, y1) if box else (None, None, None)
        rows.append({"english": text, "pos_label": label, "badge_raw": raw, "badge_width": width,
                     "margin_label": margin, "y": y, "eng_conf": round(line["conf"], 1),
                     "file": pdf.name, "pdf_page": index + 1, "line": n})
    # Fallback for partly read badges: the badge width separates one-letter labels (n, v) from
    # three-letter ones (phr, adj, adv) within a page; recorded apart from the OCR label.
    widths = sorted(r["badge_width"] for r in rows if r["badge_width"])
    wide = (widths[-1] * 0.7) if widths else None
    for r in rows:
        r["pos_fallback"] = None
        if r["pos_label"] or not r["badge_width"] or wide is None:
            continue
        raw = r["badge_raw"] or ""
        if r["badge_width"] >= wide:
            if "j" in raw or "di" in raw:
                r["pos_fallback"] = "adj"
            elif "v" in raw:
                r["pos_fallback"] = "adv"
            elif "r" in raw or " " in r["english"]:
                r["pos_fallback"] = "phr"
        elif raw in ("v", "y"):
            r["pos_fallback"] = "v"
        elif raw in ("n", "h", "u", "a"):
            r["pos_fallback"] = "n"
    return {"file": pdf.name, "pdf_page": index + 1, "header": header, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("sources/hackers"))
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/pdf_ocr/pages.jsonl"))
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--pages", help="file:page list for a sample, e.g. 0:1,0:2")
    args = parser.parse_args()
    import pypdfium2 as pdfium
    tasks = []
    for name, first_day in FILES.items():
        pdf = args.source_dir / name
        for i in range(len(pdfium.PdfDocument(str(pdf)))):
            tasks.append((pdf, i, args.dpi, first_day))
    if args.pages:
        wanted = {tuple(map(int, p.split(":"))) for p in args.pages.split(",")}
        names = list(FILES)
        tasks = [t for t in tasks if (names.index(t[0].name), t[1] + 1) in wanted]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.jobs) as pool, args.output.open("w", encoding="utf-8") as out:
        for result in pool.map(page_rows, tasks):
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(result["file"][-12:], result["pdf_page"], len(result["rows"]), file=sys.stderr)


if __name__ == "__main__":
    main()
