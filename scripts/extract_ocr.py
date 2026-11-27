"""Rasterize the specified Hackers PDFs and prepare bilingual OCR review files."""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from threading import Lock

from intake_common import (
    ENTRY_FIELDS, HACKERS_PDF_ALIASES, HACKERS_PDFS, PAGE_FIELDS,
    sha256_file, write_csv, write_json,
)


DAY_RE = re.compile(r"\bD\s*A\s*Y\s*[-:.]?\s*(\d{1,2})\b", re.IGNORECASE)
HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
HEADWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9’'–/-]*(?: [A-Za-z0-9’'–/-]+)*")
POS_RE = re.compile(
    r"(?:\s+|\s*[(\[\{])(n|v|adj|adi|adv|phr|phir|phe|prep|conj|pron|det|interj|vt|vi)\.?[)\]}]?\s*$",
    re.I,
)
CATEGORY_RE = re.compile(r"^\s*(LC|RC|Part\s*[1-7](?:\s*[,·&]\s*[1-7])?)\b", re.I)
BULLETS_RE = re.compile(r"^(?:(?:[•·●*ㅁ□☐\s]+)|(?:\d{1,3}[.)]\s*)|(?:[0OoCD]\s+))+")
FOOTER_PAGE_RE = re.compile(r"^\s*(\d{1,4})\s*\|.*(?:무료|토\s*익|Hackers)", re.I)
OCR_CHECKBOX_RE = re.compile(r"^(?:[□☐ㅁ]|[0oacdq][0oai]?)\s+", re.I)
OCR_PHRASE_MARKERS = {"phr", "phir", "phe", "phi", "bhr", "pir", "ph", "hr"}
KOREAN_POS = {"명": "noun", "동": "verb", "형": "adjective", "부": "adverb", "전": "preposition"}
ENGLISH_POS = {
    "n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb",
    "prep": "preposition", "conj": "conjunction", "pron": "pronoun", "det": "determiner",
    "interj": "interjection", "vt": "verb", "vi": "verb", "adi": "adjective",
    "phr": "phrase", "phir": "phrase", "phe": "phrase",
}


def command(*args):
    env = dict(os.environ, LC_ALL="C.UTF-8", OMP_THREAD_LIMIT="1")
    return subprocess.run(args, check=True, text=True, capture_output=True, env=env)


def engine_signature(tessdata_dir):
    extra = ["--tessdata-dir", str(tessdata_dir)] if tessdata_dir else []
    language_output = command("tesseract", *extra, "--list-langs").stdout
    installed = set(language_output.splitlines())
    missing = {"kor", "eng"} - installed
    if missing:
        raise ValueError(f"missing Tesseract language model(s): {', '.join(sorted(missing))}")
    directory_match = re.search(r'"([^"]+)"', language_output.splitlines()[0])
    model_dir = tessdata_dir or (Path(directory_match[1]) if directory_match else None)
    models = {
        lang: sha256_file(model_dir / f"{lang}.traineddata") if model_dir else None
        for lang in ("kor", "eng")
    }
    return {
        "tesseract": command("tesseract", "--version").stdout.splitlines()[0],
        "poppler": command("pdftoppm", "-v").stderr.splitlines()[0],
        "language_models_sha256": models,
    }


def expected_files(root):
    known = {}
    standard_name = {
        alias: requested for requested in HACKERS_PDFS
        for alias in (requested, *HACKERS_PDF_ALIASES.get(requested, ()))
    }
    if root.is_dir():
        for path in root.iterdir():
            name = unicodedata.normalize("NFC", path.name)
            if path.is_file() and name in standard_name:
                requested = standard_name[name]
                if requested in known:
                    raise ValueError(f"multiple source files for {requested}: {known[requested].name}, {path.name}")
                known[requested] = path
    return known


def page_count(path):
    response = command("pdfinfo", str(path))
    result = re.search(r"^Pages:\s*(\d+)\s*$", response.stdout, re.M)
    if result is None:
        raise ValueError(f"pdfinfo did not report a page count for {path.name}")
    return int(result[1])


def read_ocr_lines(path):
    groups = defaultdict(list)
    height = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["level"] == "1":
                height = int(row["height"])
            if row["level"] == "5" and row["text"].strip():
                key = tuple(row[field] for field in ("block_num", "par_num", "line_num"))
                groups[key].append(row)
    for words in groups.values():
        left = min(int(word["left"]) for word in words)
        top = min(int(word["top"]) for word in words)
        right = max(int(word["left"]) + int(word["width"]) for word in words)
        bottom = max(int(word["top"]) + int(word["height"]) for word in words)
        confidence = sum(float(word["conf"]) for word in words) / len(words)
        yield (
            " ".join(word["text"].strip() for word in words),
            (left, top, right - left, bottom - top),
            round(confidence, 2), height,
        )


