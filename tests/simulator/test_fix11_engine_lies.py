"""FIX-11: every protection engine is caught lying in both directions.

Each lie patches the real engine result inside the firm run and changes its breaches,
reasons and missing inputs to match its new disposition, so a check that reads the
engine's own findings cannot see it. I6 must still turn false on every close the lie
changes, because the required outcome comes from declared inputs and the books
(``simulator.protection_oracle`` and the SIM-1G deposit outcome).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition

from simulator import firm
from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack

I6 = "I6_DEFAULT_AND_STALE_HOLD"
DAYS = 2
LOW_NET_WORTH = Decimal("1000000")


def _profile() -> firm.FirmProfile:
    return load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small")


def _run(**kwargs: Any) -> firm.FirmRun:
    return run_firm(_profile(), days=DAYS, verify_replay=False, **kwargs)


def _lied(result: Any, disposition: Disposition) -> Any:
    update: dict[str, object] = {"disposition": disposition}
    fields = type(result).model_fields
    if disposition is Disposition.PASS:
        for name in ("breaches", "reasons", "missing_inputs"):
            if name in fields:
                update[name] = ()
    elif "breaches" in fields:
        update["breaches"] = ("FIX-11 lie: made-up breach",)
    return result.model_copy(update=update)


def _patch(monkeypatch: pytest.MonkeyPatch, engine: str, disposition: Disposition) -> None:
    if engine in {"reserve", "pab_reserve"}:
        original = firm._post_reserve_deposits

        def lying_deposits(*args: Any, **kwargs: Any) -> Any:
            customer, pab, deposits = original(*args, **kwargs)
            if engine == "reserve":
                return _lied(customer, disposition), pab, deposits
            return customer, _lied(pab, disposition), deposits

        monkeypatch.setattr(firm, "_post_reserve_deposits", lying_deposits)
        return
    name = "compute_net_capital" if engine == "net_capital" else "check_possession_or_control"
    real: Callable[..., Any] = getattr(firm, name)

    def lying(*args: Any, **kwargs: Any) -> Any:
        return _lied(real(*args, **kwargs), disposition)

    monkeypatch.setattr(firm, name, lying)


#: (engine, the honest-run inputs that make the engine's true answer the opposite of the lie)
ENGINES = ("reserve", "pab_reserve", "net_capital", "possession_or_control")
HOLD_CASES = {
    "reserve": {"reserve_stress": "customer"},
    "pab_reserve": {"reserve_stress": "pab"},
    "net_capital": {"net_worth": LOW_NET_WORTH},
    "possession_or_control": {},
}


@pytest.mark.parametrize("engine", ENGINES)
def test_wrongful_hold_on_a_passing_close_fails_i6(
    monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    honest = _run()
    passing = [
        index
        for index, day in enumerate(honest.days)
        if day.protection_dispositions[engine] == "PASS"
    ]
    assert passing, "the honest run must contain a passing close for this engine"
    assert all(honest.days[index].invariants[I6] for index in passing)
    _patch(monkeypatch, engine, Disposition.HOLD)
    lied = _run()
    assert all(not lied.days[index].invariants[I6] for index in passing)


@pytest.mark.parametrize("engine", ENGINES)
def test_wrongful_pass_on_a_holding_close_fails_i6(
    monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    inputs = HOLD_CASES[engine]
    honest = _run(**inputs)
    holding = [
        index for index, day in enumerate(honest.days) if day.protection_required[engine] == "HOLD"
    ]
    assert holding, "the honest inputs must make this engine's true answer HOLD"
    assert all(honest.days[index].protection_dispositions[engine] == "HOLD" for index in holding)
    assert all(honest.days[index].invariants[I6] for index in holding)
    _patch(monkeypatch, engine, Disposition.PASS)
    lied = _run(**inputs)
    assert all(lied.days[index].protection_dispositions[engine] == "PASS" for index in holding)
    assert all(not lied.days[index].invariants[I6] for index in holding)


def test_claude_d1_reproductions_now_fail_i6(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two lies Claude ran against 74d62eb, which left every invariant green."""
    _patch(monkeypatch, "net_capital", Disposition.HOLD)
    assert not _run().days[0].invariants[I6]
    monkeypatch.undo()
    _patch(monkeypatch, "possession_or_control", Disposition.PASS)
    assert not _run().days[1].invariants[I6]


def test_control_leg_computes_and_holds_only_on_the_declared_deficit() -> None:
    run = run_firm(_profile(), days=3, verify_replay=False)
    control = [day.protection_dispositions["possession_or_control"] for day in run.days]
    assert control == ["PASS", "HOLD", "PASS"]
    reasons = run.days[1].protection_reasons["possession_or_control"]
    assert any("SYN-SCF1-ISSUE-0000: 100 " in reason for reason in reasons)
    assert not any(
        reason.startswith("excess_margin[")
        for day in run.days
        for reason in day.protection_reasons["possession_or_control"]
    )
    assert all(all(day.invariants.values()) for day in run.days)


def test_independent_net_capital_ties_to_the_engine_to_the_cent() -> None:
    for day in _run().days:
        figures = day.protection_figures
        assert figures["independent_net_capital"] == figures["net_capital"]
