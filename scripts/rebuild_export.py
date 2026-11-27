"""Export the existing rebuild-v2 analysis without re-analysing anything.

Two outputs are written from data/rebuild/full_v31r.jsonl and its companion files:

* vocabulary/ (tracked in git): English headwords and the relations derived from open data.
  No textbook Korean glosses and no DAY order, because the textbook text and arrangement are
  not cleared for redistribution. Wiktionary text makes these files CC BY-SA 4.0.
* exports/rebuild-v2/ (git-ignored, for private Drive storage): everything, including the
  textbook Korean glosses, SQLite, CSV, JSONL, Anki TSV/APKG, notes, gold data and reports.

Each run writes MANIFEST.json with item counts, sizes and SHA-256 for every file.
"""

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sqlite3
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/rebuild"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path, header, rows):
    rows = list(rows)
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def definition(row):
    if not row["english"]:
        return None, None
    first = row["english"][0]
    if row["english_grade"] == "B" and first["wn_definition"]:
        return first["wn_definition"], "oewn"
    if first.get("kk_gloss"):
        return first["kk_gloss"], "kaikki"
    return first.get("wn_definition"), "oewn"


def colligation_candidates(path=DATA / "oanc_usage.jsonl"):
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        if row["usage_type"] != "COLLIGATION":
            continue
        d = row["details"]
        surfaces = [" ".join(a.get("surface", "").split()).casefold() for a in d.get("attestations", [])]
        shown = max(set(surfaces), key=surfaces.count) if surfaces else row["expression"]
        yield [row["headword"], shown, row["expression"], d.get("combination") or "", d.get("frequency", 0),
               "oanc_candidate_unreviewed", row["source_record_id"]]


