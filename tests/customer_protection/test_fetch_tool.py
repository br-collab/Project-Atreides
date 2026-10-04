"""The fetch tool writes each source with its sidecars, and writes nothing if any fetch fails.

No network: the tool takes its fetch function as an argument, and these tests pass a fake.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import UTC, datetime

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import fetch_customer_protection_rules as tool  # noqa: E402

TITLES = json.dumps({"titles": [{"number": 17, "up_to_date_as_of": "2026-10-01"}]}).encode()


def _versions(section: str) -> bytes:
    return json.dumps(
        {
            "content_versions": [
                {"identifier": section, "amendment_date": "2024-03-18"},
                {"identifier": section, "amendment_date": "2019-01-14"},
                {"identifier": section, "amendment_date": "2027-01-01"},
            ]
        }
    ).encode()


def fake_fetch(url: str) -> bytes:
    if url.endswith("titles.json"):
        return TITLES
    if "/versions/" in url:
        return _versions(url.rsplit("section=", 1)[1])
    return f"<P>text from {url}</P>".encode()


def test_every_source_is_written_with_its_sidecars(tmp_path: pathlib.Path) -> None:
    now = datetime(2026, 10, 4, 15, 52, tzinfo=UTC)
    files = tool.fetch_all(fake_fetch, None, now)
    tool.write_all(files, tmp_path)
    for source in tool.SOURCES:
        body = (tmp_path / source.filename).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        sidecar = (tmp_path / f"{source.filename}.sha256").read_text(encoding="utf-8")
        assert sidecar == f"{digest}  {source.filename}\n"
        meta = json.loads((tmp_path / f"{source.filename}.meta.json").read_text("utf-8"))
        assert meta["sha256"] == digest
        assert meta["retrieval_dtg"] == "202610041552"
        assert meta["label"] == source.label
        if source.section:
            assert meta["ecfr_up_to_date_as_of"] == "2026-10-01"
            assert meta["latest_amendment_date"] == "2024-03-18"
            assert "/full/2026-10-01/" in meta["url"]
        else:
            assert meta["latest_amendment_date"] is None


def test_a_failed_fetch_writes_nothing(tmp_path: pathlib.Path) -> None:
    def failing(url: str) -> bytes:
        if "17a-11" in url and "/full/" in url:
            raise OSError("HTTP 406")
        return fake_fetch(url)

    assert tool.main(["--out", str(tmp_path)], fetch=failing) == 1
    assert list(tmp_path.iterdir()) == []


def test_an_empty_response_is_a_failure(tmp_path: pathlib.Path) -> None:
    assert tool.main(["--out", str(tmp_path), "--date", "2026-10-01"], fetch=lambda _: b"") == 1


def test_a_successful_run_reports_every_hash(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tool.main(["--out", str(tmp_path / "out")], fetch=fake_fetch) == 0
    assert capsys.readouterr().out.count("  ") == len(tool.SOURCES)


def test_the_package_never_imports_the_tool() -> None:
    assert tool.SOURCES_DIR == REPO / "atreides" / "customer_protection" / "rules" / "sources"
