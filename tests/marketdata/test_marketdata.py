from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from urllib.request import Request

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketdata.catalog import CATALOG_PATH, classify_url, load_catalog
from marketdata.cli import main as cli_main
from marketdata.guard import check_repository
from marketdata.normalize import _ofr_repo_rows, normalize, reconcile, validate_rows
from marketdata.packs import build_pack, verify_pack, write_pack_lock
from marketdata.store import _AdmittedRedirect, _ensure_free_space, ingest, initialize
from marketdata.sync import sync_to_bucket, sync_to_ssd
from simulator.calibration.loader import load_calibration_pack
from simulator.runner import run_simulation


def _catalog(tmp_path: Path, row: dict[str, object]) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(json.dumps({"schema_version": "cfma.sources/1", "sources": [row]}))
    return path


def _source_row(**change: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "test",
        "url": "https://home.treasury.gov/admitted.csv",
        "license_class": "A",
        "kind": "treasury_yield_csv",
        "citation": "test government source",
    }
    row.update(change)
    return row


class _Response(io.BytesIO):
    def __init__(self, value: bytes, declared: int | None = None):
        super().__init__(value)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_catalog_assigns_class_from_exact_admitted_url(tmp_path: Path) -> None:
    path = _catalog(tmp_path, _source_row())
    assert (
        classify_url("https://home.treasury.gov/admitted.csv", catalog_path=path).license_class
        == "A"
    )
    with pytest.raises(ValueError, match="not exactly admitted"):
        classify_url("https://home.treasury.gov/other.csv", catalog_path=path)


@pytest.mark.parametrize(
    "url",
    [
        "https://fred.stlouisfed.org/series/SOFR",
        "https://www.sec.gov/Archives/edgar/data/example.txt",
        "https://api.tiingo.com/tiingo/daily",
        "https://www.finra.org/market-data/file.csv",
    ],
)
def test_excluded_and_unadmitted_hosts_are_refused_before_fetch(tmp_path: Path, url: str) -> None:
    path = _catalog(tmp_path, _source_row(url=url))
    with pytest.raises(ValueError, match="host refused"):
        load_catalog(path)


def test_class_c_and_class_x_are_refused(tmp_path: Path) -> None:
    for label in ("C", "X"):
        path = _catalog(tmp_path, _source_row(license_class=label))
        with pytest.raises(ValueError, match="class refused"):
            load_catalog(path)


def test_redirect_to_unadmitted_host_is_refused_before_following() -> None:
    with pytest.raises(ValueError, match="redirect host refused before fetch"):
        _AdmittedRedirect().redirect_request(
            Request("https://home.treasury.gov/admitted.csv"),
            io.BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://example.com/redirected.csv",
        )


def test_ingest_is_write_once_with_provenance_and_size_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _catalog(tmp_path, _source_row())
    monkeypatch.setattr(
        "marketdata.store.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=100, free=500),
    )
    payload = b"Date,1 Mo\n09/17/2019,2.04\n"
    monkeypatch.setattr("marketdata.store._open", lambda *_args, **_kwargs: _Response(payload))
    first = ingest("test", root=tmp_path / "store", catalog_path=path)
    second = ingest("test", root=tmp_path / "store", catalog_path=path)
    assert first == second
    metadata = json.loads(first.with_suffix(first.suffix + ".metadata.json").read_text())
    assert metadata["source_url"] == "https://home.treasury.gov/admitted.csv"
    assert metadata["license_class"] == "A"
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    catalog_manifest = json.loads((tmp_path / "store" / "catalog" / "manifest.json").read_text())
    assert set(catalog_manifest["files"]) == {
        "normalized.schema.json",
        "pack-locks.json",
        "sources.yaml",
    }

    monkeypatch.setattr(
        "marketdata.store.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=901, free=99),
    )
    with pytest.raises(ValueError, match="below 10 percent free"):
        ingest("test", root=tmp_path / "small", catalog_path=path)


def test_streaming_free_space_accepts_exact_threshold_and_refuses_one_byte_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = initialize(tmp_path / "store")
    monkeypatch.setattr(
        "marketdata.store.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=899, free=101),
    )
    _ensure_free_space(paths, 1)
    with pytest.raises(ValueError, match="below 10 percent free"):
        _ensure_free_space(paths, 2)


