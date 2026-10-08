"""WP-3 acceptance: the election workflow (ORDER SC-1).

Acceptance criteria, mapped:

- Late instruction refused: ``test_an_instruction_after_the_firm_deadline_is_refused_not_queued``
  and ``test_a_cover_after_the_protect_deadline_is_refused``.
- Duplicate instruction idempotent: ``test_a_duplicate_instruction_changes_nothing``,
  ``test_a_retry_after_the_deadline_is_still_a_duplicate`` and the property
  ``test_property_resubmitting_the_journal_changes_nothing``.
- Every election emits a DSOR-admissible record that round trips through the store:
  ``test_every_election_record_round_trips_through_the_store`` and
  ``test_the_elections_rebuild_from_stored_records``.

Also covered: the firm deadline parameter, the default from event data, and the uncovered
protect balance in the depository's vocabulary.

Every event, account and balance below is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from cannae_kernel.provenance import Provenance
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from atreides.corporate_actions import (
    AccountDefault,
    CorporateActionEvent,
    CorporateActionEventRecord,
    DefaultRefusal,
    ElectionBook,
    ElectionEntry,
    ElectionInstruction,
    ElectionPolicy,
    ElectionRefusal,
    EventType,
    HolderPosition,
    JournalMismatchError,
    Lifecycle,
    Milestone,
    Participation,
    ProtectCover,
    SourceIdentity,
    assign_defaults,
    firm_deadline,
    rebuild_elections,
    rebuild_elections_from_records,
    rebuild_from_records,
    record_defaults,
    record_request,
    record_submission,
)
from atreides.corporate_actions import election as election_module
from atreides.dsor import DSORStore
from atreides.rails.cns import RecordDatePosition
from tests.corporate_actions.conftest import ask, event

D = Decimal
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CLIENT = SourceIdentity(source_id="SYNTHETIC client system", reference="SYNTHETIC-MSG")
POLICY = ElectionPolicy(firm_lead_days=2)
OPTIONS = [
    {"option_id": "001", "description": "SYNTHETIC tender for cash"},
    {"option_id": "002", "description": "SYNTHETIC take no action"},
]
# Depository election deadline 20 October, protect deadline 22 October, so the firm's
# deadline under POLICY is 18 October.
FIRM_DEADLINE = date(2026, 10, 18)


def elective(
    participation: Participation = Participation.VOLUNTARY, **changes: Any
) -> CorporateActionEvent:
    base = event(participation, EventType.TENDER_OFFER).model_dump()
    base |= {"options": OPTIONS, "default_option_id": "002"} | changes
    return CorporateActionEvent.model_validate(base)


def book(built: CorporateActionEvent | None = None) -> ElectionBook:
    return ElectionBook(event=built or elective(), policy=POLICY)


def instruct(
    instruction_id: str = "I-1",
    account: str = "ACCT-A",
    quantity: str = "100",
    day: int = 15,
    *,
    option: str = "001",
    protect: bool = False,
) -> ElectionInstruction:
    return ElectionInstruction(
        instruction_id=instruction_id, account_id=account, option_id=option,
        quantity=D(quantity), received_date=date(2026, 10, day), protect=protect,
        provenance=Provenance.FACT_EXTERNAL, source=CLIENT,
    )


def cover(
    cover_id: str = "C-1", instruction_id: str = "I-1", account: str = "ACCT-A",
    quantity: str = "60", day: int = 21,
) -> ProtectCover:
    return ProtectCover(
        cover_id=cover_id, instruction_id=instruction_id, account_id=account,
        quantity=D(quantity), received_date=date(2026, 10, day),
        provenance=Provenance.FACT_EXTERNAL, source=CLIENT,
    )


def submit(start: ElectionBook, *submissions: ElectionInstruction | ProtectCover) -> ElectionBook:
    for submission in submissions:
        start, _ = start.submit(submission)
    return start


def holding(account: str, eligible: str) -> HolderPosition:
    return HolderPosition(
        account_id=account,
        position=RecordDatePosition("SYNTHETIC-XYZ", D(eligible), D(eligible)),
    )


def op(n: int) -> UUID:
    return UUID(int=n)


# --- the event's options and default --------------------------------------------------------


@pytest.mark.parametrize(
    ("participation", "changes", "message"),
    [
        (Participation.MANDATORY, {"options": OPTIONS}, "offers no election options"),
        (Participation.MANDATORY, {"default_option_id": "001"}, "offers no election options"),
        (Participation.VOLUNTARY, {"options": [*OPTIONS, OPTIONS[0]]}, "more than once"),
        (Participation.VOLUNTARY, {"default_option_id": "009"}, "is not an option"),
    ],
)
def test_options_and_default_are_consistent(
    participation: Participation, changes: dict[str, Any], message: str
) -> None:
    base = event(participation, EventType.TENDER_OFFER).model_dump() | changes
    if participation is Participation.VOLUNTARY:
        base.setdefault("options", OPTIONS)
    with pytest.raises(ValidationError, match=message):
        CorporateActionEvent.model_validate(base)


# --- the firm's deadline ---------------------------------------------------------------------


def test_the_firm_deadline_is_earlier_by_the_policy_parameter() -> None:
    assert firm_deadline(elective(), POLICY) == FIRM_DEADLINE
    assert firm_deadline(elective(), ElectionPolicy(firm_lead_days=5)) == date(2026, 10, 15)
    assert firm_deadline(event(), POLICY) is None


def test_the_firm_deadline_is_strictly_earlier() -> None:
    with pytest.raises(ValidationError):
        ElectionPolicy(firm_lead_days=0)


# --- late instructions -----------------------------------------------------------------------


@pytest.mark.requirement("SC-P-04")
def test_an_instruction_on_the_firm_deadline_is_accepted() -> None:
    _, entry = book().submit(instruct(day=FIRM_DEADLINE.day))
    assert entry.outcome == "accepted"


def test_an_instruction_after_the_firm_deadline_is_refused_not_queued() -> None:
    """Before the depository's deadline but after the firm's: refused, and nothing waits."""
    after, entry = book().submit(instruct(day=FIRM_DEADLINE.day + 1))
    assert entry.outcome == "refused" and entry.refusal is ElectionRefusal.LATE
    assert after.accepted_instructions() == ()
    assert after.elected_quantity("ACCT-A") == 0
    later, _ = after.submit(instruct("I-2", day=10))
    assert [i.instruction_id for i in later.accepted_instructions()] == ["I-2"]


def test_a_cover_after_the_protect_deadline_is_refused() -> None:
    protected = submit(book(), instruct(protect=True))
    _, entry = protected.submit(cover(day=23))
    assert entry.refusal is ElectionRefusal.LATE_COVER
    assert protected.uncovered_protect_balance("ACCT-A") == D(100)


# --- duplicates ------------------------------------------------------------------------------


def test_a_duplicate_instruction_changes_nothing() -> None:
    once = submit(book(), instruct())
    twice, entry = once.submit(instruct())
    assert entry.outcome == "duplicate" and entry.duplicate_of == 0
    assert twice.accepted_instructions() == once.accepted_instructions()
    assert twice.elected_quantity("ACCT-A") == once.elected_quantity("ACCT-A") == D(100)
    assert len(twice.journal) == 2


def test_a_retry_after_the_deadline_is_still_a_duplicate() -> None:
    """A retry of an accepted instruction is not a late instruction."""
    once = submit(book(), instruct(day=15))
    _, entry = once.submit(instruct(day=15))
    assert entry.outcome == "duplicate"


def test_a_retry_of_a_refused_instruction_stays_refused() -> None:
    once = submit(book(), instruct(option="009"))
    twice, entry = once.submit(instruct(option="009"))
    assert entry.outcome == "duplicate" and entry.duplicate_of == 0
    assert twice.accepted_instructions() == ()


def test_the_same_identifier_with_different_content_is_refused() -> None:
    once = submit(book(), instruct(quantity="100"))
    after, entry = once.submit(instruct(quantity="150"))
    assert entry.refusal is ElectionRefusal.CONFLICTING_DUPLICATE
    assert after.elected_quantity("ACCT-A") == D(100)


# --- every other refusal ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("built", "submission", "reason"),
    [
        (event(), instruct(), ElectionRefusal.NOT_ELECTIVE),
        (elective(), instruct(day=1).model_copy(update={"received_date": date(2026, 9, 30)}),
         ElectionRefusal.BEFORE_ANNOUNCEMENT),
        (elective(options=[], default_option_id=None), instruct(),
         ElectionRefusal.OPTIONS_NOT_STATED),
        (elective(), instruct(option="009"), ElectionRefusal.UNKNOWN_OPTION),
        (elective(Participation.MANDATORY_WITH_CHOICE), instruct(protect=True),
         ElectionRefusal.PROTECT_NOT_OFFERED),
        (elective(), cover(), ElectionRefusal.UNKNOWN_PROTECT),
    ],
)
def test_a_submission_is_refused_by_name(
    built: CorporateActionEvent,
    submission: ElectionInstruction | ProtectCover,
    reason: ElectionRefusal,
) -> None:
    _, entry = book(built).submit(submission)
    assert entry.outcome == "refused" and entry.refusal is reason


def test_a_voluntary_event_without_a_protect_deadline_offers_no_protect() -> None:
    dumped = elective().model_dump()
    dumped["dates"]["protect_deadline"] = None
    _, entry = book(CorporateActionEvent.model_validate(dumped)).submit(instruct(protect=True))
    assert entry.refusal is ElectionRefusal.PROTECT_NOT_OFFERED


# --- protect, in the depository's vocabulary --------------------------------------------------


def test_the_uncovered_protect_balance_falls_as_covers_arrive() -> None:
    protected = submit(book(), instruct(protect=True), instruct("I-2", quantity="40"))
    assert protected.uncovered_protect_balance("ACCT-A") == D(100)
    assert protected.elected_quantity("ACCT-A") == D(140)
    partly = submit(protected, cover("C-1", quantity="60", day=19))
    assert partly.uncovered_protect_balance("ACCT-A") == D(40)
    whole = submit(partly, cover("C-2", quantity="40", day=22))
    assert whole.uncovered_protect_balance("ACCT-A") == 0


@pytest.mark.parametrize(
    ("submissions", "the_cover"),
    [
        ((instruct(protect=True),), cover(quantity="101")),
        ((instruct(protect=True), cover("C-1", quantity="60")), cover("C-2", quantity="41")),
    ],
)
def test_a_cover_beyond_the_uncovered_quantity_is_refused(
    submissions: tuple[ElectionInstruction | ProtectCover, ...], the_cover: ProtectCover
) -> None:
    _, entry = submit(book(), *submissions).submit(the_cover)
    assert entry.refusal is ElectionRefusal.OVER_COVER


@pytest.mark.parametrize(
    "the_cover",
    [cover(instruction_id="I-9"), cover(account="ACCT-B"), cover(instruction_id="I-2")],
    ids=["unknown-instruction", "other-account", "not-a-protect-instruction"],
)
def test_a_cover_names_an_accepted_protect_instruction_of_its_account(
    the_cover: ProtectCover,
) -> None:
    started = submit(book(), instruct(protect=True), instruct("I-2", quantity="10"))
    _, entry = started.submit(the_cover)
    assert entry.refusal is ElectionRefusal.UNKNOWN_PROTECT


# --- the default -----------------------------------------------------------------------------


def test_the_default_applies_to_every_uninstructed_balance() -> None:
    elected = submit(
        book(),
        instruct("I-A", "ACCT-A", "30"),
        instruct("I-C", "ACCT-C", "150"),
        instruct("I-D", "ACCT-D", "10"),
        instruct("I-LATE", "ACCT-B", "50", day=19),
    )
    holdings = [holding("ACCT-A", "100"), holding("ACCT-B", "80"), holding("ACCT-C", "100")]
    assignment = assign_defaults(elected, holdings, date(2026, 10, 19))
    assert assignment.default_option_id == "002" and assignment.refusal is None
    by_account = {a.account_id: a for a in assignment.accounts}
    assert by_account["ACCT-A"].default_quantity == D(70)
    assert by_account["ACCT-B"].default_quantity == D(80)
    assert by_account["ACCT-C"].refusal is DefaultRefusal.OVER_INSTRUCTED
    assert by_account["ACCT-D"].refusal is DefaultRefusal.INSTRUCTED_WITHOUT_POSITION
    assert [a.account_id for a in assignment.accounts] == sorted(by_account)
    reversed_holdings = assign_defaults(elected, holdings[::-1], date(2026, 10, 19))
    assert reversed_holdings == assignment


@pytest.mark.parametrize(
    ("built", "as_of", "reason"),
    [
        (elective(), FIRM_DEADLINE, DefaultRefusal.DEADLINE_NOT_PASSED),
        (elective(default_option_id=None), date(2026, 10, 19), DefaultRefusal.DEFAULT_NOT_STATED),
        (event(), date(2026, 10, 19), DefaultRefusal.NOT_ELECTIVE),
    ],
)
def test_no_default_is_assigned_without_its_conditions(
    built: CorporateActionEvent, as_of: date, reason: DefaultRefusal
) -> None:
    assignment = assign_defaults(book(built), [holding("ACCT-A", "100")], as_of)
    assert assignment.refusal is reason
    assert assignment.default_option_id is None and assignment.accounts == ()


def test_an_account_appears_once_in_the_holdings() -> None:
    with pytest.raises(ValueError, match="more than once"):
        assign_defaults(book(), [holding("ACCT-A", "1"), holding("ACCT-A", "2")],
                        date(2026, 10, 19))


def test_an_account_default_is_a_quantity_or_a_reason() -> None:
    with pytest.raises(ValidationError, match="never both"):
        AccountDefault(account_id="A", eligible_balance=D(1), elected_quantity=D(0),
                       default_quantity=None)


@pytest.mark.parametrize(
    "changes",
    [{"outcome": "refused"}, {"outcome": "duplicate"},
     {"refusal": ElectionRefusal.LATE}, {"duplicate_of": 0}],
)
def test_an_entry_is_internally_consistent(changes: dict[str, Any]) -> None:
    entry = book().submit(instruct())[1]
    with pytest.raises(ValidationError, match="names"):
        ElectionEntry.model_validate(entry.model_dump() | changes)


# --- the journal rebuilds the book ------------------------------------------------------------

_submissions = st.lists(
    st.one_of(
        st.builds(
            instruct,
            instruction_id=st.sampled_from(["I-1", "I-2", "I-3"]),
            account=st.sampled_from(["ACCT-A", "ACCT-B"]),
            quantity=st.sampled_from(["10", "40", "100"]),
            day=st.integers(10, 24),
            option=st.sampled_from(["001", "002", "009"]),
            protect=st.booleans(),
        ),
        st.builds(
            cover,
            cover_id=st.sampled_from(["C-1", "C-2"]),
            instruction_id=st.sampled_from(["I-1", "I-2"]),
            account=st.sampled_from(["ACCT-A", "ACCT-B"]),
            quantity=st.sampled_from(["10", "60", "100"]),
            day=st.integers(15, 24),
        ),
    ),
    max_size=10,
)


@given(submissions=_submissions)
def test_property_the_journal_rebuilds_and_keeps_its_rules(
    submissions: list[ElectionInstruction | ProtectCover],
) -> None:
    live = submit(book(), *submissions)
    assert rebuild_elections(live.event, live.policy, live.journal) == live
    deadline = live.firm_deadline
    assert deadline is not None
    assert all(i.received_date <= deadline for i in live.accepted_instructions())
    assert all(c.received_date <= date(2026, 10, 22) for c in live.accepted_covers())
    for account in ("ACCT-A", "ACCT-B"):
        assert live.uncovered_protect_balance(account) >= 0
    ids = [i.instruction_id for i in live.accepted_instructions()]
    assert len(ids) == len(set(ids))


@given(submissions=_submissions)
def test_property_resubmitting_the_journal_changes_nothing(
    submissions: list[ElectionInstruction | ProtectCover],
) -> None:
    live = submit(book(), *submissions)
    again = submit(live, *(e.submission for e in live.journal))
    assert again.accepted_instructions() == live.accepted_instructions()
    assert again.accepted_covers() == live.accepted_covers()
    assert all(e.outcome in ("duplicate", "refused") for e in again.journal[len(live.journal):])
    assert all(
        e.refusal is ElectionRefusal.CONFLICTING_DUPLICATE
        for e in again.journal[len(live.journal):] if e.outcome == "refused"
    )


def test_an_altered_or_foreign_journal_does_not_rebuild() -> None:
    live = submit(book(), instruct(), instruct(day=19, instruction_id="I-2"))
    forged = live.journal[1].model_copy(update={"outcome": "accepted", "refusal": None})
    with pytest.raises(JournalMismatchError, match="records accepted"):
        rebuild_elections(live.event, live.policy, (live.journal[0], forged))
    with pytest.raises(JournalMismatchError, match="is not entry"):
        rebuild_elections(live.event, live.policy, live.journal[1:])


# --- records ---------------------------------------------------------------------------------


def recorded() -> tuple[ElectionBook, list[CorporateActionEventRecord]]:
    current, records = book(), []
    submissions: list[ElectionInstruction | ProtectCover] = [
        instruct(protect=True), instruct(protect=True), instruct("I-2", day=19), cover(day=21),
    ]
    for n, submission in enumerate(submissions):
        current, record = record_submission(current, submission, operation_id=op(200 + n),
                                            recorded_at=NOW)
        records.append(record)
    assignment = assign_defaults(current, [holding("ACCT-A", "150")], date(2026, 10, 19))
    records.append(record_defaults(current, assignment, operation_id=op(299), recorded_at=NOW))
    return current, records


def test_every_election_emits_a_record() -> None:
    _, records = recorded()
    kinds = [r.body.body_type for r in records]
    assert kinds == ["election"] * 4 + ["default_assignment"]
    assert [r.body.entry.outcome for r in records[:4]] == [  # type: ignore[union-attr]
        "accepted", "duplicate", "refused", "accepted",
    ]
    assert all(r.kind == "corporate_action_event" for r in records)
    assert all(r.outcome_provenance is Provenance.POLICY_RESULT for r in records)


def test_every_election_record_round_trips_through_the_store() -> None:
    _, records = recorded()
    with DSORStore(":memory:") as store:
        for record in records:
            stored = store.append(record, dtg=NOW)
            assert store.payload_bytes(stored.record_id) == record.model_dump_json().encode()
            replayed = store.replay(stored.record_id)
            assert isinstance(replayed, CorporateActionEventRecord)
            assert replayed == record


def test_the_elections_rebuild_from_stored_records() -> None:
    live, records = recorded()
    lifecycle, transition = record_request(
        Lifecycle(event=live.event), ask(Milestone.ELECTIONS_CLOSED, 20),
        operation_id=op(300), recorded_at=NOW,
    )
    with DSORStore(":memory:") as store:
        for record in [*records, transition]:
            store.append(record, dtg=NOW)
        stored = [r.output for r in store.records()]
    mixed = [r for r in stored if isinstance(r, CorporateActionEventRecord)]
    assert rebuild_elections_from_records(reversed(mixed)) == live
    assert rebuild_from_records(mixed) == lifecycle


def test_election_records_with_another_policy_do_not_rebuild_together() -> None:
    _, records = recorded()
    other = records[1].model_copy(update={"body": records[1].body.model_copy(
        update={"policy": ElectionPolicy(firm_lead_days=5)})})
    with pytest.raises(JournalMismatchError, match="different policy"):
        rebuild_elections_from_records([records[0], other])
    with pytest.raises(JournalMismatchError, match="no records"):
        rebuild_elections_from_records(records[4:])


def test_a_default_record_is_for_its_own_event() -> None:
    current, _ = recorded()
    foreign = assign_defaults(book(elective(Participation.MANDATORY_WITH_CHOICE)),
                              [], date(2026, 10, 19))
    with pytest.raises(ValueError, match="another event"):
        record_defaults(current, foreign, operation_id=op(1), recorded_at=NOW)


def test_docstring_states_experimental_and_prepare_only() -> None:
    text = " ".join((election_module.__doc__ or "").split())
    assert "EXPERIMENTAL" in text and "nothing here transmits" in text
