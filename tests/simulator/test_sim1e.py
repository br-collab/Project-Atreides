from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from atreides.deadlines.calendar import Market, MarketCalendar
from marketdata.catalog import CATALOG_PATH, load_catalog
from simulator.calibration.loader import PACKS_ROOT
from simulator.runner import daily_financing_charge, publish_run, run_simulation


def _spike_pack(tmp_path: Path) -> Path:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    dates: list[date] = []
    cursor = date(2019, 8, 19)
    while cursor <= date(2019, 9, 17):
        if calendar.is_business_day(cursor):
            dates.append(cursor)
        cursor += timedelta(days=1)
    assert len(dates) == 21
    catalog = load_catalog(CATALOG_PATH)
    synthetic = json.loads((PACKS_ROOT / "synthetic/1/calibration.json").read_text())
    inputs = list(synthetic["inputs"])
    for source_id, metric, value, license_class in (
        ("treasury_yield_2019", "2 Yr", "1.72", "A"),
        ("nyfed_sofr_2019", "SOFR", "2.43", "B"),
    ):
        source = catalog[source_id]
        observations = [
            {
                "date": day.isoformat(),
                "metric": metric,
                "value": "5.25" if metric == "SOFR" and day == date(2019, 9, 17) else value,
                "unit": "percent",
            }
            for day in dates
        ]
        inputs.append(
            {
                "input_id": source.source_id,
                "source_url": source.url,
                "citation": source.citation,
                "license_class": license_class,
                "ny_fed_notice": source.ny_fed_notice,
                "values": {"observations": observations},
            }
        )
    destination = tmp_path / "20_curated/packs/repo-spike-2019/5"
    destination.mkdir(parents=True)
    calibration = destination / "calibration.json"
    calibration.write_text(json.dumps({"inputs": inputs}, sort_keys=True) + "\n")
    manifest = {
        "schema_version": "cfma.calibration-manifest/1",
        "pack_id": "repo-spike-2019",
        "version": "5",
        "files": {"calibration.json": hashlib.sha256(calibration.read_bytes()).hexdigest()},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return destination


def test_explicit_spike_window_runs_all_21_published_business_days(tmp_path: Path) -> None:
    output = tmp_path / "run"
    run = run_simulation(
        seed=20261023,
        days=None,
        start=date(2019, 8, 19),
        end=date(2019, 9, 17),
        calibration_uri=_spike_pack(tmp_path).as_uri(),
    )
    assert run["days"] == 21
    assert run["window_start"] == "2019-08-19"
    assert run["window_end"] == "2019-09-17"
    final = run["closes"][-1]
    assert final["market_data"]["sofr_percent"] == "5.25"
    need = Decimal(final["market_data"]["financing_need"])
    assert Decimal(final["market_data"]["financing_charge"]) == daily_financing_charge(
        need, Decimal("5.25")
    )
    publish_run(run, output)
    notice = load_catalog(CATALOG_PATH)["nyfed_sofr_2019"].ny_fed_notice
    assert notice is not None and notice in (output / "SUMMARY.md").read_text()


def test_explicit_window_rejects_a_mismatched_days_count(tmp_path: Path) -> None:
    pack = _spike_pack(tmp_path)
    try:
        run_simulation(
            seed=20261023,
            days=20,
            start=date(2019, 8, 19),
            end=date(2019, 9, 17),
            calibration_uri=pack.as_uri(),
        )
    except ValueError as error:
        assert "exact number of dates" in str(error)
    else:
        raise AssertionError("mismatched explicit window was accepted")