def test_interrupted_raw_is_quarantined_and_catalog_refusal_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _catalog(tmp_path, _source_row())
    root = tmp_path / "store"
    monkeypatch.setattr(
        "marketdata.store.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=100, free=500),
    )
    existing = initialize(root).raw / "existing.bin"
    existing.write_bytes(b"12345678")
    monkeypatch.setattr(
        "marketdata.store._open", lambda *_args, **_kwargs: _Response(b"abc", declared=3)
    )
    ingest("test", root=root, catalog_path=path)
    assert not existing.exists()
    assert any((root / "quarantine").glob("raw-startup-*-existing.bin"))

    refused_dir = tmp_path / "refused"
    refused_dir.mkdir()
    refused = _catalog(refused_dir, _source_row(url="https://fred.stlouisfed.org/x"))
    with pytest.raises(ValueError, match="host refused"):
        ingest("test", root=root, catalog_path=refused)
    events = [
        json.loads(line)
        for line in (root / "40_runs" / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["event"] == "ingest_refused"
    assert events[-1]["reason"] == "source host refused: fred.stlouisfed.org"


def _write_raw(root: Path, source_id: str, payload: bytes, suffix: str) -> Path:
    paths = initialize(root)
    digest = hashlib.sha256(payload).hexdigest()
    target = paths.raw / source_id / f"{digest}{suffix}"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    return target


def test_raw_to_parquet_to_annex_loader_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "store"
    treasury = _write_raw(
        root,
        "treasury_yield_2019",
        b"Date,1 Mo,3 Mo\n09/16/2019,2.03,1.99\n09/17/2019,2.04,1.99\n",
        ".csv",
    )
    treasury.with_suffix(".csv.metadata.json").write_text("{}")
    normalized = normalize("treasury_yield_2019", root=root)
    assert pq.read_table(normalized).num_rows == 4
    pack = build_pack("baseline", "1", [normalized], root=root)
    loaded = load_calibration_pack(pack.as_uri())
    assert loaded.pack_id == "baseline"
    assert loaded.classes_used == ("A", "SYNTHETIC")


def test_ny_fed_notice_travels_into_pack_and_sim_summary(tmp_path: Path) -> None:
    root = tmp_path / "store"
    payload = json.dumps(
        {
            "refRates": [
                {"effectiveDate": "2019-09-16", "type": "SOFR", "percentRate": 2.43},
                {"effectiveDate": "2019-09-17", "type": "SOFR", "percentRate": 5.25},
            ]
        }
    ).encode()
    _write_raw(root, "nyfed_sofr_2019", payload, ".json")
    normalized = normalize("nyfed_sofr_2019", root=root)
    pack = build_pack("repo-spike", "1", [normalized], root=root)
    run = run_simulation(seed=29, days=1, calibration_uri=pack.as_uri())
    assert run["calibration_classes_used"] == ["B", "SYNTHETIC"]
    expected_notice = load_catalog(CATALOG_PATH)["nyfed_sofr_2019"].ny_fed_notice
    assert run["ny_fed_notices"] == [expected_notice]


def _ofr_repo_payload() -> dict[str, object]:
    series = {}
    for mnemonic in (
        "REPO-DVP_AR_TOT-F",
        "REPO-DVP_TV_TOT-F",
        "REPO-GCF_AR_TOT-F",
        "REPO-GCF_TV_TOT-F",
        "REPO-TRI_AR_TOT-F",
        "REPO-TRI_TV_TOT-F",
    ):
        unit = "Percent" if "_AR_" in mnemonic else "USD"
        series[mnemonic] = {
            "timeseries": {"aggregation": [["2020-03-09", 1.25], ["2020-03-10", None]]},
            "metadata": {
                "mnemonic": mnemonic,
                "description": {"vintage": "Final"},
                "release": {"long_name": "OFR U.S. Repo Markets Data Release"},
                "unit": {"name": unit},
            },
        }
    return series


def test_ofr_repo_parser_accepts_only_six_final_ofr_series_and_preserves_null_absence() -> None:
    """CLOSE-1 WP3.1: accept DVP/GCF/tri-party and refuse non-OFR slices."""
    source = load_catalog(CATALOG_PATH)["ofr_repo_2020"]
    rows = _ofr_repo_rows(json.dumps(_ofr_repo_payload()).encode(), source)
    assert {row["metric"] for row in rows} == set(_ofr_repo_payload())
    assert {row["date"] for row in rows} == {"2020-03-09"}
    assert {row["unit"] for row in rows} == {"percent", "usd"}

    unexpected = _ofr_repo_payload()
    unexpected["FNYR-SOFR"] = unexpected["REPO-DVP_AR_TOT-F"]
    with pytest.raises(ValueError, match="exact admitted six-series bundle"):
        _ofr_repo_rows(json.dumps(unexpected).encode(), source)

    wrong_release = _ofr_repo_payload()
    wrong_release["REPO-DVP_AR_TOT-F"]["metadata"]["release"]["long_name"] = "Elsewhere"
    with pytest.raises(ValueError, match="not an OFR final publication"):
        _ofr_repo_rows(json.dumps(wrong_release).encode(), source)

    wrong_unit = _ofr_repo_payload()
    wrong_unit["REPO-DVP_TV_TOT-F"]["metadata"]["unit"]["name"] = "Percent"
    with pytest.raises(ValueError, match="not an OFR final publication"):
        _ofr_repo_rows(json.dumps(wrong_unit).encode(), source)


def test_validation_flags_schema_range_calendar_duplicates_and_reconciliation() -> None:
    base = {
        "date": "2026-10-19",
        "metric": "SOFR",
        "value": "5.0",
        "unit": "percent",
        "source_id": "one",
        "license_class": "B",
    }
    errors = validate_rows(
        [base, {**base, "value": "101"}, {**base, "date": "2026-10-21", "value": "5.0"}]
    )
    assert any("differing values" in error for error in errors)
    assert any("out of range" in error for error in errors)
    assert any("calendar gap" in error for error in errors)


def test_reconcile_uses_normalized_sources(tmp_path: Path) -> None:
    paths = []
    for source, value in (("treasury", "5.00"), ("ofr", "5.25")):
        path = tmp_path / f"{source}.parquet"
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "date": "2026-10-23",
                        "metric": "rate",
                        "unit": "percent",
                        "source_id": source,
                        "value": value,
                    }
                ]
            ),
            path,
        )
        paths.append(path)
    assert reconcile(paths)[0].startswith("cross-source mismatch")


