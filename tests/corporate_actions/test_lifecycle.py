"""WP-1 acceptance: the corporate action event model and lifecycle (ORDER SC-1).

Acceptance criteria, mapped:

- Allowed progression: ``test_a_mandatory_event_progresses_to_paid`` and
  ``test_an_elective_event_closes_elections_and_fixes_entitlement_in_either_order``.
- Terminal behavior: ``test_nothing_follows_an_ended_lifecycle``.
- Cancellation and reversal: ``test_cancellation_is_possible_until_payment``,
  ``test_a_paid_event_is_reversed_not_cancelled``, ``test_only_a_paid_event_is_reversed``.
- Illegal progression is refused: ``test_illegal_progression_is_refused_by_name`` and
  ``test_a_refused_request_is_journaled_and_changes_nothing``.
- Replay of the journal rebuilds identical state: ``test_the_journal_rebuilds_the_lifecycle``
  and the property ``test_property_any_request_sequence_rebuilds_and_keeps_its_rules``.
- Records round trip through the existing DSOR store:
  ``test_every_record_round_trips_through_the_store`` and
  ``test_the_lifecycle_rebuilds_from_stored_records``.

Every event below is SYNTHETIC.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from cannae_kernel.provenance import Provenance
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

import atreides.corporate_actions as package
from atreides.corporate_actions import (
    CorporateActionEvent,
    CorporateActionEventRecord,
    EventDates,
    EventTerms,
    EventType,
    JournalMismatchError,
    Lifecycle,
    LifecycleStatus,
    LifecycleTransitionBody,
    Milestone,
    Participation,
    RefusalReason,
    TransitionRequest,
    rebuild,
    rebuild_from_records,
    record_request,
)
from atreides.corporate_actions import events as events_module
from atreides.corporate_actions import lifecycle as lifecycle_module
from atreides.corporate_actions import record as record_module
from atreides.dsor import DSORRecord, DSORStore, RecordKind, SettlementDomainOutput
from tests.corporate_actions.conftest import ADAPTER, ANNOUNCED, ask, event

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def op(n: int) -> UUID:
    return UUID(int=n)


def run(lifecycle: Lifecycle, *requests: TransitionRequest) -> Lifecycle:
    for request in requests:
        lifecycle, _ = lifecycle.request(request)
    return lifecycle


def last_refusal(lifecycle: Lifecycle) -> RefusalReason | None:
    return lifecycle.journal[-1].refusal


# --- the event as announced ---------------------------------------------------------------


@pytest.mark.parametrize("event_type", list(EventType))
@pytest.mark.parametrize("participation", list(Participation))
def test_every_class_and_participation_is_an_event(
    event_type: EventType, participation: Participation
) -> None:
    built = event(participation, event_type)
    assert built.event_type is event_type and built.participation is participation


def test_an_elective_event_states_its_election_deadline() -> None:
    dumped = event(Participation.VOLUNTARY).model_dump()
    dumped["dates"] |= {"election_deadline": None, "protect_deadline": None}
    with pytest.raises(ValidationError, match="states an election deadline"):
        CorporateActionEvent.model_validate(dumped)


def test_a_mandatory_event_has_no_election_deadline() -> None:
    dumped = event().model_dump()
    dumped["dates"]["election_deadline"] = date(2026, 10, 20)
    with pytest.raises(ValidationError, match="no election deadline"):
        CorporateActionEvent.model_validate(dumped)


def test_a_protect_deadline_belongs_to_a_voluntary_event() -> None:
    dumped = event(Participation.MANDATORY_WITH_CHOICE).model_dump()
    dumped["dates"]["protect_deadline"] = date(2026, 10, 22)
    with pytest.raises(ValidationError, match="belongs to a voluntary event"):
        CorporateActionEvent.model_validate(dumped)


@pytest.mark.parametrize(
    ("dates", "message"),
    [
        ({"record_date": date(2026, 9, 30)}, "precedes the announcement date"),
        ({"election_deadline": date(2026, 10, 20), "protect_deadline": date(2026, 10, 19)},
         "protect deadline cannot precede"),
        ({"record_date": date(2026, 10, 15), "payable_date": date(2026, 10, 14)},
         "payable date cannot precede"),
    ],
)
def test_dates_are_ordered(dates: dict[str, date], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EventDates(announcement_date=ANNOUNCED, **dates)


@pytest.mark.parametrize(
    "provenance", sorted(set(Provenance) - {Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC})
)
def test_an_event_is_a_reported_fact(provenance: Provenance) -> None:
    dumped = event().model_dump() | {"provenance": provenance}
    with pytest.raises(ValidationError, match="reported fact"):
        CorporateActionEvent.model_validate(dumped)


def test_an_external_event_names_its_source_separately() -> None:
    external = event().model_copy(update={"provenance": Provenance.FACT_EXTERNAL})
    assert CorporateActionEvent.model_validate(external.model_dump()).source == ADAPTER


@pytest.mark.parametrize(
    ("terms", "message"),
    [
        ({"split_new": 3}, "both sides or neither"),
        ({"cash_rate_per_share": Decimal("0.25")}, "with its currency"),
        ({"currency": "USD"}, "with its currency"),
        ({"cash_rate_per_share": 0.25, "currency": "USD"}, "not float"),
        ({"stock_rate_per_share": Decimal("-0.05")}, "greater than or equal"),
    ],
)
def test_terms_are_exact_and_complete(terms: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EventTerms(**terms)


# --- allowed progression ------------------------------------------------------------------


@pytest.mark.requirement("SC-P-04")
def test_a_mandatory_event_progresses_to_paid() -> None:
    paid = run(Lifecycle(event=event()), ask(Milestone.ENTITLEMENT_FIXED, 15),
               ask(Milestone.PAID, 30))
    assert paid.state.status is LifecycleStatus.PAID
    assert paid.state.reached == (Milestone.ENTITLEMENT_FIXED, Milestone.PAID)
    assert [e.outcome for e in paid.journal] == ["applied", "applied"]


@pytest.mark.parametrize("participation", [Participation.VOLUNTARY,
                                           Participation.MANDATORY_WITH_CHOICE])
@pytest.mark.parametrize("elections_first", [True, False])
def test_an_elective_event_closes_elections_and_fixes_entitlement_in_either_order(
    participation: Participation, elections_first: bool
) -> None:
    first, second = Milestone.ELECTIONS_CLOSED, Milestone.ENTITLEMENT_FIXED
    if not elections_first:
        first, second = second, first
    paid = run(Lifecycle(event=event(participation)), ask(first, 15), ask(second, 20),
               ask(Milestone.PAID, 30))
    assert paid.state.status is LifecycleStatus.PAID
    assert all(e.outcome == "applied" for e in paid.journal)


# --- cancellation, reversal, and the end of a lifecycle -----------------------------------


@pytest.mark.parametrize(
    "before", [(), (Milestone.ENTITLEMENT_FIXED,)], ids=["announced", "entitlement-fixed"]
)
def test_cancellation_is_possible_until_payment(before: tuple[Milestone, ...]) -> None:
    cancelled = run(Lifecycle(event=event()), *(ask(m) for m in before),
                    ask(Milestone.CANCELLED, operator=True))
    assert cancelled.state.status is LifecycleStatus.CANCELLED
    assert cancelled.journal[-1].outcome == "applied"
    assert cancelled.journal[-1].request.provenance is Provenance.HUMAN_JUDGMENT


def test_a_paid_event_is_reversed_not_cancelled() -> None:
    paid = run(Lifecycle(event=event()), ask(Milestone.ENTITLEMENT_FIXED), ask(Milestone.PAID, 30))
    refused = run(paid, ask(Milestone.CANCELLED, 30, operator=True))
    assert last_refusal(refused) is RefusalReason.ALREADY_PAID
    reversed_ = run(paid, ask(Milestone.REVERSED, 31))
    assert reversed_.state.status is LifecycleStatus.REVERSED


def test_only_a_paid_event_is_reversed() -> None:
    open_ = run(Lifecycle(event=event()), ask(Milestone.REVERSED))
    assert last_refusal(open_) is RefusalReason.NOT_PAID
    assert open_.state.status is LifecycleStatus.OPEN


@pytest.mark.parametrize("end", [Milestone.CANCELLED, Milestone.REVERSED])
@pytest.mark.parametrize("then", list(Milestone))
def test_nothing_follows_an_ended_lifecycle(end: Milestone, then: Milestone) -> None:
    ended = run(Lifecycle(event=event()), ask(Milestone.ENTITLEMENT_FIXED), ask(Milestone.PAID, 30))
    if end is Milestone.CANCELLED:
        ended = run(Lifecycle(event=event()), ask(Milestone.CANCELLED, operator=True))
    else:
        ended = run(ended, ask(Milestone.REVERSED, 31))
    after = run(ended, ask(then, 31))
    assert last_refusal(after) is RefusalReason.ENDED
    assert after.state == ended.state


# --- illegal progression ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("participation", "requests", "reason"),
    [
        (Participation.MANDATORY, [(Milestone.PAID, 30)], RefusalReason.ENTITLEMENT_NOT_FIXED),
        (Participation.VOLUNTARY, [(Milestone.ENTITLEMENT_FIXED, 15), (Milestone.PAID, 30)],
         RefusalReason.ELECTIONS_OPEN),
        (Participation.MANDATORY, [(Milestone.ELECTIONS_CLOSED, 20)], RefusalReason.NOT_ELECTIVE),
        (Participation.MANDATORY,
         [(Milestone.ENTITLEMENT_FIXED, 15), (Milestone.PAID, 30),
          (Milestone.ELECTIONS_CLOSED, 30)],
         RefusalReason.NOT_ELECTIVE),
        (Participation.MANDATORY,
         [(Milestone.ENTITLEMENT_FIXED, 15), (Milestone.ENTITLEMENT_FIXED, 16)],
         RefusalReason.ALREADY_REACHED),
        (Participation.MANDATORY,
         [(Milestone.ENTITLEMENT_FIXED, 15), (Milestone.PAID, 30), (Milestone.PAID, 30)],
         RefusalReason.ALREADY_REACHED),
        (Participation.MANDATORY, [(Milestone.ENTITLEMENT_FIXED, 15), (Milestone.PAID, 14)],
         RefusalReason.BEFORE_PREVIOUS_MILESTONE),
    ],
)
def test_illegal_progression_is_refused_by_name(
    participation: Participation, requests: list[tuple[Milestone, int]], reason: RefusalReason
) -> None:
    after = run(Lifecycle(event=event(participation)), *(ask(m, d) for m, d in requests))
    assert last_refusal(after) is reason


def test_a_milestone_before_the_announcement_is_refused() -> None:
    early = TransitionRequest(milestone=Milestone.ENTITLEMENT_FIXED,
                              effective_date=date(2026, 9, 30),
                              provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)
    assert last_refusal(run(Lifecycle(event=event()), early)) is (
        RefusalReason.BEFORE_ANNOUNCEMENT
    )


def test_a_refused_request_is_journaled_and_changes_nothing() -> None:
    lifecycle = run(Lifecycle(event=event()), ask(Milestone.ENTITLEMENT_FIXED))
    after, entry = lifecycle.request(ask(Milestone.ELECTIONS_CLOSED, 20))
    assert entry.outcome == "refused" and entry.refusal is RefusalReason.NOT_ELECTIVE
    assert after.state == lifecycle.state
    assert after.journal[-1] == entry and entry.sequence == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"outcome": "refused", "refusal": None}, "names its reason"),
        ({"outcome": "applied", "refusal": RefusalReason.ENDED}, "no refusal reason"),
    ],
)
def test_an_entry_is_internally_consistent(changes: dict[str, Any], message: str) -> None:
    entry = run(Lifecycle(event=event()), ask(Milestone.ENTITLEMENT_FIXED)).journal[0]
    with pytest.raises(ValidationError, match=message):
        type(entry).model_validate(entry.model_dump() | changes)


def test_a_refused_entry_cannot_claim_a_state_change() -> None:
    lifecycle = run(Lifecycle(event=event()), ask(Milestone.PAID, 30))
    refused, applied = lifecycle.journal[0], run(Lifecycle(event=event()),
                                                 ask(Milestone.ENTITLEMENT_FIXED)).journal[0]
    with pytest.raises(ValidationError, match="leaves the state unchanged"):
        type(refused).model_validate(
            refused.model_dump() | {"state_after": applied.state_after.model_dump()}
        )


# --- the journal rebuilds the state --------------------------------------------------------


def full_journal() -> Lifecycle:
    return run(
        Lifecycle(event=event(Participation.VOLUNTARY)),
        ask(Milestone.PAID, 15),
        ask(Milestone.ELECTIONS_CLOSED, 20),
        ask(Milestone.ENTITLEMENT_FIXED, 22),
        ask(Milestone.PAID, 30),
        ask(Milestone.CANCELLED, 30, operator=True),
        ask(Milestone.REVERSED, 31),
    )


@pytest.mark.requirement("SC-G-03")
def test_the_journal_rebuilds_the_lifecycle() -> None:
    live = full_journal()
    assert [e.outcome for e in live.journal] == [
        "refused", "applied", "applied", "applied", "refused", "applied",
    ]
    assert rebuild(live.event, live.journal) == live


def test_an_altered_entry_does_not_rebuild() -> None:
    live = full_journal()
    forged = live.journal[0].model_copy(update={
        "outcome": "applied", "refusal": None, "state_after": live.journal[1].state_after,
    })
    with pytest.raises(JournalMismatchError, match="recomputes to refused"):
        rebuild(live.event, (forged, *live.journal[1:]))


def test_a_reordered_or_gapped_journal_does_not_rebuild() -> None:
    live = full_journal()
    with pytest.raises(JournalMismatchError, match="reordered or has a gap"):
        rebuild(live.event, (live.journal[1], live.journal[0], *live.journal[2:]))
    with pytest.raises(JournalMismatchError, match="reordered or has a gap"):
        rebuild(live.event, (live.journal[0], *live.journal[2:]))


def test_another_events_entry_does_not_rebuild() -> None:
    live = full_journal()
    with pytest.raises(JournalMismatchError, match="belongs to event"):
        rebuild(event(), live.journal)


_requests = st.lists(
    st.builds(
        TransitionRequest,
        milestone=st.sampled_from(Milestone),
        effective_date=st.dates(min_value=date(2026, 9, 25), max_value=date(2026, 11, 5)),
        provenance=st.sampled_from([Provenance.FACT_SYNTHETIC, Provenance.HUMAN_JUDGMENT]),
        source=st.just(ADAPTER),
    ),
    max_size=12,
)


@given(participation=st.sampled_from(Participation), requests=_requests)
def test_property_any_request_sequence_rebuilds_and_keeps_its_rules(
    participation: Participation, requests: list[TransitionRequest]
) -> None:
    live = run(Lifecycle(event=event(participation)), *requests)
    assert rebuild(live.event, live.journal) == live
    assert len(live.journal) == len(requests)
    state = live.state
    assert len(set(state.reached)) == len(state.reached)
    if Milestone.PAID in state.reached:
        assert Milestone.ENTITLEMENT_FIXED in state.reached
        before_paid = state.reached[: state.reached.index(Milestone.PAID)]
        assert Milestone.ENTITLEMENT_FIXED in before_paid
        if participation.elective:
            assert Milestone.ELECTIONS_CLOSED in before_paid
    if not participation.elective:
        assert Milestone.ELECTIONS_CLOSED not in state.reached
    assert not ({Milestone.CANCELLED, Milestone.REVERSED} <= set(state.reached))
    applied = [e.request.effective_date for e in live.journal if e.outcome == "applied"]
    assert applied == sorted(applied) and all(d >= ANNOUNCED for d in applied)
    ended_at = next((i for i, e in enumerate(live.journal)
                     if e.outcome == "applied" and e.state_after.status.ended), None)
    if ended_at is not None:
        assert all(e.refusal is RefusalReason.ENDED for e in live.journal[ended_at + 1:])


# --- the DSOR record ------------------------------------------------------------------------


def recorded_journal() -> tuple[Lifecycle, list[CorporateActionEventRecord]]:
    lifecycle = Lifecycle(event=event(Participation.VOLUNTARY))
    records = []
    for n, request in enumerate([
        ask(Milestone.PAID, 15), ask(Milestone.ELECTIONS_CLOSED, 20),
        ask(Milestone.ENTITLEMENT_FIXED, 22), ask(Milestone.PAID, 30),
    ]):
        lifecycle, record = record_request(lifecycle, request, operation_id=op(100 + n),
                                           recorded_at=NOW)
        records.append(record)
    return lifecycle, records


def test_the_dsor_admits_the_record_kind() -> None:
    assert "corporate_action_event" in RecordKind.__args__  # type: ignore[attr-defined]
    assert "CorporateActionEventRecord" in str(SettlementDomainOutput)


def test_a_record_separates_the_facts_claim_from_the_outcomes() -> None:
    _, records = recorded_journal()
    record = records[0]
    assert record.claim_label == "EXPERIMENTAL"
    assert record.recorded_dtg == "202610051200"
    assert record.outcome_provenance is Provenance.POLICY_RESULT
    assert isinstance(record.body, LifecycleTransitionBody)
    assert record.body.event.provenance is Provenance.FACT_SYNTHETIC
    assert record.body.entry.outcome == "refused"
    with pytest.raises(ValidationError):
        CorporateActionEventRecord.model_validate(
            record.model_dump() | {"outcome_provenance": Provenance.FACT_EXTERNAL}
        )


def test_every_record_round_trips_through_the_store() -> None:
    _, records = recorded_journal()
    with DSORStore(":memory:") as store:
        for record in records:
            stored = store.append(record, dtg=NOW)
            assert stored.kind == "corporate_action_event"
            assert store.payload_bytes(stored.record_id) == record.model_dump_json().encode()
            replayed = store.replay(stored.record_id)
            assert isinstance(replayed, CorporateActionEventRecord)
            assert replayed == record
            assert replayed.model_dump_json() == record.model_dump_json()
        journaled = store.records()
        assert all(isinstance(r, DSORRecord) for r in journaled)
        assert [r.output for r in journaled] == records


def test_the_lifecycle_rebuilds_from_stored_records() -> None:
    live, records = recorded_journal()
    with DSORStore(":memory:") as store:
        for record in records:
            store.append(record, dtg=NOW)
        stored = [r.output for r in store.records()]
    assert all(isinstance(r, CorporateActionEventRecord) for r in stored)
    rebuilt = rebuild_from_records(reversed(stored))  # type: ignore[arg-type]
    assert rebuilt == live
    again = recorded_journal()[1]
    assert [r.model_dump_json() for r in again] == [r.model_dump_json() for r in records]


def test_records_of_a_different_event_do_not_rebuild_together() -> None:
    _, records = recorded_journal()
    other = records[1].model_copy(update={"body": records[1].body.model_copy(
        update={"event": event(Participation.MANDATORY_WITH_CHOICE)})})
    with pytest.raises(JournalMismatchError, match="different event"):
        rebuild_from_records([records[0], other])
    with pytest.raises(JournalMismatchError, match="no records"):
        rebuild_from_records([])


def test_a_one_way_import_graph() -> None:
    """Either import order works: the DSOR imports this package, never the reverse."""
    for first in ("atreides.corporate_actions.record", "atreides.dsor.record"):
        subprocess.run([sys.executable, "-c", f"import {first}"], check=True)
    for module in (package, events_module, lifecycle_module, record_module):
        imports = [
            line.strip() for line in inspect.getsource(module).splitlines()
            if line.startswith(("import ", "from "))
        ]
        assert not [line for line in imports if "atreides.dsor" in line], module.__name__


@pytest.mark.parametrize(
    "module", [package, events_module, lifecycle_module, record_module]
)
def test_docstrings_state_experimental(module: Any) -> None:
    assert "EXPERIMENTAL" in (module.__doc__ or "")
