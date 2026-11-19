"""PS-3B run-level truth tests."""

from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack


def _small_profile():  # type: ignore[no-untyped-def]
    return load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small")


def test_clean_five_day_small_firm_has_six_zero_break_reconciliations_daily() -> None:
    run = run_firm(_small_profile(), days=5, verify_replay=False)
    for day in run.days:
        assert len(day.reconciliation_calendar) == 6
        assert all(row.status == "RAN" for row in day.reconciliation_calendar)
        assert all(row.break_count == 0 for row in day.reconciliation_calendar)


def test_firm_run_one_share_depository_difference_is_one_break() -> None:
    day = run_firm(
        _small_profile(), days=1, mutation="DEPOSITORY_ONE_SHARE", verify_replay=False
    ).days[0]
    row = next(item for item in day.reconciliation_calendar if item.item_id == "securities-count")
    assert row.status == "FAILED"
    assert row.break_count == 1
