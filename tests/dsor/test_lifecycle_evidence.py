"""Cross-stage evidence stays explicit and exception closure stays separate."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import Digest
from cannae_kernel.clocks import EventTimes
from cannae_kernel.disposition import Disposition
from cannae_kernel.envelopes import ExecutionEvent
from cannae_kernel.finality import (
    ConditionalityStatus,
    FinalityAssertion,
    FinalityType,
    RevocabilityStatus,
)
from cannae_kernel.ids import ActorId, EventId, IntentId, LifecycleId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext

from atreides.cockpit.breaks import (
    BreakRecord,
    BreakState,
    OwnershipChange,
    ResolutionEvidence,
    ResolutionEvidenceKind,
)
from atreides.dsor.books import BooksPosting
from atreides.dsor.client_output import ClientOutputEvidence, DeliveryObservation
from atreides.dsor.lifecycle_evidence import EvidenceStage, assess_lifecycle_evidence
from atreides.messaging.finality_evidence import EvidenceState
from atreides.messaging.settlement_join import JoinedStage, SettlementJoin
from atreides.rails.secured_funding import SecuredFunding

AT = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)
EVENT = EventId("evt_" + "1" * 26)
OTHER_EVENT = EventId("evt_" + "2" * 26)
LIFECYCLE = LifecycleId("lif_" + "3" * 26)
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "4" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-operator",
    entitlement_refs=(),
    authenticated=True,
)


def _execution() -> ExecutionEvent:
    return ExecutionEvent(
        event_id=EVENT,
        lifecycle_id=LIFECYCLE,
        intent_id=IntentId("int_" + "5" * 26),
        intent_digest=Digest("sha256:" + "11" * 32),
        times=EventTimes(event_time=AT, observation_time=AT, processing_time=AT),
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=date(2026, 10, 9),
                calendar="SYNTHETIC",
                established_by="test",
            ),
        ),
        provenance=Provenance.FACT_SYNTHETIC,
        payload_digest=Digest("sha256:" + "22" * 32),
    )


def _funding() -> SecuredFunding:
    return SecuredFunding(
        authoritative_source="synthetic-member",
        amount=Decimal("1000.00"),
        currency="USD",
        account_or_facility="cash-1",
        observation_time=AT,
        provenance=Provenance.FACT_SYNTHETIC,
    )


def _assertion() -> FinalityAssertion:
    return FinalityAssertion(
        finality_type=FinalityType.CASH_FINAL,
        governing_rule_set="synthetic/0.1",
        authoritative_actor=ACTOR,
        authoritative_event_id=EVENT,
        effective_time=AT,
        observation_time=AT,
        evidence_reference="status-1",
        conditionality_status=ConditionalityStatus.UNCONDITIONAL,
        revocability_status=RevocabilityStatus.IRREVOCABLE,
        provenance=Provenance.FACT_SYNTHETIC,
    )


def _settlement(*, final: bool = True) -> SettlementJoin:
    if not final:
        return SettlementJoin(
            stage=JoinedStage.ACCEPTED,
            disposition=Disposition.HOLD,
            reason="accepted is not final",
            leg="cash",
            artifact_digest="sha256:" + "33" * 32,
            receipt_disposition=Disposition.PASS,
            venue_state=EvidenceState.ACCEPTED,
            venue_disposition=Disposition.HOLD,
            assertion=None,
        )
    return SettlementJoin(
        stage=JoinedStage.FINAL,
        disposition=Disposition.PASS,
        reason="the evidence joins",
        leg="cash",
        artifact_digest="sha256:" + "33" * 32,
        receipt_disposition=Disposition.PASS,
        venue_state=EvidenceState.FINAL,
        venue_disposition=Disposition.PASS,
        assertion=_assertion(),
    )


def _posting(event: EventId = EVENT) -> BooksPosting:
    return BooksPosting(
        posted_record_id="posting-1",
        posting_authority=ACTOR,
        effective_time=AT,
        source_event_id=event,
        provenance=Provenance.FACT_SYNTHETIC,
    )


def _output(event: EventId = EVENT, *, delivered: bool = False) -> ClientOutputEvidence:
    return ClientOutputEvidence(
        artifact_digest=Digest("sha256:" + "44" * 32),
        recipient_class="client",
        source_event_id=event,
        generation_time=AT,
        provenance=Provenance.FACT_SYNTHETIC,
        delivery=(
            DeliveryObservation(
                observation_time=AT,
                provenance=Provenance.FACT_SYNTHETIC,
                recipient_ref="client-1",
            )
            if delivered
            else None
        ),
    )


def _resolved_break() -> BreakRecord:
    ownership = OwnershipChange(
        changed_at=AT - timedelta(minutes=2),
        changed_by=ACTOR,
        previous_owner=None,
        assigned_owner=ACTOR,
        provenance=Provenance.FACT_SYNTHETIC,
    )
    evidence = ResolutionEvidence(
        break_id="break-1",
        recorded_at=AT - timedelta(minutes=1),
        recorded_by=ACTOR,
        provenance=Provenance.FACT_SYNTHETIC,
        evidence_kind=ResolutionEvidenceKind.CORRECTIVE_ACTION_VERIFIED,
        evidence_ref="evidence-1",
        detail="synthetic correction verified",
    )
    return BreakRecord(
        break_id="break-1",
        operation_id="operation-1",
        regime="SYNTHETIC",
        leg="cash",
        symptom="status mismatch",
        sources=("synthetic-source",),
        difference="one status differed",
        originating_event_at=AT - timedelta(minutes=3),
        originating_event_ref=str(EVENT),
        cause_class="status",
        owner=ACTOR,
        owner_absence_reason=None,
        ownership_history=(ownership,),
        sla_target=AT + timedelta(hours=1),
        resolution_evidence=evidence,
        state=BreakState.RESOLVED,
    )


def test_each_stage_requires_its_own_evidence() -> None:
    common = {
        "exception": None,
    }
    absent_execution = assess_lifecycle_evidence(
        execution=None,
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(),
        **common,
    )
    absent_funding = assess_lifecycle_evidence(
        execution=_execution(),
        funding=None,
        settlement=_settlement(),
        posting=_posting(),
        output=_output(),
        **common,
    )
    absent_finality = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=None,
        posting=_posting(),
        output=_output(),
        **common,
    )
    accepted_only = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(final=False),
        posting=_posting(),
        output=_output(),
        **common,
    )
    absent_posting = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=None,
        output=_output(),
        **common,
    )
    absent_output = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=None,
        **common,
    )

    assert (absent_execution.stage, absent_execution.disposition) == (
        EvidenceStage.UNREAD,
        Disposition.INDETERMINATE,
    )
    assert absent_funding.stage is EvidenceStage.EXECUTION_RECEIVED
    assert absent_finality.stage is EvidenceStage.FUNDING_SECURED
    assert accepted_only.stage is EvidenceStage.FUNDING_SECURED
    assert accepted_only.disposition is Disposition.HOLD
    assert absent_posting.stage is EvidenceStage.SETTLEMENT_FINAL
    assert absent_output.stage is EvidenceStage.BOOKS_POSTED
    assert all(
        item.disposition is Disposition.INDETERMINATE
        for item in (absent_funding, absent_finality, absent_posting, absent_output)
    )


def test_cross_stage_identity_disagreement_holds() -> None:
    wrong_posting = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(OTHER_EVENT),
        output=_output(),
    )
    wrong_output = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(OTHER_EVENT),
    )

    assert (wrong_posting.stage, wrong_posting.disposition) == (
        EvidenceStage.SETTLEMENT_FINAL,
        Disposition.HOLD,
    )
    assert (wrong_output.stage, wrong_output.disposition) == (
        EvidenceStage.BOOKS_POSTED,
        Disposition.HOLD,
    )


def test_production_and_delivery_remain_distinct() -> None:
    produced = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(),
    )
    delivered = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(delivered=True),
    )

    assert (produced.stage, produced.disposition, produced.output_delivered) == (
        EvidenceStage.OUTPUT_PRODUCED,
        Disposition.PASS,
        False,
    )
    assert (delivered.stage, delivered.disposition, delivered.output_delivered) == (
        EvidenceStage.OUTPUT_DELIVERED,
        Disposition.PASS,
        True,
    )
    assert produced.finality_assertion == delivered.finality_assertion == _assertion()


def test_exception_closure_uses_c3_evidence_without_closing_the_lifecycle() -> None:
    no_exception = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(),
    )
    resolved = assess_lifecycle_evidence(
        execution=_execution(),
        funding=_funding(),
        settlement=_settlement(),
        posting=_posting(),
        output=_output(),
        exception=_resolved_break(),
    )

    assert no_exception.exception_closure is Disposition.INDETERMINATE
    assert resolved.exception_closure is Disposition.PASS
    assert resolved.stage is EvidenceStage.OUTPUT_PRODUCED
    assert "lifecycle closed" not in resolved.reason.casefold()
