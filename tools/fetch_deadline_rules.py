#!/usr/bin/env python3
"""Fetch cited deadline sources for offline, hash-pinned review.

EXPERIMENTAL. This preflight tool is the only deadline code that touches the
network. It fetches every configured source before writing any file, preventing
a failed run from replacing a coherent source set with a partial one.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES_DIR = REPO / "atreides" / "deadlines" / "rules" / "sources"
ECFR = "https://www.ecfr.gov/api/versioner/v1"
USER_AGENT = "Project-Atreides deadline rule fetch (research, EXPERIMENTAL)"


@dataclass(frozen=True)
class Source:
    source_id: str
    citation: str
    filename: str
    section: str | None = None
    url: str | None = None


SOURCES: tuple[Source, ...] = (
    Source("17cfr242.204", "17 CFR 242.204", "17-CFR-242.204.xml", "242.204"),
    Source("17cfr240.17a-13", "17 CFR 240.17a-13", "17-CFR-240.17a-13.xml", "240.17a-13"),
    Source("17cfr240.15c3-3", "17 CFR 240.15c3-3", "17-CFR-240.15c3-3.xml", "240.15c3-3"),
    Source(
        "finra-11870",
        "FINRA Rule 11870",
        "FINRA-11870.html",
        url="https://www.finra.org/rules-guidance/rulebooks/finra-rules/11870",
    ),
)

Fetch = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept-Encoding": "gzip", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body: bytes = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body


def _ecfr_date(fetch: Fetch) -> str:
    titles = json.loads(fetch(f"{ECFR}/titles.json"))
    title = next(item for item in titles["titles"] if item["number"] == 17)
    return str(title["up_to_date_as_of"])


def source_url(source: Source, as_of: str) -> str:
    if source.url is not None:
        return source.url
    if source.section is None:
        raise ValueError(f"{source.source_id}: no URL or eCFR section")
    part = source.section.split(".", maxsplit=1)[0]
    return f"{ECFR}/full/{as_of}/title-17.xml?part={part}&section={source.section}"


def fetch_all(
    fetch: Fetch,
    as_of: str | None,
    now: datetime,
    source_ids: frozenset[str] | None = None,
) -> dict[str, bytes]:
    ecfr_as_of = as_of or _ecfr_date(fetch)
    dtg = now.astimezone(UTC).strftime("%Y%m%d%H%M")
    files: dict[str, bytes] = {}
    for source in SOURCES:
        if source_ids is not None and source.source_id not in source_ids:
            continue
        url = source_url(source, ecfr_as_of)
        body = fetch(url)
        if not body:
            raise RuntimeError(f"{source.citation}: empty response from {url}")
        sha = hashlib.sha256(body).hexdigest()
        metadata = {
            "source_id": source.source_id,
            "citation": source.citation,
            "url": url,
            "retrieval_dtg": dtg,
            "sha256": sha,
            "bytes": len(body),
            "ecfr_up_to_date_as_of": ecfr_as_of if source.section else None,
        }
        files[source.filename] = body
        files[f"{source.filename}.sha256"] = f"{sha}  {source.filename}\n".encode()
        files[f"{source.filename}.meta.json"] = (
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        ).encode()
    return files


def write_all(files: dict[str, bytes], out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(files.items()):
        (out / name).write_bytes(data)


def main(argv: list[str] | None = None, fetch: Fetch = http_get) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", help="eCFR point-in-time date, YYYY-MM-DD")
    parser.add_argument("--out", type=pathlib.Path, default=SOURCES_DIR)
    parser.add_argument(
        "--source-id",
        action="append",
        choices=[source.source_id for source in SOURCES],
        help="fetch only this configured source; repeat to select more than one",
    )
    args = parser.parse_args(argv)
    try:
        source_ids = frozenset(args.source_id) if args.source_id else None
        files = fetch_all(fetch, args.date, datetime.now(tz=UTC), source_ids)
    except Exception as exc:
        print(f"FETCH FAILED, nothing written: {exc}", file=sys.stderr)
        return 1
    write_all(files, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
