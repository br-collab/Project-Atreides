"""ATR-I-12 (slice-minimal, W2A-5): lifecycle record kinds and a verifiable journal.

Every lifecycle fact the first settlement slice needs is a DSOR record kind; a
lifecycle's records render as a kernel event chain that ``verify_chain`` checks,
and a ``JournalCheckpoint`` recorded elsewhere makes a rewritten tail detectable.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest, digest_bytes
from cannae_kernel.domains import Domain
from cannae_kernel.finality import (
    ConditionalityStatus,
    FinalityAssertion,
    FinalityType,
    RevocabilityStatus,
)
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import ActorId, CheckpointId, EventId, HaltId
from cannae_kernel.journal import ChainIssueCode, JournalCheckpoint, verify_chain
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.acceptance import evaluate_candidate
from atreides.dsor import AureonOutput, DSORStore, SettlementDomainOutput
from atreides.dsor.journal import (
    ATREIDES_DSOR_ACTOR,
    DSORRecordRef,
    lifecycle_records,
    render_journal,
)
from atreides.dsor.lifecycle_records import (
    FinalityAssertedRecord,
    HaltRecord,
    InstructionPreparedRecord,
    RailStatusObservedRecord,
    ReconciliationResultRecord,
)
from atreides.messaging.readback import SettlementStatus
from atreides.rails.cato_f import (
    CashRail,
    FundingState,
    OperationContext,
    RailState,
    RailStatus,
)
from atreides.rails.cato_f_record import CatoFDecisionRecord
from tests.acceptance.test_acceptance import _candidate, _gate

T0 = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)
LIF = "lif_01M2P20SY00000000000000001"
OTHER_LIF = "lif_01M2P20SY00000000000000002"
D = Decimal


def _human() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + "4" * 26),
        actor_kind=ActorKind.HUMAN,
        role="operator",
        entitlement_refs=(),
        authenticated=True,
    )


def _halt(active: bool) -> HaltContext:
    return HaltContext(
        halt_id=HaltId("hlt_" + "4" * 26),
        version=1 if active else 2,
        active=active,
        scope=(Domain.ATREIDES,),
        declared_by=_human(),
        declared_at=T0,
        reason="drill" if active else "drill over",
    )


def _lifecycle(store: DSORStore) -> list[Any]:
    """One settlement lifecycle, each fact appended one minute after the last."""
    candidate = _candidate()
    gate = CatoFDecisionRecord.capture(
        decision_id=uuid.uuid4(),
        lifecycle_id=LIF,
        operation=OperationContext(
            notional=D("996234.56"), currency="USD", is_material=False, is_lvps_material=False
        ),
        funding=FundingState(D("5000000"), D("996234.56"), D("10000000"), True),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=0.0,
        obligation_id=candidate.obligation_id,
        obligation_digest=digest(candidate),
    )
    acceptance = evaluate_candidate(
        candidate,
        acceptance_id=uuid.uuid4(),
        evaluated_at=T0,
        gate_decision=_gate(candidate),
        halt=None,
    )
    outputs: list[Any] = [
        HaltRecord(operation_id=uuid.uuid4(), lifecycle_id=LIF, halt=_halt(True)),
        HaltRecord(operation_id=uuid.uuid4(), lifecycle_id=LIF, halt=_halt(False)),
        gate,
        acceptance,
        InstructionPreparedRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            obligation_id=candidate.obligation_id,
            obligation_digest=digest(candidate),
            acceptance_record_digest=acceptance.digest(),
            message_definition="pacs.009.001.13",
            end_to_end_id="E2E-0002",
            artifact_digest=digest_bytes(b"<AppHdr/><Document/>"),
            prepared_at=T0,
        ),
        RailStatusObservedRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            obligation_id=candidate.obligation_id,
            end_to_end_id="E2E-0002",
            status=SettlementStatus.SETTLED,
            status_code="ACSC",
            status_report_message_id="MSG-9",
            observed_at=T0,
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        FinalityAssertedRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            obligation_id=candidate.obligation_id,
            assertion=FinalityAssertion(
                finality_type=FinalityType.CASH_FINAL,
                governing_rule_set="synthetic-fedwire-funds/v0.1",
                authoritative_actor=ActorRef(
                    actor_id=ActorId("act_" + "5" * 26),
                    actor_kind=ActorKind.EXTERNAL_EMULATOR,
                    role="rail-emulator",
                    entitlement_refs=(),
                    authenticated=True,
                ),
                authoritative_event_id=EventId("evt_" + "5" * 26),
                effective_time=T0,
                observation_time=T0 + timedelta(seconds=1),
                evidence_reference="readback:MSG-9",
                conditionality_status=ConditionalityStatus.UNCONDITIONAL,
                revocability_status=RevocabilityStatus.IRREVOCABLE,
                provenance=Provenance.FACT_SYNTHETIC,
            ),
        ),
        ReconciliationResultRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            obligation_id=candidate.obligation_id,
            status_report_message_id="MSG-9",
            matched=True,
            break_codes=(),
            reconciled_at=T0,
        ),
    ]
    for i, output in enumerate(outputs):
        store.append(output, dtg=T0 + timedelta(minutes=i))
    # A record from another lifecycle, which must not join this chain.
    store.append(
        HaltRecord(operation_id=uuid.uuid4(), lifecycle_id=OTHER_LIF, halt=_halt(True)),
        dtg=T0 + timedelta(minutes=30),
    )
    return outputs


def test_union_carries_every_lifecycle_kind_and_keeps_the_deprecated_alias() -> None:
    assert AureonOutput is SettlementDomainOutput
    names = str(SettlementDomainOutput)
    for kind in (
        "CatoFDecisionRecord",
        "ObligationAcceptanceRecord",
        "HaltRecord",
        "InstructionPreparedRecord",
        "RailStatusObservedRecord",
        "FinalityAssertedRecord",
        "ReconciliationResultRecord",
    ):
        assert kind in names


def test_every_lifecycle_record_round_trips_through_the_store() -> None:
    store = DSORStore(":memory:")
    outputs = _lifecycle(store)
    records = lifecycle_records(store, LIF)
    assert [r.output for r in records] == outputs
    assert [r.kind for r in records] == [
        "halt_context",
        "halt_context",
        "cash_gate_decision",
        "obligation_acceptance",
        "instruction_prepared",
        "rail_status_observed",
        "finality_asserted",
        "reconciliation_result",
    ]
    assert [r.output.event for r in records[:2]] == ["declared", "cleared"]  # type: ignore[union-attr]
    for record in records:
        assert store.replay(record.record_id) == record.output


def test_lifecycle_journal_verifies_and_renders_deterministically() -> None:
    store = DSORStore(":memory:")
    _lifecycle(store)
    records = lifecycle_records(store, LIF)
    envelopes = render_journal(store, records, lifecycle_id=LIF)
    report = verify_chain(envelopes)
    assert report.ok, report.issues
    assert report.event_count == 8
    assert render_journal(store, records, lifecycle_id=LIF) == envelopes
    first, halt_cleared = envelopes[0], envelopes[1]
    assert first.prior_event_digest is None and first.parent_ids == ()
    assert halt_cleared.parent_ids == (first.event_id,)
    assert first.provenance is Provenance.HUMAN_JUDGMENT
    assert envelopes[3].actor == ATREIDES_DSOR_ACTOR
    assert envelopes[5].provenance is Provenance.FACT_SYNTHETIC
    assert envelopes[6].actor.actor_kind is ActorKind.EXTERNAL_EMULATOR
    assert envelopes[3].rule_version == "obligation-acceptance/0.1-draft"
    assert envelopes[2].rule_version == "cato-f-gates/0.3"
    assert isinstance(first.payload, DSORRecordRef)
    assert first.payload.stored_payload_digest == digest_bytes(
        store.payload_bytes(records[0].record_id)
    )


def _checkpoint(envelopes: list[Any]) -> JournalCheckpoint:
    head = envelopes[-1]
    return JournalCheckpoint(
        checkpoint_id=CheckpointId("ckp_" + "6" * 26),
        lifecycle_id=head.lifecycle_id,
        domain=Domain.ATREIDES,
        head_event_id=head.event_id,
        head_digest=head.envelope_digest,
        event_count=len(envelopes),
        taken_at=T0 + timedelta(hours=1),
        recorded_by=ActorRef(
            actor_id=ActorId("act_" + "7" * 26),
            actor_kind=ActorKind.DETERMINISTIC_SERVICE,
            role="cannae-c2",
            entitlement_refs=(),
            authenticated=True,
        ),
    )


def test_a_rewritten_tail_passes_the_chain_but_fails_the_checkpoint() -> None:
    store = DSORStore(":memory:")
    _lifecycle(store)
    envelopes = render_journal(store, lifecycle_records(store, LIF), lifecycle_id=LIF)
    checkpoint = _checkpoint(envelopes)
    assert verify_chain(envelopes, expected_head=checkpoint).ok

    # Rewrite the last record's stored bytes directly, as someone with database
    # access could: the reconciliation now claims a break.
    last = lifecycle_records(store, LIF)[-1]
    forged = last.output.model_copy(  # type: ignore[union-attr]
        update={"matched": False, "break_codes": ("amount_mismatch",)}
    )
    conn: sqlite3.Connection = store._conn  # type: ignore[attr-defined]
    conn.execute(
        "UPDATE dsor_records SET payload = ? WHERE record_id = ?",
        (forged.model_dump_json(), str(last.record_id)),
    )
    conn.commit()

    rerendered = render_journal(store, lifecycle_records(store, LIF), lifecycle_id=LIF)
    assert verify_chain(rerendered).ok  # the chain alone cannot see it
    report = verify_chain(rerendered, expected_head=checkpoint)
    assert [issue.code for issue in report.issues] == [ChainIssueCode.HEAD_MISMATCH]


def test_a_rewritten_middle_record_breaks_the_chain_against_the_old_envelopes() -> None:
    store = DSORStore(":memory:")
    _lifecycle(store)
    original = render_journal(store, lifecycle_records(store, LIF), lifecycle_id=LIF)
    middle = lifecycle_records(store, LIF)[3]
    conn: sqlite3.Connection = store._conn  # type: ignore[attr-defined]
    conn.execute(
        "UPDATE dsor_records SET payload = ? WHERE record_id = ?",
        (
            middle.output.model_dump_json().replace(
                "obligation-acceptance/0.1-draft", "obligation-acceptance/0.2-draft"
            ),
            str(middle.record_id),
        ),
    )
    conn.commit()
    tampered = render_journal(store, lifecycle_records(store, LIF), lifecycle_id=LIF)
    spliced = [*original[:3], tampered[3], *original[4:]]
    codes = {issue.code for issue in verify_chain(spliced).issues}
    assert ChainIssueCode.BROKEN_PRIOR_LINK in codes


def test_record_invariants() -> None:
    with pytest.raises(ValidationError, match="matched reconciliation"):
        ReconciliationResultRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            status_report_message_id=None,
            matched=True,
            break_codes=("x",),
            reconciled_at=T0,
        )
    with pytest.raises(ValidationError):
        RailStatusObservedRecord(
            operation_id=uuid.uuid4(),
            lifecycle_id=LIF,
            end_to_end_id="E2E",
            status=SettlementStatus.SETTLED,
            status_code="ACSC",
            status_report_message_id="MSG",
            observed_at=T0,
            provenance=Provenance.FORECAST,  # a rail status is a fact, never a forecast
        )
    with pytest.raises(ValidationError):
        InstructionPreparedRecord.model_validate(
            {
                "operation_id": str(uuid.uuid4()),
                "lifecycle_id": LIF,
                "obligation_id": "obl_01M2P20SY00000000000000001",
                "obligation_digest": "sha256:" + "0" * 64,
                "acceptance_record_digest": "sha256:" + "0" * 64,
                "message_definition": "pacs.009.001.13",
                "end_to_end_id": "E2E",
                "artifact_digest": "sha256:" + "0" * 64,
                "prepared_at": T0.isoformat(),
                "is_submission": True,
            }
        )


def test_store_payload_bytes_for_an_unknown_record_raises() -> None:
    from atreides.dsor import DSORRecordNotFoundError

    with pytest.raises(DSORRecordNotFoundError):
        DSORStore(":memory:").payload_bytes(uuid.uuid4())
