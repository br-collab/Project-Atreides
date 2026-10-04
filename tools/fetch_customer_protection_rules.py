#!/usr/bin/env python3
"""Fetch the rule text the customer protection engines compute from (ORDER SC-2, WP-1).

EXPERIMENTAL (charter section 18.6 claim labels). Nothing this tool fetches is
production evidence.

THIS IS THE ONLY CODE IN THE PACKAGE THAT TOUCHES THE NETWORK
-------------------------------------------------------------
``atreides.customer_protection`` never fetches anything. It reads the files this
tool writes, checks each one against its SHA-256 (Secure Hash Algorithm, 256
bit) sidecar, and computes from what it read. The tool runs at preflight, by a
person, and its output is committed, so a computation can be replayed against
exactly the rule text it used without anybody being online.

WHAT IT FETCHES
---------------
The current full text, from the electronic Code of Federal Regulations (eCFR)
versioner, of:

- 17 CFR 240.15c3-1, the net capital rule,
- 17 CFR 240.15c3-3, the customer protection rule,
- 17 CFR 240.15c3-3a, Exhibit A to Rule 15c3-3, the reserve formula,
- 17 CFR 240.17a-11, the early warning notification rule,

and the Securities and Exchange Commission (SEC) staff FAQ (frequently asked
questions) on Rule 15c3-3 daily customer and PAB (proprietary accounts of
broker-dealers) reserve computations, which is labelled GUIDANCE. Staff
guidance is not rule text and the engines never read a figure from it.

WHAT IT WRITES
--------------
For each source, under ``atreides/customer_protection/rules/sources/``:

- the bytes exactly as served, decompressed,
- ``<file>.sha256`` in ``shasum -a 256`` format, so ``shasum -c`` verifies it,
- ``<file>.meta.json``: citation, label, URL, the retrieval DTG (date-time
  group, UTC, ``YYYYMMDDHHMM``), the eCFR currency date, and the section's
  latest amendment date as the eCFR versioner reports it.

The eCFR versioner refuses requests that do not accept a compressed response
(HTTP 406, support code 11), so every request sends ``Accept-Encoding: gzip``.

Usage::

    python3 tools/fetch_customer_protection_rules.py
    python3 tools/fetch_customer_protection_rules.py --date 2026-10-01

Exit codes: 0 every source fetched and written; 1 a fetch failed, in which case
nothing is written. A partial set of rule text is worse than the old set,
because the old set at least agrees with its own table.
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
SOURCES_DIR = REPO / "atreides" / "customer_protection" / "rules" / "sources"

ECFR = "https://www.ecfr.gov/api/versioner/v1"
USER_AGENT = "Project-Atreides customer protection rule fetch (research, EXPERIMENTAL)"


@dataclass(frozen=True)
class Source:
    source_id: str
    citation: str
    label: str
    filename: str
    #: eCFR section identifier, or None for a non-eCFR source.
    section: str | None = None
    url: str | None = None


SOURCES: tuple[Source, ...] = (
    Source("17cfr240.15c3-1", "17 CFR 240.15c3-1", "RULE", "17-CFR-240.15c3-1.xml", "240.15c3-1"),
    Source("17cfr240.15c3-3", "17 CFR 240.15c3-3", "RULE", "17-CFR-240.15c3-3.xml", "240.15c3-3"),
    Source(
        "17cfr240.15c3-3a", "17 CFR 240.15c3-3a", "RULE", "17-CFR-240.15c3-3a.xml", "240.15c3-3a"
    ),
    Source("17cfr240.17a-11", "17 CFR 240.17a-11", "RULE", "17-CFR-240.17a-11.xml", "240.17a-11"),
    Source(
        "sec-faq-15c3-3-daily",
        "SEC staff FAQ, Rule 15c3-3 daily customer and PAB reserve computations",
        "GUIDANCE",
        "SEC-FAQ-15c3-3-daily-reserve.html",
        url=(
            "https://www.sec.gov/rules-regulations/staff-guidance/"
            "trading-markets-frequently-asked-questions/"
            "frequently-asked-questions-rule-15c3-3-daily-customer-pab-reserve-computations"
        ),
    ),
)

Fetch = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    """GET ``url`` and return the decompressed body. Raises on any non-200."""
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
    title = next(t for t in titles["titles"] if t["number"] == 17)
    return str(title["up_to_date_as_of"])


def _latest_amendment(fetch: Fetch, section: str, as_of: str) -> str:
    versions = json.loads(fetch(f"{ECFR}/versions/title-17.json?section={section}"))
    dates = [
        v["amendment_date"]
        for v in versions["content_versions"]
        if v["identifier"] == section and v["amendment_date"] <= as_of
    ]
    return str(max(dates))


def source_url(source: Source, as_of: str) -> str:
    if source.url is not None:
        return source.url
    return f"{ECFR}/full/{as_of}/title-17.xml?part=240&section={source.section}"


def fetch_all(fetch: Fetch, as_of: str | None, now: datetime) -> dict[str, bytes]:
    """Every file to write, keyed by filename. Fetches everything before returning."""
    ecfr_as_of = as_of or _ecfr_date(fetch)
    dtg = now.astimezone(UTC).strftime("%Y%m%d%H%M")
    files: dict[str, bytes] = {}
    for source in SOURCES:
        url = source_url(source, ecfr_as_of)
        body = fetch(url)
        if not body:
            raise RuntimeError(f"{source.citation}: empty response from {url}")
        sha = hashlib.sha256(body).hexdigest()
        meta = {
            "source_id": source.source_id,
            "citation": source.citation,
            "label": source.label,
            "url": url,
            "retrieval_dtg": dtg,
            "sha256": sha,
            "bytes": len(body),
            "ecfr_up_to_date_as_of": ecfr_as_of if source.section else None,
            "latest_amendment_date": (
                _latest_amendment(fetch, source.section, ecfr_as_of) if source.section else None
            ),
        }
        files[source.filename] = body
        files[f"{source.filename}.sha256"] = f"{sha}  {source.filename}\n".encode()
        files[f"{source.filename}.meta.json"] = (
            json.dumps(meta, indent=2, sort_keys=True) + "\n"
        ).encode()
    return files


def write_all(files: dict[str, bytes], out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(files.items()):
        (out / name).write_bytes(data)


def main(argv: list[str] | None = None, fetch: Fetch = http_get) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", help="eCFR point-in-time date, YYYY-MM-DD (default: current)")
    parser.add_argument("--out", type=pathlib.Path, default=SOURCES_DIR)
    args = parser.parse_args(argv)
    try:
        files = fetch_all(fetch, args.date, datetime.now(tz=UTC))
    except Exception as exc:
        print(f"FETCH FAILED, nothing written: {exc}", file=sys.stderr)
        return 1
    write_all(files, args.out)
    for name in sorted(files):
        if name.endswith(".sha256"):
            print(files[name].decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
