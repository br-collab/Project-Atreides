"""Synthetic advisory break records derived from cockpit tickets.

EXPERIMENTAL and ADVISORY_ONLY. These records make the evidence behind a
break displayable. They do not assign an owner, resolve a break, change the
cockpit ticket, or create a submission capability.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import canonical_bytes
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.cockpit.clearing_cockpit import BreakTicket

__all__ = [
    "BreakAction",
    "BreakRecord",
    "BreakState",
    "OwnershipChange",
    "ResolutionEvidence",
    "ResolutionEvidenceKind",
    "assign_break_owner",
    "break_record_from_ticket",
    "resolve_break",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BreakState(StrEnum):
    """The current investigative state, not the cockpit ticket status."""

    INTAKE_UNASSIGNED = "INTAKE_UNASSIGNED"
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BreakAction(_Frozen):
    """One action in the break's append-only investigative history."""

    occurred_at: datetime
    actor: ActorRef
    action: str = Field(min_length=1)

    @model_validator(mode="after")
    def _time_is_aware(self) -> Self:
        if self.occurred_at.tzinfo is None:
            raise ValueError("break action time must be timezone-aware")
        return self


class ResolutionEvidenceKind(StrEnum):
    """Closed evidence kinds that can support operational closure."""

    CORRECTIVE_ACTION_VERIFIED = "CORRECTIVE_ACTION_VERIFIED"
    AUTHORITY_CONFIRMATION = "AUTHORITY_CONFIRMATION"


class OwnershipChange(_Frozen):
    """One attributable owner assignment in append-only order."""

    changed_at: datetime
    changed_by: ActorRef
    previous_owner: ActorRef | None
    assigned_owner: ActorRef
    provenance: Provenance

    @model_validator(mode="after")
    def _valid_change(self) -> Self:
        if self.changed_at.tzinfo is None:
            raise ValueError("ownership change time must be timezone-aware")
        if not self.changed_by.authenticated:
            raise ValueError("ownership change actor must be authenticated")
        if not self.assigned_owner.authenticated:
            raise ValueError("assigned break owner must be authenticated")
        if self.previous_owner == self.assigned_owner:
            raise ValueError("ownership change must assign a different owner")
        return self


class ResolutionEvidence(_Frozen):
    """Evidence supporting a claimed resolution."""

    break_id: str = Field(min_length=1)
    recorded_at: datetime
    recorded_by: ActorRef
    provenance: Provenance
    evidence_kind: ResolutionEvidenceKind
    evidence_ref: str = Field(min_length=1)
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def _time_is_aware(self) -> Self:
        if self.recorded_at.tzinfo is None:
            raise ValueError("resolution evidence time must be timezone-aware")
        if not self.recorded_by.authenticated:
            raise ValueError("resolution actor must be authenticated")
        return self


class BreakRecord(_Frozen):
    """A replayable evidence record for one existing cockpit break ticket."""

    schema_version: Literal["atreides.break/0.1-experimental"] = "atreides.break/0.1-experimental"
    enforcement_status: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    experimental: Literal[True] = True
    synthetic: Literal[True] = True
    break_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    leg: str = Field(min_length=1)
    symptom: str = Field(min_length=1)
    sources: tuple[str, ...] = Field(min_length=1)
    difference: str = Field(min_length=1)
    originating_event_at: datetime
    originating_event_ref: str = Field(min_length=1)
    cause_class: str = Field(min_length=1)
    owner: ActorRef | None
    owner_absence_reason: str | None
    ownership_history: tuple[OwnershipChange, ...] = ()
    sla_target: datetime
    actions: tuple[BreakAction, ...] = ()
    resolution_evidence: ResolutionEvidence | None = None
    state: BreakState = BreakState.INTAKE_UNASSIGNED
    dsor_record_id: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.originating_event_at.tzinfo is None:
            raise ValueError("originating event time must be timezone-aware")
        if self.sla_target.tzinfo is None:
            raise ValueError("SLA target must be timezone-aware")
        if self.owner is None and not self.owner_absence_reason:
            raise ValueError("an absent owner must carry an explicit absence reason")
        if self.owner is not None and self.owner_absence_reason is not None:
            raise ValueError("owner_absence_reason is set only when owner is absent")
        if self.owner is None and self.state is not BreakState.INTAKE_UNASSIGNED:
            raise ValueError("an ownerless break must remain in fail-closed intake")
        if self.owner is not None:
            if self.state is BreakState.INTAKE_UNASSIGNED:
                raise ValueError("an assigned break cannot remain in unassigned intake")
            if not self.owner.authenticated:
                raise ValueError("break owner must be authenticated")
            if not self.ownership_history:
                raise ValueError("an assigned break must preserve ownership history")
            if self.ownership_history[-1].assigned_owner != self.owner:
                raise ValueError("current owner must match the latest ownership change")
        previous: ActorRef | None = None
        for change in self.ownership_history:
            if change.previous_owner != previous:
                raise ValueError("ownership history is not contiguous")
            previous = change.assigned_owner
        if self.state is BreakState.RESOLVED and self.resolution_evidence is None:
            raise ValueError("a resolved break must carry resolution evidence")
        if self.state is not BreakState.RESOLVED and self.resolution_evidence is not None:
            raise ValueError("resolution evidence is set only by the closure transition")
        if (
            self.resolution_evidence is not None
            and self.resolution_evidence.break_id != self.break_id
        ):
            raise ValueError("resolution evidence belongs to another break")
        return self

    @property
    def owner_missing(self) -> bool:
        """Whether the board must fail closed because no owner is recorded."""
        return self.owner is None

    def canonical_bytes(self) -> bytes:
        """Deterministic kernel canonical bytes for replay and publication."""
        return canonical_bytes(self)


