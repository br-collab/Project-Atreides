"""External action receipts are evidence, and they fail closed.

The digest they are checked against is the one the emitter produces for the
prepared artifact. A translated or hand-built digest is not the proof.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cannae_kernel.canonical import digest_bytes
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import EventId
from cannae_kernel.journal import verify_chain
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.dsor import DSORStore, SettlementDomainOutput
from atreides.dsor.journal import ATREIDES_DSOR_ACTOR, lifecycle_records, render_journal
from atreides.dsor.lifecycle_records import ExternalActionReceiptRecord
from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import emit_instruction_artifact, instruction_artifact_digest
from atreides.messaging.receipt import (
    ExternalAction,
    ExternalActionReceipt,
    assess_receipt,
    assess_receipts,
    read_receipt,
)

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
EVENT = EventId("evt_" + "4" * 26)
OTHER_EVENT = EventId("evt_" + "5" * 26)
LIF = "lif_01M2P20SY00000000000000001"
DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32
_FORBIDDEN = ("compliant", "approved", "cleared", "certified")


def _instruction() -> CashLegInstruction:
    member = FinancialInstitution(bicfi="AAAAUS33XXX")
    return CashLegInstruction(
        message_id="MSG-001",
        end_to_end_id="E2E-001",
        created_at=T0,
        amount=Decimal("1000000.00"),
        currency="USD",
        debtor=member,
        creditor=FinancialInstitution(bicfi="BBBBUS33XXX"),
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=member,
        receiver=FinancialInstitution(bicfi="BBBBUS33XXX"),
    )


def _receipt(**overrides: object) -> ExternalActionReceipt:
    fields: dict[str, object] = {
        "entitled_member_id": "member-1",
        "event_id": EVENT,
        "action": ExternalAction.CLEARING_SUBMISSION,
        "artifact_digest": DIGEST,
        "observation_time": T0 + timedelta(hours=1),
        "provenance": Provenance.FACT_SYNTHETIC,
        "message_id": "MSG-001",
        "end_to_end_id": "E2E-001",
    }
    fields.update(overrides)
    return ExternalActionReceipt.model_validate(fields)


def _json(**overrides: object) -> str:
    payload: dict[str, object] = {
        "entitled_member_id": "member-1",
        "event_id": str(EVENT),
        "action": "SETTLEMENT_INSTRUCTION",
        "artifact_digest": DIGEST,
        "observation_time": "2026-08-14T13:00:00Z",
        "provenance": "FACT_EXTERNAL",
        "message_id": "MSG-001",
        "end_to_end_id": "E2E-001",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _no_claim(text: str) -> None:
    folded = text.casefold()
    for word in _FORBIDDEN:
        assert word not in folded


def test_both_actions_are_evidence_and_neither_can_submit_or_authorize() -> None:
    clearing = _receipt()
    instructed = _receipt(action=ExternalAction.SETTLEMENT_INSTRUCTION)
    assert clearing.action is ExternalAction.CLEARING_SUBMISSION
    assert instructed.action is ExternalAction.SETTLEMENT_INSTRUCTION
    assert clearing.action is not instructed.action
    for receipt in (clearing, instructed):
        assert receipt.is_submission is False
        assert receipt.authorizes_action is False
        assert not hasattr(receipt, "submit")


def test_a_receipt_refuses_to_become_an_instruction() -> None:
    with pytest.raises(ValidationError):
        _receipt(is_submission=True)
    with pytest.raises(ValidationError):
        _receipt(authorizes_action=True)
    with pytest.raises(ValidationError):
        _receipt(provenance=Provenance.FORECAST)
    with pytest.raises(ValidationError):
        _receipt(entitled_member_id=" member-1")
    with pytest.raises(ValidationError):
        _receipt(entitled_member_id="member-1 ")
    with pytest.raises(ValidationError):
        _receipt(message_id="M" * 36)
    with pytest.raises(ValidationError):
        _receipt(artifact_digest="not-a-digest")
    with pytest.raises(ValidationError):
        _receipt(observation_time=datetime(2026, 8, 14, 13, 0))


def test_read_receipt_accepts_a_typed_mapping_and_json_and_fails_closed() -> None:
    typed = read_receipt(_receipt().model_dump())
    assert isinstance(typed, ExternalActionReceipt)
    parsed = read_receipt(_json())
    parsed_bytes = read_receipt(_json().encode())
    assert isinstance(parsed, ExternalActionReceipt)
    assert isinstance(parsed_bytes, ExternalActionReceipt)
    assert parsed.action is ExternalAction.SETTLEMENT_INSTRUCTION
    assert parsed.provenance is Provenance.FACT_EXTERNAL
    for payload in (
        None,
        3,
        _json(action="SUBMIT"),
        _json(is_submission=True),
        _json(provenance="FORECAST"),
        _json(submit=True),
        b"[]",
        {"entitled_member_id": "member-1"},
    ):
        refused = read_receipt(payload)
        assert not isinstance(refused, ExternalActionReceipt)
        assert refused.disposition is Disposition.INDETERMINATE
        _no_claim(refused.reason)


def test_assessment_passes_only_an_exact_current_digest() -> None:
    receipt = _receipt()
    passed = assess_receipt(receipt, prepared_artifact_digest=DIGEST, prepared_at=T0)
    assert passed.disposition is Disposition.PASS
    _no_claim(passed.reason)
    equal_time = assess_receipt(
        receipt,
        prepared_artifact_digest=DIGEST,
        prepared_at=receipt.observation_time,
    )
    assert equal_time.disposition is Disposition.PASS
    held = assess_receipt(receipt, prepared_artifact_digest=OTHER_DIGEST, prepared_at=T0)
    assert held.disposition is Disposition.HOLD
    stale = _receipt(observation_time=T0 - timedelta(seconds=1))
    assert (
        assess_receipt(stale, prepared_artifact_digest=DIGEST, prepared_at=T0).disposition
        is Disposition.HOLD
    )
    for digest, prepared_at in (
        (None, T0),
        ("sha256:NOPE", T0),
        (DIGEST, None),
        (DIGEST, datetime(2026, 8, 14, 12, 0)),
        (DIGEST, datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=-4)))),
    ):
        unread = assess_receipt(receipt, prepared_artifact_digest=digest, prepared_at=prepared_at)
        assert unread.disposition is Disposition.INDETERMINATE
        _no_claim(unread.reason)


def test_the_receipt_matches_the_emitter_digest_and_nothing_else() -> None:
    instruction = _instruction()
    artifact = emit_instruction_artifact(instruction)
    digest = instruction_artifact_digest(artifact)
    assert digest == digest_bytes(artifact.header_xml + artifact.document_xml)
    receipt = _receipt(
        artifact_digest=digest,
        observation_time=instruction.created_at,
        message_id=instruction.message_id,
        end_to_end_id=instruction.end_to_end_id,
    )
    passed = assess_receipt(
        receipt,
        prepared_artifact_digest=digest,
        prepared_at=instruction.created_at,
    )
    assert passed.disposition is Disposition.PASS
    tampered = digest_bytes(artifact.header_xml + artifact.document_xml + b"x")
    held = assess_receipt(
        receipt,
        prepared_artifact_digest=tampered,
        prepared_at=instruction.created_at,
    )
    assert held.disposition is Disposition.HOLD
    assert tampered != digest


def test_a_set_fails_closed_on_absence_disagreement_and_staleness() -> None:
    ok = _receipt()
    assert (
        assess_receipts([], prepared_artifact_digest=DIGEST, prepared_at=T0).disposition
        is Disposition.INDETERMINATE
    )
    disagreements = (
        _receipt(action=ExternalAction.SETTLEMENT_INSTRUCTION),
        _receipt(artifact_digest=OTHER_DIGEST),
        _receipt(entitled_member_id="member-2"),
        _receipt(message_id="MSG-002"),
        _receipt(end_to_end_id="E2E-002"),
    )
    for other in disagreements:
        conflict = assess_receipts(
            [ok, other],
            prepared_artifact_digest=DIGEST,
            prepared_at=T0,
        )
        assert conflict.disposition is Disposition.HOLD
        _no_claim(conflict.reason)
    repeated = assess_receipts([ok, _receipt()], prepared_artifact_digest=DIGEST, prepared_at=T0)
    assert repeated.disposition is Disposition.PASS
    both_events = assess_receipts(
        [ok, _receipt(event_id=OTHER_EVENT)],
        prepared_artifact_digest=DIGEST,
        prepared_at=T0,
    )
    assert both_events.disposition is Disposition.PASS
    stale = assess_receipts(
        [ok, _receipt(event_id=OTHER_EVENT, observation_time=T0 - timedelta(seconds=1))],
        prepared_artifact_digest=DIGEST,
        prepared_at=T0,
    )
    assert stale.disposition is Disposition.HOLD
    unknown = assess_receipts([ok], prepared_artifact_digest=None, prepared_at=T0)
    assert unknown.disposition is Disposition.INDETERMINATE


def test_the_record_round_trips_and_the_journal_keeps_the_fact() -> None:
    receipt = _receipt()
    record = ExternalActionReceiptRecord(
        operation_id=uuid.uuid4(),
        lifecycle_id=LIF,
        receipt=receipt,
    )
    with pytest.raises(ValidationError, match="lifecycle"):
        ExternalActionReceiptRecord(operation_id=uuid.uuid4(), lifecycle_id=None, receipt=receipt)
    store = DSORStore(":memory:")
    store.append(record, dtg=T0)
    stored = lifecycle_records(store, LIF)
    assert len(stored) == 1
    assert stored[0].kind == "external_action_receipt"
    assert stored[0].output == record
    assert store.replay(stored[0].record_id) == record
    envelopes = render_journal(store, stored, lifecycle_id=LIF)
    report = verify_chain(envelopes)
    assert report.ok, report.issues
    assert envelopes[0].provenance is Provenance.FACT_SYNTHETIC
    assert envelopes[0].actor == ATREIDES_DSOR_ACTOR
    assert envelopes[0].rule_version == "external-action-receipt/0.1"
    names = str(SettlementDomainOutput)
    for kind in (
        "ExternalActionReceiptRecord",
        "CustomerProtectionComputationRecord",
        "CorporateActionEventRecord",
    ):
        assert kind in names
