from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from marketdata.catalog import CATALOG_PATH, load_catalog
from simulator.calibration.loader import DEFAULT_PACK, PACKS_ROOT, load_calibration_pack
from simulator.runner import run_simulation


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "20_curated" / "packs" / "synthetic" / "1"
    target.parent.mkdir(parents=True)
    shutil.copytree(PACKS_ROOT / DEFAULT_PACK, target)
    return target


def _rewrite(pack: Path, change) -> None:  # type: ignore[no-untyped-def]
    data_path = pack / "calibration.json"
    document = json.loads(data_path.read_text())
    change(document)
    data_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["calibration.json"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def test_default_and_local_copy_have_identical_economics(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    default = run_simulation(seed=29, days=5)
    local = run_simulation(seed=29, days=5, calibration_uri=copied.as_uri())
    assert default["economics_digest"] == local["economics_digest"]
    assert default["calibration_manifest_digest"] == local["calibration_manifest_digest"]
    assert default["calibration_classes_used"] == ["SYNTHETIC"]


def test_cfma_data_uri_addresses_one_local_pack(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    copied = _copy_pack(tmp_path)
    monkeypatch.setenv("CFMA_DATA_URI", copied.as_uri())
    assert load_calibration_pack().pack_id == "synthetic"
    with pytest.raises(ValueError, match="network schemes are refused"):
        load_calibration_pack("https://example.test/store")


def test_arbitrary_manifest_directory_is_outside_the_calibration_seam(tmp_path: Path) -> None:
    arbitrary = tmp_path / "arbitrary"
    shutil.copytree(PACKS_ROOT / DEFAULT_PACK, arbitrary)
    with pytest.raises(ValueError, match="repository synthetic pack root or <store>"):
        load_calibration_pack(arbitrary.as_uri())


def test_corrupt_byte_refuses_and_names_file(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    path = copied / "calibration.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"integrity mismatch: calibration\.json"):
        load_calibration_pack(copied.as_uri())


@pytest.mark.parametrize("label", ["C", "ACAD", "X", ""])
def test_unadmitted_or_unlabelled_class_refused(tmp_path: Path, label: str) -> None:
    copied = _copy_pack(tmp_path)
    _rewrite(copied, lambda doc: doc["inputs"][0].update(license_class=label))
    with pytest.raises(ValueError, match="class refused"):
        load_calibration_pack(copied.as_uri())


def test_class_b_requires_notice(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    _rewrite(copied, lambda doc: doc["inputs"][0].update(license_class="B"))
    with pytest.raises(ValueError, match="requires the NY Fed notice"):
        load_calibration_pack(copied.as_uri())


def test_class_b_notice_is_carried_into_summary(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    source = load_catalog(CATALOG_PATH)["nyfed_sofr_2019"]
    assert source.ny_fed_notice is not None
    notice = source.ny_fed_notice

    def admit_class_b(document: dict[str, Any]) -> None:
        row = cast(dict[str, Any], document["inputs"][0])
        row.update(license_class="B", source_url=source.url, ny_fed_notice=notice)

    _rewrite(copied, admit_class_b)
    run = run_simulation(seed=29, days=1, calibration_uri=copied.as_uri())
    assert run["ny_fed_notices"] == [notice]


def test_fred_host_refused_even_when_labelled_a(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    _rewrite(
        copied,
        lambda doc: doc["inputs"][1].update(source_url="https://api.stlouisfed.org/fred/series"),
    )
    with pytest.raises(ValueError, match="FRED source refused"):
        load_calibration_pack(copied.as_uri())


@pytest.mark.parametrize("column", ["cusip", "instrument_figi", "ticker_symbol"])
def test_security_identifier_shaped_column_refused(tmp_path: Path, column: str) -> None:
    copied = _copy_pack(tmp_path)
    _rewrite(copied, lambda doc: doc["inputs"][0]["values"].update({column: "FORBIDDEN"}))
    with pytest.raises(ValueError, match="forbidden identifier-shaped key"):
        load_calibration_pack(copied.as_uri())


def test_cusip_shaped_value_is_refused_even_under_an_innocent_key(tmp_path: Path) -> None:
    copied = _copy_pack(tmp_path)
    _rewrite(copied, lambda doc: doc["inputs"][0]["values"].update({"label": "037833100"}))
    with pytest.raises(ValueError, match="CUSIP-shaped value"):
        load_calibration_pack(copied.as_uri())


def test_single_loader_is_the_only_calibration_call_site() -> None:
    root = Path(__file__).parents[2] / "simulator"
    call_sites = []
    for path in root.rglob("*.py"):
        if path.name == "loader.py":
            continue
        if "load_calibration_pack(" in path.read_text():
            call_sites.append(path.relative_to(root).as_posix())
    assert call_sites == ["runner.py"]

    calibration_sources = (root / "calibration").glob("*.py")
    for path in calibration_sources:
        if path.name == "loader.py":
            continue
        source = path.read_text()
        assert "Path(" not in source
        assert ".read_" not in source
        assert "open(" not in source
