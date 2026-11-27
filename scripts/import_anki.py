"""Inspect or import a user-provided Anki deck as a distinct local source."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from getpass import getpass
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from zipfile import BadZipFile, ZipFile

from intake_common import sha256_file, write_json, write_jsonl


SOURCE_ID = "hackers_anki_user"
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
DB_MEMBERS = ("collection.anki21b", "collection.anki21", "collection.anki2")
DAY_RE = re.compile(r"(?<![A-Za-z0-9])day[\s_.-]*(0?[1-9]|[12][0-9]|30)(?![0-9])", re.I)


def copy_bounded(reader, target):
    total = 0
    with target.open("wb") as writer:
        while block := reader.read(1024 * 1024):
            total += len(block)
            if total > MAX_MEMBER_BYTES:
                raise ValueError("Anki archive member exceeds the supported size")
            writer.write(block)


def extract_member(archive, info, target, password=None):
    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError("Anki archive member exceeds the supported size")
    if info.flag_bits & 1 and password is None:
        raise ValueError("Archive member is encrypted; use --password-env or --ask-password")
    with archive.open(info, pwd=password) as reader:
        copy_bounded(reader, target)


def decode_db(blob, target):
    zstd = shutil.which("zstd")
    if zstd is None:
        raise ValueError("The system `zstd` utility is required for current Anki packages")
    with subprocess.Popen([zstd, "--decompress", "--stdout", "--", str(blob)], stdout=subprocess.PIPE) as process:
        try:
            with process.stdout as stream:
                copy_bounded(stream, target)
        except BaseException:
            process.kill()
            raise
        if process.wait():
            raise ValueError("Anki collection Zstandard decompression failed")


@contextmanager
def open_collection(path, password=None):
    with tempfile.TemporaryDirectory(prefix="anki-intake-") as folder:
        folder = Path(folder)
        package = path
        package_name = path.name
        if path.suffix.lower() == ".zip":
            with ZipFile(path) as outer:
                candidates = [item for item in outer.infolist() if not item.is_dir()
                              and PurePosixPath(item.filename).suffix.lower() == ".apkg"]
                if len(candidates) != 1:
                    raise ValueError("ZIP must contain exactly one Anki .apkg file")
                package_name = PurePosixPath(candidates[0].filename).name
                package = folder / "package.apkg"
                extract_member(outer, candidates[0], package, password)
        if package.suffix.lower() != ".apkg":
            raise ValueError("Use an .apkg file or a .zip containing exactly one .apkg")
        with ZipFile(package) as archive:
            names = archive.namelist()
            member = next((name for name in DB_MEMBERS if name in names), None)
            if member is None or names.count(member) != 1:
                raise ValueError("Anki SQLite collection is missing or repeated")
            target = folder / "collection.sqlite"
            if member.endswith("21b"):
                blob = folder / "collection.zst"
                extract_member(archive, archive.getinfo(member), blob, password)
                decode_db(blob, target)
            else:
                extract_member(archive, archive.getinfo(member), target, password)
        with target.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise ValueError("Anki collection is not a SQLite database")
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            # Anki declares unicase in its schema. Queries here order and filter by numeric IDs only.
            db.create_collation("unicase", unicode_case_comparison)
            db.row_factory = sqlite3.Row
            yield db, package_name, member


def unicode_case_comparison(left, right):
    left, right = left.casefold(), right.casefold()
    return (left > right) - (left < right)


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden = tag
        elif tag in {"br", "div", "p", "li", "tr"} and self.hidden is None:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden == tag:
            self.hidden = None
        if tag in {"div", "p", "li", "tr"} and self.hidden is None:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.hidden is None:
            self.parts.append(data)


def field_text(value):
    parser = Text()
    parser.feed(value)
    parser.close()
    text = re.sub(r"\[sound:[^\]]+\]", "", "".join(parser.parts))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def display_deck(name):
    return name.replace("\x1f", "::")


def collection_metadata(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"notes", "cards", "col"} <= tables:
        raise ValueError("Anki collection is missing notes, cards or version metadata")
    version = db.execute("SELECT ver FROM col").fetchone()[0]
    if {"notetypes", "fields", "decks"} <= tables:
        fields = defaultdict(list)
        for row in db.execute("SELECT ntid,ord,name FROM fields ORDER BY ntid,ord"):
            fields[row["ntid"]].append((row["ord"], row["name"]))
        models = {row["id"]: (row["name"], fields[row["id"]])
                  for row in db.execute("SELECT id,name FROM notetypes")}
        decks = {row["id"]: display_deck(row["name"]) for row in db.execute("SELECT id,name FROM decks")}
    else:
        row = db.execute("SELECT models,decks FROM col").fetchone()
        models = {int(key): (model["name"], sorted((field["ord"], field["name"]) for field in model["flds"]))
                  for key, model in json.loads(row["models"]).items()}
        decks = {int(key): display_deck(deck["name"]) for key, deck in json.loads(row["decks"]).items()}
    return version, models, decks


def open_day_values(*values):
    return set(int(match.group(1)) for value in values for match in DAY_RE.finditer(value))


def resolve_day(deck, tags, field=""):
    days = open_day_values(deck, tags, field)
    stripped = field.strip()
    if re.fullmatch(r"0?[1-9]|[12][0-9]|30", stripped):
        days.add(int(stripped))
    if len(days) > 1:
        raise ValueError(f"Conflicting source DAY labels: {sorted(days)}")
    return next(iter(days), None)


def deck_membership(db):
    memberships = defaultdict(list)
    for row in db.execute("SELECT id,nid,CASE WHEN odid<>0 THEN odid ELSE did END AS origin_deck "
                          "FROM cards ORDER BY id"):
        memberships[row["nid"], row["origin_deck"]].append(row["id"])
    return memberships


def inspect(db, package_name, member):
    version, models, decks = collection_metadata(db)
    notes = dict(db.execute("SELECT mid,count(*) FROM notes GROUP BY mid"))
    memberships = deck_membership(db)
    cards = Counter()
    deck_notes = Counter()
    for (_, did), entries in memberships.items():
        cards[did] += len(entries)
        deck_notes[did] += 1
    return {
        "source_id": SOURCE_ID,
        "package_filename": package_name,
        "collection_member": member,
        "schema_version": version,
        "note_count": sum(notes.values()),
        "card_count": sum(cards.values()),
        "notes_with_cards": len({nid for nid, _ in memberships}),
        "note_deck_membership_count": len(memberships),
        "note_models": [{"id": mid, "name": name, "fields": dict(fields), "note_count": notes[mid]}
                        for mid, (name, fields) in sorted(models.items())],
        "decks": [{"id": did, "name": label, "note_count": deck_notes[did], "card_count": cards[did],
                   "explicit_day_labels": sorted(open_day_values(label))} for did, label in sorted(decks.items())],
    }


def select_model_fields(models, model_id, *names):
    if model_id not in models:
        raise ValueError(f"Unknown note model ID {model_id}; run --inspect")
    by_name = {name.casefold(): index for index, name in models[model_id][1]}
    positions = []
    for name in names:
        if name is None:
            positions.append(None)
        elif name.casefold() in by_name:
            positions.append(by_name[name.casefold()])
        else:
            raise ValueError(f"Unknown note field {name!r}; run --inspect")
    return positions


def import_notes(db, package_name, path, checksum, args):
    version, models, decks = collection_metadata(db)
    selected = set(args.deck_id)
    if selected - decks.keys():
        raise ValueError("Selected deck IDs must exist in the Anki collection")
    if args.deck_prefix:
        prefix = display_deck(args.deck_prefix).removesuffix("::")
        branch = {did for did, name in decks.items() if name == prefix or name.startswith(prefix + "::")}
        if not branch:
            raise ValueError(f"No decks found in the selected branch {prefix!r}")
        selected = selected & branch if selected else branch
        if not selected:
            raise ValueError("Selected deck IDs are outside the selected branch")
    positions = select_model_fields(models, args.model_id, args.headword_field, args.meaning_field,
                                    args.day_field, args.pos_field)
    memberships = deck_membership(db)
    decks_by_note = defaultdict(list)
    for (nid, did), cards in memberships.items():
        if not selected or did in selected:
            decks_by_note[nid].append((did, cards))
    result = []
    for note in db.execute("SELECT id,guid,tags,flds FROM notes WHERE mid=? ORDER BY id", (args.model_id,)):
        note_id = note["id"]
        fields = note["flds"].split("\x1f")
        if any(index is not None and index >= len(fields) for index in positions):
            raise ValueError(f"Anki note {note_id}: selected field is outside the field array")
        if note_id not in decks_by_note:
            continue
        headword, meaning, day_field, pos = (field_text(fields[index]) if index is not None else ""
                                             for index in positions)
        if not headword or any(char in headword for char in "\t\n\x00"):
            raise ValueError(f"Anki note {note_id}: headword is empty or has multiple lines")
        for did, card_ids in sorted(decks_by_note[note_id]):
            deck = decks.get(did)
            if deck is None:
                raise ValueError(f"Anki note {note_id}: missing deck metadata for {did}")
            result.append({
                "headword": headword,
                "original_korean_meaning": meaning or None,
                "part_of_speech": pos or None,
                "entry_type": None,
                "day": resolve_day(deck, note["tags"], day_field),
                "category": deck,
                "source_id": SOURCE_ID,
                "source_record_id": f"{note_id}:{did}",
                "filename": path.name,
                "anki_package_filename": package_name,
                "anki_note_id": note_id,
                "anki_note_guid": note["guid"],
                "anki_deck_id": did,
                "anki_model_id": args.model_id,
                "anki_card_ids": card_ids,
                "source_sha256": checksum,
                "pdf_page": None,
                "printed_page": None,
                "verification_status": "source_attested",
                "extraction_method": "anki_user_package_import",
                "version": f"anki_schema_{version}",
            })
    if not result:
        raise ValueError("No notes with cards matched the selected deck and note model")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="local .apkg, or .zip containing exactly one .apkg")
    password = parser.add_mutually_exclusive_group()
    password.add_argument("--password-env", metavar="VARIABLE", help="read the archive password from this environment variable")
    password.add_argument("--ask-password", action="store_true", help="prompt in the local terminal without echo")
    parser.add_argument("--inspect", action="store_true", help="show counts, decks and model fields without importing content")
    parser.add_argument("--model-id", type=int)
    parser.add_argument("--deck-id", action="append", type=int, default=[])
    parser.add_argument("--deck-prefix", help="select the exact named deck branch and its subdecks")
    parser.add_argument("--expected-count", type=int, help="require this many selected note/deck occurrences")
    parser.add_argument("--require-all-days", action="store_true", help="require explicit DAY 01–30 coverage")
    parser.add_argument("--headword-field")
    parser.add_argument("--meaning-field")
    parser.add_argument("--day-field")
    parser.add_argument("--pos-field")
    parser.add_argument("--output", type=Path, default=Path("data/intermediate/anki.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("data/intermediate/anki-manifest.json"))
    args = parser.parse_args(argv)
    if not args.inspect and not (args.model_id and args.headword_field and args.meaning_field):
        parser.error("set the note model and fields explicitly (use --inspect to find them)")
    if len({path.resolve() for path in (args.input, args.output, args.manifest)}) != 3:
        parser.error("input, output and manifest must be separate files")
    try:
        secret = getpass("Archive password: ") if args.ask_password else os.environ.get(args.password_env or "")
        if args.password_env and not secret:
            raise ValueError("The nominated archive password environment variable is absent or empty")
        # Publish provenance only; the credential is never included in commands or artifacts.
        checksum = sha256_file(args.input)
        with open_collection(args.input, secret.encode() if secret else None) as (db, package_name, member):
            manifest = inspect(db, package_name, member)
            manifest.update(filename=args.input.name, sha256=checksum)
            if args.inspect:
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
                return 0
            records = import_notes(db, package_name, args.input, checksum, args)
        if sha256_file(args.input) != checksum:
            raise ValueError("Anki package changed during import")
        counts = Counter(record["day"] for record in records if record["day"] is not None)
        unknown_days = len(records) - sum(counts.values())
        complete = set(counts) == set(range(1, 31)) and not unknown_days
        if args.expected_count is not None and len(records) != args.expected_count:
            raise ValueError(f"Expected {args.expected_count} occurrences, found {len(records)}")
        if args.require_all_days and not complete:
            raise ValueError("Selected occurrences lack complete DAY 01–30 coverage")
        write_jsonl(args.output, records)
        manifest.update({
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "selected_deck_prefix": args.deck_prefix,
            "selected_deck_ids": args.deck_id,
            "expected_count": args.expected_count,
            "extracted_count": len(records),
            "days": dict(sorted(counts.items())),
            "unknown_day_count": unknown_days,
            "day_coverage_complete": complete,
            "unique_headword_count": len({unicodedata.normalize("NFKC", r["headword"]).casefold() for r in records}),
            "output_records_sha256": sha256_file(args.output),
        })
        write_json(args.manifest, manifest)
        print(f"Imported {len(records)} Anki note/deck occurrences; {manifest['unknown_day_count']} without source DAY labels.")
    except (OSError, ValueError, RuntimeError, BadZipFile, sqlite3.Error) as error:
        print(f"Anki import: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
