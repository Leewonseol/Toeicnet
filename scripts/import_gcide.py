"""Extract GCIDE sense evidence with the per-definition lineage the dictionary records.

GCIDE marks each definition with ``<source>``. Webster 1913 text, definitions taken from
WordNet and later editor additions are different lineages: a WordNet-derived GCIDE sense
must never count as a second independent source beside Open English WordNet. Each record
keeps that lineage in ``lineage`` and ``derived_from`` so the verifier can reject it.
"""

from __future__ import annotations

import argparse
import html
import re
import tarfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from external_records import normalize_headword, targets, write_jsonl

PARAGRAPH = re.compile(r"<p>(.*?)</p>", re.S)
TAG = re.compile(r"<(?P<name>[a-z]+)>(?P<body>.*?)</(?P=name)>", re.S)
ENTITY = re.compile(r"<([a-z0-9]+)/>?")
# GCIDE writes accented letters and ligatures as empty tags such as <eacute/> or <ae/>.
ENTITIES = {
    "ae": "ae", "AE": "AE", "oe": "oe", "OE": "OE", "eacute": "é", "egrave": "è", "ecir": "ê",
    "aacute": "á", "agrave": "à", "acir": "â", "uuml": "ü", "ouml": "ö", "auml": "ä",
    "iuml": "ï", "ccedil": "ç", "ntil": "ñ", "frac12": "1/2", "frac14": "1/4", "deg": "°",
    "mdash": "—", "ndash": "–", "lsquo": "‘", "rsquo": "’", "ldquo": "“", "rdquo": "”",
    "sect": "§", "pound": "£", "cre": "", "br": " ",
}
POS = {
    "n.": "noun", "n. pl.": "noun", "n. sing.": "noun", "v. t.": "verb", "v. i.": "verb",
    "v.": "verb", "v. t. & i.": "verb", "v. i. & t.": "verb", "a.": "adjective",
    "p. a.": "adjective", "adj.": "adjective", "adv.": "adverb", "prep.": "preposition",
    "conj.": "conjunction", "interj.": "interjection", "pron.": "pronoun",
}
POS_TAGS = {"v. t.": ("transitive",), "v. i.": ("intransitive",), "n. pl.": ("plural",)}
USAGE_TAGS = {"obs.": "obsolete", "archaic": "archaic", "r.": "rare", "rare": "rare", "colloq.": "colloquial"}
WEBSTER = {"1913 Webster", "Webster 1913", "Webster 1913 Suppl.", "+PJC", "1913 Webster +PJC"}
WORDNET = re.compile(r"^WordNet\b")


def lineage(source: str | None) -> tuple[str, tuple[str, ...]]:
    """Return (lineage, derived_from) for a GCIDE <source> value."""
    value = " ".join((source or "").split())
    if WORDNET.match(value):
        return "wordnet", ("globalwordnet", "oewn", "wordnet")
    if value in WEBSTER or value.startswith("1913 Webster") or value.startswith("Webster 1913"):
        return "webster1913", ("webster1913",)
    if value.strip(".") == "PJC":
        return "gcide_editor", ()
    return "other", (value,) if value else ()


def text(fragment: str) -> str:
    fragment = ENTITY.sub(lambda match: ENTITIES.get(match.group(1), ""), fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return " ".join(html.unescape(fragment).replace("\\'", "'").split())


def _tags(fragment: str) -> list[tuple[str, str, int]]:
    return [(match["name"], match["body"], match.start()) for match in TAG.finditer(fragment)]


def entries(lines: Iterable[str], filename: str) -> Iterator[dict]:
    """Yield one record per definition, carrying entry, POS and source state across paragraphs."""
    data = "".join(lines)
    headword = pos_label = etymology = None
    line, offset = 1, 0
    for paragraph in PARAGRAPH.finditer(data):
        body = re.sub(r"<vmorph>.*?</vmorph>", "", paragraph.group(1), flags=re.S)
        line += data.count("\n", offset, paragraph.start())
        offset = paragraph.start()
        items = _tags(body)
        names = [name for name, _, _ in items]
        if "ent" in names:
            headword = text(next(value for name, value, _ in items if name == "ent"))
            pos_label, etymology = None, None
        if headword is None:
            continue
        first_def = next((start for name, _, start in items if name == "def"), len(body))
        labels = [text(value) for name, value, start in items if name == "pos" and start < first_def]
        if labels:
            pos_label = labels[-1]
        if "ety" in names:
            etymology = text(next(value for name, value, _ in items if name == "ety"))
        sources = [text(value) for name, value, _ in items if name == "source"]
        marks = {text(value).strip("[]").casefold() for name, value, _ in items if name == "mark"}
        sense_number = next((text(value) for name, value, _ in items if name == "sn"), None)
        for index, (name, value, _) in enumerate(item for item in items if item[0] == "def"):
            definition = text(value)
            if not definition:
                continue
            source = sources[0] if sources else None
            kind, derived = lineage(source)
            tags = {USAGE_TAGS[mark] for mark in marks if mark in USAGE_TAGS}
            tags.update(POS_TAGS.get(pos_label or "", ()))
            yield {
                "headword": headword, "pos_label": pos_label,
                "part_of_speech": POS.get(pos_label or "", pos_label),
                "sense_number": sense_number, "definition": definition, "gcide_source": source,
                "lineage": kind, "derived_from": list(derived), "tags": sorted(tags),
                "etymology_text": etymology, "source_record_id": f"{filename}:{line}:def:{index + 1}",
            }


def archive_members(path: Path) -> Iterator[tuple[str, list[str]]]:
    """Read CIDE.* from an extracted directory or the release tarball."""
    if path.is_dir():
        for member in sorted(path.glob("CIDE.*")):
            yield member.name, member.read_text(encoding="latin-1").splitlines(keepends=True)
        return
    # Read the compressed stream once in archive order; seeking back into .xz restarts decompression.
    files = {}
    with tarfile.open(path, "r|*") as archive:
        for member in archive:
            name = Path(member.name).name
            if member.isfile() and re.fullmatch(r"CIDE\.[A-Z]", name):
                files[name] = archive.extractfile(member).read().decode("latin-1")
    for name in sorted(files):
        yield name, files[name].splitlines(keepends=True)


def candidate_records(path: Path, wanted: set[str] | None, *, version: str) -> Iterator[dict]:
    for filename, lines in archive_members(path):
        for entry in entries(lines, filename):
            if wanted is not None and normalize_headword(entry["headword"]) not in wanted:
                continue
            yield {
                **entry, "kind": "sense_candidate", "source_id": "gcide", "version": version,
                "url": "https://gcide.gnu.org.ua/", "extraction_method": "gcide_cide_markup",
                "verification_status": "source_attested",
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="gcide-*.tar.xz or an extracted directory")
    parser.add_argument("--version", required=True)
    parser.add_argument("--targets", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wanted = targets(args.targets) if args.targets else None
    count = write_jsonl(args.output, candidate_records(args.input, wanted, version=args.version))
    print(f"{count} GCIDE sense records -> {args.output}")


if __name__ == "__main__":
    main()
