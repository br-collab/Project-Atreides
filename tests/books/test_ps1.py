from datetime import UTC, date, datetime
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
    LotElection,
    MoneyInstruction,
    SecuritiesConfirmation,
    book_location_balances,
    build_money_statement,
    build_securities_count,
    project_tax_lots,
    reconcile_values,
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
    result = reconcile_values(
        item_id="cash-to-bank",
        books_values={},
        outside_values=statement.balances,
        owner="TREASURY_CONTROL",
        as_of=day,
        sources_read=("Atreides equities books", statement.name),
    )
    assert result.status == "FAILED"
    assert result.breaks[0].owner == "TREASURY_CONTROL"
    assert result.breaks[0].age_calendar_days == 0


def test_reserve_instruction_missing_from_statement_is_not_evidenced() -> None:
    day = date(2026, 11, 18)
    result = reconcile_values(
        item_id="reserve-bank-to-books",
        books_values={"CUSTOMER_RESERVE": Decimal("500.00")},
        outside_values={},
        owner="CUSTOMER_PROTECTION_CONTROL",
        as_of=day,
        sources_read=("reserve bank statement", "reserve_bank_balances"),
    )
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
    outside = {
        f"{issue}@{location}": quantity
        for (issue, location), quantity in count.positions.items()
    }
    result = reconcile_values(
        item_id="securities-count",
        books_values=book_location_balances(books, day),
        outside_values=outside,
        owner="SECURITIES_COUNT_CONTROL",
        as_of=day,
        sources_read=("equities books", "independent securities confirmations"),
    )
    assert result.status == "FAILED"
    assert result.breaks[0].difference == Decimal(1)


def test_fifo_specific_identification_and_late_election() -> None:
    first = _entry("BUY-1", date(2026, 11, 16), Decimal(10), Decimal(-100))
    second = _entry("BUY-2", date(2026, 11, 17), Decimal(10), Decimal(-200))
    sale = _entry("SALE-1", date(2026, 11, 18), Decimal(-12), Decimal(300))
    lots, relief = project_tax_lots((first, second, sale), account_id="CUSTOMER-1", issue="SYN-EQ")
    assert relief[0].basis == Decimal("140.00")
    assert relief[0].realized_gain == Decimal("160.00")
    assert sum((lot.remaining_basis for lot in lots), Decimal()) == Decimal("160.00")

    lots, relief = project_tax_lots(
        (first, second, sale),
        account_id="CUSTOMER-1",
        issue="SYN-EQ",
        elections=(LotElection("SALE-1", "LOT-BUY-2", date(2026, 11, 18)),),
        settlement_dates={"SALE-1": date(2026, 11, 19)},
    )
    assert relief[0].basis == Decimal("220.00")
    assert relief[0].realized_gain == Decimal("80.00")
    assert sum((lot.remaining_basis for lot in lots), Decimal()) == Decimal("80.00")

    with pytest.raises(ValueError, match="LATE_SPECIFIC_IDENTIFICATION_ELECTION"):
        project_tax_lots(
            (first, second, sale),
            account_id="CUSTOMER-1",
            issue="SYN-EQ",
            elections=(LotElection("SALE-1", "LOT-BUY-2", date(2026, 11, 20)),),
            settlement_dates={"SALE-1": date(2026, 11, 19)},
        )


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
