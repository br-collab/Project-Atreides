from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atreides.deadlines.calendar import Market, MarketCalendar
from simulator.calibration.loader import PACKS_ROOT
from simulator.runner import daily_financing_charge, publish_run, run_simulation
from tools.regenerate_spike_artifacts import label_summary_freshness


def _spike_pack(tmp_path: Path) -> Path:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    dates: list[date] = []
    cursor = date(2019, 8, 19)
    while cursor <= date(2019, 9, 17):
        if calendar.is_business_day(cursor):
            dates.append(cursor)
        cursor += timedelta(days=1)
    assert len(dates) == 21
    synthetic = json.loads((PACKS_ROOT / "synthetic/1/calibration.json").read_text())
    inputs = list(synthetic["inputs"])
    # These invented observations prove window arithmetic only. They do not
    # impersonate the published Treasury or New York Fed series.
    for input_id, metric, value in (
        ("synthetic_2y_window", "2 Yr", "1.72"),
        ("synthetic_sofr_window", "SOFR", "2.43"),
    ):
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
                "input_id": input_id,
                "source_url": f"synthetic://sim-1f/{input_id}",
                "citation": "SYNTHETIC window fixture, not a published series",
                "license_class": "SYNTHETIC",
                "values": {"observations": observations},
            }
        )
    destination = tmp_path / "20_curated/packs/synthetic-spike-window/1"
    destination.mkdir(parents=True)
    calibration = destination / "calibration.json"
    calibration.write_text(json.dumps({"inputs": inputs}, sort_keys=True) + "\n")
    manifest = {
        "schema_version": "cfma.calibration-manifest/1",
        "pack_id": "synthetic-spike-window",
        "version": "1",
        "files": {"calibration.json": hashlib.sha256(calibration.read_bytes()).hexdigest()},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return destination


def test_explicit_synthetic_window_runs_all_21_business_days(tmp_path: Path) -> None:
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
    assert "New York Fed notices\n\n- None" in (output / "SUMMARY.md").read_text()


def test_notice_format_fixture_is_explicitly_not_market_data(tmp_path: Path) -> None:
    run = run_simulation(seed=20261023, days=1)
    notice = "NOTICE-FORMAT TEST ONLY — not a market-data provenance claim"
    run["ny_fed_notices"] = [notice]
    publish_run(run, tmp_path)
    assert notice in (tmp_path / "SUMMARY.md").read_text()


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


def test_cli_boundary_requires_both_dates_for_a_dated_pack(tmp_path: Path) -> None:
    pack = _spike_pack(tmp_path)
    with pytest.raises(ValueError, match="require explicit --start and --end"):
        run_simulation(
            seed=20261023,
            days=21,
            calibration_uri=pack.as_uri(),
            require_explicit_dated_window=True,
        )


@pytest.mark.parametrize(
    ("artifact", "pack_id", "version", "window"),
    [
        ("spike-2019", "repo-spike-2019", "5", ("2019-08-19", "2019-09-17")),
        ("stress-2020-03", "stress-2020-03", "1", ("2020-02-10", "2020-03-31")),
        ("stress-2023-03", "stress-2023-03", "1", ("2023-02-09", "2023-03-24")),
    ],
)
def test_committed_spike_publications_are_output_only_and_complete(
    artifact: str, pack_id: str, version: str, window: tuple[str, str]
) -> None:
    publication = Path(__file__).parents[2] / "simulator/publication" / artifact
    assert {path.name for path in publication.iterdir()} == {
        "SUMMARY.md",
        "daily-close.json",
        "run-summary.json",
        "trend.json",
    }
    run = json.loads((publication / "run-summary.json").read_text())
    assert run["calibration_pack_id"] == pack_id
    assert run["calibration_pack_version"] == version
    assert run["calibration_classes_used"] == ["A", "B", "SYNTHETIC"]
    assert (run["window_start"], run["window_end"]) == window
    assert run["repository_shas"]["atreides"]
    assert "repo" in run["not_tested"]
    summary = (publication / "SUMMARY.md").read_text()
    assert summary.count("New York Fed is not responsible for publication") == 5
    assert "run outputs only, not the pack or its data" in summary
    assert f"Source commit: `{run['repository_shas']['atreides']}`" in summary


def test_all_dated_publications_keep_the_same_not_tested_boundary() -> None:
    root = Path(__file__).parents[2] / "simulator/publication"
    boundaries = {
        tuple(json.loads((root / artifact / "run-summary.json").read_text())["not_tested"])
        for artifact in ("spike-2019", "stress-2020-03", "stress-2023-03")
    }
    assert len(boundaries) == 1


def test_publication_labels_a_behind_source_and_removes_the_label_when_current(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "SUMMARY.md"
    summary.write_text("# Run\n")
    label_summary_freshness(
        summary,
        source_commit="source",
        current_commit="main",
        is_ancestor=lambda older, newer: (older, newer) == ("source", "main"),
    )
    assert "Artifact freshness: `STALE`" in summary.read_text()
    label_summary_freshness(
        summary,
        source_commit="main",
        current_commit="main",
        is_ancestor=lambda _older, _newer: False,
    )
    assert "Artifact freshness:" not in summary.read_text()
