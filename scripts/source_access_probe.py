#!/usr/bin/env python3
"""Check dictionary access, robots rules and definition markers without keeping page text.

Each source is checked with a few headwords. The probe records the HTTP status, whether
robots.txt allows the page for this project's agent and for Anthropic's published agent
tokens, and whether a definition marker occurs in the response. Response bodies are
discarded after the marker count. Access and permission to store or collect are recorded
separately: an ``available`` page does not grant automated collection rights.
"""

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "ToeicnetSourceProbe/1.0 (+dictionary access check; Claude Code)"
# Robots rules are honored for every token that could describe this agent, not just its UA string.
AGENT_TOKENS = ("ToeicnetSourceProbe", "Claude-User", "ClaudeBot", "Claude-SearchBot", "Claude-Web", "anthropic-ai")
PROBE_HEADWORDS = ("apply", "requirement", "acquire", "contingent", "employment")
STATUSES = (
    "available", "forbidden", "robots_denied", "rate_limited", "authentication_required",
    "license_required", "timeout", "parsing_failed", "unavailable",
)
# A status in this set stops further requests to the same source.
STOPPING = frozenset({"forbidden", "robots_denied", "authentication_required", "license_required"})
CHALLENGE_MARKERS = ("Just a moment...", "cf-challenge", "captcha", "g-recaptcha", "Attention Required!")
RETRYABLE = frozenset({429, 500, 502, 503, 504})