def tables(rows, korean, colligations=None):
    """Build every table once; `korean` adds the textbook gloss columns (private export only)."""
    order = sorted(rows, key=lambda r: (r["headword"].casefold(), r["item_id"])) if not korean else rows
    t = {}
    if korean:
        head = ["headword", "korean_textbook", "pos", "deck", "english_grade", "english_definition", "korean_status",
                "verification_method", "definition_source", "wordnet_sense_ids", "wiktionary_sense_ids",
                "korean_evidence_wiktionary", "day", "item_id"]
    else:
        head = ["headword", "source_set", "pos", "english_grade", "english_definition", "korean_status",
                "verification_method", "definition_source", "wordnet_sense_ids", "wiktionary_sense_ids", "item_id"]
    out = []
    for r in order:
        text, src = definition(r)
        wn = ";".join(e["wn_sense"] for e in r["english"] if e["wn_sense"])
        kk = ";".join(e["kk_sense"] for e in r["english"] if e["kk_sense"])
        if korean:
            out.append([r["headword"], " / ".join(r["korean"]), "/".join(r["pos"]), r["deck"], r["english_grade"], text or "",
                        r["korean_status"], r["method"], src or "", wn, kk, ";".join(r["korean_evidence"]), r["day"], r["item_id"]])
        else:
            out.append([r["headword"], "core" if r["core"] else "back", "/".join(r["pos"]), r["english_grade"], text or "",
                        r["korean_status"], r["method"], src or "", wn, kk, r["item_id"]])
    t["headwords"] = (head, out)

    prefixes, suffixes, derivs, bases = [], [], [], defaultdict(list)
    for r in order:
        m = r["morphology"]
        if not m or m["type"] == "multiword":
            continue
        seg = m["segments"]
        affixes = [s for s in seg if s.startswith("-") or s.endswith("-")]
        free = [s for s in seg if s not in affixes]
        derivs.append([r["headword"], m["type"], " + ".join(seg), ";".join(free), ";".join(affixes), m["source"]])
        for a in affixes:
            (prefixes if a.endswith("-") else suffixes).append([a, r["headword"], " + ".join(seg), m["source"]])
        for b in free:
            bases[b].append(r["headword"])
    t["morphology/derivations"] = (["headword", "formation_type", "segmentation", "bases", "affixes", "source_record"], derivs)
    t["morphology/prefixes"] = (["prefix", "headword", "segmentation", "source_record"], sorted(prefixes))
    t["morphology/suffixes"] = (["suffix", "headword", "segmentation", "source_record"], sorted(suffixes))
    t["morphology/roots"] = (["base", "derived_headwords", "count"],
                             sorted(([b, ";".join(sorted(set(h))), len(set(h))] for b, h in bases.items()),
                                    key=lambda x: (-x[2], x[0])))

    hist, shared = [], defaultdict(set)
    for r in order:
        e = r["etymology"]
        if not e:
            continue
        hist.append([r["headword"], e["family"], e["language"], e.get("etymon") or "", e["type"], e.get("root") or "", e["source"]])
        if e.get("root"):
            shared[e["root"]].add(r["headword"])
    t["etymology/historical_roots"] = (["headword", "family", "source_language", "etymon", "relation", "pie_root", "source_record"], hist)
    t["etymology/shared_origins"] = (["pie_root", "count", "headwords"],
                                     sorted(([k, len(v), ";".join(sorted(v))] for k, v in shared.items() if len(v) >= 2),
                                            key=lambda x: (-x[1], x[0])))

    syn, ant, themes = [], [], []
    for r in order:
        rel = r.get("textbook_relations") or []
        for x in rel:
            (syn if x["relation"] == "synonym" else ant).append([r["headword"], x["target"], "textbook_note", "", ""])
        if r["english_grade"] != "B":
            continue
        sense = next((e["wn_sense"] for e in r["english"] if e["wn_sense"]), "")
        for s in r["semantics"]["synonyms"]:
            syn.append([r["headword"], s, "wordnet_synset", sense, r["method"]])
        for a in r["semantics"]["antonyms"]:
            ant.append([r["headword"], a, "wordnet_antonym", sense, r["method"]])
        for f in r["semantics"]["fields"]:
            themes.append([f, r["headword"], sense, r["method"]])
    t["semantics/synonyms"] = (["headword", "synonym", "evidence", "wordnet_sense", "verification_method"], syn)
    t["semantics/antonyms"] = (["headword", "antonym", "evidence", "wordnet_sense", "verification_method"], ant)
    t["semantics/themes"] = (["wordnet_lexicographer_file", "headword", "wordnet_sense", "verification_method"], sorted(themes))

    coll, colig, idioms = [], [], []
    for r in order:
        for c in r["usage"]["collocations"]:
            row = [r["headword"], c["expression"], c["lemma"], c.get("combination") or "", c["frequency"], c["logdice"], c["record"]]
            (coll if c["type"] == "collocation" else colig).append(row)
        if " " in r["headword"] and r["english_grade"] in ("B", "C"):
            text, src = definition(r)
            kind = {"verb": "phrasal_or_multiword_verb", "preposition": "prepositional_expression",
                    "noun": "compound_noun"}.get(r["english"][0]["pos"], r["english"][0]["pos"])
            idioms.append([r["headword"], kind, r["english_grade"], text, src,
                           ";".join(e["kk_sense"] or e["wn_sense"] or "" for e in r["english"])])
    t["usage/collocations"] = (["headword", "collocation", "lemma", "combination", "oanc_frequency", "logdice", "oanc_record"], coll)
    # The v3.1 usage filter needs association scores, which OANC colligation records do not
    # carry, so no colligation was kept in the analysis. Export the corpus candidates as
    # unreviewed, with frequency and the most common attested surface form.
    heads = {r["headword"] for r in rows}
    for c in (colligations if colligations is not None else colligation_candidates()):
        if c[0] in heads:
            colig.append(c)
    t["usage/colligations"] = (["headword", "colligation", "lemma", "combination", "oanc_frequency", "status", "oanc_record"],
                               sorted(colig, key=lambda x: (x[0].casefold(), -x[4], x[1])))
    t["usage/idioms"] = (["expression", "type", "english_grade", "english_definition", "definition_source", "sense_ids"], idioms)
    return t


