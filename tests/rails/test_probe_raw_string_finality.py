"""ATR-I-05 regression: enum values are coerced at the boundary, never fail open.

``project_funding`` and Cato Cash compare enum members by identity. Until Wave 2
a finality class arriving as a plain string (from JSON, a dict, a caller)
matched no identity check and fell through to FUNDED. The Atreides inventory
probe (15 Sep 2026, commit 31b62f0) and stress case E2.5 both showed it.

Fixed in W2A-1 (``atreides.rails.boundary``): a string equal to a member's
value becomes that member; anything else is kept, reported as unrecognised,
and refused - INDETERMINATE from the funding model, HOLD from the gate. Both
spellings from the W0 probe are covered: the enum's own value, and the
lower-case form named in the Wave 0 order.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from atreides.rails.boundary import coerce_member, describe, unrecognised
from atreides.rails.cato_cash import (
    CashRail,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)
from atreides.rails.determination import DeterminationOutcome
from atreides.rails.finality import FinalityClass
from atreides.rails.funding_state import FundingDisposition, FundingInputs, project_funding
from atreides.rails.perimeter import SettlementPerimeter

D = Decimal


def _inputs(finality_class: Any, **changes: Any) -> FundingInputs:
    # Well funded on every other axis, so FUNDED is the answer unless a
    # refusing branch is taken.
    fields: dict[str, Any] = {
        "opening_position": D("10000000"),
        "obligation": D("1000000"),
        "finality_class": finality_class,
        "settlement_offset_seconds": 3600,
        "window_close_offset_seconds": 14400,
        "net_debit_cap": D("50000000"),
        "clearing_fund_requirement": D("500000"),
        "clearing_fund_posted": D("500000"),
    }
    fields.update(changes)
    return FundingInputs(**fields)


def test_enum_correspondent_dependent_is_indeterminate() -> None:
    projection = project_funding(_inputs(FinalityClass.CORRESPONDENT_DEPENDENT))
    assert projection.disposition is FundingDisposition.INDETERMINATE


def test_exact_value_string_is_coerced_to_the_member() -> None:
    inputs = _inputs("CORRESPONDENT_DEPENDENT")
    assert inputs.finality_class is FinalityClass.CORRESPONDENT_DEPENDENT
    assert inputs.unrecognised_fields == ()
    assert project_funding(inputs).disposition is FundingDisposition.INDETERMINATE


@pytest.mark.parametrize(
    "raw", ["correspondent_dependent", "Correspondent_Dependent", "GROSS", "", 3, None]
)
def test_unrecognised_finality_class_is_indeterminate_never_funded(raw: object) -> None:
    projection = project_funding(_inputs(raw))
    assert projection.disposition is FundingDisposition.INDETERMINATE
    assert "Unrecognised input" in projection.rationale
    assert "ATR-I-05" in projection.rationale


def test_wrongly_cased_gross_final_is_not_treated_as_gross_final() -> None:
    # The member would be FUNDED here; a misspelling must not be.
    assert project_funding(_inputs(FinalityClass.GROSS_FINAL)).disposition is (
        FundingDisposition.FUNDED
    )
    assert project_funding(_inputs("gross_final")).disposition is (
        FundingDisposition.INDETERMINATE
    )


def test_unrecognised_determination_outcome_is_indeterminate() -> None:
    projection = project_funding(
        _inputs(FinalityClass.GROSS_FINAL, determination_outcome="AWAITING_DETERMINATION")
    )
    assert projection.disposition is FundingDisposition.INDETERMINATE
    assert projection.determination_outcome is DeterminationOutcome.QUALIFICATION_UNKNOWN
    coerced = _inputs(FinalityClass.GROSS_FINAL, determination_outcome="awaiting_determination")
    assert coerced.determination_outcome is DeterminationOutcome.AWAITING_DETERMINATION


def test_stress_e2_5_json_string_matches_the_enum_result() -> None:
    # Stress case E2.5: a finality class arriving as a plain string from JSON.
    payload = json.loads(
        '{"opening_position": "1000", "obligation": "10", '
        '"finality_class": "DETERMINATION_DEPENDENT", "settlement_offset_seconds": 3600}'
    )
    from_json = FundingInputs(
        opening_position=D(payload["opening_position"]),
        obligation=D(payload["obligation"]),
        finality_class=payload["finality_class"],
        settlement_offset_seconds=payload["settlement_offset_seconds"],
    )
    from_enum = FundingInputs(
        opening_position=D("1000"),
        obligation=D("10"),
        finality_class=FinalityClass.DETERMINATION_DEPENDENT,
        settlement_offset_seconds=3600,
    )
    assert project_funding(from_json).disposition is project_funding(from_enum).disposition


# ---- Cato Cash -------------------------------------------------------------------------------


def _funding() -> FundingState:
    return FundingState(
        projected_funded_position=D("5000000"),
        net_obligation=D("1000000"),
        net_debit_cap_headroom=D("10000000"),
        clearing_fund_sufficient=True,
    )


def _rails() -> dict[CashRail, RailState]:
    return {CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)}


def _operation(**changes: Any) -> OperationContext:
    fields: dict[str, Any] = {
        "notional": D("1000000"),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
        "settlement_perimeter": SettlementPerimeter.OFF_US,
    }
    fields.update(changes)
    return OperationContext(**fields)


def test_gate_coerces_exact_value_strings() -> None:
    op = _operation(settlement_perimeter="OFF_US", determination_outcome="not_applicable")
    assert op.settlement_perimeter is SettlementPerimeter.OFF_US
    assert op.determination_outcome is DeterminationOutcome.NOT_APPLICABLE
    as_strings = evaluate(operation=op, funding=_funding(), rails=_rails(), ofr_stlfsi4=0.0)
    as_members = evaluate(
        operation=_operation(), funding=_funding(), rails=_rails(), ofr_stlfsi4=0.0
    )
    assert as_strings == as_members


@pytest.mark.parametrize(
    "changes",
    [
        {"determination_outcome": "AWAITING_DETERMINATION"},
        {"settlement_perimeter": "on_us"},
        {"depository_linked_rail": "FEDWIRE"},
    ],
)
def test_gate_holds_on_an_unrecognised_operation_input(changes: dict[str, Any]) -> None:
    decision = evaluate(
        operation=_operation(**changes), funding=_funding(), rails=_rails(), ofr_stlfsi4=0.0
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.INPUT_UNRECOGNISED
    (name,) = changes
    expected = ((f"unrecognised:{name}", f"UNRECOGNISED:{changes[name]!r}"),)
    assert decision.checks_evaluated == expected


def test_rail_state_coerces_and_an_unrecognised_status_is_never_usable() -> None:
    assert RailState("fedwire", "available", 7200).usable  # type: ignore[arg-type]
    assert RailState(CashRail.FEDWIRE, "AVAILABLE", 7200).status == "AVAILABLE"  # type: ignore[arg-type]
    assert not RailState(CashRail.FEDWIRE, "AVAILABLE", 7200).usable  # type: ignore[arg-type]


def test_boundary_helpers() -> None:
    assert coerce_member(RailStatus, "closed") is RailStatus.CLOSED
    assert coerce_member(RailStatus, RailStatus.CLOSED) is RailStatus.CLOSED
    assert coerce_member(RailStatus, "CLOSED") == "CLOSED"
    assert coerce_member(RailStatus, b"closed") == b"closed"
    assert unrecognised(a=(RailStatus, RailStatus.CLOSED), b=(RailStatus, "x")) == ("b",)
    assert describe(RailStatus.CLOSED) == "closed"
    assert describe("x") == "UNRECOGNISED:'x'"