def pair_sparse_columns(lines):
    """Suggest row pairs when sparse OCR separates a check-box table into columns."""
    if not lines or not lines[0][3]:
        return []
    page_height = lines[0][3]
    band = page_height * 0.017
    visual = [line for line in lines if line[2] >= 55 and line[1][3] >= 11]
    anchors = []
    for text, (left, _, _, _), _, _ in visual:
        if OCR_CHECKBOX_RE.match(text):
            clean = OCR_CHECKBOX_RE.sub("", text).strip(" .—–·ㆍ'‘")
            if HEADWORD_RE.fullmatch(clean):
                anchors.append(left)
    if len(anchors) < 5:
        return []
    column = median(anchors)
    korean = []
    for text, bbox, confidence, _ in visual:
        if bbox[0] > column + page_height * 0.13 and (hit := HANGUL_RE.search(text)):
            korean.append((text, hit.start(), bbox, confidence))
    pairs = []
    for text, bbox, confidence, _ in visual:
        x, top, width, height = bbox
        if not column - band <= x <= column + band * 1.5:
            continue
        english = OCR_CHECKBOX_RE.sub("", text).strip(" .—–·ㆍ'‘")
        if not HEADWORD_RE.fullmatch(english) or len(english) < 2:
            continue
        center = top + height / 2
        aligned = [
            row for row in korean
            if row[2][0] > x + width and abs(row[2][1] + row[2][3] / 2 - center) < band * 0.42
        ]
        if not aligned:
            continue
        aligned.sort(key=lambda row: row[2][0])
        first_text, first_korean = aligned[0][:2]
        left_margin = first_text[:first_korean]
        markers = set(re.findall(r"[a-z]+", left_margin.casefold()))
        pos = " phr" if markers & OCR_PHRASE_MARKERS else ""
        prefix = "~" if "~" in left_margin else ""
        gloss = prefix + " ".join(row[0][row[1]:] for row in aligned)
        last_right = max(item[2][0] + item[2][2] for item in aligned)
        pair_confidence = min(confidence, *(item[3] for item in aligned))
        pairs.append((f"{english}{pos} {gloss}", (x, top, last_right - x, height), pair_confidence, page_height))
    return pairs


def candidate_entries(lines, filename, checksum, page):
    entries = []
    category = ""
    ordered_lines = sorted(lines, key=lambda line: (line[1][1], line[1][0]))
    for text, bbox, confidence, height in ordered_lines:
        if DAY_RE.search(text) or FOOTER_PAGE_RE.search(text) or (
            height and bbox[1] > height * 0.92
        ):
            continue
        label = CATEGORY_RE.match(text)
        if label:
            category = ("Part " + re.sub(r"\s+", "", label[1][4:]) if label[1].casefold().startswith("part")
                        else label[1].upper())
            text = text[label.end():].strip()
        text = BULLETS_RE.sub("", text)
        korean = HANGUL_RE.search(text)
        if korean is None:
            continue
        english = text[:korean.start()].strip()
        meaning = text[korean.start():].strip()
        part_of_speech = ""
        pos = POS_RE.search(english)
        if pos:
            part_of_speech = ENGLISH_POS[pos[1].casefold()]
            english = english[:pos.start()].strip()
        elif meaning and meaning[0] in KOREAN_POS:
            marker = re.match(r"^([명동형부전])(?:[.\])]|\s)\s*(.+)", meaning)
            if marker:
                part_of_speech = KOREAN_POS[marker[1]]
                meaning = marker[2]
        english = english.rstrip("([{:")
        if HEADWORD_RE.fullmatch(english) is None:
            continue
        entries.append({
            "filename": filename, "source_sha256": checksum, "pdf_page": page,
            "entry_index": len(entries) + 1, "headword": english,
            "original_korean_meaning": meaning, "part_of_speech": part_of_speech,
            "entry_type": "", "category": category, "homonym_key": "",
            "ocr_bbox": ",".join(map(str, bbox)), "ocr_confidence": confidence,
            "review_note": "",
        })
    return entries


ARTIFACT_NAMES = ("image.png", "ocr.txt", "ocr.tsv")
PDFIUM_LOCK = Lock()


