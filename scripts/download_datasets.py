"""Download licensed datasets and record their exact local artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import yaml

from external_records import atomic_output

CHUNK_SIZE = 1024 * 1024
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def checksum(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def dataset_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict) or not isinstance(config.get("sources"), dict):
        raise ValueError(f"{path}: expected a sources mapping")
    return config["sources"]


def fetch(url: str, partial: Path, expected: str | None) -> dict:
    # An interrupted range from a prior revision can only be adopted after a pinned hash check.
    previous = partial.stat().st_size if expected and partial.exists() else 0
    headers = {"User-Agent": "toeic-etymology/1.0 (licensed dataset download)"}
    if previous:
        headers["Range"] = f"bytes={previous}-"

    with urlopen(Request(url, headers=headers), timeout=60) as response:
        accept_range = response.status == 206
        if accept_range and (
            not previous or not response.headers.get("Content-Range", "").startswith(f"bytes {previous}-")
        ):
            raise ValueError("Server returned an unexpected Content-Range")
        with partial.open("ab" if accept_range else "wb") as handle:
            shutil.copyfileobj(response, handle, CHUNK_SIZE)
        return {
            "resolved_url": response.geturl(),
            "http_etag": response.headers.get("ETag"),
            "http_last_modified": response.headers.get("Last-Modified"),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }


def download(source_id: str, config: dict, directory: Path, previous: dict | None) -> dict:
    if config.get("download_allowed") is not True:
        raise ValueError(f"{source_id}: automated download permission is not recorded")
    url = config["download_url"]
    if urlparse(url).scheme != "https":
        raise ValueError(f"{source_id}: expected an HTTPS download URL")
    filename = config.get("filename") or Path(unquote(urlparse(url).path)).name
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError(f"{source_id}: unsafe dataset filename")
    version = str(config["version"])
    license_id = config["license"]
    if not version or not license_id:
        raise ValueError(f"{source_id}: version and license are required")
    expected = config.get("sha256")
    if expected:
        if not SHA256.fullmatch(expected):
            raise ValueError(f"{source_id}: invalid configured SHA-256")
        expected = expected.lower()

    path = directory / filename
    partial = directory / (filename + ".part")
    details: dict = {}
    if path.is_file():
        digest = checksum(path)
        if previous and previous.get("sha256") == digest and previous.get("version") == version:
            details = {
                key: previous.get(key)
                for key in ("resolved_url", "http_etag", "http_last_modified", "downloaded_at")
            }
        elif expected != digest:
            raise ValueError(f"{source_id}: existing file has no matching configured or locked checksum")
    else:
        if partial.exists() and expected and checksum(partial) == expected:
            digest = expected
        else:
            details = fetch(url, partial, expected)
            digest = checksum(partial)
        if expected is not None and digest != expected:
            partial.unlink(missing_ok=True)
            raise ValueError(f"{source_id}: downloaded file did not match the configured SHA-256")
        partial.replace(path)
    if expected is not None and digest != expected:
        raise ValueError(f"{source_id}: existing file did not match the configured SHA-256")

    return {
        "source_id": source_id,
        "version": version,
        "license": license_id,
        "url": url,
        "filename": filename,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        **details,
        "downloaded_at": details.get("downloaded_at") or config.get("downloaded_at"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_ids", nargs="*")
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--directory", type=Path, default=Path("data/external"))
    parser.add_argument("--lock", type=Path, default=Path("data/external/datasets.lock.json"))
    args = parser.parse_args()
    sources = dataset_config(args.config)
    selected = args.source_ids or [
        source_id for source_id, item in sources.items() if item.get("download_allowed") is True
    ]
    args.directory.mkdir(parents=True, exist_ok=True)
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.with_suffix(".mutex").open("a") as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        manifest = json.loads(args.lock.read_text(encoding="utf-8")) if args.lock.is_file() else {}
        for source_id in selected:
            try:
                manifest[source_id] = download(source_id, sources[source_id], args.directory, manifest.get(source_id))
            except (OSError, KeyError, ValueError) as error:
                parser.exit(1, f"{source_id}: {error}\n")
            with atomic_output(args.lock) as handle:
                json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
                handle.write("\n")
            print(f"{source_id}: {manifest[source_id]['filename']} ({manifest[source_id]['sha256']})")


if __name__ == "__main__":
    main()
