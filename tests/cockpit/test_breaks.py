"""Acceptance tests for the experimental advisory break record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cannae_kernel.actor import ActorId, ActorKind, ActorRef
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.cockpit.breaks import (
    BreakRecord,
    BreakState,
    OwnershipChange,
    ResolutionEvidence,
    assign_break_owner,
    break_record_from_ticket,
)
from atreides.cockpit.clearing_cockpit import BreakLeg, BreakTicket, PortalRegime

RAISED_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
SLA_TARGET = RAISED_AT + timedelta(hours=4)
OPERATION_ID = UUID("00000000-0000-0000-0000-000000000111")
DSOR_ID = UUID("00000000-0000-0000-0000-000000000222")


def _actor(suffix: str = "1") -> ActorRef:
    return ActorRef(
        actor_id=ActorId(f"act_01M2P20SY0000000000000000{suffix}"),
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


def _intake(**changes: object) -> BreakRecord:
    values: dict[str, object] = {
        "ticket": _ticket(),
        "symptom": "cash balance mismatch",
        "sources": ("operator readback", "instruction package"),
        "difference": "expected 10, actual 9",
        "originating_event_ref": "readback:00000000",
        "cause_class": "UNKNOWN",
        "owner": None,
        "owner_absence_reason": "awaiting production owner assignment",
        "sla_target": SLA_TARGET,
    }
    values.update(changes)
    return break_record_from_ticket(**values)  # type: ignore[arg-type]


def _record(**changes: object) -> BreakRecord:
    assigned = assign_break_owner(
        _intake(),
        owner=_actor(),
        changed_by=_actor("2"),
        changed_at=RAISED_AT + timedelta(minutes=5),
        provenance=Provenance.HUMAN_JUDGMENT,
    )
    if not changes:
        return assigned
    values = assigned.model_dump()
    values.update(changes)
    return BreakRecord.model_validate(values)


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
    record = _intake()
    replayed = BreakRecord.model_validate_json(record.model_dump_json())
    assert replayed.owner is None
    assert replayed.owner_missing is True
    assert replayed.owner_absence_reason == "awaiting production owner assignment"
    assert replayed.state is BreakState.INTAKE_UNASSIGNED


def test_absent_owner_without_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="explicit absence reason"):
        _intake(owner_absence_reason=None)


def test_actionable_ownerless_break_is_refused() -> None:
    with pytest.raises(ValidationError, match="fail-closed intake"):
        _intake(state=BreakState.OPEN)


def test_assignment_and_reassignment_are_attributable_and_contiguous() -> None:
    first = _record()
    second_owner = _actor("3")
    reassigned = assign_break_owner(
        first,
        owner=second_owner,
        changed_by=_actor("2"),
        changed_at=RAISED_AT + timedelta(minutes=10),
        provenance=Provenance.HUMAN_JUDGMENT,
    )
    assert reassigned.owner == second_owner
    assert reassigned.state is BreakState.OPEN
    assert len(reassigned.ownership_history) == 2
    assert reassigned.ownership_history[1].previous_owner == _actor()
    assert reassigned.ownership_history[1].changed_by == _actor("2")


def test_assignment_refuses_unauthenticated_actor_and_same_owner() -> None:
    unauthenticated = _actor("3").model_copy(update={"authenticated": False})
    with pytest.raises(ValidationError, match="must be authenticated"):
        assign_break_owner(
            _intake(),
            owner=_actor(),
            changed_by=unauthenticated,
            changed_at=RAISED_AT,
            provenance=Provenance.HUMAN_JUDGMENT,
        )
    with pytest.raises(ValidationError, match="different owner"):
        OwnershipChange(
            changed_at=RAISED_AT,
            changed_by=_actor("2"),
            previous_owner=_actor(),
            assigned_owner=_actor(),
            provenance=Provenance.HUMAN_JUDGMENT,
        )


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
    _intake(ticket=ticket)
    assert ticket.status == "OPEN_ON_WORKBENCH"
