"""Acceptance tests for the experimental advisory break record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cannae_kernel.actor import ActorId, ActorKind, ActorRef
from pydantic import ValidationError

from atreides.cockpit.breaks import (
    BreakRecord,
    BreakState,
    ResolutionEvidence,
    break_record_from_ticket,
)
from atreides.cockpit.clearing_cockpit import BreakLeg, BreakTicket, PortalRegime

RAISED_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
SLA_TARGET = RAISED_AT + timedelta(hours=4)
OPERATION_ID = UUID("00000000-0000-0000-0000-000000000111")
DSOR_ID = UUID("00000000-0000-0000-0000-000000000222")


def _actor() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01M2P20SY00000000000000001"),
        actor_kind=ActorKind.HUMAN,
        role="settlement operations",
        entitlement_refs=("synthetic:cockpit",),
        authenticated=True,
    )


def _ticket() -> BreakTicket:
    return BreakTicket(
        break_id="BRK-00000000-cash",
        operation_id=OPERATION_ID,
        regime=PortalRegime.CCP,
        leg=BreakLeg.FUNDING,
        detail='{"actual":"9","expected":"10"}',
        dsor_record_id=DSOR_ID,
        raised_at=RAISED_AT,
    )


def _record(**changes: object) -> BreakRecord:
    values: dict[str, object] = {
        "ticket": _ticket(),
        "symptom": "cash balance mismatch",
        "sources": ("operator readback", "instruction package"),
        "difference": "expected 10, actual 9",
        "originating_event_ref": "readback:00000000",
        "cause_class": "UNKNOWN",
        "owner": _actor(),
        "owner_absence_reason": None,
        "sla_target": SLA_TARGET,
    }
    values.update(changes)
    return break_record_from_ticket(**values)  # type: ignore[arg-type]


def test_resolved_without_resolution_evidence_is_refused() -> None:
    with pytest.raises(ValidationError, match="must carry resolution evidence"):
        _record(state=BreakState.RESOLVED)


def test_resolved_with_resolution_evidence_is_accepted() -> None:
    evidence = ResolutionEvidence(
        recorded_at=RAISED_AT + timedelta(hours=1),
        recorded_by=_actor(),
        evidence_ref="synthetic:reconciliation:1",
        detail="balances match on replay",
    )
    record = _record(state=BreakState.RESOLVED, resolution_evidence=evidence)
    assert record.state is BreakState.RESOLVED
    assert record.resolution_evidence == evidence


def test_absent_owner_is_explicit_and_survives_round_trip() -> None:
    record = _record(owner=None, owner_absence_reason="no owner recorded")
    replayed = BreakRecord.model_validate_json(record.model_dump_json())
    assert replayed.owner is None
    assert replayed.owner_missing is True
    assert replayed.owner_absence_reason == "no owner recorded"


def test_absent_owner_without_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="explicit absence reason"):
        _record(owner=None, owner_absence_reason=None)


def test_same_inputs_produce_identical_canonical_bytes() -> None:
    first = _record()
    second = _record()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.originating_event_at == _ticket().raised_at
    assert first.dsor_record_id == str(DSOR_ID)
    assert first.enforcement_status == "ADVISORY_ONLY"
    assert first.experimental is True
    assert first.synthetic is True


def test_builder_does_not_change_ticket_status() -> None:
    ticket = _ticket()
    _record(ticket=ticket)
    assert ticket.status == "OPEN_ON_WORKBENCH"
