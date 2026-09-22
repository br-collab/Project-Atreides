"""ATR-I-04 regression: a Cato Cash decision is bound, evidenced, stored and replayable.

Before Wave 2 a gate decision carried no reference to the obligation it
governed, a PROCEED with zero checks constructed (stress case H6.3), and the
DSOR output union had no member that could carry a gate decision (stress case
E7.5). Fixed in W2A-3.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter

from atreides.dsor import DSORStore
from atreides.dsor.record import AureonOutput
from atreides.rails.cato_cash import (
    GATE_SET_VERSION,
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
from atreides.rails.cato_cash_record import CatoCashDecisionRecord

D = Decimal
OBLIGATION = "obl_01M2P20SY00000000000000001"
DIGEST = "sha256:" + "ab" * 32


def _inputs(**changes: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "operation": OperationContext(
            notional=D("1000000.00"), currency="USD", is_material=False, is_lvps_material=False
        ),
        "funding": FundingState(D("5000000"), D("1000000"), D("10000000"), True),
        "rails": {CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        "ofr_stlfsi4": 0.0,
        "obligation_id": OBLIGATION,
        "obligation_digest": DIGEST,
    }
    inputs.update(changes)
    return inputs


def test_decision_carries_the_obligation_and_gate_set_version() -> None:
    decision = evaluate(**_inputs())
    assert decision.proceeds
    assert decision.bound
    assert (decision.obligation_id, decision.obligation_digest) == (OBLIGATION, DIGEST)
    assert decision.gate_set_version == GATE_SET_VERSION
    assert decision.checks_evaluated


def _proceed(**changes: Any) -> CatoCashDecision:
    fields: dict[str, Any] = {
        "decision": GateDecision.PROCEED,
        "reason_code": ReasonCode.CLEARED,
        "recommended_rail": CashRail.FEDWIRE,
        "finality_class": FinalityClass.GROSS_FINAL,
        "rationale": "",
        "checks_evaluated": (("x", "y"),),
        "funding_state_snapshot": (),
    }
    fields.update(changes)
    return CatoCashDecision(**fields)


def test_stress_h6_3_proceed_with_no_checks_is_refused() -> None:
    with pytest.raises(ValueError, match="must record the checks"):
        _proceed(checks_evaluated=())
    held = _proceed(
        decision=GateDecision.HOLD, reason_code=ReasonCode.BROAD_STRESS_HOLD, checks_evaluated=()
    )
    assert not held.proceeds


def test_stress_h6_3_json_boundary_cannot_forge_an_evidence_free_proceed() -> None:
    adapter = TypeAdapter(CatoCashDecision)
    raw = json.loads(adapter.dump_json(_proceed()))
    raw["checks_evaluated"] = []
    with pytest.raises(ValueError, match="must record the checks"):
        adapter.validate_python(raw)
    raw["checks_evaluated"] = [["x", "y"]]
    assert adapter.validate_python(raw).proceeds


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"obligation_id": OBLIGATION}, "together"),
        ({"obligation_digest": DIGEST}, "together"),
        (
            {"obligation_id": "lif_01M2P20SY00000000000000001", "obligation_digest": DIGEST},
            "must start with 'obl_'",
        ),
        ({"obligation_id": OBLIGATION, "obligation_digest": "sha256:XYZ"}, "64 lower-case hex"),
        ({"gate_set_version": ""}, "gate_set_version"),
        ({"decision": "proceed"}, "unrecognised gate decision"),
        ({"reason_code": "cleared"}, "unrecognised reason code"),
    ],
)
def test_malformed_decision_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _proceed(**changes)


def test_decision_strings_are_coerced() -> None:
    assert _proceed(decision="PROCEED", reason_code="CLEARED").decision is GateDecision.PROCEED


# ---- Decision of record ---------------------------------------------------------------------


def test_stress_e7_5_the_output_union_carries_a_gate_decision() -> None:
    assert "CatoCashDecisionRecord" in str(AureonOutput)


@pytest.mark.parametrize("ofr", [0.0, 0.75, 1.5, float("nan"), float("inf")])
def test_decision_replayed_from_the_dsor_reproduces_the_same_decision(ofr: float) -> None:
    record = CatoCashDecisionRecord.capture(
        decision_id=uuid.uuid4(), settlement_operation_id=uuid.uuid4(), **_inputs(ofr_stlfsi4=ofr)
    )
    store = DSORStore(":memory:")
    stored = store.append(record)
    replayed = store.replay(stored.record_id)
    assert isinstance(replayed, CatoCashDecisionRecord)
    assert stored.kind == "cash_gate_decision"
    assert replayed.decision == record.decision
    assert replayed.replay() == record.decision
    assert replayed.reproduces() is True


def test_several_decisions_for_one_operation_do_not_collide_in_the_store() -> None:
    operation = uuid.uuid4()
    store = DSORStore(":memory:")
    for ofr in (0.0, 0.75):
        store.append(
            CatoCashDecisionRecord.capture(
                decision_id=uuid.uuid4(),
                settlement_operation_id=operation,
                **_inputs(ofr_stlfsi4=ofr),
            )
        )


def test_a_tampered_decision_does_not_reproduce() -> None:
    record = CatoCashDecisionRecord.capture(decision_id=uuid.uuid4(), **_inputs(ofr_stlfsi4=1.5))
    assert record.decision.decision is GateDecision.ESCALATE
    tampered = record.model_copy(update={"decision": evaluate(**_inputs())})
    assert tampered.reproduces() is False


def test_a_record_from_another_gate_set_version_is_not_judged() -> None:
    record = CatoCashDecisionRecord.capture(decision_id=uuid.uuid4(), **_inputs())
    older = record.model_copy(update={"gate_set_version": "cato-cash-gates/0.2"})
    assert older.reproduces() is None