ATTRIBUTION = """# Toeicnet vocabulary data (rebuild-v2)

Generated by `scripts/rebuild_export.py` from the rule v3.1 analysis (commit history: branch `rebuild-v2`).
Each DAY folder follows the textbook DAY of the Anki deck (빈출 = core, 기초 = basic, 800, 900).
Columns `korean_textbook` hold the textbook's Korean glosses. They are 해커스 copyrighted material,
stored in this private repository by the owner's decision of 2026-11-27 for personal study; they are
not covered by the licence below and must not be redistributed.

Sources and licences for everything except `korean_textbook` (attribution required; CC BY-SA 4.0):
- Open English WordNet 2025, Open English Wordnet Community and Princeton WordNet, CC BY 4.0,
  https://en-word.net/ — definitions, synset synonyms, antonyms, lexicographer files.
- English Wiktionary contributors via Wiktextract/Kaikki dump enwiktionary-2026-10-01, CC BY-SA 4.0,
  https://kaikki.org/ — glosses, etymology templates (languages, etymons, PIE roots), morphology templates.
- Open American National Corpus GrAF release datasets-2026-09-25 (no use restrictions), https://anc.org/ —
  collocation and colligation statistics and record IDs.
Changes: senses were aligned to textbook items by rules (and, where `verification_method` is
`model_reviewed_pair`, accepted by a model review without human checking); fields were normalised.
"""


