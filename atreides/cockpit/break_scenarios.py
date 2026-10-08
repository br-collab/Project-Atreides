"""Committed synthetic break records for publication seam verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId

from atreides.cockpit.breaks import BreakRecord, BreakState, break_record_from_ticket
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
    owned = break_record_from_ticket(
        BreakTicket(break_id="BRK-SYNTHETIC-FUNDING", leg=BreakLeg.FUNDING, **common),
        symptom="synthetic funding mismatch",
        sources=("synthetic instruction package", "synthetic operator readback"),
        difference="expected 10, actual 9",
        originating_event_ref="synthetic:readback:funding",
        cause_class="SYNTHETIC_DATA_MISMATCH",
        owner=_owner(),
        owner_absence_reason=None,
        sla_target=event_at + timedelta(hours=4),
        state=BreakState.INVESTIGATING,
    )
    unowned = break_record_from_ticket(
        BreakTicket(break_id="BRK-SYNTHETIC-POSITION", leg=BreakLeg.POSITION, **common),
        symptom="synthetic position mismatch",
        sources=("synthetic instruction package", "synthetic operator readback"),
        difference="expected 100, actual 99",
        originating_event_ref="synthetic:readback:position",
        cause_class="UNKNOWN",
        owner=None,
        owner_absence_reason="no owner recorded",
        sla_target=event_at + timedelta(hours=2),
    )
    return owned, unowned
