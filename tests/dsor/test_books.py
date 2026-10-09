"""A books and records posting is evidence. A match is not a posting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.journal import verify_chain
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.dsor import DSORStore, SettlementDomainOutput
from atreides.dsor.books import BooksPosting, BooksPostingRecord, assess_posting, read_posting
from atreides.dsor.journal import ATREIDES_DSOR_ACTOR, lifecycle_records, render_journal

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
EVENT = EventId("evt_" + "4" * 26)
OTHER = EventId("evt_" + "5" * 26)
LIF = "lif_01M2P20SY00000000000000001"
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "4" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-ledger",
    entitlement_refs=(),
    authenticated=True,
)
_FORBIDDEN = ("compliant", "approved", "cleared", "certified")


def _posting(**overrides: object) -> BooksPosting:
    fields: dict[str, object] = {
        "posted_record_id": "posted-1",
        "posting_authority": ACTOR,
        "effective_time": T0,
        "source_event_id": EVENT,
        "provenance": Provenance.FACT_SYNTHETIC,
    }
    fields.update(overrides)
    return BooksPosting.model_validate(fields)


def _no_claim(reason: str) -> None:
    folded = reason.casefold()
    for word in _FORBIDDEN:
        assert word not in folded


def test_a_match_does_not_post_and_a_real_posting_does() -> None:
    missing = assess_posting(None, matched=True)
    absent = assess_posting(None, matched=False)
    posted = assess_posting(_posting(), matched=True, source_event_id=EVENT)
    mismatch = assess_posting(_posting(), source_event_id=OTHER)
    assert missing.disposition is Disposition.INDETERMINATE
    assert absent.disposition is Disposition.INDETERMINATE
    assert posted.disposition is Disposition.PASS
    assert mismatch.disposition is Disposition.HOLD
    for item in (missing, absent, posted, mismatch):
        _no_claim(item.reason)


def test_an_unreadable_posting_is_indeterminate() -> None:
    payload = _posting().model_dump(mode="json")
    payload["provenance"] = "FORECAST"
    unread = read_posting(payload)
    assert unread.disposition is Disposition.INDETERMINATE
    _no_claim(unread.reason)


def test_the_record_round_trips_and_the_journal_keeps_the_fact() -> None:
    posting = _posting()
    record = BooksPostingRecord(operation_id=uuid.uuid4(), lifecycle_id=LIF, posting=posting)
    with pytest.raises(ValidationError, match="lifecycle"):
        BooksPostingRecord(operation_id=uuid.uuid4(), lifecycle_id=None, posting=posting)
    store = DSORStore(":memory:")
    store.append(record, dtg=T0)
    stored = lifecycle_records(store, LIF)
    assert stored[0].kind == "books_posting"
    assert store.replay(stored[0].record_id) == record
    envelopes = render_journal(store, stored, lifecycle_id=LIF)
    report = verify_chain(envelopes)
    assert report.ok, report.issues
    assert envelopes[0].provenance is Provenance.FACT_SYNTHETIC
    assert envelopes[0].actor == ATREIDES_DSOR_ACTOR
    assert envelopes[0].rule_version == "books-posting/0.1"
    assert "BooksPostingRecord" in str(SettlementDomainOutput)