TARGETS = {
    "collins": {
        "commercial_web": True,
        "base": "https://www.collinsdictionary.com", "entry": "/dictionary/english/{word}",
        "markers": ('class="def"',), "license_status": "license_required",
        "license_note": "Site terms; Collins API requires registration and separate terms.",
    },
    "merriam_webster": {
        "commercial_web": True,
        "base": "https://www.merriam-webster.com", "entry": "/dictionary/{word}",
        "markers": ("dtText",), "license_status": "license_required",
        "license_note": "Site terms; Dictionary API (dictionaryapi.com) requires a key and its own terms.",
    },
    "merriam_webster_api": {
        "base": "https://dictionaryapi.com", "entry": "/api/v3/references/collegiate/json/{word}",
        "markers": ('"shortdef"',), "auth_markers": ("Key is required", "Invalid API key"),
        "license_status": "license_required", "provider_group": "merriam_webster",
        "license_note": "Terms read 2026-11-27: non-commercial only, 1000 queries/day per reference, at most two references; section 5(a) bars automated or recorded queries without written approval and 5(i) bars comparison with third-party products, so batch verification needs written approval.",
    },
    "etymonline": {
        "base": "https://www.etymonline.com", "entry": "/word/{word}",
        "markers": ("etymology",), "license_status": "license_required",
        "license_note": "No public dump or API confirmed; bulk storage rights unconfirmed.",
    },
    "cambridge": {
        "commercial_web": True,
        "base": "https://dictionary.cambridge.org", "entry": "/dictionary/english/{word}",
        "markers": ("ddef_d",), "license_status": "license_required",
        "license_note": "Commercial; data licensing via dictionary.cambridge.org/license.html.",
    },
    "oxford": {
        "commercial_web": True,
        "base": "https://www.oxfordlearnersdictionaries.com", "entry": "/definition/english/{word}",
        "markers": ('class="def"',), "license_status": "license_required",
        "license_note": "Commercial; Oxford Languages API is a separate licence.",
    },
    "longman": {
        "commercial_web": True,
        "base": "https://www.ldoceonline.com", "entry": "/dictionary/{word}",
        "markers": ('class="DEF"',), "license_status": "license_required",
        "license_note": "Commercial; no public API or dump confirmed.",
    },
    "britannica": {
        "commercial_web": True,
        "base": "https://www.britannica.com", "entry": "/dictionary/{word}",
        "markers": ("dtText", 'class="def'), "license_status": "license_required",
        "provider_group": "merriam_webster",
        "license_note": "Shares the Merriam-Webster learner data lineage; not an independent source.",
    },
    "naver_dict": {
        "commercial_web": True,
        "base": "https://en.dict.naver.com", "entry": "/#/search?query={word}",
        "markers": (), "license_status": "license_required", "platform": True,
        "license_note": "Platform that redistributes other publishers' dictionaries; count the named provider, not Naver.",
    },
}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def robots_decision(lines, url, tokens=AGENT_TOKENS):
    """Return (allowed, denied_tokens). Any denied token blocks the request."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(lines)
    denied = [token for token in tokens if not parser.can_fetch(token, url)]
    return not denied, denied


def classify(status=None, *, body="", markers=(), auth_markers=(), error=None):
    """Map one response or transport error to a registry status and a short reason."""
    if error == "proxy_denied":
        return "unavailable", "environment network policy refused the connection"
    if error == "timeout":
        return "timeout", "no response within the timeout"
    if error:
        return "unavailable", error
    if any(marker in body for marker in auth_markers):
        return "authentication_required", "service requires an API key"
    if status in (401, 407):
        return "authentication_required", f"HTTP {status}"
    if status == 402:
        return "license_required", "HTTP 402"
    has_definition = bool(markers) and any(marker in body for marker in markers)
    # A served entry page may embed a CAPTCHA widget elsewhere; only a page without the entry is a challenge.
    if not (status == 200 and has_definition) and any(
        marker.lower() in body.lower() for marker in CHALLENGE_MARKERS
    ):
        return "forbidden", f"HTTP {status} with a browser or CAPTCHA challenge"
    if status == 403:
        return "forbidden", "HTTP 403"
    if status == 429:
        return "rate_limited", "HTTP 429"
    if status is None or status >= 400:
        return "unavailable", f"HTTP {status}"
    if not markers:
        return "parsing_failed", "no static definition marker is defined for this page"
    if has_definition:
        return "available", "definition marker present"
    return "parsing_failed", "definition marker absent"


def _fetch(url, timeout):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), dict(response.headers), None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), dict(error.headers or {}), None
    except TimeoutError:
        return None, "", {}, "timeout"
    except urllib.error.URLError as error:
        reason = str(error.reason)
        if "timed out" in reason:
            return None, "", {}, "timeout"
        if "Tunnel connection failed: 403" in reason or "407" in reason:
            return None, "", {}, "proxy_denied"
        return None, "", {}, f"transport error: {type(error.reason).__name__}"


def fetch_with_backoff(url, *, timeout=25, retries=2, base_delay=2.0, sleep=time.sleep, fetch=_fetch):
    """Retry only HTTP 429 and transient 5xx, with exponential backoff and a capped Retry-After."""
    attempts = 0
    while True:
        attempts += 1
        status, body, headers, error = fetch(url, timeout)
        if error or status not in RETRYABLE or attempts > retries:
            return status, body, error, attempts
        delay = base_delay * (2 ** (attempts - 1))
        retry_after = (headers or {}).get("Retry-After")
        if retry_after and str(retry_after).isdigit():
            delay = max(delay, min(float(retry_after), 30.0))
        sleep(delay)


def probe_source(source_id, target, headwords=PROBE_HEADWORDS, *, delay=3.0, sleep=time.sleep, fetch=_fetch):
    checked_at = now()
    robots_url = target["base"] + "/robots.txt"
    robots_status, robots_body, robots_error, _ = fetch_with_backoff(robots_url, sleep=sleep, fetch=fetch)
    checks = []
    if robots_error:
        status, reason = classify(error=robots_error)
        return _summary(source_id, target, checked_at, robots_status, [], status, reason)
    # RFC 9309: unreachable 5xx robots means disallow; 4xx means no restriction.
    robots_lines = robots_body.splitlines() if robots_status and robots_status < 400 else []
    if robots_status and robots_status >= 500:
        return _summary(source_id, target, checked_at, robots_status, [], "unavailable", "robots.txt unreachable (5xx)")
    sleep(delay)
    for word in headwords:
        url = target["base"] + target["entry"].format(word=word)
        allowed, denied = robots_decision(robots_lines, url)
        if not allowed:
            checks.append({"headword": word, "url": url, "status": "robots_denied", "http_status": None,
                           "reason": "robots.txt disallows " + ", ".join(denied), "attempts": 0})
            break
        http_status, body, error, attempts = fetch_with_backoff(url, sleep=sleep, fetch=fetch)
        status, reason = classify(http_status, body=body, markers=target.get("markers", ()),
                                  auth_markers=target.get("auth_markers", ()), error=error)
        marker_hits = sum(body.count(marker) for marker in target.get("markers", ())) if body else 0
        del body
        checks.append({"headword": word, "url": url, "status": status, "http_status": http_status,
                       "reason": reason, "attempts": attempts, "definition_marker_hits": marker_hits})
        if status in STOPPING:
            break
        sleep(delay)
    status, reason = aggregate(checks)
    return _summary(source_id, target, checked_at, robots_status, checks, status, reason)


def aggregate(checks):
    """A stopping status dominates; otherwise any extractable page makes the source available."""
    if not checks:
        return "unavailable", "no page checked"
    for check in checks:
        if check["status"] in STOPPING:
            return check["status"], check["reason"]
    available = sum(check["status"] == "available" for check in checks)
    if available:
        return "available", f"definition marker present for {available}/{len(checks)} headwords"
    counts = {}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    status = max(counts, key=lambda key: (counts[key], -STATUSES.index(key)))
    return status, next(check["reason"] for check in checks if check["status"] == status)


def _summary(source_id, target, checked_at, robots_status, checks, status, reason):
    assert status in STATUSES, status
    return {
        "source_id": source_id, "checked_at": checked_at, "base_url": target["base"],
        "robots_http_status": robots_status, "access_status": status, "access_reason": reason,
        "license_status": target["license_status"], "license_note": target["license_note"],
        # Access never implies permission: automated collection stays off without a licence.
        "automated_collection_allowed": False, "content_stored": False,
        # A platform or a second outlet of the same data never counts as a separate source.
        "independent_source": not target.get("platform", False) and target.get("provider_group", source_id) == source_id,
        "provider_group": target.get("provider_group", source_id),
        "checks": checks,
    }


REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS source_access_checks (
    source_id TEXT NOT NULL, checked_at TEXT NOT NULL,
    access_status TEXT NOT NULL CHECK(access_status IN ({statuses})),
    access_reason TEXT NOT NULL, license_status TEXT NOT NULL,
    automated_collection_allowed INTEGER NOT NULL CHECK(automated_collection_allowed IN (0,1)),
    independent_source INTEGER NOT NULL CHECK(independent_source IN (0,1)),
    provider_group TEXT NOT NULL, checks_json TEXT NOT NULL CHECK(json_valid(checks_json)),
    PRIMARY KEY(source_id, checked_at)
) STRICT;
CREATE VIEW IF NOT EXISTS source_access_current AS
SELECT * FROM source_access_checks AS latest
WHERE checked_at = (SELECT max(checked_at) FROM source_access_checks WHERE source_id = latest.source_id);
""".format(statuses=",".join(f"'{status}'" for status in STATUSES))


