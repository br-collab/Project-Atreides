"""ATR-I-01: obligation acceptance, 0.1-draft (W2A-4).

Atreides accepts or refuses an obligation formed elsewhere and never rewrites its
economics. The record references the obligation by id and digest; preparation
of an instruction requires an ACCEPTED record for the same digest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import ActorId, HaltId
from pydantic import ValidationError

from atreides.acceptance import (
    ACCEPTANCE_RULE_VERSION,
    AcceptanceOutcome,
    CashLeg,
    ExpectedFinality,
    ObligationAcceptanceRecord,
    ObligationCandidate,
    Participant,
    PredicateResult,
    PreparationRefusedError,
    SecuritiesLeg,
    SourceReference,
    evaluate_candidate,
    prepare_instruction,
)
from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import PreparationHaltedError
from atreides.rails.cato_f import (
    CashRail,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)

T = datetime(2026, 9, 17, 16, 0, tzinfo=UTC)
D = Decimal
OBL = "obl_01M2P20SY00000000000000001"
LIF = "lif_01M2P20SY00000000000000001"


def _candidate(**changes: Any) -> ObligationCandidate:
    fields: dict[str, Any] = {
        "obligation_id": OBL,
        "obligation_version": 1,
        "lifecycle_id": LIF,
        "delivery_pattern": "DVP",
        "source_references": (
            SourceReference(reference_type="execution", reference_id="exe-1", digest=None),
        ),
        "securities_leg": SecuritiesLeg(
            lifecycle_id=LIF,
            delivery_pattern="DVP",
            instrument_id="912828XX1",
            quantity=D("1000000"),
            deliverer_participant_id="P-SELLER",
            receiver_participant_id="P-BUYER",
        ),
        "cash_leg": CashLeg(
            lifecycle_id=LIF,
            delivery_pattern="DVP",
            principal=D("995000.00"),
            accrued_interest=D("1234.56"),
            total=D("996234.56"),
            currency="USD",
            value_date="2026-09-18",
            payer_participant_id="P-BUYER",
            payee_participant_id="P-SELLER",
        ),
        "participants": (
            Participant(participant_id="P-BUYER", role="buyer"),
            Participant(participant_id="P-SELLER", role="seller"),
        ),
        "expected_finality": (
            ExpectedFinality(leg="securities", finality_type="ASSET_FINAL"),
            ExpectedFinality(leg="cash", finality_type="CASH_FINAL"),
        ),
    }
    fields.update(changes)
    return ObligationCandidate(**fields)


def _gate(candidate: ObligationCandidate, *, ofr: float = 0.0, **binding: Any) -> Any:
    return evaluate(
        operation=OperationContext(
            notional=D("996234.56"), currency="USD", is_material=False, is_lvps_material=False
        ),
        funding=FundingState(D("5000000"), D("996234.56"), D("10000000"), True),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=ofr,
        obligation_id=binding.get("obligation_id", candidate.obligation_id),
        obligation_digest=binding.get("obligation_digest", digest(candidate)),
    )


def _halt(*, active: bool = True, scope: Any = "ALL") -> HaltContext:
    return HaltContext(
        halt_id=HaltId("hlt_" + "3" * 26),
        version=4,
        active=active,
        scope=scope,
        declared_by=ActorRef(
            actor_id=ActorId("act_" + "3" * 26),
            actor_kind=ActorKind.HUMAN,
            role="operator",
            entitlement_refs=(),
            authenticated=True,
        ),
        declared_at=T,
        reason="drill",
    )


def _evaluate(candidate: ObligationCandidate, **kw: Any) -> ObligationAcceptanceRecord:
    kw.setdefault("gate_decision", _gate(candidate))
    kw.setdefault("halt", None)
    return evaluate_candidate(candidate, acceptance_id=uuid.uuid4(), evaluated_at=T, **kw)


def _by_name(record: ObligationAcceptanceRecord) -> dict[str, PredicateResult]:
    return {p.predicate: p for p in record.evaluated_predicates}


# ---- Accepted path ---------------------------------------------------------------------------


def test_clean_candidate_with_a_bound_proceed_is_accepted() -> None:
    candidate = _candidate()
    record = _evaluate(candidate)
    assert record.outcome is AcceptanceOutcome.ACCEPTED
    assert record.disposition is Disposition.PASS
    assert record.accepted and record.accepted_at == T
    assert record.obligation_digest == digest(candidate)
    assert record.rule_version == ACCEPTANCE_RULE_VERSION
    assert record.reason_codes == ()
    assert dict(record.data_versions)["cato_f_gate_set"] == "cato-f-gates/0.3"
    assert set(_by_name(record)) == {
        "required_fields_present",
        "no_unknown_enums",
        "leg_linkage",
        "halt_not_active",
        "funding_bound",
    }


def test_the_record_references_the_obligation_and_copies_no_economics() -> None:
    record = _evaluate(_candidate())
    dumped = record.model_dump_json()
    for economic in ("996234.56", "995000.00", "912828XX1", "P-BUYER", "USD"):
        assert economic not in dumped
    assert record.digest().startswith("sha256:")


def test_evaluation_never_changes_the_candidate() -> None:
    candidate = _candidate()
    before = digest(candidate)
    snapshot = candidate.model_dump()
    for kw in ({}, {"halt": _halt()}, {"gate_decision": None}):
        _evaluate(candidate, **kw)
    assert digest(candidate) == before
    assert candidate.model_dump() == snapshot


def test_free_of_payment_needs_no_cash_leg_or_gate() -> None:
    fop = _candidate(
        delivery_pattern="FOP",
        securities_leg=_candidate().securities_leg.model_copy(update={"delivery_pattern": "FOP"}),  # type: ignore[union-attr]
        cash_leg=None,
        expected_finality=(ExpectedFinality(leg="securities", finality_type="ASSET_FINAL"),),
    )
    assert _evaluate(fop, gate_decision=None).outcome is AcceptanceOutcome.ACCEPTED


def test_payment_only_needs_no_securities_leg() -> None:
    cash = _candidate().cash_leg.model_copy(update={"delivery_pattern": "PAYMENT_ONLY"})  # type: ignore[union-attr]
    payment = _candidate(
        delivery_pattern="PAYMENT_ONLY",
        securities_leg=None,
        cash_leg=cash,
        expected_finality=(ExpectedFinality(leg="cash", finality_type="CASH_FINAL"),),
    )
    assert _evaluate(payment).outcome is AcceptanceOutcome.ACCEPTED


# ---- Each predicate --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"obligation_version": None}, "MISSING:obligation_version"),
        ({"lifecycle_id": None}, "MISSING:lifecycle_id"),
        ({"delivery_pattern": None}, "MISSING:delivery_pattern"),
        ({"source_references": ()}, "MISSING:source_references"),
        ({"participants": ()}, "MISSING:participants"),
        ({"securities_leg": None}, "MISSING:securities_leg"),
        ({"cash_leg": None}, "MISSING:cash_leg"),
        ({"expected_finality": ()}, "MISSING:expected_finality.cash"),
    ],
)
def test_missing_required_field_is_rejected(changes: dict[str, Any], code: str) -> None:
    record = _evaluate(_candidate(**changes))
    assert record.outcome is AcceptanceOutcome.REJECTED
    assert code in _by_name(record)["required_fields_present"].reason_codes


def test_missing_leg_fields_are_named() -> None:
    thin = _candidate(cash_leg=CashLeg(lifecycle_id=LIF, delivery_pattern="DVP"))
    codes = _by_name(_evaluate(thin))["required_fields_present"].reason_codes
    assert "MISSING:cash_leg.total" in codes
    assert "MISSING:cash_leg.value_date" in codes


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"delivery_pattern": "dvp"}, "UNKNOWN_ENUM:delivery_pattern"),
        (
            {
                "expected_finality": (
                    ExpectedFinality(leg="cash", finality_type="SETTLED"),
                    ExpectedFinality(leg="securities", finality_type="ASSET_FINAL"),
                )
            },
            "UNKNOWN_ENUM:expected_finality[0].finality_type",
        ),
    ],
)
def test_unknown_enum_is_indeterminate_never_accepted(changes: dict[str, Any], code: str) -> None:
    candidate = _candidate(**changes)
    record = _evaluate(candidate)
    assert record.outcome in {AcceptanceOutcome.INDETERMINATE, AcceptanceOutcome.REJECTED}
    assert code in record.reason_codes
    assert _by_name(record)["no_unknown_enums"].disposition is Disposition.INDETERMINATE


def test_unknown_enum_alone_is_indeterminate() -> None:
    finality = (
        ExpectedFinality(leg="securities", finality_type="asset_final"),
        ExpectedFinality(leg="cash", finality_type="CASH_FINAL"),
    )
    assert _evaluate(_candidate(expected_finality=finality)).outcome is (
        AcceptanceOutcome.INDETERMINATE
    )


@pytest.mark.parametrize(
    ("leg", "update", "code"),
    [
        (
            "cash_leg",
            {"lifecycle_id": "lif_01M2P20SY00000000000000009"},
            "LEG_LIFECYCLE_MISMATCH:cash_leg",
        ),
        (
            "securities_leg",
            {"delivery_pattern": "FOP"},
            "LEG_DELIVERY_PATTERN_MISMATCH:securities_leg",
        ),
    ],
)
def test_unlinked_legs_are_rejected(leg: str, update: dict[str, Any], code: str) -> None:
    changed = getattr(_candidate(), leg).model_copy(update=update)
    record = _evaluate(_candidate(**{leg: changed}))
    assert record.outcome is AcceptanceOutcome.REJECTED
    assert code in _by_name(record)["leg_linkage"].reason_codes


def test_active_halt_holds_and_records_its_version() -> None:
    record = _evaluate(_candidate(), halt=_halt())
    assert record.outcome is AcceptanceOutcome.HELD
    assert record.halt_context_version == 4
    assert "HALT_ACTIVE" in record.reason_codes
    other = _evaluate(_candidate(), halt=_halt(scope=(Domain.AUREON,)))
    assert other.outcome is AcceptanceOutcome.ACCEPTED
    assert other.halt_context_version == 4


@pytest.mark.parametrize(
    ("gate", "code"),
    [
        (lambda c: None, "CASH_GATE_DECISION_MISSING"),
        (lambda c: _gate(c, obligation_id=None, obligation_digest=None), "CASH_GATE_UNBOUND"),
        (
            lambda c: _gate(c, obligation_id="obl_01M2P20SY00000000000000009"),
            "CASH_GATE_OTHER_OBLIGATION",
        ),
        (lambda c: _gate(c, obligation_digest="sha256:" + "0" * 64), "CASH_GATE_STALE_DIGEST"),
    ],
)
def test_funding_evidence_that_is_not_about_this_obligation_is_indeterminate(
    gate: Any, code: str
) -> None:
    candidate = _candidate()
    record = _evaluate(candidate, gate_decision=gate(candidate))
    assert record.outcome is AcceptanceOutcome.INDETERMINATE
    assert record.reason_codes == (code,)


@pytest.mark.parametrize(
    ("ofr", "decision"), [(0.75, GateDecision.HOLD), (1.5, GateDecision.ESCALATE)]
)
def test_bound_gate_hold_or_escalate_holds(ofr: float, decision: GateDecision) -> None:
    candidate = _candidate()
    gate = _gate(candidate, ofr=ofr)
    assert gate.decision is decision
    record = _evaluate(candidate, gate_decision=gate)
    assert record.outcome is AcceptanceOutcome.HELD
    assert record.reason_codes[0].startswith(f"CASH_GATE_{decision.value}:")


def test_the_most_severe_predicate_decides() -> None:
    record = _evaluate(_candidate(lifecycle_id=None), halt=_halt(), gate_decision=None)
    assert record.outcome is AcceptanceOutcome.REJECTED
    assert record.disposition is Disposition.BLOCK


def test_candidate_refuses_floats_and_bad_dates() -> None:
    with pytest.raises(ValidationError):
        CashLeg(total=996234.56)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        CashLeg(value_date="18/09/2026")


def test_record_is_internally_consistent() -> None:
    record = _evaluate(_candidate())
    with pytest.raises(ValidationError, match="domain word"):
        ObligationAcceptanceRecord.model_validate(
            {**record.model_dump(), "outcome": AcceptanceOutcome.HELD}
        )
    with pytest.raises(ValidationError, match="accepted_at"):
        ObligationAcceptanceRecord.model_validate({**record.model_dump(), "accepted_at": None})
    with pytest.raises(ValidationError, match="timezone-aware"):
        ObligationAcceptanceRecord.model_validate(
            {**record.model_dump(), "evaluated_at": datetime(2026, 9, 17), "accepted_at": T}
        )
    with pytest.raises(ValidationError, match="names a reason code"):
        PredicateResult(predicate="x", disposition=Disposition.HOLD, detail="y")


# ---- Preparation -----------------------------------------------------------------------------


def _instruction() -> CashLegInstruction:
    return CashLegInstruction(
        message_id="AUR20260917000002",
        end_to_end_id="E2E-0002",
        created_at=T,
        amount=D("996234.56"),
        currency="USD",
        debtor=FinancialInstitution("DDDDUS33"),
        creditor=FinancialInstitution("EEEEUS33"),
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=FinancialInstitution("DDDDUS33"),
        receiver=FinancialInstitution("FFFFUS33"),
    )


def test_preparation_proceeds_only_against_an_accepted_record_for_the_same_digest() -> None:
    candidate = _candidate()
    accepted = _evaluate(candidate)
    artifact = prepare_instruction(candidate, accepted, _instruction())
    assert artifact.is_submission is False


def test_preparation_is_refused_without_an_accepted_record() -> None:
    candidate = _candidate()
    with pytest.raises(PreparationRefusedError, match="No acceptance record"):
        prepare_instruction(candidate, None, _instruction())
    held = _evaluate(candidate, halt=_halt())
    with pytest.raises(PreparationRefusedError, match="HELD, not ACCEPTED"):
        prepare_instruction(candidate, held, _instruction())


def test_preparation_is_refused_for_another_version_of_the_obligation() -> None:
    candidate = _candidate()
    accepted = _evaluate(candidate)
    revised = _candidate(obligation_version=2)
    with pytest.raises(PreparationRefusedError, match=r"not .* at"):
        prepare_instruction(revised, accepted, _instruction())


def test_preparation_still_honours_a_halt() -> None:
    candidate = _candidate()
    with pytest.raises(PreparationHaltedError):
        prepare_instruction(candidate, _evaluate(candidate), _instruction(), halt=_halt())


def test_reason_code_for_gate_uses_reason() -> None:
    candidate = _candidate()
    held = _evaluate(candidate, gate_decision=_gate(candidate, ofr=0.75))
    assert held.reason_codes == (f"CASH_GATE_HOLD:{ReasonCode.BROAD_STRESS_HOLD.value}",)
