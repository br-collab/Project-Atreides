"""Shared SYNTHETIC events for the corporate action tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId
from cannae_kernel.provenance import Provenance

from atreides.corporate_actions import (
    CorporateActionEvent,
    EventDates,
    EventTerms,
    EventType,
    Milestone,
    Participation,
    SourceIdentity,
    TransitionRequest,
)
from atreides.corporate_actions.movement import MovementAuthorityReference

ADAPTER = SourceIdentity(source_id="synthetic-dtc-adapter", reference="SYNTHETIC-ANN-1")
OPERATOR = SourceIdentity(source_id="SYNTHETIC operations desk")
ANNOUNCED = date(2026, 10, 1)


def movement_authority(event_id: str) -> MovementAuthorityReference:
    return MovementAuthorityReference(
        governed_event_id=event_id,
        authorizing_actor=ActorRef(
            actor_id=ActorId("act_01K6A7C8D9E0F1G2H3J4K5M6N7"),
            actor_kind=ActorKind.DETERMINISTIC_SERVICE,
            role="synthetic-corporate-action-authority",
            entitlement_refs=("SYNTHETIC-AUTHORITY-1",),
            authenticated=True,
        ),
        authority_record_uri="dsor://synthetic/corporate-action-authority/1",
        provenance=Provenance.FACT_SYNTHETIC,
    )


def event(
    participation: Participation = Participation.MANDATORY,
    event_type: EventType = EventType.CASH_DIVIDEND,
    **terms: object,
) -> CorporateActionEvent:
    elective = participation is not Participation.MANDATORY
    return CorporateActionEvent(
        event_id=f"SYNTHETIC-{event_type.value}-{participation.value}",
        security_id="SYNTHETIC-XYZ",
        event_type=event_type,
        participation=participation,
        dates=EventDates(
            announcement_date=ANNOUNCED,
            record_date=date(2026, 10, 15),
            election_deadline=date(2026, 10, 20) if elective else None,
            protect_deadline=(
                date(2026, 10, 22) if participation is Participation.VOLUNTARY else None
            ),
            payable_date=date(2026, 10, 30),
        ),
        terms=EventTerms(**terms) if terms else EventTerms(
            cash_rate_per_share=Decimal("0.25"), currency="USD"
        ),
        provenance=Provenance.FACT_SYNTHETIC,
        source=ADAPTER,
    )


def ask(milestone: Milestone, day: int = 15, *, operator: bool = False) -> TransitionRequest:
    return TransitionRequest(
        milestone=milestone,
        effective_date=date(2026, 10, day),
        provenance=Provenance.HUMAN_JUDGMENT if operator else Provenance.FACT_SYNTHETIC,
        source=OPERATOR if operator else ADAPTER,
    )
