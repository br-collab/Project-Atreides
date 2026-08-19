"""The escalation register - raised, and not delivered until acknowledged.

THE CLAIM THIS PACKAGE MAKES
----------------------------
**An escalation is not delivered because it was raised. It is delivered when
somebody acknowledges it.** Everything here follows from that one sentence.

The framework already had the raising half. A gate returns ESCALATE, an agent
builds an ``EscalationRequired``, and the object carries a tier. What it did
not have was any concept of the other end: no destination, no queue, no
acknowledgement, and therefore no way to answer the only question that
matters about an escalation, which is whether a human has it.

The consequence was a specific and quiet failure mode. A system can escalate
correctly, record the escalation correctly, replay the escalation correctly,
and have nobody working it - and every artifact it produces will look right.
An unread escalation and a worked one are byte-identical in a store that only
records that one was raised.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No transport. No email, no pager, no webhook, no queue client, no socket. This
package holds the *state* of a delivery and refuses to hold the delivery
mechanism, for the same reason the framework refuses to submit payments: the
moment it acquires a transport it acquires an outage, a credential, a retry
policy and a duplicate-delivery problem, and none of those belong in a
governance layer.

What it does instead is make the absence measurable. ``unacknowledged()`` and
``overdue()`` are the whole product: a firm that wires a pager to this
register can prove the pager fired, and a firm that wires nothing to it can
see exactly how many escalations nobody has touched. Both are better than the
previous state, in which neither question could be asked.

WHY THERE IS NO CLOCK
---------------------
Same architectural contract as the gate and the funding model: PURE, NO I/O,
NO CLOCK. Every time in this module is an offset in seconds supplied by the
caller, so the register is replayable. A register that consulted a clock could
not answer "what did this look like at 14:05 yesterday", which is the question
an investigation asks.

WHY APPEND-ONLY
---------------
An acknowledgement is not a state change on the escalation, it is a second
record about it. The escalation is never mutated and never removed. A firm
that acknowledged an escalation and then found out the acknowledgement was
somebody clicking through a queue needs the original raising, its deadline,
and the acknowledgement that came late, all three - and a mutable status field
would have destroyed two of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

__all__ = [
    "DOCTRINE_VERSION",
    "Acknowledgement",
    "Escalation",
    "EscalationAlreadyAcknowledgedError",
    "EscalationNotFoundError",
    "EscalationRegister",
    "EscalationState",
    "absent_acknowledgement",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-ESCALATION-001-draft-v0.1"


class EscalationState(StrEnum):
    """Where an escalation has got to.

    Derived from the records, never stored. A stored status can disagree with
    the records that produced it; a derived one cannot.
    """

    RAISED = "raised"
    """Raised, and nobody has acknowledged it. NOT delivered - this is the
    state the framework previously had no way to express, and the state most
    operational escalation failures actually sit in."""

    ACKNOWLEDGED = "acknowledged"
    """A named person acknowledged it, within its deadline where it had one."""

    ACKNOWLEDGED_LATE = "acknowledged_late"
    """Acknowledged after its deadline. Distinct from ACKNOWLEDGED because
    "somebody got to it eventually" and "somebody got to it in time" are
    different facts about a control, and a review that cannot separate them
    cannot tell whether the control works."""

    OVERDUE = "overdue"
    """Past its deadline and still unacknowledged. The finding this register
    exists to produce."""


class EscalationNotFoundError(KeyError):
    """Acknowledging something this register never raised.

    Its own exception rather than a bare KeyError, because the operational
    meaning is specific: somebody is acknowledging an escalation that does not
    exist here, which is either a stale identifier or an acknowledgement aimed
    at the wrong register.
    """


class EscalationAlreadyAcknowledgedError(Exception):
    """A second acknowledgement for an escalation that already has one.

    Refused rather than recorded. Two acknowledgements mean two people each
    believe they have it, and the second one silently overwriting the first
    would destroy the evidence of exactly that.
    """


@dataclass(frozen=True, slots=True)
class Escalation:
    """One escalation, as raised.

    Immutable. Acknowledgement is a separate record; see the module docstring.
    """

    escalation_id: str
    operation_id: UUID
    #: Offset in seconds from the caller's reference instant. This module
    #: reads no clock.
    raised_at_offset_seconds: int
    #: Why, in enough words that somebody reading it cold can act.
    reason: str
    #: Who or what tier this is for. A string rather than an enum because the
    #: tiering vocabulary belongs to the firm's own authority model, and this
    #: register's job is to record the destination it was given rather than to
    #: define the destinations.
    routed_to: str
    #: The offset by which it must be acknowledged. ``None`` means no deadline
    #: was set, which this register records rather than invents: an
    #: escalation with no deadline can never be overdue, and a firm that wants
    #: overdue detection has to state a deadline.
    acknowledge_by_offset_seconds: int | None = None
    doctrine_version: str = DOCTRINE_VERSION

    def __post_init__(self) -> None:
        if not self.escalation_id:
            raise ValueError("escalation_id is required")
        if not self.reason:
            raise ValueError(
                "an escalation with no reason is not an escalation; the "
                "person receiving it needs to know what they are receiving"
            )
        if not self.routed_to:
            raise ValueError(
                "an escalation with no destination is the condition this "
                "register exists to make impossible"
            )
        if (
            self.acknowledge_by_offset_seconds is not None
            and self.acknowledge_by_offset_seconds < self.raised_at_offset_seconds
        ):
            raise ValueError(
                "acknowledge_by_offset_seconds precedes the raising; a "
                "deadline in the past is overdue at birth and says nothing "
                "about anybody's response"
            )

    @property
    def has_deadline(self) -> bool:
        return self.acknowledge_by_offset_seconds is not None


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """A named person taking an escalation.

    ``acknowledged_by`` is required and is not defaulted. An acknowledgement
    with no name attached answers the question "has somebody got this" with
    "something has", which is the answer that made this register necessary.
    """

    escalation_id: str
    acknowledged_by: str
    acknowledged_at_offset_seconds: int

    def __post_init__(self) -> None:
        if not self.acknowledged_by:
            raise ValueError(
                "an acknowledgement must name who acknowledged it; an "
                "anonymous acknowledgement is indistinguishable from an "
                "automated one clearing a queue"
            )


class EscalationRegister:
    """Append-only register of escalations and their acknowledgements.

    In-process and unsynchronised, deliberately. Persisting this belongs to
    the DSOR, and a register that opened its own store would put a second
    system of record beside the one the framework already has.
    """

    def __init__(self) -> None:
        self._raised: dict[str, Escalation] = {}
        self._acknowledged: dict[str, Acknowledgement] = {}
        self._order: list[str] = []

    # -- raising ----------------------------------------------------------

    def raise_escalation(self, escalation: Escalation) -> Escalation:
        """Record an escalation. Raising is not delivering."""
        if escalation.escalation_id in self._raised:
            raise EscalationAlreadyAcknowledgedError(
                f"escalation {escalation.escalation_id} has already been "
                f"raised; re-raising would overwrite the original and its "
                f"deadline"
            )
        self._raised[escalation.escalation_id] = escalation
        self._order.append(escalation.escalation_id)
        return escalation

    # -- acknowledging ----------------------------------------------------

    def acknowledge(
        self, escalation_id: str, *, by: str, at_offset_seconds: int
    ) -> Acknowledgement:
        """Record that a named person has taken this escalation."""
        if escalation_id not in self._raised:
            raise EscalationNotFoundError(
                f"no escalation {escalation_id} in this register; an "
                f"acknowledgement for something never raised is either a "
                f"stale identifier or the wrong register"
            )
        if escalation_id in self._acknowledged:
            existing = self._acknowledged[escalation_id]
            raise EscalationAlreadyAcknowledgedError(
                f"escalation {escalation_id} was already acknowledged by "
                f"{existing.acknowledged_by}; a second acknowledgement means "
                f"two people each believe they have it, and overwriting the "
                f"first would destroy the evidence of that"
            )
        ack = Acknowledgement(
            escalation_id=escalation_id,
            acknowledged_by=by,
            acknowledged_at_offset_seconds=at_offset_seconds,
        )
        self._acknowledged[escalation_id] = ack
        return ack

    # -- reading ----------------------------------------------------------

    def state(self, escalation_id: str, *, as_of_offset_seconds: int) -> EscalationState:
        """Derive the state of one escalation at a stated instant."""
        escalation = self._raised.get(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"no escalation {escalation_id}")
        ack = self._acknowledged.get(escalation_id)
        deadline = escalation.acknowledge_by_offset_seconds
        if ack is not None:
            if deadline is not None and ack.acknowledged_at_offset_seconds > deadline:
                return EscalationState.ACKNOWLEDGED_LATE
            return EscalationState.ACKNOWLEDGED
        if deadline is not None and as_of_offset_seconds > deadline:
            return EscalationState.OVERDUE
        return EscalationState.RAISED

    def unacknowledged(self, *, as_of_offset_seconds: int) -> tuple[Escalation, ...]:
        """Every escalation nobody has taken, oldest first.

        The number a firm should be looking at, and the number that did not
        exist before this register did.
        """
        return tuple(
            self._raised[eid]
            for eid in self._order
            if eid not in self._acknowledged
            and self._raised[eid].raised_at_offset_seconds <= as_of_offset_seconds
        )

    def overdue(self, *, as_of_offset_seconds: int) -> tuple[Escalation, ...]:
        """Every escalation past its deadline and still unacknowledged.

        Escalations with no deadline are never overdue and are never returned
        here. That is not leniency: an escalation nobody put a deadline on
        cannot be late, and reporting it as late would be this register
        inventing a bound the firm declined to set. They remain in
        :meth:`unacknowledged`, which is where they should be read.
        """
        return tuple(
            e
            for e in self.unacknowledged(as_of_offset_seconds=as_of_offset_seconds)
            if e.acknowledge_by_offset_seconds is not None
            and as_of_offset_seconds > e.acknowledge_by_offset_seconds
        )

    def acknowledgement_for(self, escalation_id: str) -> Acknowledgement | None:
        """The acknowledgement, or ``None`` where nobody has taken it."""
        if escalation_id not in self._raised:
            raise EscalationNotFoundError(f"no escalation {escalation_id}")
        return self._acknowledged.get(escalation_id)

    @property
    def raised(self) -> tuple[Escalation, ...]:
        """Every escalation, in the order raised. Never removed."""
        return tuple(self._raised[eid] for eid in self._order)

    def __len__(self) -> int:
        return len(self._raised)


def absent_acknowledgement(escalation_id: str) -> str:
    """Why an unacknowledged escalation is not a delivered one.

    Named and exported, and returning a sentence rather than a value, for the
    same reason as ``absent_gate_decision()`` and ``absent_readback()``: the
    answer to "was this escalation delivered" when nobody has acknowledged it
    is a refusal, and refusals belong in one auditable place rather than as a
    convention at every call site.

    The specific error this prevents is the one that made the register
    necessary. A system that records raising and not receipt produces an
    identical artifact for an escalation somebody is working and an escalation
    nobody has read, and the second is the one that hurts.
    """
    return (
        f"Escalation {escalation_id} has been raised and not acknowledged. It "
        f"is not delivered. Nothing in this framework knows whether a human "
        f"has seen it, and an escalation nobody has read is operationally "
        f"identical to one that was never raised - the difference is only "
        f"visible in the record, which is why this register keeps one "
        f"(AUR-CUSTODY-ESCALATION-001 draft)."
    )
