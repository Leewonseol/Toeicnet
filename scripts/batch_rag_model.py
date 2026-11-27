"""Run a caller-supplied local model command against bounded review packets."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
from itertools import islice
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryFile

from batch_rag_verify import MODEL_REVIEW_INSTRUCTIONS, _validate_model_judgment, load_model_decisions
from intake_common import read_jsonl, sha256_file, write_json
from review_common import write_jsonl


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected an integer of at least 1")
    return number


def nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("expected an integer of at least 0")
    return number


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected positive finite seconds")
    return number


def packet_indexes(path, limit):
    packets = {}
    candidate_ids = {}
    for packet in islice(read_jsonl(path), limit):
        key = packet.get("case_key")
        if not isinstance(key, str) or not key.strip() or key in packets:
            raise ValueError("Packets require distinct, nonempty case_key values")
        candidates = packet.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"Case {key} requires a candidates list")
        ids = set()
        for candidate in candidates:
            cid = candidate.get("candidate_id") if isinstance(candidate, dict) else None
            if not isinstance(cid, str) or not cid.strip() or cid in ids:
                raise ValueError(f"Case {key} requires distinct, nonempty candidate IDs")
            ids.add(cid)
        packets[key] = packet
        candidate_ids[key] = ids
    if not packets:
        raise ValueError("No model review packets found")
    return packets, candidate_ids


def validate_decisions(rows, expected_ids, *, complete):
    if not isinstance(rows, list):
        raise ValueError("Model command must return a JSON list of decisions")
    decisions = {}
    for raw in rows:
        decision = _validate_model_judgment(raw)
        key = decision["case_key"]
        if key not in expected_ids or key in decisions:
            raise ValueError("Model decision has an unexpected or repeated case_key")
        if not set(decision["candidate_ids"]) <= expected_ids[key]:
            raise ValueError(f"Case {key} cites a candidate from outside its packet")
        if decision.get("korean") is not None:
            raise ValueError(f"Case {key} includes a Korean judgment outside the model task")
        decisions[key] = decision
    if complete and decisions.keys() != expected_ids.keys():
        raise ValueError("Model command must return one decision for every requested case")
    return decisions


def checkpoint_state(packets_path):
    return {
        "schema_version": 1,
        "packets_sha256": sha256_file(packets_path),
        "instructions_sha256": hashlib.sha256(MODEL_REVIEW_INSTRUCTIONS.encode("utf-8")).hexdigest(),
    }


@contextmanager
def exclusively(lock_path):
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def load_checkpoint(output_path, state_path, expected, candidate_ids, resume):
    if not resume:
        if output_path.exists() or state_path.exists():
            raise ValueError("The output or checkpoint already exists. Use --resume to continue it.")
        write_json(state_path, expected)
        return {}
    if not state_path.is_file():
        raise ValueError("No adapter checkpoint. Choose a fresh output path to start.")
    with state_path.open(encoding="utf-8") as state:
        if json.load(state) != expected:
            raise ValueError("The packet file or review instructions changed since the checkpoint")
    if not output_path.exists():
        return {}
    previous = load_model_decisions(output_path)
    return validate_decisions(list(previous.values()), candidate_ids, complete=False)


def model_response(command, request, timeout, max_response_bytes):
    with TemporaryFile() as stdout:
        result = subprocess.run(
            command, input=request, stdout=stdout, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False, shell=False,
        )
        if result.returncode:
            raise ValueError(f"Local command exited with code {result.returncode}")
        if stdout.tell() > max_response_bytes:
            raise ValueError("Local command exceeded the response byte limit")
        stdout.seek(0)
        try:
            return json.load(stdout)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Local command did not return valid JSON") from error


def run_batches(args, packets, candidate_ids, completed):
    attempts = 0
    sent_bytes = 0
    previous_count = len(completed)
    remaining = [key for key in packets if key not in completed]
    for start in range(0, len(remaining), args.batch_size):
        keys = remaining[start:start + args.batch_size]
        request = json.dumps({
            "instructions": MODEL_REVIEW_INSTRUCTIONS,
            "cases": [packets[key] for key in keys],
        }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(request) > args.max_request_bytes:
            raise ValueError(f"Batch exceeds the request byte limit at {len(completed)} saved cases. Use a smaller --batch-size.")
        expected = {key: candidate_ids[key] for key in keys}
        for attempt in range(args.retries + 1):
            if attempts >= args.max_calls:
                raise ValueError(f"Call limit reached at {len(completed)} saved cases after {attempts} calls.")
            if args.max_total_request_bytes is not None and sent_bytes + len(request) > args.max_total_request_bytes:
                raise ValueError(f"Total request byte limit reached at {len(completed)} saved cases.")
            attempts += 1
            sent_bytes += len(request)
            try:
                rows = model_response(args.command, request, args.timeout, args.max_response_bytes)
                validated = validate_decisions(rows, expected, complete=True)
            except (ValueError, subprocess.TimeoutExpired) as error:
                if attempt == args.retries:
                    if isinstance(error, subprocess.TimeoutExpired):
                        error = "Local command timed out"
                    raise ValueError(f"Batch failed after {attempt + 1} call(s), {len(completed)} cases saved. {error}") from None
            else:
                completed.update(validated)
                write_jsonl(args.output, (completed[key] for key in packets if key in completed))
                break
    return {
        "cases_selected": len(packets), "cases_resumed": previous_count,
        "cases_completed": len(completed), "command_calls": attempts, "request_bytes": sent_bytes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True, help="Input model_packets.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="Validated decisions JSONL")
    parser.add_argument("--max-cases", type=positive_int, required=True, help="Limit selected cases to this input prefix")
    parser.add_argument("--max-calls", type=positive_int, required=True, help="Per-invocation limit including retries")
    parser.add_argument("--batch-size", type=positive_int, default=8)
    parser.add_argument("--timeout", type=positive_seconds, default=60, help="Seconds per local command")
    parser.add_argument("--retries", type=nonnegative_int, default=1, help="Retries per unsuccessful batch")
    parser.add_argument("--max-request-bytes", type=positive_int, default=2_000_000)
    parser.add_argument("--max-response-bytes", type=positive_int, default=2_000_000)
    parser.add_argument("--max-total-request-bytes", type=positive_int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--command", required=True, nargs=argparse.REMAINDER, help="Pass the local command argv last")
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command or not args.command[0].strip():
        parser.error("--command requires an executable and optional arguments")

    state_path = args.output.with_name(args.output.name + ".checkpoint.json")
    lock_path = args.output.with_name(args.output.name + ".lock")
    if len({path.resolve() for path in (args.packets, args.output, state_path, lock_path)}) != 4:
        parser.error("Packet, output and checkpoint paths must be distinct")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with exclusively(lock_path):
            state = checkpoint_state(args.packets)
            packets, candidate_ids = packet_indexes(args.packets, args.max_cases)
            completed = load_checkpoint(args.output, state_path, state, candidate_ids, args.resume)
            results = run_batches(args, packets, candidate_ids, completed)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