def render_page(source, page, image, config):
    if config.get("renderer") == "pdfium":
        import pypdfium2 as pdfium

        # PDFium requires serialization of its API calls even across documents.
        with PDFIUM_LOCK, pdfium.PdfDocument(source) as document:
            with closing(document[page - 1]) as pdf_page:
                with closing(pdf_page.render(scale=config["dpi"] / 72, grayscale=True)) as bitmap:
                    rendered = bitmap.to_pil().copy()
        rendered.save(image.with_suffix(".png"), compress_level=1)
    else:
        command("pdftoppm", "-f", str(page), "-l", str(page), "-r", str(config["dpi"]),
                "-png", "-singlefile", str(source), str(image))


def completed_checkpoint(destination):
    checkpoint = destination / "done.json"
    if checkpoint.is_file():
        try:
            completed = json.loads(checkpoint.read_text(encoding="utf-8"))
            return all(
                (destination / name).is_file() and completed.get(name) == (destination / name).stat().st_size
                for name in ARTIFACT_NAMES
            )
        except (AttributeError, OSError, ValueError):
            return False
    return False


def ocr_page(source, page, cache, config, tessdata_dir, cached_only=False):
    destination = cache / f"page-{page:03}"
    if completed_checkpoint(destination):
        return destination
    if cached_only:
        return None
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination) as temp:
        temporary = Path(temp)
        image = temporary / "image"
        render_page(source, page, image, config)
        flags = ["--tessdata-dir", str(tessdata_dir)] if tessdata_dir else []
        command("tesseract", str(image.with_suffix(".png")), str(temporary / "ocr"),
                *flags, "-l", "kor+eng", "--psm", str(config["psm"]),
                "-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1")
        for name in ARTIFACT_NAMES:
            (temporary / name).replace(destination / name)
        write_json(destination / "done.json", {name: (destination / name).stat().st_size for name in ARTIFACT_NAMES})
    return destination


def page_candidate(artifact, filename, checksum, page, first_day, last_day, output_dir, psm=3):
    lines = list(read_ocr_lines(artifact / "ocr.tsv"))
    candidates = lines
    if psm in {11, 12}:
        pairs = pair_sparse_columns(lines)
        if pairs:
            english_column = median(pair[1][0] for pair in pairs)
            candidates = [
                line for line in lines
                if CATEGORY_RE.match(line[0]) or line[1][0] <= english_column + line[3] * 0.03
            ] + pairs
    entries = candidate_entries(candidates, filename, checksum, page)
    day_hits = {
        int(match[1]) for text, _, _, _ in lines for match in DAY_RE.finditer(text)
        if first_day <= int(match[1]) <= last_day
    }
    printed_hits = {
        int(text) for text, (_, top, _, _), _, height in lines
        if height and top > height * 0.90 and re.fullmatch(r"\d{1,4}", text) and int(text) > 0
    }
    printed_hits.update(
        int(match[1]) for text, (_, top, _, _), _, height in lines
        if height and top > height * 0.80 and (match := FOOTER_PAGE_RE.match(text)) and int(match[1]) > 0
    )
    return {
        "filename": filename, "source_sha256": checksum, "pdf_page": page,
        "day": next(iter(day_hits)) if len(day_hits) == 1 else "",
        "printed_page": next(iter(printed_hits)) if len(printed_hits) == 1 else "",
        "reviewed_entries": "", "review_status": "pending", "review_note": "",
        "image_path": str((artifact / "image.png").relative_to(output_dir)),
        "ocr_path": str((artifact / "ocr.txt").relative_to(output_dir)),
    }, entries


