"""Client output production is not delivery, and a posting is not production."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import EventId
from cannae_kernel.journal import verify_chain
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.dsor import DSORStore, SettlementDomainOutput
from atreides.dsor.client_output import (
    ClientOutputEvidence,
    ClientOutputRecord,
    DeliveryObservation,
    OutputStage,
    assess_client_output,
    read_client_output,
)
from atreides.dsor.journal import ATREIDES_DSOR_ACTOR, lifecycle_records, render_journal

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
EVENT = EventId("evt_" + "4" * 26)
OTHER = EventId("evt_" + "5" * 26)
LIF = "lif_01M2P20SY00000000000000001"
DIGEST = "sha256:" + "ab" * 32
_FORBIDDEN = ("compliant", "approved", "cleared", "certified")


def _delivery() -> DeliveryObservation:
    return DeliveryObservation(
        observation_time=T0,
        provenance=Provenance.FACT_SYNTHETIC,
        recipient_ref="client-class-desk",
    )


def _output(**overrides: object) -> ClientOutputEvidence:
    fields: dict[str, object] = {
        "artifact_digest": DIGEST,
        "recipient_class": "institutional-client",
        "source_event_id": EVENT,
        "generation_time": T0,
        "provenance": Provenance.FACT_SYNTHETIC,
    }
    fields.update(overrides)
    return ClientOutputEvidence.model_validate(fields)


def _no_claim(reason: str) -> None:
    folded = reason.casefold()
    for word in _FORBIDDEN:
        assert word not in folded


def test_posting_does_not_produce_output_and_production_does_not_deliver() -> None:
    from_posting = assess_client_output(None, posted=True)
    produced = assess_client_output(_output(), posted=True, source_event_id=EVENT)
    delivered = assess_client_output(_output(delivery=_delivery()), source_event_id=EVENT)
    mismatch = assess_client_output(_output(delivery=_delivery()), source_event_id=OTHER)
    assert from_posting.stage is OutputStage.UNREAD
    assert from_posting.disposition is Disposition.INDETERMINATE
    assert from_posting.delivered is False
    assert produced.stage is OutputStage.PRODUCED
    assert produced.disposition is Disposition.PASS
    assert produced.delivered is False
    assert delivered.stage is OutputStage.DELIVERED
    assert delivered.disposition is Disposition.PASS
    assert delivered.delivered is True
    assert mismatch.disposition is Disposition.HOLD
    assert mismatch.delivered is False
    for item in (from_posting, produced, delivered, mismatch):
        _no_claim(item.reason)


def test_an_unreadable_output_is_not_a_delivery() -> None:
    payload = _output().model_dump(mode="json")
    payload["provenance"] = "POLICY_RESULT"
    unread = read_client_output(payload)
    assert unread.stage is OutputStage.UNREAD
    assert unread.disposition is Disposition.INDETERMINATE
    assert unread.delivered is False
    _no_claim(unread.reason)


def test_the_record_round_trips_and_the_journal_keeps_the_fact() -> None:
    evidence = _output()
    record = ClientOutputRecord(
        operation_id=uuid.uuid4(),
        lifecycle_id=LIF,
        client_output=evidence,
    )
    with pytest.raises(ValidationError, match="lifecycle"):
        ClientOutputRecord(operation_id=uuid.uuid4(), lifecycle_id=None, client_output=evidence)
    store = DSORStore(":memory:")
    store.append(record, dtg=T0)
    stored = lifecycle_records(store, LIF)
    assert stored[0].kind == "client_output"
    assert store.replay(stored[0].record_id) == record
    envelopes = render_journal(store, stored, lifecycle_id=LIF)
    report = verify_chain(envelopes)
    assert report.ok, report.issues
    assert envelopes[0].provenance is Provenance.FACT_SYNTHETIC
    assert envelopes[0].actor == ATREIDES_DSOR_ACTOR
    assert envelopes[0].rule_version == "client-output/0.1"
    assert "ClientOutputRecord" in str(SettlementDomainOutput)
