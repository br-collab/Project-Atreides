"""The DSOR record of one corporate action lifecycle request, election or default.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

WHAT IS RECORDED
----------------
Each of these becomes one :class:`CorporateActionEventRecord` of kind
``corporate_action_event``, admissible to the DSOR (Decision System of
Record), with a body that says which it is:

- a lifecycle request, applied or refused (:class:`LifecycleTransitionBody`):
  the event as announced and the journal entry, with the state before and
  after;
- an election submission, accepted, refused or a duplicate
  (:class:`ElectionBody`): the event, the firm's policy and the entry;
- a default assignment (:class:`DefaultAssignmentBody`): the event, the
  policy and every account's default or the reason it has none.

Nothing is recorded by reference only, so an event's records are enough to
rebuild its lifecycle (:func:`rebuild_from_records`) and its elections
(:func:`rebuild_elections_from_records`).

The record is admissible, not written. This package assembles records and
proves they round trip through the existing store; it does not claim that a
running service appends every one of them.

TWO KINDS OF CLAIM, KEPT APART
------------------------------
The event and each request carry the provenance of the fact they report
(``FACT_EXTERNAL``, ``FACT_SYNTHETIC``, or ``HUMAN_JUDGMENT`` for an
operator's decision). Whether a request was applied or refused is a
different claim, the output of this package's rules, so the record states it
separately as ``POLICY_RESULT``.

THE DIRECTION OF THE IMPORT
---------------------------
:mod:`atreides.dsor.record` imports this module to admit the record into its
closed ``SettlementDomainOutput`` union. This package never imports the DSOR,
which keeps the dependency one way and the import graph acyclic.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from cannae_kernel.provenance import Provenance
from pydantic import Field

from atreides.corporate_actions.election import (
    DefaultAssignment,
    ElectionBook,
    ElectionEntry,
    ElectionInstruction,
    ElectionPolicy,
    ProtectCover,
    rebuild_elections,
)
from atreides.corporate_actions.events import CorporateActionEvent
from atreides.corporate_actions.lifecycle import (
    JournalMismatchError,
    Lifecycle,
    TransitionEntry,
    TransitionRequest,
    rebuild,
)
from atreides.customer_protection.common import Frozen
from atreides.customer_protection.rules.model import CLAIM_LABEL, DTG_PATTERN

__all__ = [
    "CorporateActionEventRecord",
    "DefaultAssignmentBody",
    "ElectionBody",
    "LifecycleTransitionBody",
    "RecordBody",
    "rebuild_elections_from_records",
    "rebuild_from_records",
    "record_defaults",
    "record_request",
    "record_submission",
]


class LifecycleTransitionBody(Frozen):
    """A lifecycle request against an event, and what the lifecycle did with it."""

    body_type: Literal["lifecycle_transition"] = "lifecycle_transition"
    event: CorporateActionEvent
    entry: TransitionEntry


class ElectionBody(Frozen):
    """An election submission against an event, and what the workflow did with it."""

    body_type: Literal["election"] = "election"
    event: CorporateActionEvent
    policy: ElectionPolicy
    entry: ElectionEntry


class DefaultAssignmentBody(Frozen):
    """The default applied to every account's uninstructed balance."""

    body_type: Literal["default_assignment"] = "default_assignment"
    event: CorporateActionEvent
    policy: ElectionPolicy
    assignment: DefaultAssignment


RecordBody = Annotated[
    LifecycleTransitionBody | ElectionBody | DefaultAssignmentBody,
    Field(discriminator="body_type"),
]


class CorporateActionEventRecord(Frozen):
    """DSOR output for one corporate action lifecycle request."""

    kind: Literal["corporate_action_event"] = "corporate_action_event"
    schema_version: Literal["0.1-draft"] = "0.1-draft"
    #: The record's own identifier, and the DSOR store's record subject.
    operation_id: UUID
    #: When the record was assembled, as a DTG (date-time group), UTC, ``YYYYMMDDHHMM``.
    recorded_dtg: str = Field(pattern=DTG_PATTERN)
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    #: The kind of claim the outcome is: the result of this package's rules.
    outcome_provenance: Literal[Provenance.POLICY_RESULT] = Provenance.POLICY_RESULT
    body: RecordBody


def record_request(
    lifecycle: Lifecycle,
    request: TransitionRequest,
    *,
    operation_id: UUID,
    recorded_at: datetime,
) -> tuple[Lifecycle, CorporateActionEventRecord]:
    """Apply or refuse ``request`` and assemble its record. Pure: caller supplies id, time."""
    advanced, entry = lifecycle.request(request)
    record = CorporateActionEventRecord(
        operation_id=operation_id,
        recorded_dtg=_dtg(recorded_at),
        body=LifecycleTransitionBody(event=lifecycle.event, entry=entry),
    )
    return advanced, record


def _dtg(recorded_at: datetime) -> str:
    return recorded_at.astimezone(UTC).strftime("%Y%m%d%H%M")


def record_submission(
    book: ElectionBook,
    submission: ElectionInstruction | ProtectCover,
    *,
    operation_id: UUID,
    recorded_at: datetime,
) -> tuple[ElectionBook, CorporateActionEventRecord]:
    """Accept, refuse or recognise a duplicate, and assemble its record. Pure."""
    advanced, entry = book.submit(submission)
    record = CorporateActionEventRecord(
        operation_id=operation_id,
        recorded_dtg=_dtg(recorded_at),
        body=ElectionBody(event=book.event, policy=book.policy, entry=entry),
    )
    return advanced, record


def record_defaults(
    book: ElectionBook,
    assignment: DefaultAssignment,
    *,
    operation_id: UUID,
    recorded_at: datetime,
) -> CorporateActionEventRecord:
    """Assemble the record of a default assignment made from ``book``. Pure."""
    if assignment.event_id != book.event.event_id:
        raise ValueError("the assignment is for another event")
    return CorporateActionEventRecord(
        operation_id=operation_id,
        recorded_dtg=_dtg(recorded_at),
        body=DefaultAssignmentBody(event=book.event, policy=book.policy, assignment=assignment),
    )


def _one_event(bodies: list[LifecycleTransitionBody] | list[ElectionBody]) -> CorporateActionEvent:
    if not bodies:
        raise JournalMismatchError("no records to rebuild from")
    event = bodies[0].event
    if any(body.event != event for body in bodies[1:]):
        raise JournalMismatchError("a record carries a different event from the first record")
    return event


def rebuild_from_records(records: Iterable[CorporateActionEventRecord]) -> Lifecycle:
    """Rebuild one event's lifecycle from its records, in any order.

    Only lifecycle records are read; an event's election and default records
    may be passed alongside. Every lifecycle record must describe the same
    event as announced: a record carrying a different version of the event
    cannot be part of the same journal.
    """
    bodies = sorted(
        (r.body for r in records if isinstance(r.body, LifecycleTransitionBody)),
        key=lambda b: b.entry.sequence,
    )
    return rebuild(_one_event(bodies), tuple(b.entry for b in bodies))


def rebuild_elections_from_records(records: Iterable[CorporateActionEventRecord]) -> ElectionBook:
    """Rebuild one event's election book from its records, in any order.

    Only election records are read. Every one must carry the same event and
    the same policy.
    """
    bodies = sorted(
        (r.body for r in records if isinstance(r.body, ElectionBody)),
        key=lambda b: b.entry.sequence,
    )
    event = _one_event(bodies)
    policy = bodies[0].policy
    if any(body.policy != policy for body in bodies[1:]):
        raise JournalMismatchError("a record carries a different policy from the first record")
    return rebuild_elections(event, policy, tuple(b.entry for b in bodies))
