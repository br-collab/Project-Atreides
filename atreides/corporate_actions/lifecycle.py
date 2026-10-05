"""The corporate action lifecycle: which milestones may follow which, and the journal.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

MILESTONES, NOT A FIXED SEQUENCE
--------------------------------
Event classes do not share one order of dates. A cash-or-stock dividend fixes
its holders at the record date and closes elections afterwards; a tender offer
closes elections before anything is allocated. So the lifecycle is a set of
milestones reached, with the rules that hold for every class:

- the entitlement is fixed at most once, and elections close at most once;
- elections close only on an elective event (voluntary, or mandatory with a
  choice);
- payment needs the entitlement fixed and, on an elective event, elections
  closed;
- cancellation is possible until payment, and ends the lifecycle;
- after payment the only change is a reversal, which ends the lifecycle;
- nothing follows an ended lifecycle;
- a milestone cannot be dated before the announcement or before the milestone
  that preceded it.

A REFUSAL IS RECORDED, NOT RAISED
---------------------------------
Every request produces one :class:`TransitionEntry`, applied or refused, with
the typed reason for a refusal. A refused request leaves the state unchanged.
This is domain validation, not an advisory disposition: there is no PASS,
HOLD or INDETERMINATE here, only what happened and why.

THE JOURNAL REBUILDS THE STATE
------------------------------
:func:`rebuild` replays the requests in a journal against the event and
requires every recomputed entry to equal the recorded one. A journal that was
altered, reordered or truncated in the middle does not rebuild.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from cannae_kernel.provenance import Provenance
from pydantic import Field, model_validator

from atreides.corporate_actions.events import CorporateActionEvent, SourceIdentity
from atreides.customer_protection.common import Frozen

__all__ = [
    "JournalMismatchError",
    "Lifecycle",
    "LifecycleState",
    "LifecycleStatus",
    "Milestone",
    "RefusalReason",
    "TransitionEntry",
    "TransitionRequest",
    "rebuild",
]


class Milestone(StrEnum):
    """What a request asks the lifecycle to record."""

    #: Who is entitled is fixed: the record date for a mandatory event.
    ENTITLEMENT_FIXED = "entitlement_fixed"
    #: No further elections are accepted. Elective events only.
    ELECTIONS_CLOSED = "elections_closed"
    PAID = "paid"
    #: Withdrawn before payment.
    CANCELLED = "cancelled"
    #: Undone after payment.
    REVERSED = "reversed"


class LifecycleStatus(StrEnum):
    OPEN = "open"
    PAID = "paid"
    CANCELLED = "cancelled"
    REVERSED = "reversed"

    @property
    def ended(self) -> bool:
        return self in (LifecycleStatus.CANCELLED, LifecycleStatus.REVERSED)


class RefusalReason(StrEnum):
    """Why a request was refused. Each names the rule it broke."""

    ENDED = "ended"
    """The lifecycle was cancelled or reversed. Nothing follows."""
    ALREADY_REACHED = "already_reached"
    """The milestone was recorded before. It is recorded once."""
    NOT_ELECTIVE = "not_elective"
    """Elections close only on an elective event."""
    ENTITLEMENT_NOT_FIXED = "entitlement_not_fixed"
    """Payment needs the entitlement fixed first."""
    ELECTIONS_OPEN = "elections_open"
    """Payment on an elective event needs elections closed first."""
    NOT_PAID = "not_paid"
    """Only a paid event can be reversed. One not yet paid is cancelled instead."""
    ALREADY_PAID = "already_paid"
    """A paid event cannot be cancelled. It is reversed instead."""
    BEFORE_ANNOUNCEMENT = "before_announcement"
    """The milestone is dated before the event was announced."""
    BEFORE_PREVIOUS_MILESTONE = "before_previous_milestone"
    """The milestone is dated before the one that preceded it."""


class LifecycleState(Frozen):
    """Where one event's lifecycle stands."""

    status: LifecycleStatus = LifecycleStatus.OPEN
    #: Milestones applied, in the order they were applied.
    reached: tuple[Milestone, ...] = ()
    #: The effective date of the last applied milestone.
    last_effective_date: date | None = None


class TransitionRequest(Frozen):
    """A request to record a milestone, and on whose word."""

    milestone: Milestone
    effective_date: date
    #: What kind of claim the milestone is: reported by DTC (``FACT_EXTERNAL``), by a
    #: synthetic adapter (``FACT_SYNTHETIC``), or an operator's decision
    #: (``HUMAN_JUDGMENT``), for example a cancellation.
    provenance: Provenance
    source: SourceIdentity


