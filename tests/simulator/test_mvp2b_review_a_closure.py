"""MVP-2B Review A closure acceptance."""

from dataclasses import replace

import pytest

from simulator.calibration import load_calibration_pack
from simulator.early_warning import warning_workflow_held
from simulator.firm import load_firm_profile, run_firm


def _profile(version: str = "6"):  # type: ignore[no-untyped-def]
    return load_firm_profile(load_calibration_pack(f"firm-synthetic/{version}"), "small")


def test_projection_cut_turns_i13_and_i6_false() -> None:
    day = run_firm(
        _profile(),
        days=1,
        mutation="PROJECTION_CUT_RESERVE_CREDIT",
        verify_replay=False,
    ).days[0]
    assert day.invariants["I13_FOCUS_TIE_OUT"] is False
    assert day.invariants["I6_DEFAULT_AND_STALE_HOLD"] is False
    assert "reserve_total_credits" in day.focus_tie_out.differences


def test_unsourced_bank_control_turns_i3_false_with_owned_break() -> None:
    day = run_firm(
        _profile(),
        days=1,
        mutation="UNSOURCED_BANK_CONTROL",
        verify_replay=False,
    ).days[0]
    unsourced = [item for item in day.street_breaks if item.cause == "UNSOURCED_LOCATION"]
    assert day.invariants["I3_STOCK_RECORD_EQUALS_STREET"] is False
    assert len(unsourced) == 1
    assert unsourced[0].location == "BANK_CONTROL"
    assert unsourced[0].difference == 5
    assert unsourced[0].owner == "SCF1_SETTLEMENT_CONTROL"


def test_one_control_loan_supports_four_day_run() -> None:
    run = run_firm(_profile(), days=4, verify_replay=False)
    assert len(run.days) == 4
    assert _profile().control_deficit == (1, 0, 8225)


def test_pack4_ambiguous_fail_order_is_refused() -> None:
    with pytest.raises(ValueError, match="FAIL_LOT_ORDER_OLDEST_FIRST_AMBIGUOUS"):
        _profile("4")


def test_swapped_warning_paragraph_turns_i16_false() -> None:
    day = run_firm(
        _profile(), days=1, verify_replay=False, early_warning_stress=True
    ).days[0]
    assert len(day.early_warning_notices) == 2
    swapped = (
        replace(
            day.early_warning_notices[0],
            paragraph=day.early_warning_notices[1].paragraph,
        ),
        day.early_warning_notices[1],
    )
    from atreides.customer_protection.net_capital import EarlyWarning

    fired = tuple(
        EarlyWarning(
            rule_id=f"synthetic-{index}",
            paragraph=notice.paragraph,
            threshold=notice.threshold,
            measure=notice.measure,
            cushion=notice.cushion,
            triggered=True,
            note="synthetic test warning",
        )
        for index, notice in enumerate(day.early_warning_notices)
    )
    assert warning_workflow_held(fired, swapped) is False
