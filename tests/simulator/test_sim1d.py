from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from marketdata.catalog import CATALOG_PATH, load_catalog
from simulator.calibration.loader import PACKS_ROOT
from simulator.runner import daily_financing_charge, run_simulation, treasury_clean_price


def _real_pack(tmp_path: Path, *, sofr: bool = True) -> Path:
    synthetic = json.loads((PACKS_ROOT / "synthetic/1/calibration.json").read_text())
    catalog = load_catalog(CATALOG_PATH)
    treasury = catalog["treasury_yield_2019"]
    rows = [
        {
            "input_id": treasury.source_id,
            "source_url": treasury.url,
            "citation": treasury.citation,
            "license_class": "A",
            "values": {
                "observations": [
                    {"date": "2019-09-17", "metric": "2 Yr", "value": "1.72", "unit": "percent"}
                ]
            },
        }
    ]
    if sofr:
        source = catalog["nyfed_sofr_2019"]
        rows.append(
            {
                "input_id": source.source_id,
                "source_url": source.url,
                "citation": source.citation,
                "license_class": "B",
                "ny_fed_notice": source.ny_fed_notice,
                "values": {
                    "observations": [
                        {"date": "2019-09-17", "metric": "SOFR", "value": "5.25", "unit": "percent"}
                    ]
                },
            }
        )
    destination = tmp_path / "20_curated/packs/test-real/1"
    destination.mkdir(parents=True)
    calibration = destination / "calibration.json"
    calibration.write_text(
        json.dumps({"inputs": synthetic["inputs"] + rows}, sort_keys=True) + "\n"
    )
    manifest = {
        "schema_version": "cfma.calibration-manifest/1",
        "pack_id": "test-real",
        "version": "1",
        "files": {"calibration.json": hashlib.sha256(calibration.read_bytes()).hexdigest()},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return destination


def test_real_sofr_and_treasury_yield_drive_close(tmp_path: Path) -> None:
    run = run_simulation(seed=20261023, days=1, calibration_uri=_real_pack(tmp_path).as_uri())
    close = run["closes"][0]
    assert close["business_date"] == "2019-09-17"
    assert close["market_data"]["sofr_percent"] == "5.25"
    assert Decimal(close["market_data"]["financing_charge"]) > 0
    assert Decimal(close["market_data"]["treasury_clean_price_64ths"]) > 0
    assert run["all_invariants_pass"] is True


def test_missing_real_rate_holds_without_carry_forward(tmp_path: Path) -> None:
    close = run_simulation(
        seed=20261023, days=1, calibration_uri=_real_pack(tmp_path, sofr=False).as_uri()
    )["closes"][0]
    assert "MARKET_RATE_INPUTS" in close["holds"]
    assert close["market_data"]["sofr_percent"] is None
    assert close["market_data"]["financing_charge"] is None


def test_skipping_financing_post_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from simulator import runner

    original = runner.drive_estate

    def omit_financing(**kwargs: object):
        kwargs["post_financing"] = False
        return original(**kwargs)

    monkeypatch.setattr(runner, "drive_estate", omit_financing)
    close = run_simulation(seed=20261023, days=1, calibration_uri=_real_pack(tmp_path).as_uri())[
        "closes"
    ][0]
    assert close["invariant_results"]["I2_BOOKED_FROM_REPORTS"] is False


@seed(20261023)
@settings(max_examples=200)
@given(
    need=st.decimals(min_value="0.01", max_value="1000000000", places=2),
    rate=st.decimals(min_value="0.01", max_value="25", places=4),
)
def test_financing_charge_conserves_to_the_cent(need: Decimal, rate: Decimal) -> None:
    charge = daily_financing_charge(need, rate)
    assert charge == charge.quantize(Decimal("0.01"))
    assert charge == (need * rate / Decimal(100) / Decimal(360)).quantize(Decimal("0.01"))


@seed(20261023)
@settings(max_examples=200)
@given(
    par_yield=st.decimals(min_value="0.01", max_value="25", places=4),
    coupon=st.decimals(min_value="0.01", max_value="25", places=4),
)
def test_treasury_price_conserves_to_one_sixty_fourth(par_yield: Decimal, coupon: Decimal) -> None:
    price = treasury_clean_price(par_yield, coupon, 2)
    assert price * 64 == (price * 64).to_integral_value()