class TransitionEntry(Frozen):
    """One request and what the lifecycle did with it."""

    event_id: str
    #: Position in the journal, from zero, counting refused requests too.
    sequence: int = Field(ge=0)
    request: TransitionRequest
    outcome: Literal["applied", "refused"]
    refusal: RefusalReason | None = None
    state_before: LifecycleState
    state_after: LifecycleState

    @model_validator(mode="after")
    def _consistent(self) -> TransitionEntry:
        if self.outcome == "refused":
            if self.refusal is None:
                raise ValueError("a refused request names its reason")
            if self.state_after != self.state_before:
                raise ValueError("a refused request leaves the state unchanged")
        elif self.refusal is not None:
            raise ValueError("an applied request has no refusal reason")
        return self


class JournalMismatchError(ValueError):
    """A journal does not rebuild: an entry is not what its request recomputes to."""


def _refusal(
    event: CorporateActionEvent, state: LifecycleState, request: TransitionRequest
) -> RefusalReason | None:
    milestone = request.milestone
    if state.status.ended:
        return RefusalReason.ENDED
    if request.effective_date < event.dates.announcement_date:
        return RefusalReason.BEFORE_ANNOUNCEMENT
    if state.last_effective_date is not None and request.effective_date < state.last_effective_date:
        return RefusalReason.BEFORE_PREVIOUS_MILESTONE
    if milestone is Milestone.REVERSED:
        return None if state.status is LifecycleStatus.PAID else RefusalReason.NOT_PAID
    if milestone is Milestone.CANCELLED:
        return RefusalReason.ALREADY_PAID if state.status is LifecycleStatus.PAID else None
    if milestone in state.reached:
        return RefusalReason.ALREADY_REACHED
    if milestone is Milestone.ELECTIONS_CLOSED and not event.participation.elective:
        return RefusalReason.NOT_ELECTIVE
    if milestone is Milestone.PAID:
        if Milestone.ENTITLEMENT_FIXED not in state.reached:
            return RefusalReason.ENTITLEMENT_NOT_FIXED
        if event.participation.elective and Milestone.ELECTIONS_CLOSED not in state.reached:
            return RefusalReason.ELECTIONS_OPEN
    return None


_STATUS_AFTER = {
    Milestone.PAID: LifecycleStatus.PAID,
    Milestone.CANCELLED: LifecycleStatus.CANCELLED,
    Milestone.REVERSED: LifecycleStatus.REVERSED,
}


def _step(
    event: CorporateActionEvent,
    state: LifecycleState,
    sequence: int,
    request: TransitionRequest,
) -> TransitionEntry:
    refusal = _refusal(event, state, request)
    if refusal is not None:
        return TransitionEntry(
            event_id=event.event_id, sequence=sequence, request=request, outcome="refused",
            refusal=refusal, state_before=state, state_after=state,
        )
    after = LifecycleState(
        status=_STATUS_AFTER.get(request.milestone, state.status),
        reached=(*state.reached, request.milestone),
        last_effective_date=request.effective_date,
    )
    return TransitionEntry(
        event_id=event.event_id, sequence=sequence, request=request, outcome="applied",
        state_before=state, state_after=after,
    )


class Lifecycle(Frozen):
    """One event, where it stands, and every request made of it. Immutable."""

    event: CorporateActionEvent
    state: LifecycleState = LifecycleState()
    journal: tuple[TransitionEntry, ...] = ()

    def request(self, request: TransitionRequest) -> tuple[Lifecycle, TransitionEntry]:
        """Apply or refuse ``request``. Returns the new lifecycle and the journal entry."""
        entry = _step(self.event, self.state, len(self.journal), request)
        advanced = Lifecycle(
            event=self.event, state=entry.state_after, journal=(*self.journal, entry)
        )
        return advanced, entry


def rebuild(event: CorporateActionEvent, journal: tuple[TransitionEntry, ...]) -> Lifecycle:
    """Replay ``journal`` against ``event`` and return the lifecycle it produces.

    Raises :class:`JournalMismatchError` where an entry is out of sequence,
    belongs to another event, or is not what its request recomputes to.
    """
    lifecycle = Lifecycle(event=event)
    for expected_sequence, recorded in enumerate(journal):
        if recorded.event_id != event.event_id:
            raise JournalMismatchError(
                f"entry {recorded.sequence} belongs to event {recorded.event_id!r}, "
                f"not {event.event_id!r}"
            )
        if recorded.sequence != expected_sequence:
            raise JournalMismatchError(
                f"entry {recorded.sequence} is at position {expected_sequence}: "
                f"the journal is reordered or has a gap"
            )
        lifecycle, recomputed = lifecycle.request(recorded.request)
        if recomputed != recorded:
            raise JournalMismatchError(
                f"entry {recorded.sequence} records {recorded.outcome} "
                f"({recorded.refusal}), and its request recomputes to "
                f"{recomputed.outcome} ({recomputed.refusal})"
            )
    return lifecycle
