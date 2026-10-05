"""The DSOR record of one corporate action lifecycle request.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

WHAT IS RECORDED
----------------
Every lifecycle request, applied or refused, becomes one
:class:`CorporateActionEventRecord` of kind ``corporate_action_event``,
admissible to the DSOR (Decision System of Record): the event as announced
and the journal entry, which carries the request, the outcome, any refusal
reason, and the state before and after. Nothing is recorded by reference
only, so a run of records is enough to rebuild the lifecycle
(:func:`rebuild_from_records`).

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
from typing import Literal
from uuid import UUID

from cannae_kernel.provenance import Provenance
from pydantic import Field

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
    "LifecycleTransitionBody",
    "rebuild_from_records",
    "record_request",
]


class LifecycleTransitionBody(Frozen):
    """A lifecycle request against an event, and what the lifecycle did with it."""

    body_type: Literal["lifecycle_transition"] = "lifecycle_transition"
    event: CorporateActionEvent
    entry: TransitionEntry


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
    body: LifecycleTransitionBody


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
        recorded_dtg=recorded_at.astimezone(UTC).strftime("%Y%m%d%H%M"),
        body=LifecycleTransitionBody(event=lifecycle.event, entry=entry),
    )
    return advanced, record


def rebuild_from_records(records: Iterable[CorporateActionEventRecord]) -> Lifecycle:
    """Rebuild one event's lifecycle from its records, in any order.

    Records are ordered by journal sequence. Every record must describe the
    same event as announced; a record carrying a different version of the
    event cannot be part of the same journal.
    """
    ordered = sorted(records, key=lambda r: r.body.entry.sequence)
    if not ordered:
        raise JournalMismatchError("no records to rebuild from")
    event = ordered[0].body.event
    for record in ordered[1:]:
        if record.body.event != event:
            raise JournalMismatchError(
                f"record {record.operation_id} carries a different event from the first record"
            )
    return rebuild(event, tuple(r.body.entry for r in ordered))
