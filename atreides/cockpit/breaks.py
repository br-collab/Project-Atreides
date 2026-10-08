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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.cockpit.clearing_cockpit import BreakTicket

__all__ = [
    "BreakAction",
    "BreakRecord",
    "BreakState",
    "ResolutionEvidence",
    "break_record_from_ticket",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BreakState(StrEnum):
    """The current investigative state, not the cockpit ticket status."""

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


class ResolutionEvidence(_Frozen):
    """Evidence supporting a claimed resolution."""

    recorded_at: datetime
    recorded_by: ActorRef
    evidence_ref: str = Field(min_length=1)
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def _time_is_aware(self) -> Self:
        if self.recorded_at.tzinfo is None:
            raise ValueError("resolution evidence time must be timezone-aware")
        return self


class BreakRecord(_Frozen):
    """A replayable evidence record for one existing cockpit break ticket."""

    schema_version: Literal["atreides.break/0.1-experimental"] = (
        "atreides.break/0.1-experimental"
    )
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
    sla_target: datetime
    actions: tuple[BreakAction, ...] = ()
    resolution_evidence: ResolutionEvidence | None = None
    state: BreakState = BreakState.OPEN
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
        if self.state is BreakState.RESOLVED and self.resolution_evidence is None:
            raise ValueError("a resolved break must carry resolution evidence")
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
    sla_target: datetime,
    actions: tuple[BreakAction, ...] = (),
    resolution_evidence: ResolutionEvidence | None = None,
    state: BreakState = BreakState.OPEN,
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
        sla_target=sla_target,
        actions=actions,
        resolution_evidence=resolution_evidence,
        state=state,
        dsor_record_id=None if ticket.dsor_record_id is None else str(ticket.dsor_record_id),
    )
