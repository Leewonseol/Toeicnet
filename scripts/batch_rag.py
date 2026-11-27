"""Resume evidence retrieval and sense review against the existing TOEIC SQLite database."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from time import perf_counter

from batch_rag_benchmark import evaluate_sample, select_sample, write_review_packet
from batch_rag_modules import load_module_evidence
from batch_rag_retrieval import EvidenceRetriever
from batch_rag_verify import adjudicate_english, adjudicate_korean, load_model_decisions, model_review_packet
from export_semantic_coverage import coverage_rows
from review_common import normalized_lemma


DEFAULT_DB = Path("data/processed/toeic.db")
DEFAULT_OUTPUT = Path("data/intermediate/batch_rag")
BASELINE_A = "learner_cross_verified_sense_linked"
OPEN_MATCH = "open_candidates_pending_alignment"
SCHEMA = Path(__file__).with_name("batch_rag_schema.sql")
MODULES = ("morphology", "etymology", "lexical_semantics", "lexical_usage")


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def revision():
    directory = Path(__file__).parent
    paths = [directory / name for name in (
        "batch_rag.py", "batch_rag_benchmark.py", "batch_rag_modules.py",
        "batch_rag_retrieval.py", "batch_rag_verify.py",
    )] + [SCHEMA]
    return hashlib.sha256(b"\0".join(path.read_bytes() for path in paths)).hexdigest()


def baseline_and_fingerprint(connection):
    rows = list(coverage_rows(connection, "anki"))
    sources = [tuple(row) for row in connection.execute(
        "SELECT source_id, version, independence_group FROM sources ORDER BY source_id"
    )]
    input_hashes = [tuple(row) for row in connection.execute(
        "SELECT input_kind,sha256,row_count FROM run_input ORDER BY input_kind,sha256"
    )]
    reviewed = [tuple(row) for row in connection.execute("""
        SELECT so.occurrence_id,so.sense_id,en.status,en.english_definition,
               ko.status,ko.verified_korean_meaning
        FROM sense_occurrences so JOIN english_definitions en USING (sense_id)
        JOIN korean_translations ko USING (sense_id) ORDER BY so.occurrence_id,so.sense_id
    """)]
    value = digest([rows, sources, input_hashes, reviewed])
    return rows, value


def case_identity(target, reviewed):
    gloss = " ".join((target.get("original_korean_meaning") or "").split())
    previously_linked = sorted(row["sense_id"] for row in reviewed if row.get("sense_id"))
    return digest([
        target["word_id"], normalized_lemma(target["headword"]),
        " ".join((target.get("part_of_speech") or "").casefold().split()),
        gloss or target["occurrence_id"], previously_linked,
    ])


def priority(target):
    state = target["meaning_evidence_state"]
    return 0 if state == OPEN_MATCH else 2 if state == BASELINE_A else 1


def get_targets(retriever, baseline):
    measured = {row["occurrence_id"]: row for row in baseline}
    targets = {
        row["occurrence_id"]: {**row, **measured[row["occurrence_id"]]}
        for row in retriever.targets() if row["occurrence_id"] in measured
    }
    if targets.keys() != measured.keys():
        raise ValueError("Source intake and retrieval target IDs do not match.")
    return targets


def candidate_refs(candidates):
    fields = ("candidate_id", "evidence_ref", "source_id", "source_record_id",
              "source_version", "source_url", "independence_group", "part_of_speech",
              "match_method", "url")
    return [{field: row[field] for field in fields if field in row} for row in candidates]


def packet_for(retriever, target, top_k):
    started = perf_counter()
    packet = retriever.retrieve(target, per_channel=top_k)
    packet["target"] = target
    packet["case_key"] = case_identity(target, packet.get("reviewed", []))
    packet["retrieval_ms"] = (perf_counter() - started) * 1000
    return packet


def atomic_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path, results):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        for row in results:
            output.write(stable_json(row) + "\n")
    temporary.replace(path)


def merge_decisions(paths):
    combined = {}
    for path in paths:
        for key, decision in load_model_decisions(path).items():
            if key in combined and combined[key] != decision:
                raise ValueError(f"Multiple decisions disagree for case {key}.")
            combined[key] = decision
    return combined


def load_module_reviews(path):
    reviews = {}
    if path is None:
        return reviews
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            module = row["module"]
            if module not in MODULES or row["verdict"] not in {"attested", "insufficient"}:
                raise ValueError("Unknown module review type or verdict.")
            for field in ("occurrence_id", "reference_id", "claim", "reason", "reviewer"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError(f"A module review requires {field}.")
            key = (row["occurrence_id"], module, row["reference_id"])
            if key in reviews:
                raise ValueError(f"Duplicate module evidence review: {key}.")
            reviews[key] = row
    return reviews


def attach_module_reviews(module_evidence, module_reviews):
    for (occurrence, module, reference_id), review in module_reviews.items():
        result = module_evidence.get(occurrence, {}).get(module, {})
        reference = next((item for item in result.get("evidence", [])
                          if reference_id in {item.get("candidate_id"), item.get("edge_id")}), None)
        if reference is None:
            raise ValueError(f"Module review cited an unrelated or unavailable reference: {reference_id}.")
        if review["verdict"] == "attested" and reference.get("status") == "disputed":
            raise ValueError(f"Cannot mark a disputed relation attested: {reference_id}.")
        result.setdefault("source_fact_reviews", []).append({
            **review, "scope": "cited_source_record",
            "workbook_sense_alignment": reference.get("scope") == "occurrence_sense",
        })


def load_archive_refs(paths, targets):
    refs = {}
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                observation = json.loads(line)
                occurrence = observation["occurrence_id"]
                record = observation["record"]
                if occurrence not in targets or record["source_id"] not in {"oewn", "kaikki"}:
                    raise ValueError("Archive observation is outside the current source scope.")
                if observation["headword"] != targets[occurrence]["headword"]:
                    raise ValueError("Archive observation headword does not match the existing occurrence.")
                refs.setdefault(occurrence, []).append({
                    **{key: record.get(key) for key in ("source_id", "source_record_id", "version", "url")},
                    **{key: observation.get(key) for key in ("matched_form", "lookup_basis", "review_status")},
                })
    return refs


def adjudicate(packet, decision):
    target = packet["target"]
    established = packet.get("reviewed", [])
    sense_candidates = packet.get("senses", [])
    korean_candidates = packet.get("korean_candidates", packet.get("korean", []))
    case = {**target, "case_key": packet["case_key"]}
    inputs = {"case": case, "established": established, "korean_candidates": korean_candidates}
    try:
        english = adjudicate_english(sense_candidates, **inputs, decision=decision)
    except ValueError as error:
        if decision is None:
            raise
        english = adjudicate_english(sense_candidates, **inputs)
        english["rejected_model_review"] = str(error)
    korean_inputs = {"established": established, "candidates": korean_candidates}
    try:
        korean = adjudicate_korean(
            **korean_inputs, decision=decision, english=english,
            english_candidates=sense_candidates, case=case,
        )
    except ValueError as error:
        if decision is None:
            raise
        korean = adjudicate_korean(**korean_inputs)
        korean["rejected_model_review"] = str(error)
    return english, korean


def cache_or_decide(connection, run_id, packet, decision, rules):
    key = packet["case_key"]
    cache_key = digest([rules, key, packet.get("senses"), packet.get("reviewed"),
                        packet.get("korean", packet.get("korean_candidates")), decision])
    existing = connection.execute("""
        SELECT english_json,korean_json FROM batch_rag_cases WHERE cache_key=?
        ORDER BY (run_id=?) DESC,run_id LIMIT 1
    """, (cache_key, run_id)).fetchone()
    if existing:
        english, korean = map(json.loads, existing)
    else:
        english, korean = adjudicate(packet, decision)
    conflict = connection.execute("""
        INSERT INTO batch_rag_cases VALUES(?,?,?,?,?)
        ON CONFLICT(run_id,case_key) DO UPDATE SET cache_key=excluded.cache_key
        WHERE batch_rag_cases.cache_key=excluded.cache_key
        RETURNING cache_key
    """, (run_id, key, cache_key, stable_json(english), stable_json(korean))).fetchone()
    if conflict is None:
        raise ValueError(f"Case {key} resolved to different evidence within one batch.")
    return english, korean, existing is not None


def save_occurrence(connection, run_id, packet, modules, archive_refs, cache_hit):
    target = packet["target"]
    connection.execute("""
        INSERT INTO batch_rag_occurrences VALUES(?,?,?,?,?,?,?,?)
    """, (
        run_id, target["occurrence_id"], packet["case_key"], priority(target),
        stable_json(modules), stable_json({
            "senses": candidate_refs(packet.get("senses", [])),
            "korean": candidate_refs(packet.get("korean_candidates", [])),
            "archive": archive_refs,
        }), packet["retrieval_ms"], int(cache_hit),
    ))


def assessment_rows(connection, run_id, targets):
    result = connection.execute("""
        SELECT occurrence_id,case_key,priority,english_json,korean_json,
               modules_json,candidate_refs_json
        FROM batch_rag_assessments WHERE run_id=? ORDER BY priority,occurrence_id
    """, (run_id,))
    for occurrence, key, rank, english, korean, modules, refs in result:
        yield {
            "target": targets[occurrence], "case_key": key, "priority": rank,
            "english": json.loads(english), "korean": json.loads(korean),
            "modules": json.loads(modules), "candidate_refs": json.loads(refs),
        }


def queue_rows(assessments):
    for row in assessments:
        target, english, korean = row["target"], row["english"], row["korean"]
        pending = {}
        if english["grade"] in {"C", "D", "E"}:
            pending["english"] = english.get("review_reason") or "independent_definition_needed"
        if english.get("rejected_model_review"):
            pending["model_review"] = english["rejected_model_review"]
        if korean.get("rejected_model_review"):
            pending["korean"] = korean["rejected_model_review"]
        elif korean["status"] != "verified":
            pending["korean"] = korean.get("review_reason") or korean["status"]
        for name in MODULES:
            module = row["modules"].get(name, {})
            if module.get("next_review"):
                pending[name] = module["next_review"]
        if pending:
            yield {
                "target": target, "case_key": row["case_key"], "priority": row["priority"],
                "english_grade": english["grade"], "pending": pending,
                "candidate_refs": row["candidate_refs"],
            }


def summarize(results, elapsed, retrieval, cache_hits, unique_cases, decision_count):
    before = Counter(row["target"]["meaning_evidence_state"] for row in results)
    grades = Counter(row["english"]["grade"] for row in results)
    languages = Counter(row["korean"]["status"] for row in results)
    methods = Counter(row["english"].get("method") for row in results)
    source_grades = {}
    module_statuses = {module: Counter() for module in MODULES}
    module_judgments = {module: Counter() for module in MODULES}
    for row in results:
        source = row["target"]["source_id"]
        source_grades.setdefault(source, Counter())[row["english"]["grade"]] += 1
        for module, review in row["modules"].items():
            module_statuses[module][review["classification"]] += 1
            module_judgments[module].update(item["verdict"] for item in review.get("source_fact_reviews", []))
    return {
        "occurrence_count": len(results), "unique_cases": unique_cases,
        "before_english": dict(before), "grades": {grade: grades[grade] for grade in "ABCDE"},
        "before_korean_verified": sum(bool(row["target"]["korean_verified_senses"]) for row in results),
        "korean_statuses": dict(languages), "methods": dict(methods),
        "grades_by_source": source_grades, "module_statuses": module_statuses,
        "module_model_reviews": module_judgments,
        "retrieval_seconds": retrieval,
        "elapsed_seconds_this_invocation": elapsed, "semantic_cache_hits": cache_hits,
        "mean_retrieval_ms_per_occurrence": 1000 * retrieval / len(results) if results else None,
        "decision_records_supplied": decision_count, "external_api_calls": 0,
        "archive_observations": sum(len(row["candidate_refs"].get("archive", [])) for row in results),
        "occurrences_with_archive_observations": sum(
            bool(row["candidate_refs"].get("archive")) for row in results
        ),
        "indexed_recovery_among_initial_no_exact": sum(
            row["priority"] == 1 and bool(row["candidate_refs"].get("senses")) for row in results
        ),
        "model_reviews_rejected": sum(bool(row["english"].get("rejected_model_review")) for row in results),
        "korean_reviews_rejected": sum(bool(row["korean"].get("rejected_model_review")) for row in results),
        "external_api_cost_usd": 0, "historical_manual_time_available": False,
        "review_queue_occurrences": sum(1 for _ in queue_rows(results)),
    }


def run(connection, args):
    started = perf_counter()
    baseline, fingerprint = baseline_and_fingerprint(connection)
    retriever = EvidenceRetriever(connection)
    targets = get_targets(retriever, baseline)
    sample = [targets[row["occurrence_id"]] for row in select_sample(baseline, size=100)]
    pilot_dir = args.output / "pilot"
    if args.command == "prepare":
        directory = pilot_dir
        selected = sample
        if args.review_queue:
            directory = args.output / "next_review"
            with args.review_queue.open(encoding="utf-8") as stream:
                pending = (json.loads(line) for line in stream if line.strip())
                cases = {}
                for row in pending:
                    if "english" in row["pending"]:
                        cases.setdefault(row["case_key"], row["target"]["occurrence_id"])
                    if len(cases) == args.review_limit:
                        break
            selected = [targets[key] for key in cases.values()]
        directory.mkdir(parents=True, exist_ok=True)
        packets = [packet_for(retriever, target, args.top_k) for target in selected]
        atomic_jsonl(directory / "retrieval.jsonl", packets)
        if args.review_queue is None:
            write_review_packet(directory / "independent_review_packet.jsonl", packets)
        atomic_jsonl(directory / "model_packets.jsonl", (
            model_review_packet(
                packet["case_key"], packet["target"], packet["senses"],
                korean_candidates=packet.get("korean_candidates", []), usage=packet.get("usage", []),
            ) for packet in packets
        ))
        return {"retrieved_occurrences": len(packets), "directory": str(directory), "input_fingerprint": fingerprint}

    if args.command == "full":
        gate_path = args.pilot_summary or pilot_dir / "summary.json"
        with gate_path.open(encoding="utf-8") as stream:
            gate = json.load(stream)
        if gate["input_fingerprint"] != fingerprint or gate["rules_fingerprint"] != revision():
            raise ValueError("The pilot report applies to a different input or implementation.")
        if not gate.get("pilot_gate_passed") or gate.get("top_k") != args.top_k:
            raise ValueError("The independent 100-occurrence pilot evaluation has not passed.")
    decisions = merge_decisions(args.model_decisions)
    settings = {
        "rules": revision(), "top_k": args.top_k, "decision_digest": digest(decisions),
        "gold_digest": hashlib.sha256(args.gold.read_bytes()).hexdigest() if args.gold else None,
        "module_review_digest": hashlib.sha256(args.module_reviews.read_bytes()).hexdigest() if args.module_reviews else None,
        "archive_digests": [hashlib.sha256(path.read_bytes()).hexdigest() for path in args.archive_observations],
    }
    directory = pilot_dir if args.command == "pilot" else args.output / "full"
    directory.mkdir(parents=True, exist_ok=True)
    run_id = digest([args.command, fingerprint, settings])[:24]
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    connection.execute("INSERT OR IGNORE INTO batch_rag_runs VALUES(?,?,?,?,?,NULL,NULL)",
                       (run_id, args.command, fingerprint, stable_json(settings), utc_now()))
    connection.commit()
    done = {row[0] for row in connection.execute(
        "SELECT occurrence_id FROM batch_rag_occurrences WHERE run_id=?", (run_id,)
    )}
    selected = sample if args.command == "pilot" else sorted(targets.values(), key=priority)
    module_evidence = load_module_evidence(connection)
    attach_module_reviews(module_evidence, load_module_reviews(args.module_reviews))
    archive_refs = load_archive_refs(args.archive_observations, targets)
    packets = []
    for index, target in enumerate(selected, 1):
        occurrence = target["occurrence_id"]
        if occurrence not in done or args.command == "pilot":
            packet = packet_for(retriever, target, args.top_k)
        if occurrence not in done:
            decision = decisions.get(packet["case_key"]) or decisions.get(occurrence)
            if decision:
                decision = {**decision, "case_key": packet["case_key"]}
            _, _, cache_hit = cache_or_decide(connection, run_id, packet, decision, settings["rules"])
            save_occurrence(connection, run_id, packet, module_evidence.get(occurrence, {}),
                            archive_refs.get(occurrence, []), cache_hit)
        if args.command == "pilot":
            packets.append(packet)
        if index % args.checkpoint == 0:
            connection.commit()
    connection.commit()

    results = list(assessment_rows(connection, run_id, targets))
    if len(results) != len(selected):
        raise ValueError("Stored decisions do not cover the complete selected batch.")
    rows = connection.execute("""
        SELECT COALESCE(SUM(retrieval_ms),0) / 1000, COALESCE(SUM(cache_hit),0),
               COUNT(DISTINCT case_key)
        FROM batch_rag_occurrences WHERE run_id=?
    """, (run_id,)).fetchone()
    summary = summarize(results, perf_counter() - started, *rows, len(decisions))
    summary.update(run_id=run_id, input_fingerprint=fingerprint,
                   rules_fingerprint=settings["rules"], top_k=args.top_k)
    if args.command == "pilot" and args.gold:
        by_id = {row["target"]["occurrence_id"]: row for row in results}
        for packet in packets:
            packet["english"] = by_id[packet["target"]["occurrence_id"]]["english"]
        validation = evaluate_sample(packets, gold_path=args.gold, k=min(5, args.top_k))
        summary["pilot_benchmark"] = validation
        summary["pilot_gate_passed"] = pilot_passes(validation)

    atomic_jsonl(directory / "assessments.jsonl", results)
    atomic_jsonl(directory / "review_queue.jsonl", queue_rows(results))
    atomic_json(directory / "summary.json", summary)
    connection.execute("""
        UPDATE batch_rag_runs SET finished_at=?,metrics_json=? WHERE run_id=?
    """, (utc_now(), stable_json(summary), run_id))
    connection.commit()
    return summary


def pilot_passes(report):
    """Require independent review, non-regressing recall, and precise observed positive links."""
    benchmark = report["retrieval"]
    baseline = benchmark["baseline"]["5"]["candidate_recall"]
    ranked = benchmark["reranked"]["5"]["candidate_recall"]
    alignment = report["meaning_link_precision"]
    grade_b = report["grade_B_precision"]
    return (
        report["sample_count"] == report["review_label_count"] == 100
        and baseline["value"] is not None and ranked["value"] is not None
        and ranked["value"] >= baseline["value"]
        and alignment["denominator"] >= 10 and alignment["value"] >= 0.95
        and grade_b["denominator"] >= 5 and grade_b["value"] >= 0.95
        and not report["wrong_cross_sense_groups"]
        and not report["grade_B_predictions_without_decisive_gold"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "pilot", "full"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--checkpoint", type=int, default=100)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--pilot-summary", type=Path)
    parser.add_argument("--model-decisions", type=Path, action="append", default=[])
    parser.add_argument("--module-reviews", type=Path)
    parser.add_argument("--archive-observations", type=Path, action="append", default=[])
    parser.add_argument("--review-queue", type=Path, help="Prepare further packet(s) from the English review queue")
    parser.add_argument("--review-limit", type=int, default=100)
    args = parser.parse_args()
    if args.top_k < 5 or min(args.checkpoint, args.review_limit) < 1:
        parser.error("--top-k must be at least 5 and checkpoint/review limits must be positive")
    if args.review_queue and args.command != "prepare":
        parser.error("--review-queue applies only to prepare")
    mode = "ro" if args.command == "prepare" else "rw"
    uri = args.db.resolve().as_uri() + f"?mode={mode}"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        result = run(connection, args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