def _clean_parquet(tmp_path: Path, *, identifier: bool = False, clean: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "input.parquet"
    row: dict[str, object] = {
        "date": "2019-09-17",
        "metric": "SOFR",
        "value": "5.25",
        "unit": "percent",
        "source_id": "nyfed_sofr_2019",
        "source_url": load_catalog(CATALOG_PATH)["nyfed_sofr_2019"].url,
        "citation": "NY Fed published SOFR",
        "license_class": "B",
        "ny_fed_notice": load_catalog(CATALOG_PATH)["nyfed_sofr_2019"].ny_fed_notice,
    }
    if identifier:
        row["metric"] = "037833100"
    pq.write_table(pa.Table.from_pylist([row]), path)
    path.with_suffix(".metadata.json").write_text(
        json.dumps(
            {
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "license_class": row["license_class"],
                "ny_fed_notice": row["ny_fed_notice"],
                "raw_sha256": "raw",
                "validation_status": "clean" if clean else "unclean",
            }
        )
    )
    return path


def test_build_pack_refuses_unclean_and_identifier_inputs(tmp_path: Path) -> None:
    # A status word in a sidecar is not trusted; the rows are revalidated.
    assert build_pack(
        "revalidated", "1", [_clean_parquet(tmp_path, clean=False)], root=tmp_path / "a"
    ).exists()
    with pytest.raises(ValueError, match="CUSIP-shaped value"):
        build_pack(
            "bad",
            "1",
            [_clean_parquet(tmp_path / "identified", identifier=True)],
            root=tmp_path / "b",
        )


def test_build_pack_refuses_sidecar_catalog_class_or_notice_edits(tmp_path: Path) -> None:
    path = _clean_parquet(tmp_path / "source")
    metadata_path = path.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text())
    metadata["license_class"] = "A"
    metadata["ny_fed_notice"] = "edited"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match=r"sidecar/catalog mismatch.*license_class.*ny_fed_notice"):
        build_pack("bad-sidecar", "1", [path], root=tmp_path / "store")