def break_record_from_ticket(
    ticket: BreakTicket,
    *,
    symptom: str,
    sources: tuple[str, ...],
    difference: str,
    originating_event_ref: str,
    cause_class: str,
    owner: ActorRef | None,
    owner_absence_reason: str | None,
    ownership_history: tuple[OwnershipChange, ...] = (),
    sla_target: datetime,
    actions: tuple[BreakAction, ...] = (),
    resolution_evidence: ResolutionEvidence | None = None,
    state: BreakState = BreakState.INTAKE_UNASSIGNED,
) -> BreakRecord:
    """Build a richer record without changing or reinterpreting the ticket."""
    return BreakRecord(
        break_id=ticket.break_id,
        operation_id=str(ticket.operation_id),
        regime=ticket.regime.value,
        leg=ticket.leg.value,
        symptom=symptom,
        sources=sources,
        difference=difference,
        originating_event_at=ticket.raised_at,
        originating_event_ref=originating_event_ref,
        cause_class=cause_class,
        owner=owner,
        owner_absence_reason=owner_absence_reason,
        ownership_history=ownership_history,
        sla_target=sla_target,
        actions=actions,
        resolution_evidence=resolution_evidence,
        state=state,
        dsor_record_id=None if ticket.dsor_record_id is None else str(ticket.dsor_record_id),
    )


def assign_break_owner(
    record: BreakRecord,
    *,
    owner: ActorRef,
    changed_by: ActorRef,
    changed_at: datetime,
    provenance: Provenance,
) -> BreakRecord:
    """Assign or reassign ownership at the break-management boundary."""
    change = OwnershipChange(
        changed_at=changed_at,
        changed_by=changed_by,
        previous_owner=record.owner,
        assigned_owner=owner,
        provenance=provenance,
    )
    updated = record.model_dump()
    updated.update(
        owner=owner,
        owner_absence_reason=None,
        ownership_history=(*record.ownership_history, change),
        state=(BreakState.OPEN if record.state is BreakState.INTAKE_UNASSIGNED else record.state),
    )
    return BreakRecord.model_validate(updated)


def resolve_break(record: BreakRecord, *, evidence: ResolutionEvidence) -> BreakRecord:
    """Close an investigated break from attributable, break-bound evidence."""
    if record.state is not BreakState.INVESTIGATING:
        raise ValueError("only an investigating break can be resolved")
    if record.owner is None:
        raise ValueError("an ownerless break cannot be resolved")
    if evidence.break_id != record.break_id:
        raise ValueError("resolution evidence belongs to another break")
    if evidence.recorded_at < record.originating_event_at:
        raise ValueError("resolution evidence predates the break")
    if record.ownership_history and evidence.recorded_at < record.ownership_history[-1].changed_at:
        raise ValueError("resolution evidence predates the current ownership")
    updated = record.model_dump()
    updated.update(state=BreakState.RESOLVED, resolution_evidence=evidence)
    return BreakRecord.model_validate(updated)
