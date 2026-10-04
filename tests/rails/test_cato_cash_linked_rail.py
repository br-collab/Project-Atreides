"""A depository-linked rail is validated, not assumed (ORDER HYG-2).

Ladder rule 4 says the money side of a depository settlement has one rail,
determined by the linkage, and that the gate validates its availability
rather than choosing (CASH-001 SV.C.4). Before this order nothing validated
it: the gate returned PROCEED onto a linked rail that was closed, capped
below the notional, or missing from the rail state altogether.

There is nothing to fall back to. A linked settlement has one rail, so a
linked rail that cannot carry the operation is a HOLD, never a different
rail. Each case below keeps an open Fedwire in the rail state to prove the
gate does not route around the linkage.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from atreides.rails.cato_cash import (
    RAIL_FINALITY,
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
from atreides.rails.perimeter import SettlementPerimeter, continuously_available

NOTIONAL = Decimal("5000000")

#: The defect this file was written against, recorded before the fix. Strict,
#: so the suite fails the moment the defect is fixed until this marker is
#: removed: the fix and the evidence that it fixed something land together.
_DEFECT = pytest.mark.xfail(
    strict=True,
    reason="ORDER HYG-2: rule 4 returns the linked rail without validating it",
)


def _open_fedwire() -> dict[CashRail, RailState]:
    return {CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)}


def _op(linked: CashRail, **kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": NOTIONAL,
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
        "depository_linked_rail": linked,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _funded(obligation: Decimal = NOTIONAL) -> FundingState:
    return FundingState(
        projected_funded_position=Decimal("100000000000"),
        net_obligation=obligation,
        net_debit_cap_headroom=Decimal("100000000000"),
        clearing_fund_sufficient=True,
    )


def _eval(
    operation: OperationContext, linked_state: RailState | None
) -> CatoCashDecision:
    rails = _open_fedwire()
    if linked_state is not None:
        rails[linked_state.rail] = linked_state
    return evaluate(
        operation=operation,
        funding=_funded(operation.notional),
        rails=rails,
        ofr_stlfsi4=0.0,
    )


# --- a linked rail that cannot carry the operation holds -------------------


@pytest.mark.parametrize(
    ("linked", "state", "op_kw", "condition"),
    [
        pytest.param(
            CashRail.NSS_DTC_NSCC,
            RailState(CashRail.NSS_DTC_NSCC, RailStatus.CLOSED),
            {},
            "is not usable",
            id="closed",
        ),
        pytest.param(
            CashRail.NSS_DTC_NSCC,
            RailState(CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, -1),
            {},
            "is not usable",
            id="past-cutoff",
        ),
        pytest.param(
            CashRail.NSS_DTC_NSCC,
            RailState(
                CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200, Decimal("1000000")
            ),
            {},
            "value cap",
            id="over-value-cap",
        ),
        pytest.param(
            CashRail.NSS_DTC_NSCC,
            None,
            {},
            "is absent from the rail state",
            id="absent-from-rail-state",
        ),
        pytest.param(
            CashRail.TOKENIZED_DEPOSIT,
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE),
            {"within_business_hours": False},
            "not continuously available outside business hours",
            id="ledger-final-off-hours-perimeter-not-assessed",
        ),
        pytest.param(
            CashRail.TOKENIZED_DEPOSIT,
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE),
            {
                "within_business_hours": False,
                "settlement_perimeter": SettlementPerimeter.OFF_US,
            },
            "not continuously available outside business hours",
            id="ledger-final-off-hours-off-us",
        ),
        pytest.param(
            CashRail.PORTS_WHOLESALE,
            RailState(CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED),
            {},
            "reserved placeholder",
            id="ports-not-yet-issued",
        ),
        pytest.param(
            CashRail.PORTS_WHOLESALE,
            RailState(CashRail.PORTS_WHOLESALE, RailStatus.AVAILABLE),
            {},
            "reserved placeholder",
            id="ports-marked-available",
        ),
    ],
)
@_DEFECT
def test_a_linked_rail_that_cannot_carry_the_operation_holds(
    linked: CashRail,
    state: RailState | None,
    op_kw: dict[str, object],
    condition: str,
) -> None:
    decision = _eval(_op(linked, **op_kw), state)
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.NO_RAIL_IN_WINDOW
    assert decision.recommended_rail is None
    assert linked.value in decision.rationale
    assert condition in decision.rationale


@_DEFECT
def test_the_reserved_placeholder_holds_even_when_marked_available() -> None:
    """The one case ``_serviceable`` alone would pass. Check 6 excludes the
    PORTS placeholder by name, and the linked path must exclude it the same
    way, or a caller that flips its status settles onto infrastructure that
    does not exist."""
    decision = _eval(
        _op(CashRail.PORTS_WHOLESALE),
        RailState(CashRail.PORTS_WHOLESALE, RailStatus.AVAILABLE),
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.NO_RAIL_IN_WINDOW


# --- a serviceable linked rail still proceeds, on that rail -----------------


def test_a_serviceable_linked_rail_proceeds_on_that_rail() -> None:
    decision = _eval(
        _op(CashRail.NSS_DTC_NSCC),
        RailState(CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.reason_code is ReasonCode.CLEARED
    assert decision.recommended_rail is CashRail.NSS_DTC_NSCC
    assert decision.finality_class is FinalityClass.DEFERRED_NET
    assert "determined" in decision.rationale
    assert "CASH-001 SV.C.4" in decision.rationale


def test_a_linked_rail_within_its_value_cap_proceeds() -> None:
    decision = _eval(
        _op(CashRail.NSS_DTC_NSCC),
        RailState(CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200, NOTIONAL),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.NSS_DTC_NSCC


def test_an_on_us_ledger_final_linked_rail_proceeds_outside_business_hours() -> None:
    """On-us, a ledger-final rail is a book entry and is continuously
    available, so the off-hours condition does not apply."""
    decision = _eval(
        _op(
            CashRail.TOKENIZED_DEPOSIT,
            within_business_hours=False,
            settlement_perimeter=SettlementPerimeter.ON_US,
        ),
        RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.TOKENIZED_DEPOSIT


# --- property: a linked operation proceeds exactly when its rail can carry it


def _carries(
    rails: dict[CashRail, RailState], operation: OperationContext
) -> bool:
    """Serviceability restated from public parts, independent of the gate's
    own predicate, so the property checks the gate rather than itself."""
    linked = operation.depository_linked_rail
    assert linked is not None
    state = rails.get(linked)
    if state is None or linked is CashRail.PORTS_WHOLESALE:
        return False
    if not state.usable:
        return False
    if state.value_cap is not None and operation.notional > state.value_cap:
        return False
    if operation.within_business_hours:
        return True
    return continuously_available(
        is_ledger_final=RAIL_FINALITY.get(linked) is FinalityClass.LEDGER_FINAL,
        perimeter=operation.settlement_perimeter,
    )


_rail_states = st.builds(
    RailState,
    rail=st.sampled_from(CashRail),
    status=st.sampled_from(RailStatus),
    seconds_to_cutoff=st.none() | st.integers(min_value=-3600, max_value=86400),
    value_cap=st.none()
    | st.decimals(min_value=1, max_value=100_000_000, places=0),
)


@_DEFECT
@given(
    linked=st.sampled_from(CashRail),
    states=st.lists(_rail_states, max_size=len(CashRail)),
    notional=st.decimals(min_value=1, max_value=100_000_000, places=0),
    within_business_hours=st.booleans(),
    perimeter=st.sampled_from(SettlementPerimeter),
)
def test_a_linked_operation_proceeds_exactly_when_its_rail_can_carry_it(
    linked: CashRail,
    states: list[RailState],
    notional: Decimal,
    within_business_hours: bool,
    perimeter: SettlementPerimeter,
) -> None:
    rails = {state.rail: state for state in states}
    operation = _op(
        linked,
        notional=notional,
        within_business_hours=within_business_hours,
        settlement_perimeter=perimeter,
    )
    decision = evaluate(
        operation=operation, funding=_funded(notional), rails=rails, ofr_stlfsi4=0.0
    )
    # Every other check passes here (funded, unstressed, immaterial), so the
    # linked rail alone decides, and it must decide in both directions: a
    # gate that held everything would satisfy the first half on its own.
    if _carries(rails, operation):
        assert decision.decision is GateDecision.PROCEED
        assert decision.recommended_rail is linked
    else:
        assert decision.decision is GateDecision.HOLD
        assert decision.reason_code is ReasonCode.NO_RAIL_IN_WINDOW
        assert decision.recommended_rail is None