def test_verify_quarantines_corruption_and_annex_loader_refuses(tmp_path: Path) -> None:
    source = _clean_parquet(tmp_path / "source")
    root = tmp_path / "store"
    pack = build_pack("immutable", "1", [source], root=root)
    (pack / "calibration.json").write_bytes((pack / "calibration.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_pack(pack, store=initialize(root))
    assert list((root / "quarantine").glob("corrupt-*"))
    with pytest.raises(ValueError, match="integrity mismatch"):
        load_calibration_pack(pack.as_uri())


def test_pack_lock_is_immutable(tmp_path: Path) -> None:
    source = _clean_parquet(tmp_path / "source")
    pack = build_pack("locked", "1", [source], root=tmp_path / "store")
    lock = tmp_path / "locks.json"
    lock.write_text('{"schema_version":"cfma.pack-locks/1","packs":{}}')
    first = write_pack_lock(pack, lock)
    assert write_pack_lock(pack, lock) == first


def test_pack_observations_are_chronological(tmp_path: Path) -> None:
    path = _clean_parquet(tmp_path / "source")
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows.append({**rows[0], "date": "2019-09-16", "value": "2.11"})
    pq.write_table(pa.Table.from_pylist(rows), path)
    pack = build_pack("ordered", "1", [path], root=tmp_path / "store")
    document = json.loads((pack / "calibration.json").read_text())
    source = next(row for row in document["inputs"] if row["input_id"] == "nyfed_sofr_2019")
    assert [row["date"] for row in source["values"]["observations"]] == [
        "2019-09-16",
        "2019-09-17",
    ]


def test_sync_to_ssd_uploads_only_new_and_refuses_raw(tmp_path: Path) -> None:
    source = _clean_parquet(tmp_path / "source")
    root = tmp_path / "store"
    pack = build_pack("sync", "1", [source], root=root)
    destination = tmp_path / "ssd"
    assert (
        sync_to_ssd(pack.parent.parent, destination, curated_root=root / "20_curated" / "packs")
        == 2
    )
    assert (
        sync_to_ssd(pack.parent.parent, destination, curated_root=root / "20_curated" / "packs")
        == 0
    )
    with pytest.raises(ValueError, match="outside 20_curated"):
        sync_to_ssd(root / "00_raw", destination, curated_root=root / "20_curated" / "packs")


class _S3StandIn(BaseHTTPRequestHandler):
    objects: ClassVar[dict[str, tuple[bytes, str]]] = {}

    def do_HEAD(self) -> None:
        if self.path not in self.objects:
            self.send_response(404)
            self.end_headers()
            return
        _, digest = self.objects[self.path]
        self.send_response(200)
        self.send_header("x-amz-meta-sha256", digest)
        self.end_headers()

    def do_PUT(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", "0")))
        self.objects[self.path] = (body, self.headers["x-amz-meta-sha256"])
        self.send_response(200)
        self.send_header("ETag", '"local"')
        self.end_headers()

    def log_message(self, *_: object) -> None:
        return


def test_bucket_sync_against_local_s3_compatible_stand_in(tmp_path: Path) -> None:
    _S3StandIn.objects = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _S3StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = _clean_parquet(tmp_path / "source")
        root = tmp_path / "store"
        pack = build_pack("bucket", "1", [source], root=root)
        kwargs = {
            "curated_root": root / "20_curated" / "packs",
            "endpoint_url": f"http://127.0.0.1:{server.server_port}",
        }
        assert (
            cli_main(
                [
                    "--root",
                    str(root),
                    "sync",
                    "--to",
                    "bucket",
                    str(pack.parent.parent),
                    "s3://local/packs",
                    "--endpoint-url",
                    kwargs["endpoint_url"],
                ]
            )
            == 0
        )
        assert sync_to_bucket(pack.parent.parent, "s3://local/packs", **kwargs) == 0
        assert len(_S3StandIn.objects) == 2
        with pytest.raises(ValueError, match="outside 20_curated"):
            sync_to_bucket(root / "00_raw", "s3://local/packs", **kwargs)
    finally:
        server.shutdown()
        thread.join()


def test_repository_guard_and_production_profile() -> None:
    root = Path(__file__).parents[2]
    assert check_repository(root) == []
    env = {**os.environ, "ATREIDES_PROFILE": "production"}
    result = subprocess.run(
        [sys.executable, "-c", "import marketdata"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "unavailable in the production profile" in result.stderr


def test_marketdata_is_excluded_from_wheel_configuration() -> None:
    pyproject = (Path(__file__).parents[2] / "pyproject.toml").read_text()
    assert 'include = ["atreides*"]' in pyproject


def test_catalog_contains_only_order_admitted_hosts_and_ny_fed_notice() -> None:
    catalog = load_catalog(CATALOG_PATH)
    assert {source.license_class for source in catalog.values()} == {"A", "B"}
    assert catalog["nyfed_sofr_2019"].ny_fed_notice
    assert catalog["ofr_repo_2020"].license_class == "A"
    assert catalog["ofr_repo_2023"].license_class == "A"
