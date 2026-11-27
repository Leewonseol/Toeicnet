"""Shared I/O conventions for open-source candidate adapters."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import gzip
import json
from pathlib import Path
import tempfile
import unicodedata

POS = {
    "n": "noun",
    "v": "verb",
    "a": "adjective",
    "s": "adjective",
    "r": "adverb",
    "adj": "adjective",
    "adv": "adverb",
    "prep": "preposition",
    "conj": "conjunction",
    "det": "determiner",
    "pron": "pronoun",
    "intj": "interjection",
    "num": "numeral",
}


def normalize_pos(pos: str | None) -> str | None:
    return POS.get(pos, pos)


def normalize_headword(word: str) -> str:
    word = unicodedata.normalize("NFKC", word)
    return " ".join(word.replace("’", "'").casefold().split())


def open_data(path: Path, mode: str = "rt"):
    kwargs = {} if "b" in mode else {"encoding": "utf-8"}
    return gzip.open(path, mode, **kwargs) if path.suffix == ".gz" else path.open(mode, **kwargs)


def read_jsonl(path: Path) -> Iterator[dict]:
    with open_data(path) as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected a JSON object")
                yield row


def targets(paths: Iterable[Path]) -> set[str]:
    return {
        normalize_headword(row["headword"])
        for path in paths
        for row in read_jsonl(path)
        if row.get("headword")
    }


@contextmanager
def atomic_output(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    )
    temp_path = Path(temporary.name)
    try:
        with temporary:
            yield temporary
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    count = 0
    with atomic_output(path) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count
