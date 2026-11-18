from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance
from hypothesis import given, seed
from hypothesis import strategies as st

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
)
from atreides.books.ps1 import (
    InstructionKind,
    InstructionLog,
    LotElection,
    MoneyInstruction,
    SecuritiesConfirmation,
    build_money_statement,
    build_securities_count,
    project_tax_lots,
    reconcile,
)
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting

ACTOR = ActorRef(
    actor_id=ActorId("act_00000000000000000000000008"),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-ps1",
    entitlement_refs=(),
    authenticated=True,
)


def _entry(
    entry_id: str,
    day: date,
    quantity: Decimal,
    money: Decimal,
    *,
    location: AccountType = AccountType.PENDING_SETTLEMENT,
) -> JournalEntry:
    event_id = "evt_" + f"{abs(hash(entry_id)) % 10**26:026d}"
    return JournalEntry(
        entry_id=entry_id,
        source_event_id=event_id,
        source=PostingSource.ALLOCATION,
        effective_date=day,
        effective_date_basis="TRADE_DATE",
        authority="PS1_SYNTHETIC",
        lines=(
            LedgerLine(
                account_id="CUSTOMER-1",
                account_type=AccountType.CUSTOMER_CASH,
                record_side=RecordSide.OWNERSHIP,
                issue="SYN-EQ",
                quantity=quantity,
            ),
            LedgerLine(
                account_id=location.value,
                account_type=location,
                record_side=RecordSide.LOCATION,
                issue="SYN-EQ",
                quantity=-quantity,
            ),
            LedgerLine(
                account_id="CUSTOMER-1",
                account_type=AccountType.CUSTOMER_CASH,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=money,
            ),
            LedgerLine(
                account_id="CLEARING",
                account_type=AccountType.CLEARING_PAYABLE,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=-money,
            ),
        ),
        posting=BooksPosting(
            posted_record_id=entry_id,
            posting_authority=ACTOR,
            effective_time=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_event_id=EventId(event_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=True,
    )


def test_friday_trade_settles_on_next_business_day() -> None:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    assert calendar.add_business_days(date(2026, 11, 20), 1) == date(2026, 11, 23)


def test_cash_instruction_missing_from_books_creates_owned_aged_break() -> None:
    day = date(2026, 11, 18)
    statement = build_money_statement(
        "synthetic bank statement",
        (MoneyInstruction("DEP-1", day, Decimal("100.00"), InstructionKind.CUSTOMER_DEPOSIT),),
        day,
    )
    result = reconcile("cash-to-bank", EquitiesBooks(break_owner="TEST"), statement, day)
    assert result.status == "FAILED"
    assert result.breaks[0].owner == "TREASURY_CONTROL"
    assert result.breaks[0].age_calendar_days == 0


def test_instruction_log_is_append_only_and_refuses_duplicate_ids() -> None:
    log = InstructionLog()
    instruction = MoneyInstruction(
        "DEP-1", date(2026, 11, 18), Decimal("100.00"), InstructionKind.CUSTOMER_DEPOSIT
    )
    log.append(instruction)
    assert log.instructions == (instruction,)
    with pytest.raises(ValueError, match="DUPLICATE_OUTSIDE_INSTRUCTION"):
        log.append(instruction)


def test_nonzero_books_refuse_an_empty_outside_source() -> None:
    day = date(2026, 11, 18)
    books = EquitiesBooks(break_owner="TEST")
    books.post(_entry("BUY-EMPTY-SOURCE", day, Decimal(10), Decimal(-100)))
    empty = build_securities_count((), day)
    with pytest.raises(ValueError, match="EMPTY_OUTSIDE_SOURCE_WITH_BOOK_BALANCE"):
        reconcile("securities-count", books, empty, day)


def test_reserve_instruction_missing_from_statement_is_not_evidenced() -> None:
    day = date(2026, 11, 18)
    books = EquitiesBooks(break_owner="TEST")
    event_id = "evt_70000000000000000000000000"
    books.post(
        JournalEntry(
            entry_id="RESERVE-1",
            source_event_id=event_id,
            source=PostingSource.CASH_MOVEMENT,
            effective_date=day,
            effective_date_basis="VALUE_DATE",
            authority="PS1B_TEST",
            lines=(
                LedgerLine(
                    account_id="RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
                    account_type=AccountType.RESERVE_BANK_CUSTOMER,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=Decimal("500.00"),
                ),
                LedgerLine(
                    account_id="FIRM-OPERATING-CASH",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=Decimal("-500.00"),
                ),
            ),
            posting=BooksPosting(
                posted_record_id="RESERVE-1",
                posting_authority=ACTOR,
                effective_time=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                source_event_id=EventId(event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )
    statement = build_money_statement(
        "reserve bank statement",
        (
            MoneyInstruction(
                "RESERVE-OPENING",
                day,
                Decimal(),
                InstructionKind.OPENING,
                "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
            ),
        ),
        day,
    )
    result = reconcile("reserve-bank-to-books", books, statement, day)
    assert result.status == "FAILED"
    assert result.breaks[0].owner == "CUSTOMER_PROTECTION_CONTROL"


def test_one_share_securities_count_difference_is_owned() -> None:
    day = date(2026, 11, 18)
    books = EquitiesBooks(break_owner="TEST")
    books.post(_entry("BUY-1", day, Decimal(10), Decimal(-100)))
    count = build_securities_count(
        (SecuritiesConfirmation("DTC-1", day, "SYN-EQ", "PENDING_SETTLEMENT", Decimal(9)),),
        day,
    )
    result = reconcile("securities-count", books, count, day)
    assert result.status == "FAILED"
    assert result.breaks[0].difference == Decimal(1)


def test_fifo_specific_identification_and_late_election() -> None:
    first = _entry("BUY-1", date(2026, 11, 16), Decimal(10), Decimal(-100))
    second = _entry("BUY-2", date(2026, 11, 17), Decimal(10), Decimal(-200))
    sale = _entry("SALE-1", date(2026, 11, 18), Decimal(-12), Decimal(300))
    settlement_time = datetime(2026, 11, 19, 14, tzinfo=UTC)
    settlement_base = _entry(
        "SETTLE-SALE-1", date(2026, 11, 19), Decimal(12), Decimal(-300)
    )
    settlement = settlement_base.model_copy(
        update={
            "effective_date_basis": "SETTLEMENT_DATE",
            "settles_entry_id": "SALE-1",
            "posting": settlement_base.posting.model_copy(
                update={"effective_time": settlement_time}
            ),
        }
    )
    lots, relief = project_tax_lots((first, second, sale), account_id="CUSTOMER-1", issue="SYN-EQ")
    assert relief[0].basis == Decimal("140.00")
    assert relief[0].realized_gain == Decimal("160.00")
    assert sum((lot.remaining_basis for lot in lots), Decimal()) == Decimal("160.00")

    lots, relief = project_tax_lots(
        (first, second, sale, settlement),
        account_id="CUSTOMER-1",
        issue="SYN-EQ",
        elections=(
            LotElection(
                "SALE-1", "LOT-BUY-2", datetime(2026, 11, 19, 13, 59, 59, tzinfo=UTC)
            ),
        ),
    )
    assert relief[0].basis == Decimal("220.00")
    assert relief[0].realized_gain == Decimal("80.00")
    assert sum((lot.remaining_basis for lot in lots), Decimal()) == Decimal("80.00")

    with pytest.raises(ValueError, match="LATE_SPECIFIC_IDENTIFICATION_ELECTION"):
        project_tax_lots(
            (first, second, sale, settlement),
            account_id="CUSTOMER-1",
            issue="SYN-EQ",
            elections=(
                LotElection(
                    "SALE-1", "LOT-BUY-2", settlement_time + timedelta(seconds=1)
                ),
            ),
        )


def test_trade_date_entry_cannot_claim_to_settle_another_entry() -> None:
    entry = _entry("NOT-A-SETTLEMENT", date(2026, 11, 18), Decimal(1), Decimal(-10))
    with pytest.raises(ValueError, match="only a settlement-date entry"):
        JournalEntry(**(entry.model_dump() | {"settles_entry_id": "SALE-1"}))


@seed(20261118)
@given(
    q1=st.integers(min_value=1, max_value=1000),
    q2=st.integers(min_value=1, max_value=1000),
    p1=st.integers(min_value=1, max_value=100000),
    p2=st.integers(min_value=1, max_value=100000),
)
def test_lot_projection_conserves_quantity_and_basis(q1: int, q2: int, p1: int, p2: int) -> None:
    first = _entry("BUY-1", date(2026, 11, 16), Decimal(q1), -Decimal(q1 * p1) / 100)
    second = _entry("BUY-2", date(2026, 11, 17), Decimal(q2), -Decimal(q2 * p2) / 100)
    lots, relief = project_tax_lots(
        (first, second), account_id="CUSTOMER-1", issue="SYN-EQ"
    )
    assert not relief
    assert sum((lot.remaining_quantity for lot in lots), Decimal()) == Decimal(q1 + q2)
    assert sum((lot.remaining_basis for lot in lots), Decimal()) == Decimal(q1 * p1 + q2 * p2) / 100
