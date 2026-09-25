"""ATR-I-01 acceptance through the frozen envelope-plus-payload boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.absence import Absent, Recorded
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes_of, digest, digest_bytes
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.envelopes import ObligationAcceptanceRecord, SettlementObligationEnvelope
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import ActorId, HaltId, LifecycleId, ObligationId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext

from atreides.acceptance.candidate import (
    CandidatePathDescriptor,
    CashLeg,
    ExpectedFinality,
    ObligationCandidate,
    Participant,
    SecuritiesLeg,
    SourceManifest,
    SourceReference,
)
from atreides.acceptance.service import (
    PreparationRefusedError,
    evaluate_candidate,
    prepare_instruction,
)
from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import PreparationHaltedError
from atreides.rails.cato_cash import (
    CashRail,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    evaluate,
)

T = datetime(2026, 9, 17, 16, 0, tzinfo=UTC)
D = Decimal
OBL = ObligationId("obl_01M2P20SY00000000000000001")
LIF = LifecycleId("lif_01M2P20SY00000000000000001")
ACTOR = ActorRef(
    actor_id=ActorId("act_01M2P20SY00000000000000001"),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="atreides-acceptance-service",
    entitlement_refs=(),
    authenticated=True,
)


def _candidate(**changes: Any) -> ObligationCandidate:
    fields: dict[str, Any] = {
        "source_manifest": SourceManifest(
            references=(
                SourceReference(kind="EXECUTION", identifier="exe-1", digest="sha256:" + "1" * 64),
            )
        ),
        "securities_leg": SecuritiesLeg(
            instrument_id="912828XX1",
            quantity=D("1000000"),
            delivering_account_id="SEC-SELLER",
            receiving_account_id="SEC-BUYER",
        ),
        "cash_leg": CashLeg(
            principal=D("995000.00"),
            accrued=D("1234.56"),
            total=D("996234.56"),
            currency="USD",
            value_date="2026-09-18",
            paying_account_id="CASH-BUYER",
            receiving_account_id="CASH-SELLER",
        ),
        "participants": (
            Participant(participant_id="P-SELLER", account_id="SEC-SELLER", role="DELIVERER"),
            Participant(participant_id="P-BUYER", account_id="SEC-BUYER", role="RECEIVER"),
            Participant(participant_id="P-BUYER", account_id="CASH-BUYER", role="DELIVERER"),
            Participant(participant_id="P-SELLER", account_id="CASH-SELLER", role="RECEIVER"),
        ),
        "delivery_pattern": "DVP",
        "candidate_paths": (
            CandidatePathDescriptor(
                path_id="fedwire-dvp",
                rail="Fedwire",
                securities_route="securities",
                cash_route="cash",
                delivery_pattern="DVP",
            ),
        ),
        "expected_finality": (
            ExpectedFinality(
                leg="SECURITIES", finality_type="ASSET_FINAL", governing_rule_set="sec/1"
            ),
            ExpectedFinality(leg="CASH", finality_type="CASH_FINAL", governing_rule_set="cash/1"),
        ),
        "corrections": (),
    }
    fields.update(changes)
    return ObligationCandidate(**fields)


def _wire(candidate: ObligationCandidate) -> tuple[SettlementObligationEnvelope, bytes]:
    payload = canonical_bytes_of(candidate)
    envelope = SettlementObligationEnvelope(
        obligation_id=OBL,
        lifecycle_id=LIF,
        transformation_digest="sha256:" + "2" * 64,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=date(2026, 9, 18),
                calendar="Fedwire Funds",
                established_by="L.C. obligation payload",
            ),
        ),
        provenance=Provenance.POLICY_RESULT,
        payload_digest=digest_bytes(payload),
    )
    return envelope, payload


def _gate(envelope: SettlementObligationEnvelope, *, ofr: float = 0.0, **binding: Any) -> Any:
    return evaluate(
        operation=OperationContext(
            notional=D("996234.56"), currency="USD", is_material=False, is_lvps_material=False
        ),
        funding=FundingState(D("5000000"), D("996234.56"), D("10000000"), True),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=ofr,
        obligation_id=binding.get("obligation_id", envelope.obligation_id),
        obligation_digest=binding.get("obligation_digest", digest(envelope)),
    )


def _evaluate(candidate: ObligationCandidate, **changes: Any) -> ObligationAcceptanceRecord:
    envelope, payload = _wire(candidate)
    changes.setdefault("gate_decision", _gate(envelope))
    changes.setdefault("halt", None)
    return evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        **changes,
    )


def _reason(record: ObligationAcceptanceRecord) -> str:
    assert isinstance(record.dsor_record, Absent)
    return record.dsor_record.reason


def test_clean_candidate_with_a_bound_proceed_is_accepted() -> None:
    envelope, payload = _wire(_candidate())
    record = evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=_gate(envelope),
        halt=None,
    )
    assert isinstance(record, ObligationAcceptanceRecord)
    assert record.disposition is Disposition.PASS
    assert isinstance(record.dsor_record, Recorded)
    assert record.obligation_digest == digest(envelope)
    assert record.decided_by == ACTOR


def test_the_record_references_the_envelope_and_copies_no_economics() -> None:
    record = _evaluate(_candidate())
    dumped = record.model_dump_json()
    for economic in ("996234.56", "995000.00", "912828XX1", "P-BUYER", "USD"):
        assert economic not in dumped


def test_payload_digest_mismatch_is_a_recorded_refusal() -> None:
    envelope, payload = _wire(_candidate())
    tampered = payload.replace(b"996234.56", b"996234.57")
    record = evaluate_candidate(
        envelope,
        tampered,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=None,
        halt=None,
    )
    assert record.disposition is not Disposition.PASS
    assert _reason(record) == "PAYLOAD_DIGEST_MISMATCH"
    assert record.obligation_digest == digest(envelope)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"source_manifest": None}, "MISSING:source_manifest.references"),
        ({"delivery_pattern": None}, "MISSING:delivery_pattern"),
        ({"participants": ()}, "MISSING:participants"),
        ({"candidate_paths": ()}, "MISSING:candidate_paths"),
        ({"securities_leg": None}, "MISSING:securities_leg"),
        ({"cash_leg": None}, "MISSING:cash_leg"),
        ({"expected_finality": ()}, "MISSING:expected_finality.cash"),
    ],
)
def test_missing_required_field_is_rejected(changes: dict[str, Any], code: str) -> None:
    record = _evaluate(_candidate(**changes))
    assert record.disposition is Disposition.BLOCK
    assert code in _reason(record)


def test_unknown_enum_is_indeterminate_never_accepted() -> None:
    record = _evaluate(_candidate(delivery_pattern="dvp"))
    assert record.disposition is not Disposition.PASS
    assert "UNKNOWN_ENUM:delivery_pattern" in _reason(record)


def test_unlinked_leg_account_is_rejected() -> None:
    leg = _candidate().cash_leg.model_copy(update={"paying_account_id": "UNKNOWN"})  # type: ignore[union-attr]
    record = _evaluate(_candidate(cash_leg=leg))
    assert record.disposition is Disposition.BLOCK
    assert "LEG_ACCOUNT_MISMATCH:cash_leg" in _reason(record)


def _halt(*, active: bool = True, scope: Any = "ALL") -> HaltContext:
    return HaltContext(
        halt_id=HaltId("hlt_" + "3" * 26),
        version=4,
        active=active,
        scope=scope,
        declared_by=ACTOR,
        declared_at=T,
        reason="drill",
    )


def test_active_halt_holds() -> None:
    record = _evaluate(_candidate(), halt=_halt())
    assert record.disposition is Disposition.HOLD
    assert "HALT_ACTIVE" in _reason(record)
    other = _evaluate(_candidate(), halt=_halt(scope=(Domain.AUREON,)))
    assert other.disposition is Disposition.PASS


@pytest.mark.parametrize(
    ("gate_factory", "code"),
    [
        (lambda e: None, "CASH_GATE_DECISION_MISSING"),
        (lambda e: _gate(e, obligation_id=None, obligation_digest=None), "CASH_GATE_UNBOUND"),
        (
            lambda e: _gate(e, obligation_id=ObligationId("obl_01M2P20SY00000000000000009")),
            "CASH_GATE_OTHER_OBLIGATION",
        ),
        (lambda e: _gate(e, obligation_digest="sha256:" + "0" * 64), "CASH_GATE_STALE_DIGEST"),
    ],
)
def test_funding_evidence_not_about_envelope_is_indeterminate(gate_factory: Any, code: str) -> None:
    envelope, payload = _wire(_candidate())
    record = evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=gate_factory(envelope),
        halt=None,
    )
    assert record.disposition is Disposition.INDETERMINATE
    assert code in _reason(record)


@pytest.mark.parametrize("ofr", [0.75, 1.5])
def test_bound_gate_hold_or_escalate_holds(ofr: float) -> None:
    envelope, payload = _wire(_candidate())
    gate = _gate(envelope, ofr=ofr)
    assert gate.decision in {GateDecision.HOLD, GateDecision.ESCALATE}
    record = evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=gate,
        halt=None,
    )
    assert record.disposition is Disposition.HOLD
    assert f"CASH_GATE_{gate.decision.value}" in _reason(record)


def test_session_business_date_is_consumed_unchanged() -> None:
    envelope, payload = _wire(_candidate())
    before = envelope.session
    evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=_gate(envelope),
        halt=None,
    )
    assert envelope.session == before


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


def _accepted_wire() -> tuple[SettlementObligationEnvelope, bytes, ObligationAcceptanceRecord]:
    envelope, payload = _wire(_candidate())
    acceptance = evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=_gate(envelope),
        halt=None,
    )
    assert acceptance.disposition is Disposition.PASS
    return envelope, payload, acceptance


def test_preparation_requires_the_accepted_frozen_envelope_and_payload() -> None:
    envelope, payload, acceptance = _accepted_wire()
    artifact = prepare_instruction(envelope, payload, acceptance, _instruction())
    assert artifact.is_submission is False


def test_preparation_refuses_missing_or_non_pass_acceptance() -> None:
    envelope, payload, _ = _accepted_wire()
    with pytest.raises(PreparationRefusedError, match="No acceptance record"):
        prepare_instruction(envelope, payload, None, _instruction())

    held = evaluate_candidate(
        envelope,
        payload,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T,
        decided_by=ACTOR,
        gate_decision=_gate(envelope),
        halt=_halt(),
    )
    with pytest.raises(PreparationRefusedError, match="HOLD, not PASS"):
        prepare_instruction(envelope, payload, held, _instruction())


def test_preparation_refuses_tampered_payload() -> None:
    envelope, payload, acceptance = _accepted_wire()
    tampered = payload.replace(b"996234.56", b"996234.57")
    with pytest.raises(PreparationRefusedError, match="PAYLOAD_DIGEST_MISMATCH"):
        prepare_instruction(envelope, tampered, acceptance, _instruction())


def test_preparation_refuses_acceptance_for_another_envelope() -> None:
    envelope, payload, acceptance = _accepted_wire()
    other_acceptance = acceptance.model_copy(
        update={"obligation_id": ObligationId("obl_01M2P20SY00000000000000009")}
    )
    with pytest.raises(PreparationRefusedError, match="names another obligation"):
        prepare_instruction(envelope, payload, other_acceptance, _instruction())

    other = envelope.model_copy(update={"transformation_digest": "sha256:" + "9" * 64})
    with pytest.raises(PreparationRefusedError, match="does not reference this envelope digest"):
        prepare_instruction(other, payload, acceptance, _instruction())


def test_preparation_still_honours_a_halt() -> None:
    envelope, payload, acceptance = _accepted_wire()
    with pytest.raises(PreparationHaltedError):
        prepare_instruction(envelope, payload, acceptance, _instruction(), halt=_halt())
