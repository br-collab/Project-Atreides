"""SCF-2 activity-driven protection, history, borrow and close-out evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from simulator.firm import FirmProfile, load_firm_profile, run_firm, synthetic_filed_history
from simulator.runner import load_calibration_pack


def _profile() -> FirmProfile:
    return replace(
        load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small"),
        executions_per_day=100,
    )


def test_activity_drives_credits_debits_borrows_and_rule_204() -> None:
    run = run_firm(_profile(), days=3, verify_replay=False)
    assert all(day.protection_figures["customer_credits"] is not None for day in run.days)
    assert all(day.protection_figures["customer_debits"] is not None for day in run.days)
    assert run.days[1].fails_by_age
    assert run.days[1].rule_204_close_outs
    averages = [day.protection_figures["average_total_credits"] for day in run.days]
    assert all(value is not None and value >= Decimal("500000000") for value in averages)


def test_twelve_month_focus_stand_in_and_honest_absence() -> None:
    profile = _profile()
    history = synthetic_filed_history(profile, run_date := date(2027, 1, 4))
    assert history is not None and len(history) == 12
    missing = replace(profile, filed_history_months=0)
    assert synthetic_filed_history(missing, run_date) is None
    close = run_firm(missing, days=1, verify_replay=False).days[0]
    assert close.protection_figures["average_total_credits"] is None


def test_complete_generated_shortfall_path_fires() -> None:
    close = run_firm(
        _profile(),
        days=1,
        mutation="FORCE_RESERVE_PASS_ON_SHORT_DAY",
        verify_replay=False,
    ).days[0]
    assert close.protection_figures["reserve_requirement"] is not None
    assert not close.invariants["I6_DEFAULT_AND_STALE_HOLD"]
