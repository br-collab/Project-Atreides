"""SCF-1 firm-volume acceptance and money-path properties."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from simulator import firm
from simulator.firm import (
    MUTATIONS,
    attack_firm_run,
    draw_executions,
    load_firm_profile,
    publish_firm,
    roll_forward,
    run_firm,
)
from simulator.runner import load_calibration_pack


def test_profile_is_declared_synthetic_and_deterministic() -> None:
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small")
    assert (profile.accounts, profile.issues, profile.executions_per_day) == (200, 20, 1000)
    assert profile.synthetic
    assert draw_executions(profile, date(2027, 1, 4), 7) == draw_executions(
        profile, date(2027, 1, 4), 7
    )


@seed(20261024)
@settings(max_examples=200, deadline=None)
@given(
    opening=st.dictionaries(
        st.tuples(st.sampled_from(("A", "B")), st.sampled_from(("I1", "I2"))),
        st.integers(-1_000_000, 1_000_000),
    ),
    activity=st.dictionaries(
        st.tuples(st.sampled_from(("A", "B")), st.sampled_from(("I1", "I2"))),
        st.integers(-100_000, 100_000),
    ),
    opening_cash=st.dictionaries(
        st.sampled_from(("A", "B")), st.decimals(-1_000_000, 1_000_000, places=2)
    ),
    cash_activity=st.dictionaries(
        st.sampled_from(("A", "B")), st.decimals(-100_000, 100_000, places=2)
    ),
)
def test_roll_forward_conserves_shares_and_cents(
    opening: dict[tuple[str, str], int],
    activity: dict[tuple[str, str], int],
    opening_cash: dict[str, Decimal],
    cash_activity: dict[str, Decimal],
) -> None:
    opening_quantity = {key: Decimal(value) for key, value in opening.items()}
    activity_quantity = {key: Decimal(value) for key, value in activity.items()}
    positions, cash = roll_forward(opening_quantity, opening_cash, activity_quantity, cash_activity)
    for key in opening_quantity.keys() | activity_quantity.keys():
        assert positions[key] == opening_quantity.get(key, Decimal()) + activity_quantity.get(
            key, Decimal()
        )
        assert positions[key] == positions[key].quantize(Decimal("1"))
    for account in opening_cash.keys() | cash_activity.keys():
        assert cash[account] == opening_cash.get(account, Decimal()) + cash_activity.get(
            account, Decimal()
        )
        assert cash[account] == cash[account].quantize(Decimal("0.01"))


def test_small_day_drives_real_estate_and_mutations_fail(tmp_path) -> None:
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small")
    run = run_firm(profile, seed=20261024, days=1)
    assert all(run.days[0].invariants.values())
    attacked = attack_firm_run(run)
    assert set(attacked) == set(MUTATIONS)
    assert all(attacked.values())
    assert {"I1_QUANTITY_MONEY_CONSERVE", "I11_POSITION_ROLL_FORWARD"} <= set(
        attacked["DROP_FILL_FROM_BOOKS"]
    )
    assert {"I1_QUANTITY_MONEY_CONSERVE", "I11_POSITION_ROLL_FORWARD"} <= set(
        attacked["DOUBLE_POST_NEW_EVENT"]
    )
    assert "I6_DEFAULT_AND_STALE_HOLD" in attacked["FORCE_RESERVE_PASS_ON_SHORT_DAY"]
    publish_firm(run, tmp_path)
    summary = json.loads((tmp_path / "run-summary.json").read_text())
    assert summary["profile"]["synthetic"]
    assert "real firm, account or security identifiers" in summary["not_claimed"]


def test_real_reserve_engine_lie_fails_i6(monkeypatch: pytest.MonkeyPatch) -> None:
    """SCF-1 WP4: force the real reserve engine to PASS while a deposit is short."""
    original = firm.compute_reserve

    def lying_reserve(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        return result.model_copy(update={"disposition": Disposition.PASS, "breaches": ()})

    monkeypatch.setattr(firm, "compute_reserve", lying_reserve)
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small")
    run = run_firm(
        profile,
        seed=20261024,
        days=1,
        mutation="FORCE_RESERVE_PASS_ON_SHORT_DAY",
        verify_replay=False,
    )
    assert any(not day.invariants["I6_DEFAULT_AND_STALE_HOLD"] for day in run.days)
