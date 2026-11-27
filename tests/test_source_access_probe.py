import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import source_access_probe as probe


TARGET = {"base": "https://dict.example", "entry": "/word/{word}", "markers": ('class="def"',),
          "license_status": "license_required", "license_note": "test"}


class FakeSite:
    def __init__(self, robots, pages):
        self.robots, self.pages, self.requests = robots, pages, []

    def __call__(self, url, timeout):
        self.requests.append(url)
        if url.endswith("/robots.txt"):
            return 200, self.robots, {}, None
        response = self.pages[url.rsplit("/", 1)[1]]
        return response.pop(0) if isinstance(response, list) else response


class SourceAccessProbeTest(unittest.TestCase):
    def test_classification_separates_access_failures(self):
        self.assertEqual(probe.classify(200, body='<p class="def">x</p>', markers=('class="def"',))[0], "available")
        self.assertEqual(probe.classify(200, body="<p>x</p>", markers=('class="def"',))[0], "parsing_failed")
        self.assertEqual(probe.classify(403, body="Just a moment...")[0], "forbidden")
        self.assertEqual(probe.classify(200, body="please solve the captcha", markers=('class="def"',))[0], "forbidden")
        # An entry page that embeds a CAPTCHA widget elsewhere is still served content.
        self.assertEqual(probe.classify(200, body='recaptcha <p class="def">x</p>', markers=('class="def"',))[0],
                         "available")
        self.assertEqual(probe.classify(200, body="Key is required.", auth_markers=("Key is required",))[0],
                         "authentication_required")
        self.assertEqual(probe.classify(429)[0], "rate_limited")
        self.assertEqual(probe.classify(error="timeout")[0], "timeout")
        self.assertEqual(probe.classify(error="proxy_denied")[0], "unavailable")

    def test_any_anthropic_token_denied_blocks_the_request(self):
        site = FakeSite("User-agent: ClaudeBot\nDisallow: /\n", {})
        row = probe.probe_source("x", TARGET, ("apply", "acquire"), sleep=lambda _: None, fetch=site)
        self.assertEqual(row["access_status"], "robots_denied")
        self.assertEqual(site.requests, ["https://dict.example/robots.txt"])
        self.assertFalse(row["automated_collection_allowed"])

    def test_forbidden_stops_without_retry(self):
        site = FakeSite("", {"apply": (403, "", {}, None), "acquire": (200, 'class="def"', {}, None)})
        row = probe.probe_source("x", TARGET, ("apply", "acquire"), sleep=lambda _: None, fetch=site)
        self.assertEqual(row["access_status"], "forbidden")
        self.assertEqual(len(site.requests), 2)
        self.assertEqual(row["checks"][0]["attempts"], 1)

    def test_rate_limit_retries_with_capped_backoff(self):
        delays = []
        site = FakeSite("", {"apply": [(429, "", {"Retry-After": "120"}, None), (200, 'class="def"', {}, None)]})
        row = probe.probe_source("x", TARGET, ("apply",), delay=0, sleep=delays.append, fetch=site)
        self.assertEqual(row["access_status"], "available")
        self.assertEqual(row["checks"][0]["attempts"], 2)
        self.assertIn(30.0, delays)

    def test_registry_keeps_access_and_licence_apart(self):
        site = FakeSite("", {"apply": (200, 'class="def"', {}, None)})
        row = probe.probe_source("x", {**TARGET, "provider_group": "y"}, ("apply",), sleep=lambda _: None, fetch=site)
        self.assertEqual((row["access_status"], row["license_status"]), ("available", "license_required"))
        self.assertFalse(row["independent_source"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "t.db"
            probe.write_registry(path, [row])
            with sqlite3.connect(path) as db:
                stored = db.execute("SELECT access_status, checks_json FROM source_access_current").fetchone()
        self.assertEqual(stored[0], "available")
        self.assertNotIn("class=", json.loads(stored[1])[0]["reason"])


if __name__ == "__main__":
    unittest.main()
