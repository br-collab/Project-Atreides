"""The deadline fetcher is offline-testable and can stage one work package."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import fetch_deadline_rules as tool  # noqa: E402


def _fake_fetch(url: str) -> bytes:
    if url.endswith("titles.json"):
        return json.dumps({"titles": [{"number": 17, "up_to_date_as_of": "2026-10-07"}]}).encode()
    return f"source from {url}".encode()


def test_one_source_can_be_fetched_with_exact_bytes_and_sidecars(
    tmp_path: pathlib.Path,
) -> None:
    now = datetime(2026, 10, 9, 10, 44, tzinfo=UTC)
    files = tool.fetch_all(_fake_fetch, None, now, frozenset({"17cfr242.204"}))
    tool.write_all(files, tmp_path)

    assert set(files) == {
        "17-CFR-242.204.xml",
        "17-CFR-242.204.xml.sha256",
        "17-CFR-242.204.xml.meta.json",
    }
    body = (tmp_path / "17-CFR-242.204.xml").read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    assert (tmp_path / "17-CFR-242.204.xml.sha256").read_text() == (
        f"{digest}  17-CFR-242.204.xml\n"
    )
    metadata = json.loads((tmp_path / "17-CFR-242.204.xml.meta.json").read_text())
    assert metadata["sha256"] == digest
    assert metadata["retrieval_dtg"] == "202610091044"


def test_fetch_failure_writes_nothing(tmp_path: pathlib.Path) -> None:
    def fail(_: str) -> bytes:
        raise OSError("offline")

    result = tool.main(["--out", str(tmp_path), "--source-id", "17cfr242.204"], fetch=fail)
    assert result == 1
    assert list(tmp_path.iterdir()) == []
