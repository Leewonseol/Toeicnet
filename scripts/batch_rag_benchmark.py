"""Reproducible occurrence sampling and evidence-labelled retrieval evaluation."""

from collections import Counter, defaultdict
import hashlib

from review_common import jsonl_records, write_jsonl


CORE_SOURCE = "hackers_anki_user"
BACK_SOURCE = "hackers_back"
STRATUM_WEIGHTS = {
    "existing_A_control": 20,
    "few_open_candidates": 15,
    "many_open_candidates": 45,
    "no_exact_open_candidate": 20,
}


def sample_stratum(row):
    if row.get("learner_cross_verified_senses"):
        return "existing_A_control"
    count = sum(row.get("open_sense_candidates", {}).values())
    if count == 0:
        return "no_exact_open_candidate"
    if count <= 2:
        return "few_open_candidates"
    return "many_open_candidates"


def _sample_key(row):
    key = f"toeic-batch-rag-benchmark-v1:{row['occurrence_id']}"
    return hashlib.sha256(key.encode()).hexdigest()


def select_sample(rows, size=100):
    """Take a reproducible, deliberately enriched sample from both sources."""
    if size < 1:
        raise ValueError("sample size must be positive")
    groups = defaultdict(list)
    for row in rows:
        groups[sample_stratum(row)].append(row)
    for group in groups.values():
        group.sort(key=_sample_key)

    selected = []
    seen = set()

    def add(row):
        identifier = row["occurrence_id"]
        if identifier not in seen:
            selected.append(row)
            seen.add(identifier)

    for stratum, weight in STRATUM_WEIGHTS.items():
        group = groups[stratum]
        quota = size * weight // 100
        start = len(selected)
        for source in (CORE_SOURCE, BACK_SOURCE):
            limit = (quota // 2) if source == CORE_SOURCE else (quota - quota // 2)
            source_rows = (row for row in group if row["source_id"] == source)
            for index, row in enumerate(source_rows):
                if index >= limit:
                    break
                add(row)
        for row in group:
            if len(selected) - start >= quota:
                break
            add(row)

    for row in sorted((row for group in groups.values() for row in group), key=_sample_key):
        if len(selected) >= size:
            break
        add(row)
    return selected


def _candidate_key(candidate):
    if isinstance(candidate, str):
        return candidate
    return candidate.get("candidate_id") or candidate.get("evidence_ref")


def _candidate_ids(candidates):
    return list(dict.fromkeys(key for candidate in candidates if (key := _candidate_key(candidate))))


def write_review_packet(path, packets):
    """Write local evidence for an independent reviewer without model grades or ranks."""
    def rows():
        for packet in packets:
            target = packet["target"]
            candidates = {}
            for channel in ("senses", "baseline_senses", "evaluation_senses"):
                for candidate in packet.get(channel, ()):
                    identifier = _candidate_key(candidate)
                    if not identifier:
                        continue
                    payload = candidate.get("payload") or {}
                    fields = (
                        "headword", "source_id", "independence_group", "source_record_id", "url", "version",
                        "part_of_speech", "definition", "tags", "qualifiers", "match_basis",
                    )
                    candidates[identifier] = {
                        **{field: candidate.get(field) or payload.get(field) for field in fields},
                        "candidate_id": identifier,
                    }
            yield {
                "occurrence_id": target["occurrence_id"],
                "headword": target["headword"],
                "part_of_speech": target.get("part_of_speech"),
                "original_korean_meaning": target.get("original_korean_meaning"),
                "stratum": sample_stratum(target),
                "candidates": [candidates[key] for key in sorted(candidates)],
            }

    return write_jsonl(path, rows())


def _load_gold(path):
    gold = {}
    for location, row in jsonl_records([path]):
        occurrence_id = row.get("occurrence_id")
        matches = row.get("matches", [])
        nonmatches = row.get("nonmatches", [])
        if not isinstance(occurrence_id, str) or not occurrence_id or occurrence_id in gold:
            raise ValueError(f"{location}: expected a unique occurrence_id")
        for name, candidates in (("matches", matches), ("nonmatches", nonmatches)):
            if not isinstance(candidates, list) or not all(isinstance(item, str) and item for item in candidates):
                raise ValueError(f"{location}: {name} must be a list of candidate IDs")
            if len(candidates) != len(set(candidates)):
                raise ValueError(f"{location}: {name} contains duplicated IDs")
        if set(matches) & set(nonmatches):
            raise ValueError(f"{location}: an evidence ID has conflicting labels")
        groups = row.get("sense_groups", [])
        if not isinstance(groups, list) or not all(
            isinstance(group, list) and all(isinstance(item, str) for item in group)
            and group and set(group) <= set(matches) for group in groups
        ):
            raise ValueError(f"{location}: sense_groups must contain lists of matching IDs")
        if row.get("expected_grade") not in (None, "A", "B", "C", "D", "E"):
            raise ValueError(f"{location}: expected_grade must be A–E or null")
        if not isinstance(row.get("reviewer"), str) or not row["reviewer"].strip():
            raise ValueError(f"{location}: reviewer is required")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError(f"{location}: reason is required")
        gold[occurrence_id] = row
    return gold


def _ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _recall(packets, gold, channel, cutoffs):
    results = {}
    for cutoff in cutoffs:
        found = relevant = hits = queries = 0
        for packet in packets:
            label = gold.get(packet["target"]["occurrence_id"], {})
            matches = set(label.get("matches", []))
            if not matches:
                continue
            queries += 1
            ranking = _candidate_ids(packet.get(channel, ()))[:cutoff]
            retrieved = len(matches.intersection(ranking))
            relevant += len(matches)
            found += retrieved
            hits += bool(retrieved)
        results[str(cutoff)] = {
            "candidate_recall": _ratio(found, relevant),
            "query_hit_rate": _ratio(hits, queries),
        }
    return results


def evaluate_sample(packets, gold_path=None, k=5):
    """Score only observed labels and leave unsupported metrics explicitly undefined."""
    if k < 1:
        raise ValueError("k must be positive")
    packets = list(packets)
    gold = _load_gold(gold_path) if gold_path else {}
    packet_ids = {packet["target"]["occurrence_id"] for packet in packets}
    if len(packet_ids) != len(packets):
        raise ValueError("sample packets must have distinct occurrence IDs")
    unknown = set(gold) - packet_ids
    if unknown:
        raise ValueError(f"gold file contains {len(unknown)} occurrences outside the sample")

    agreed_grades = labelled_grades = confirmed = incorrect = unlabelled = 0
    strict_b = reviewed_b = undecided_b = 0
    predicted_grades = Counter()
    grade_predictions_by_source = defaultdict(Counter)
    wrong_links = []
    wrong_cross_sense_groups = []
    for packet in packets:
        target = packet["target"]
        occurrence_id = target["occurrence_id"]
        decision = packet.get("english", {})
        grade = decision.get("grade")
        predicted_grades[grade or "unclassified"] += 1
        grade_predictions_by_source[target["source_id"]][grade or "unclassified"] += 1
        label = gold.get(occurrence_id, {})
        expected = label.get("expected_grade")
        if expected and grade in {"A", "B", "C", "D", "E"}:
            labelled_grades += 1
            agreed_grades += grade == expected
        matches = set(label.get("matches", []))
        nonmatches = set(label.get("nonmatches", []))
        ids = set(_candidate_ids(decision.get("candidate_ids", ()))) if grade in {"A", "B", "C"} else set()
        confirmed += len(ids & matches)
        incorrect += len(ids & nonmatches)
        unlabelled += len(ids - matches - nonmatches)
        for candidate_id in sorted(ids & nonmatches):
            wrong_links.append({"occurrence_id": occurrence_id, "candidate_id": candidate_id})
        if grade != "B":
            continue
        groups = [set(group) for group in label.get("sense_groups", [])]
        same_sense = any(ids <= group for group in groups) if groups else ids <= matches
        inappropriate_group = bool(groups and ids and ids <= matches and not same_sense)
        if inappropriate_group:
            wrong_cross_sense_groups.append({"occurrence_id": occurrence_id, "candidate_ids": sorted(ids)})
        if (expected and expected != "B") or ids & nonmatches or inappropriate_group:
            reviewed_b += 1
        elif expected == "B" and ids and same_sense:
            strict_b += 1
            reviewed_b += 1
        else:
            undecided_b += 1

    cutoffs = sorted({1, min(3, k), k})
    return {
        "sample_count": len(packets),
        "sampling_strata": dict(Counter(sample_stratum(packet["target"]) for packet in packets)),
        "review_label_count": len(gold),
        "reviewers": dict(Counter(row["reviewer"] for row in gold.values())),
        "gold_grade_distribution": dict(Counter(row.get("expected_grade") or "unresolved" for row in gold.values())),
        "gold_meaning_links": {
            "matching": sum(len(row.get("matches", [])) for row in gold.values()),
            "nonmatching": sum(len(row.get("nonmatches", [])) for row in gold.values()),
        },
        "retrieval": {
            "measurement_scope": "explicitly labelled relevant candidates, not exhaustive dictionary recall",
            "baseline": _recall(packets, gold, "baseline_senses", cutoffs),
            "reranked": _recall(packets, gold, "senses", cutoffs),
        },
        "english_grade_distribution": dict(predicted_grades),
        "english_grade_by_occurrence_source": {
            source: dict(counts) for source, counts in sorted(grade_predictions_by_source.items())
        },
        "grade_agreement": _ratio(agreed_grades, labelled_grades),
        "meaning_link_precision": _ratio(confirmed, confirmed + incorrect),
        "wrong_meaning_links": wrong_links,
        "wrong_cross_sense_groups": wrong_cross_sense_groups,
        "unlabelled_predicted_meaning_links": unlabelled,
        "grade_B_precision": _ratio(strict_b, reviewed_b),
        "grade_B_predictions_without_decisive_gold": undecided_b,
    }
