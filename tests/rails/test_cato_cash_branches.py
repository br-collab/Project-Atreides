"""Deterministic example tests for Cato Cash branches that randomness reached.

The per-file branch floor on ``atreides/rails/cato_cash.py`` was met on some
Hypothesis seeds and missed on others, because the only test reaching one
ladder branch was a property test that reached it by chance (ORDER HYG-1).
A floor that depends on the seed is not a floor. Every test here is a plain
example, so the branches it covers are covered on every run, and the
``floor`` Hypothesis profile in ``tests/conftest.py`` exists to prove that.

Each test names the branch it pins by the condition, not by a line number,
because line numbers move and conditions do not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.rails.cato_cash import (
    CashRail,
    CatoCashDecision,
    FinalityClass,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)


def _rails(**overrides: RailState | None) -> dict[CashRail, RailState]:
    """Standard rail state, with overrides; ``None`` removes a rail."""
    base: dict[CashRail, RailState] = {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, None, Decimal("10000000")
        ),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }
    for name, state in overrides.items():
        rail = CashRail(name)
        if state is None:
            base.pop(rail, None)
        else:
            base[rail] = state
    return base


def _op(notional: str = "1000000", **kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": Decimal(notional),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _funded(obligation: str = "1000000") -> FundingState:
    return FundingState(
        projected_funded_position=Decimal("100000000000"),
        net_obligation=Decimal(obligation),
        net_debit_cap_headroom=Decimal("100000000000"),
        clearing_fund_sufficient=True,
    )


def _eval(
    operation: OperationContext, rails: dict[CashRail, RailState]
) -> CatoCashDecision:
    return evaluate(
        operation=operation,
        funding=_funded(str(operation.notional)),
        rails=rails,
        ofr_stlfsi4=0.0,
    )


def _assert_default_fedwire(decision: CatoCashDecision) -> None:
    assert decision.decision is GateDecision.PROCEED
    assert decision.reason_code is ReasonCode.CLEARED
    assert decision.recommended_rail is CashRail.FEDWIRE
    assert decision.finality_class is FinalityClass.GROSS_FINAL
    assert decision.rationale.startswith("Default rail (CASH-001 SV.C.6).")


# --- WP-1: the tokenized preference falls through to the Fedwire default ---
#
# Rule 5 prefers a tokenized-deposit rail when both counterparties support
# one. Where that rail cannot carry the operation, rule 5 does not apply and
# rule 6, the Fedwire default, decides (CASH-001 SV.C.5 and SV.C.6). Before
# these tests only random property examples reached that fall through.


@pytest.mark.parametrize(
    "tokenized_state",
    [
        pytest.param(None, id="tokenized-rail-absent"),
        pytest.param(
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.CLOSED),
            id="tokenized-rail-closed",
        ),
        pytest.param(
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, -1),
            id="tokenized-rail-past-cutoff",
        ),
    ],
)
def test_supported_but_unusable_tokenized_rail_falls_through_to_fedwire(
    tokenized_state: RailState | None,
) -> None:
    """Both counterparties support tokenized deposits, but the tokenized rail
    is not among the usable rails. Support is not availability."""
    decision = _eval(
        _op(tokenized_deposit_supported=True),
        _rails(tokenized_deposit=tokenized_state),
    )
    _assert_default_fedwire(decision)


def test_tokenized_rail_over_its_value_cap_falls_through_to_fedwire() -> None:
    """The tokenized rail is open, but the notional exceeds its value cap, so
    it cannot carry the operation and the default decides. Also the only
    example that exercises the value cap test inside the ladder's preference
    helper."""
    capped = RailState(
        CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None, Decimal("500000")
    )
    decision = _eval(
        _op("1000000", tokenized_deposit_supported=True),
        _rails(tokenized_deposit=capped),
    )
    _assert_default_fedwire(decision)


def test_tokenized_rail_within_its_value_cap_is_still_preferred() -> None:
    """Control for the test above: the same capped rail wins when the
    operation fits, so the fall through is caused by the cap and nothing
    else."""
    capped = RailState(
        CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None, Decimal("500000")
    )
    decision = _eval(
        _op("400000", tokenized_deposit_supported=True),
        _rails(tokenized_deposit=capped),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.TOKENIZED_DEPOSIT
    assert "CASH-001 SV.C.5" in decision.rationale
