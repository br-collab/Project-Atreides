"""Render a lifecycle's DSOR records as a kernel event journal (ATR-I-12; JUM-D-12).

Each domain keeps its own append-only journal, and the Cannae C2 harness verifies
it without trusting the domain. This adapter is Atreides' side of that: it turns
the DSOR records for one ``lifecycle_id`` into a hash-chained sequence of kernel
``EventEnvelope`` s that ``cannae_kernel.journal.verify_chain`` can check, and that
a ``JournalCheckpoint`` recorded elsewhere can pin.

What an envelope carries
------------------------
The envelope payload is :class:`DSORRecordRef`: the record's id, kind, correction
pointer and the ``sha256:`` digest of the exact JSON bytes the store holds. The
record itself is not re-encoded into the kernel's canonical form, because DSOR
outputs legitimately contain values that form refuses (UUIDs, stress readings as
floats). Hashing the stored bytes covers every byte of the payload anyway: change
one and the reference digest, the payload digest, the envelope digest and every
later link change with it.

Deterministic: rendering the same records twice gives byte-identical envelopes.
Read-only: nothing here writes to the store.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import Digest, digest_bytes
from cannae_kernel.clocks import EventTimes
from cannae_kernel.domains import Domain
from cannae_kernel.events import EventEnvelope, seal
from cannae_kernel.ids import ActorId, EventId, LifecycleId, encode_ulid
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

from atreides.dsor.lifecycle_records import (
    FinalityAssertedRecord,
    HaltRecord,
    RailStatusObservedRecord,
)
from atreides.dsor.record import DSORRecord
from atreides.dsor.store import DSORStore

__all__ = [
    "ATREIDES_DSOR_ACTOR",
    "JOURNAL_SCHEMA_VERSION",
    "DSORRecordRef",
    "lifecycle_records",
    "render_journal",
]

JOURNAL_SCHEMA_VERSION = "atreides-dsor-journal/0.1-draft"

#: The actor on envelopes for records Atreides' own services produced.
ATREIDES_DSOR_ACTOR = ActorRef(
    actor_id=ActorId("act_" + "0" * 25 + "1"),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="atreides-dsor",
    entitlement_refs=(),
    authenticated=True,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_MS = timedelta(milliseconds=1)


class DSORRecordRef(BaseModel):
    """The kernel-canonical reference an envelope carries for one DSOR record."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    record_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    correction_of: str | None
    stored_payload_digest: Digest


def lifecycle_records(store: DSORStore, lifecycle_id: str) -> tuple[DSORRecord, ...]:
    """The store's records whose output names ``lifecycle_id``, in append order."""
    return tuple(
        r for r in store.records() if getattr(r.output, "lifecycle_id", None) == lifecycle_id
    )


def _event_id(record: DSORRecord) -> EventId:
    # Deterministic: the record's own time and id, so a re-render is identical.
    ms = (record.dtg.astimezone(UTC) - _EPOCH) // _EPOCH_MS
    return EventId("evt_" + encode_ulid(ms, record.record_id.bytes[:10]))


def _provenance_and_actor(output: Any) -> tuple[Provenance, ActorRef]:
    if isinstance(output, RailStatusObservedRecord):
        return output.provenance, ATREIDES_DSOR_ACTOR
    if isinstance(output, FinalityAssertedRecord):
        return output.assertion.provenance, output.assertion.authoritative_actor
    if isinstance(output, HaltRecord):
        declarer = output.halt.declared_by
        provenance = (
            Provenance.HUMAN_JUDGMENT
            if declarer.actor_kind is ActorKind.HUMAN
            else Provenance.POLICY_RESULT
        )
        return provenance, declarer
    return Provenance.POLICY_RESULT, ATREIDES_DSOR_ACTOR


def _rule_version(output: Any) -> str:
    for attribute in ("rule_version", "gate_set_version", "doctrine_version"):
        value = getattr(output, attribute, None)
        if isinstance(value, str) and value:
            return value
    return "unversioned"


def render_journal(
    store: DSORStore,
    records: Sequence[DSORRecord],
    *,
    lifecycle_id: str,
) -> list[EventEnvelope[DSORRecordRef]]:
    """Seal ``records`` as a chain of envelopes, in the order given.

    Pass the records of one lifecycle, in append order (:func:`lifecycle_records`).
    The first envelope has no prior digest; every later one links to the envelope
    before it, and names it as its parent.
    """
    lifecycle = LifecycleId(lifecycle_id)
    envelopes: list[EventEnvelope[DSORRecordRef]] = []
    prior: EventEnvelope[DSORRecordRef] | None = None
    for record in records:
        output = record.output
        at = record.dtg.astimezone(UTC)
        provenance, actor = _provenance_and_actor(output)
        payload = DSORRecordRef(
            record_id=str(record.record_id),
            kind=record.kind,
            correction_of=None if record.correction_of is None else str(record.correction_of),
            stored_payload_digest=digest_bytes(store.payload_bytes(record.record_id)),
        )
        envelope = seal(
            event_id=_event_id(record),
            lifecycle_id=lifecycle,
            parent_ids=() if prior is None else (prior.event_id,),
            producer_domain=Domain.ATREIDES,
            event_type=record.kind,
            schema_version=JOURNAL_SCHEMA_VERSION,
            rule_version=_rule_version(output),
            times=EventTimes(event_time=at, observation_time=at, processing_time=at),
            provenance=provenance,
            actor=actor,
            idempotency_key=f"dsor:{record.record_id}",
            payload=payload,
            prior_event_digest=None if prior is None else prior.envelope_digest,
        )
        envelopes.append(envelope)
        prior = envelope
    return envelopes