def process_sources(args):
    available = expected_files(args.source_dir)
    files = {}
    config = {"dpi": args.dpi, "psm": args.psm}
    errors = []
    ready = []
    for requested, (first_day, last_day, expected_pages) in HACKERS_PDFS.items():
        source = available.get(requested)
        filename = source.name if source else requested
        info = {
            "status": "unavailable", "sha256": None, "expected_pages": expected_pages,
            "pdf_pages": None, "ocr_pages": 0, "day_range": [first_day, last_day], "pages": [],
            "requested_filename": requested,
        }
        files[filename] = info
        if source is None:
            aliases = HACKERS_PDF_ALIASES.get(requested, ())
            alternatives = f" (or {', '.join(aliases)})" if aliases else ""
            errors.append(f"missing {args.source_dir / requested}{alternatives}")
            continue
        try:
            info["sha256"] = sha256_file(source)
            info["pdf_pages"] = page_count(source)
            if info["pdf_pages"] != expected_pages:
                raise ValueError(f"expected {expected_pages} PDF pages, found {info['pdf_pages']}")
            info["status"] = "pending"
            ready.append((filename, source, info))
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            info["status"] = "failed"
            errors.append(f"{filename}: {error}")
    if ready:
        try:
            config.update(engine_signature(args.tessdata_dir))
            if args.renderer == "pdfium":
                import pypdfium2 as pdfium

                config.update(renderer="pdfium", pypdfium2=version("pypdfium2"),
                              pdfium=pdfium.PDFIUM_INFO.version, pillow=version("Pillow"))
        except (ImportError, OSError, ValueError, subprocess.CalledProcessError) as error:
            errors.append(str(error))
            ready = []

    page_rows = []
    entry_rows = []
    for filename, source, info in ready:
        first_day, last_day = info["day_range"]
        cache_key = hashlib.sha256(json.dumps(
            {"checksum": info["sha256"], **config}, sort_keys=True
        ).encode()).hexdigest()
        cache = args.output_dir / "cache" / cache_key
        pages_to_process = info["pdf_pages"]
        if args.sample_pages is not None:
            pages_to_process = min(args.sample_pages, pages_to_process)
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            tasks = [
                (page, executor.submit(ocr_page, source, page, cache, config, args.tessdata_dir, args.cached_only))
                for page in range(1, pages_to_process + 1)
            ]
            for page, task in tasks:
                try:
                    artifact = task.result()
                    if artifact is None:
                        continue
                    page_row, entries = page_candidate(
                        artifact, filename, info["sha256"], page, first_day, last_day, args.output_dir,
                        args.psm,
                    )
                    page_rows.append(page_row)
                    entry_rows.extend(entries)
                    info["pages"].append(page)
                    info["ocr_pages"] += 1
                except (OSError, ValueError, subprocess.CalledProcessError) as error:
                    errors.append(f"{filename} PDF page {page}: {getattr(error, 'stderr', None) or error}")
        print(f"{filename}: {info['ocr_pages']}/{pages_to_process} OCR pages", flush=True)
        try:
            changed = sha256_file(source) != info["sha256"]
        except OSError:
            changed = True
        if changed:
            errors.append(f"{filename}: source changed during OCR")
            page_rows = [row for row in page_rows if row["filename"] != filename]
            entry_rows = [row for row in entry_rows if row["filename"] != filename]
            info["pages"] = []
            info["ocr_pages"] = 0
        if info["ocr_pages"] == info["expected_pages"]:
            info["status"] = "ocr_complete"
        else:
            info["status"] = "sampled" if args.cached_only or info["ocr_pages"] == pages_to_process else "failed"
    prefix = "snapshot." if args.cached_only else ""
    write_csv(args.output_dir / f"{prefix}candidates.pages.csv", PAGE_FIELDS, page_rows)
    write_csv(args.output_dir / f"{prefix}candidates.entries.csv", ENTRY_FIELDS, entry_rows)
    write_json(args.output_dir / f"{prefix}manifest.json", {
        "source_id": "hackers_back", "config": config, "files": files,
        "expected_pages": sum(info["expected_pages"] for info in files.values()),
        "ocr_pages": len(page_rows), "candidate_entries": len(entry_rows),
        "ready_for_full_image_review": not errors and all(info["status"] == "ocr_complete" for info in files.values()),
        "errors": errors,
    })
    for error in errors:
        print(f"OCR: {error}", file=sys.stderr)
    print(f"OCR completed for {len(page_rows)} pages; {len(entry_rows)} candidates await image review.")
    return bool(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("sources/hackers"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/intermediate/ocr"))
    parser.add_argument("--tessdata-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--psm", type=int, choices=(3, 4, 6, 11, 12), default=3)
    parser.add_argument("--renderer", choices=("poppler", "pdfium"), default="poppler",
                        help="PDF rasterizer; pdfium uses grayscale and requires pypdfium2 and Pillow")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--sample-pages", type=int, help="render the first N pages per source PDF")
    parser.add_argument("--cached-only", action="store_true", help="write snapshot.* from completed page checkpoints")
    args = parser.parse_args()
    if not 150 <= args.dpi <= 600:
        parser.error("--dpi must be between 150 and 600")
    if args.jobs < 1 or (args.sample_pages is not None and args.sample_pages < 1):
        parser.error("--jobs and --sample-pages must be positive")
    try:
        return process_sources(args)
    except (OSError, ValueError) as error:
        print(f"OCR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