def write_registry(db_path, rows):
    with sqlite3.connect(db_path) as db:
        db.executescript(REGISTRY_DDL)
        db.executemany(
            "INSERT OR REPLACE INTO source_access_checks VALUES (?,?,?,?,?,?,?,?,?)",
            [(row["source_id"], row["checked_at"], row["access_status"], row["access_reason"],
              row["license_status"], int(row["automated_collection_allowed"]), int(row["independent_source"]),
              row["provider_group"], json.dumps(row["checks"], ensure_ascii=False)) for row in rows],
        )


def markdown(rows):
    lines = [
        "# 사전 접근성 점검", "",
        f"점검 시각(UTC): {min(row['checked_at'] for row in rows)} – {max(row['checked_at'] for row in rows)}. "
        f"표제어: {', '.join(PROBE_HEADWORDS)}. 응답 본문은 정의 표지 계수 후 폐기했고 저장하지 않았다.", "",
        "| 출처 | 접근 상태 | 근거 | robots.txt | 확인 표제어 | 이용 권한 | 자동 수집 | 별도 출처로 계산 · 계보 |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        words = ", ".join(f"{check['headword']}:{check['status']}" for check in row["checks"]) or "–"
        lines.append(
            f"| {row['source_id']} | `{row['access_status']}` | {row['access_reason']} | "
            f"{row['robots_http_status'] or '–'} | {words} | `{row['license_status']}` | "
            f"{'허용' if row['automated_collection_allowed'] else '중단'} | "
            f"{'예' if row['independent_source'] else '아니요'} · {row['provider_group']} |"
        )
    lines += ["", "이용 권한은 접근 상태와 별도로 판단했다. " + " ".join(
        f"{row['source_id']}: {row['license_note']}" for row in rows)]
    return "\n".join(lines) + "\n"


def plan(requested, previous, *, allow_commercial_web=False, recheck_blocked=False):
    """Choose sources to request. Commercial web pages and recorded blocks are never re-requested by default."""
    selected, carried = [], []
    for source in requested:
        target, last = TARGETS[source], previous.get(source)
        if target.get("commercial_web") and not allow_commercial_web:
            if last:
                carried.append(last)
            continue
        if last and last["access_status"] in STOPPING and not recheck_blocked:
            carried.append(last)
            continue
        selected.append(source)
    return selected, carried


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=sorted(TARGETS))
    parser.add_argument("--allow-commercial-web", action="store_true",
                        help="Also request commercial dictionary web pages (excluded from the required pipeline)")
    parser.add_argument("--recheck-blocked", action="store_true",
                        help="Request a source again although its last status was forbidden, robots_denied or auth")
    parser.add_argument("--from-json", action="store_true",
                        help="Send no request; load the recorded results (e.g. into --db)")
    parser.add_argument("--headword", action="append")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--json", type=Path, default=ROOT / "reports/source_access.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "reports/source_access.md")
    parser.add_argument("--db", type=Path, help="Optional SQLite DB receiving source_access_checks rows")
    args = parser.parse_args(argv)
    previous = {}
    if args.json.exists():
        previous = {row["source_id"]: row for row in json.loads(args.json.read_text(encoding="utf-8"))["sources"]}
    requested = args.source or list(TARGETS)
    if args.from_json:
        selected, carried = [], [previous[source] for source in requested if source in previous]
    else:
        selected, carried = plan(requested, previous, allow_commercial_web=args.allow_commercial_web,
                                 recheck_blocked=args.recheck_blocked)
    fresh = {source: probe_source(source, TARGETS[source], tuple(args.headword or PROBE_HEADWORDS), delay=args.delay)
             for source in selected}
    merged = {**previous, **{row["source_id"]: row for row in carried}, **fresh}
    rows = [merged[source] for source in TARGETS if source in merged]
    args.json.write_text(json.dumps({"user_agent": USER_AGENT, "agent_tokens": AGENT_TOKENS, "sources": rows},
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(rows), encoding="utf-8")
    if args.db:
        write_registry(args.db, rows)
    for row in rows:
        state = "checked" if row["source_id"] in fresh else "recorded"
        print(f"{row['source_id']}: {row['access_status']} ({row['access_reason']}; {state})")


if __name__ == "__main__":
    main()