def build_sqlite(path, rows, extra):
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE items(item_id TEXT PRIMARY KEY, headword TEXT, deck TEXT, day INTEGER, core INTEGER,
      korean_textbook TEXT, pos TEXT, english_grade TEXT, method TEXT, korean_status TEXT, analysis_json TEXT);
    CREATE TABLE english_senses(item_id TEXT, wiktionary_sense TEXT, wiktionary_gloss TEXT, wordnet_sense TEXT,
      wordnet_definition TEXT, pos TEXT, similarity REAL);
    CREATE TABLE review_queue(item_id TEXT, headword TEXT, grade TEXT, reason TEXT, proposed_pairs_json TEXT);
    CREATE TABLE model_review(item_id TEXT, headword TEXT, accepted_pairs_json TEXT, reviewer TEXT);
    CREATE TABLE gold(sample TEXT, n INTEGER, record_json TEXT);
    """)
    for r in rows:
        db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            r["item_id"], r["headword"], r["deck"], r["day"], int(r["core"]), " / ".join(r["korean"]), "/".join(r["pos"]),
            r["english_grade"], r["method"], r["korean_status"], json.dumps(r, ensure_ascii=False)))
        for e in r["english"]:
            db.execute("INSERT INTO english_senses VALUES(?,?,?,?,?,?,?)", (
                r["item_id"], e["kk_sense"], e.get("kk_gloss"), e["wn_sense"], e.get("wn_definition"), e["pos"], e.get("similarity")))
    for q in extra["queue"]:
        db.execute("INSERT INTO review_queue VALUES(?,?,?,?,?)", (q["item_id"], q["headword"], q["grade"], q["reason"],
                                                                   json.dumps(q["proposed_pairs"], ensure_ascii=False)))
    for m in extra["review"]:
        db.execute("INSERT INTO model_review VALUES(?,?,?,?)", (m["item_id"], m["headword"], json.dumps(m["accepted_pairs"]), m["reviewer"]))
    for name, recs in extra["gold"].items():
        for g in recs:
            db.execute("INSERT INTO gold VALUES(?,?,?)", (name, g["n"], json.dumps(g, ensure_ascii=False)))
    db.commit()
    db.execute("VACUUM")
    db.close()


def build_apkg(path, cards_dir):
    import genanki
    model = genanki.Model(1831004201, "Toeicnet v2 card", fields=[{"name": "Front"}, {"name": "Back"}],
                          templates=[{"name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{FrontSide}}<hr id=answer>{{Back}}"}])
    decks, total = [], 0
    for i, tsv in enumerate(sorted(cards_dir.glob("*.tsv"))):
        lines = tsv.read_text(encoding="utf-8").splitlines()
        name = next(l.split(":", 1)[1] for l in lines if l.startswith("#deck:"))
        deck = genanki.Deck(1831004300 + i, name)
        for line in lines:
            if line.startswith("#"):
                continue
            front, back, tags = line.split("\t")
            guid = genanki.guid_for(name, front)
            deck.add_note(genanki.Note(model=model, fields=[front, back], tags=tags.split(), guid=guid))
            total += 1
        decks.append(deck)
    genanki.Package(decks).write_to_file(str(path))
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=DATA / "full_v31r.jsonl")
    parser.add_argument("--public", type=Path, default=ROOT / "vocabulary")
    parser.add_argument("--private", type=Path, default=ROOT / "exports/rebuild-v2")
    parser.add_argument("--part-size", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    rows = [json.loads(l) for l in args.analysis.open(encoding="utf-8")]
    queue = [json.loads(l) for l in (DATA / "review_queue.jsonl").open(encoding="utf-8")]
    review = [json.loads(l) for l in (DATA / "gold/core_model_review.jsonl").open(encoding="utf-8")]
    gold = {name: [json.loads(l) for l in (DATA / f"gold/{name}_gold.jsonl").open(encoding="utf-8")] for name in ("sample", "holdout")}
    counts = {}

    # Repository tables, split by textbook DAY so each file renders as a table on GitHub. By
    # the owner's decision of 2026-11-27 they include the textbook Korean glosses (private repo).
    if args.public.exists():
        shutil.rmtree(args.public)
    collig = list(colligation_candidates())
    for name in ("morphology/prefixes", "morphology/suffixes", "morphology/roots", "etymology/shared_origins"):
        header, data = tables(rows, korean=True, colligations=[])[name]
        counts[f"vocabulary/{name}.csv"] = write_csv(args.public / f"{name}.csv", header, data)
    per_day = ("headwords", "morphology/derivations", "etymology/historical_roots", "semantics/synonyms",
               "semantics/antonyms", "semantics/themes", "usage/collocations", "usage/colligations", "usage/idioms")
    day_index = []
    for day in sorted({r["day"] for r in rows}):
        day_rows = [r for r in rows if r["day"] == day]
        built = tables(day_rows, korean=True, colligations=collig)
        folder = args.public / "days" / f"DAY{day:02d}"
        entry = {"day": day, "items": len(day_rows), "core": sum(r["core"] for r in day_rows), "files": {}}
        for name in per_day:
            header, data = built[name]
            if data:  # a DAY without, e.g., any antonym gets no antonym file
                n = write_csv(folder / f"{name.split('/')[-1]}.csv", header, data)
                entry["files"][name.split("/")[-1]] = n
                counts[f"vocabulary/days/DAY{day:02d}/{name.split('/')[-1]}.csv"] = n
        ids = {r["item_id"] for r in day_rows}
        pending = [q for q in queue if q["item_id"] in ids]
        if pending:
            entry["files"]["pending"] = write_csv(folder / "pending.csv", ["item_id", "headword", "grade", "reason", "proposed_pairs"],
                                                  [[q["item_id"], q["headword"], q["grade"], q["reason"], json.dumps(q["proposed_pairs"])] for q in pending])
        day_index.append(entry)
    review_dir = args.public / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    with (review_dir / "model_review.jsonl").open("w", encoding="utf-8") as h:
        for m in review:
            h.write(json.dumps(m, ensure_ascii=False) + "\n")
    with (review_dir / "gold_sample_and_holdout.jsonl").open("w", encoding="utf-8") as h:
        for name, recs in gold.items():
            for g in recs:
                h.write(json.dumps({"sample": name, **g}, ensure_ascii=False) + "\n")
    counts["vocabulary/review/model_review.jsonl"] = len(review)
    counts["vocabulary/review/gold_sample_and_holdout.jsonl"] = sum(map(len, gold.values()))
    lines = [ATTRIBUTION, "", "## DAY별 자료", "",
             "| DAY | 항목 | 본 단어 | 표제어·뜻 | 파생 | 어원 | 동의어 | 반의어 | 의미장 | 콜로케이션 | 문법적 연어 후보 | 숙어 | 검토 대기 |",
             "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for e in day_index:
        d = f"days/DAY{e['day']:02d}"
        def cell(key):
            n = e["files"].get(key)
            return f"[{n:,}]({d}/{key}.csv)" if n else "–"
        lines.append(f"| {e['day']:02d} | {e['items']:,} | {e['core']:,} | {cell('headwords')} | {cell('derivations')} | {cell('historical_roots')} | "
                     f"{cell('synonyms')} | {cell('antonyms')} | {cell('themes')} | {cell('collocations')} | {cell('colligations')} | "
                     f"{cell('idioms')} | {cell('pending')} |")
    lines += ["", "DAY를 가로지르는 집단: [접두사](morphology/prefixes.csv) · [접미사](morphology/suffixes.csv) · "
              "[어기](morphology/roots.csv) · [공통 PIE 어근](etymology/shared_origins.csv). 한 표제어가 두 DAY에 있으면 두 DAY에 모두 나온다."]
    (args.public / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return_public = True


    # Private export: everything, including textbook glosses.
    out = args.private
    if out.exists():
        shutil.rmtree(out)
    (out / "csv").mkdir(parents=True)
    for name, (header, data) in tables(rows, korean=True).items():
        counts[f"csv/{name}.csv"] = write_csv(out / "csv" / f"{name.replace('/', '__')}.csv", header, data)
    shutil.copy(args.analysis, out / "full_analysis_v31r.jsonl")
    counts["full_analysis_v31r.jsonl"] = len(rows)
    for name in ("review_queue.jsonl", "source_items.jsonl", "source_audit.json", "sample100.jsonl", "holdout40.jsonl",
                 "sample_v31_eval.json", "holdout_v31_eval.json"):
        shutil.copy(DATA / name, out / name)
    build_sqlite(out / "toeicnet_rebuild_v2.sqlite", rows, {"queue": queue, "review": review, "gold": gold})
    counts["toeicnet_rebuild_v2.sqlite:items"] = len(rows)
    with tarfile.open(out / "gold_and_review.tar.gz", "w:gz") as tar:
        tar.add(DATA / "gold", arcname="gold")
    with tarfile.open(out / "anki_tsv.tar.gz", "w:gz") as tar:
        tar.add(DATA / "cards", arcname="cards")
    counts["toeicnet_rebuild_v2.apkg:notes"] = build_apkg(out / "toeicnet_rebuild_v2.apkg", DATA / "cards")
    with tarfile.open(out / "notes_part1-3.tar.gz", "w:gz") as tar:
        tar.add(ROOT / "notes/rebuild_v2", arcname="notes")
    for name in ("rebuild_v2_report.md", "rebuild_v2_summary.json"):
        shutil.copy(ROOT / "reports" / name, out / name)
    # Lexicon extractions, so a later session does not re-scan 3 GB of dumps; split for the
    # 10 MB connector limit.
    for name in ("kaikki_targets.jsonl", "kaikki_korean.jsonl", "wordnet_targets.json", "gcide_targets.jsonl", "oanc_usage.jsonl"):
        raw = gzip.compress((DATA / name).read_bytes(), 6)
        parts = [raw[i:i + args.part_size] for i in range(0, len(raw), args.part_size)]
        for i, part in enumerate(parts):
            (out / "lexicon" / f"{name}.gz.part{i:02d}").parent.mkdir(exist_ok=True)
            (out / "lexicon" / f"{name}.gz.part{i:02d}").write_bytes(part)
        counts[f"lexicon/{name}.gz"] = {"parts": len(parts), "sha256_joined": hashlib.sha256(raw).hexdigest()}

    manifest = {"source_analysis": args.analysis.name, "rules": rows[0]["rules"], "counts": counts, "files": {}}
    for base in (out, args.public):
        for f in sorted(p for p in base.rglob("*") if p.is_file() and p.name != "MANIFEST.json"):
            manifest["files"][str(f.relative_to(ROOT))] = {"bytes": f.stat().st_size, "sha256": sha256(f)}
    for base in (out, args.public):
        (base / "MANIFEST.json").write_text(json.dumps(
            {**manifest, "files": {k: v for k, v in manifest["files"].items() if k.startswith(str(base.relative_to(ROOT)))}},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
