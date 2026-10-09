"""Committed synthetic break records for publication seam verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId
from cannae_kernel.provenance import Provenance

from atreides.cockpit.breaks import (
    BreakRecord,
    BreakState,
    ResolutionEvidence,
    ResolutionEvidenceKind,
    assign_break_owner,
    break_record_from_ticket,
    resolve_break,
)
from atreides.cockpit.clearing_cockpit import BreakLeg, BreakTicket, PortalRegime

__all__ = ["REQUIRED_BREAK_IDS", "build_synthetic_records"]

REQUIRED_BREAK_IDS = frozenset({"BRK-SYNTHETIC-FUNDING", "BRK-SYNTHETIC-POSITION"})


def _owner() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01M2P20SY00000000000000001"),
        actor_kind=ActorKind.HUMAN,
        role="settlement operations",
        entitlement_refs=("synthetic:cockpit",),
        authenticated=True,
    )


def build_synthetic_records() -> tuple[BreakRecord, ...]:
    """Build the required scenarios through the real WP-1 record builder."""
    event_at = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    common = {
        "operation_id": UUID("00000000-0000-0000-0000-000000000111"),
        "regime": PortalRegime.CCP,
        "detail": "synthetic mismatch",
        "dsor_record_id": UUID("00000000-0000-0000-0000-000000000222"),
        "raised_at": event_at,
    }
    owned_intake = break_record_from_ticket(
        BreakTicket(break_id="BRK-SYNTHETIC-FUNDING", leg=BreakLeg.FUNDING, **common),
        symptom="synthetic funding mismatch",
        sources=("synthetic instruction package", "synthetic operator readback"),
        difference="expected 10, actual 9",
        originating_event_ref="synthetic:readback:funding",
        cause_class="SYNTHETIC_DATA_MISMATCH",
        owner=None,
        owner_absence_reason="awaiting production owner assignment",
        sla_target=event_at + timedelta(hours=4),
    )
    assigned = assign_break_owner(
        owned_intake,
        owner=_owner(),
        changed_by=_owner(),
        changed_at=event_at + timedelta(minutes=5),
        provenance=Provenance.FACT_SYNTHETIC,
    )
    owned_values = assigned.model_dump()
    owned_values["state"] = BreakState.INVESTIGATING
    investigating = BreakRecord.model_validate(owned_values)
    owned = resolve_break(
        investigating,
        evidence=ResolutionEvidence(
            break_id=investigating.break_id,
            recorded_at=event_at + timedelta(hours=1),
            recorded_by=_owner(),
            provenance=Provenance.FACT_SYNTHETIC,
            evidence_kind=ResolutionEvidenceKind.CORRECTIVE_ACTION_VERIFIED,
            evidence_ref="synthetic:corrective-action:funding",
            detail="synthetic cause corrected and replay verified",
        ),
    )
    unowned = break_record_from_ticket(
        BreakTicket(break_id="BRK-SYNTHETIC-POSITION", leg=BreakLeg.POSITION, **common),
        symptom="synthetic position mismatch",
        sources=("synthetic instruction package", "synthetic operator readback"),
        difference="expected 100, actual 99",
        originating_event_ref="synthetic:readback:position",
        cause_class="UNKNOWN",
        owner=None,
        owner_absence_reason="awaiting production owner assignment",
        sla_target=event_at + timedelta(hours=2),
    )
    return owned, unowned
