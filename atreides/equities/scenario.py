"""Deterministic EQ-1B Atreides scenario and publication documents."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
    ReserveActivity,
    ReserveSourceFact,
)
from atreides.books.projections import project_customer_protection, project_margin_accounts
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import compute_reserve
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.deadlines.rule_204 import Rule204Fail, Rule204Origin, assess_rule_204
from atreides.dsor.books import BooksPosting
from atreides.equities.documents import (
    LocateDocument,
    LocateRecord,
    attest_capacity,
    attest_locates,
    project_capacity,
)
from atreides.margin.engine import MarginAccount, MarginResult, compute_margin
from atreides.rails.cns import (
    CloseOutRegime,
    MarketProfile,
    ProcessingDateRule,
    net_positions,
    settle_net_position,
)

ACTOR = ActorRef(
    actor_id=ActorId("act_" + "7" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="eq1b-synthetic-books",
    entitlement_refs=(),
    authenticated=True,
)
PRICES = {"ACME": Decimal(100), "PENNY": Decimal(4)}
MOVED_PRICES = {"ACME": Decimal(30), "PENNY": Decimal(4)}


def _json(value: BaseModel | dict[str, object]) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _line(
    account_id: str,
    account_type: AccountType,
    side: RecordSide,
    *,
    issue: str | None = None,
    quantity: Decimal = Decimal(0),
    money: Decimal = Decimal(0),
) -> LedgerLine:
    return LedgerLine(
        account_id=account_id,
        account_type=account_type,
        record_side=side,
        issue=issue,
        quantity=quantity,
        currency="USD" if side is RecordSide.MONEY else None,
        money=money,
    )


def _entry(
    number: int,
    source: PostingSource,
    lines: tuple[LedgerLine, ...],
    at: datetime,
    basis: str,
    *,
    synthetic: bool = False,
    reserve_source_facts: tuple[ReserveSourceFact, ...] = (),
) -> JournalEntry:
    alphabet = "12345678ABCDEFGHJKMNPQRSTVWXYZ"
    event_id = EventId("evt_0" + alphabet[number] * 25)
    entry_id = f"EQ1B-{number}"
    return JournalEntry(
        entry_id=entry_id,
        source_event_id=str(event_id),
        source=source,
        effective_date=at.date(),
        effective_date_basis=basis,
        authority="EQ1B_SYNTHETIC_OPERATOR",
        lines=lines,
        posting=BooksPosting(
            posted_record_id=entry_id,
            posting_authority=ACTOR,
            effective_time=at,
            source_event_id=event_id,
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        reserve_source_facts=reserve_source_facts,
        synthetic=synthetic,
    )


def _post_scenario(books: EquitiesBooks, at: datetime) -> None:
    entries = (
        (
            PostingSource.CASH_MOVEMENT,
            "VALUE_DATE",
            (
                _line(
                    "CUSTOMER-1", AccountType.CUSTOMER_MARGIN, RecordSide.MONEY, money=Decimal(600)
                ),
                _line("FIRM", AccountType.CASH, RecordSide.MONEY, money=Decimal(-600)),
            ),
        ),
        (
            PostingSource.TRADE_CAPTURE,
            "TRADE_DATE",
            (
                _line(
                    "CUSTOMER-1",
                    AccountType.CUSTOMER_MARGIN,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(10),
                ),
                _line(
                    "DTC", AccountType.DTC, RecordSide.LOCATION, issue="ACME", quantity=Decimal(-10)
                ),
                _line(
                    "CUSTOMER-1",
                    AccountType.CUSTOMER_MARGIN,
                    RecordSide.MONEY,
                    money=Decimal(-1000),
                ),
                _line("NSCC", AccountType.CASH, RecordSide.MONEY, money=Decimal(1000)),
            ),
        ),
        (
            PostingSource.ALLOCATION,
            "TRADE_DATE",
            (
                _line(
                    "CUSTOMER-1",
                    AccountType.CUSTOMER_MARGIN,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(-2),
                ),
                _line(
                    "CUSTOMER-2",
                    AccountType.CUSTOMER_CASH,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(2),
                ),
            ),
        ),
        (
            PostingSource.CNS_SETTLEMENT,
            "SETTLEMENT_DATE",
            (
                _line(
                    "DTC", AccountType.DTC, RecordSide.LOCATION, issue="ACME", quantity=Decimal(2)
                ),
                _line(
                    "BANK",
                    AccountType.BANK_CONTROL,
                    RecordSide.LOCATION,
                    issue="ACME",
                    quantity=Decimal(-2),
                ),
            ),
        ),
        (
            PostingSource.CNS_FAIL,
            "SETTLEMENT_DATE",
            (
                _line(
                    "DTC", AccountType.DTC, RecordSide.LOCATION, issue="ACME", quantity=Decimal(5)
                ),
                _line(
                    "FAIL-D",
                    AccountType.FAIL_TO_DELIVER,
                    RecordSide.LOCATION,
                    issue="ACME",
                    quantity=Decimal(-5),
                ),
                _line(
                    "CUSTOMER-1",
                    AccountType.CUSTOMER_MARGIN,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(-1),
                ),
                _line(
                    "FAIL-R",
                    AccountType.FAIL_TO_RECEIVE,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(1),
                ),
            ),
        ),
        (
            PostingSource.TRADE_CAPTURE,
            "TRADE_DATE",
            (
                _line(
                    "CUSTOMER-3",
                    AccountType.CUSTOMER_MARGIN,
                    RecordSide.OWNERSHIP,
                    issue="PENNY",
                    quantity=Decimal(-100),
                ),
                _line(
                    "BORROW",
                    AccountType.STOCK_BORROWED,
                    RecordSide.OWNERSHIP,
                    issue="PENNY",
                    quantity=Decimal(100),
                ),
                _line(
                    "CUSTOMER-3", AccountType.CUSTOMER_MARGIN, RecordSide.MONEY, money=Decimal(400)
                ),
                _line("NSCC", AccountType.CASH, RecordSide.MONEY, money=Decimal(-400)),
            ),
        ),
        (
            PostingSource.CORPORATE_ACTION,
            "PAY_DATE",
            (
                _line(
                    "CUSTOMER-2",
                    AccountType.CUSTOMER_CASH,
                    RecordSide.OWNERSHIP,
                    issue="ACME",
                    quantity=Decimal(1),
                ),
                _line(
                    "DTC", AccountType.DTC, RecordSide.LOCATION, issue="ACME", quantity=Decimal(-1)
                ),
            ),
        ),
        (
            PostingSource.CASH_MOVEMENT,
            "VALUE_DATE",
            (
                _line(
                    "CUSTOMER-3", AccountType.CUSTOMER_MARGIN, RecordSide.MONEY, money=Decimal(1000)
                ),
                _line("FIRM", AccountType.CASH, RecordSide.MONEY, money=Decimal(-1000)),
            ),
        ),
        (
            PostingSource.MARGIN_INTEREST,
            "VALUE_DATE",
            (
                _line(
                    "CUSTOMER-1", AccountType.CUSTOMER_MARGIN, RecordSide.MONEY, money=Decimal(-10)
                ),
                _line("FIRM", AccountType.CASH, RecordSide.MONEY, money=Decimal(10)),
            ),
        ),
    )
    reserve_sources = {
        5: (
            ReserveSourceFact(
                account_type=AccountType.FAIL_TO_DELIVER,
                issue="ACME",
                activity=ReserveActivity.CUSTOMER,
                settlement_date=at.date(),
                contract_price=Decimal(100),
            ),
            ReserveSourceFact(
                account_type=AccountType.FAIL_TO_RECEIVE,
                issue="ACME",
                activity=ReserveActivity.CUSTOMER,
                settlement_date=at.date(),
                contract_price=Decimal(100),
            ),
        ),
        6: (
            ReserveSourceFact(
                account_type=AccountType.STOCK_BORROWED,
                issue="PENNY",
                activity=ReserveActivity.CUSTOMER,
                settlement_date=at.date(),
                contract_price=Decimal(4),
            ),
        ),
    }
    for number, (source, basis, lines) in enumerate(entries, 1):
        books.post(
            _entry(
                number,
                source,
                lines,
                at,
                basis,
                synthetic=source is PostingSource.MARGIN_INTEREST,
                reserve_source_facts=reserve_sources.get(number, ()),
            )
        )


def _margin(
    accounts: tuple[MarginAccount, ...], at: datetime, calendar: MarketCalendar
) -> tuple[MarginResult, ...]:
    return tuple(
        compute_margin(
            account,
            trade_date=at.date(),
            calendar=calendar,
            house_maintenance_rate=Decimal("0.30"),
            maintenance_call_due_business_days=2,
        )
        for account in accounts
    )


def build_equities_publications(taken_at: datetime) -> dict[str, bytes]:
    """Run settlement, books, margin and protection once and return stable documents."""
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    books = EquitiesBooks(break_owner="EQ1B_STOCK_RECORD_CONTROL")
    _post_scenario(books, taken_at)
    assert not books.verify_stock_record()
    accounts = project_margin_accounts(
        books,
        prices=PRICES,
        new_trades=frozenset({("CUSTOMER-1", "ACME"), ("CUSTOMER-3", "PENNY")}),
    )
    moved_accounts = project_margin_accounts(books, prices=MOVED_PRICES)
    initial_results = _margin(accounts, taken_at, calendar)
    moved_results = _margin(moved_accounts, taken_at, calendar)
    journal_digest = books.digest()
    capacity = project_capacity(
        journal_digest=journal_digest,
        as_of=taken_at,
        maximum_age_seconds=300,
        margin_results=initial_results,
        accounts=accounts,
    )
    protection_inputs = project_customer_protection(
        books,
        as_of=taken_at.date(),
        prices=MOVED_PRICES,
        net_worth=Decimal(10_000_000),
        calendar=calendar,
        margin_results=moved_results,
    )
    rules = load_rule_table()
    protection = {
        "books_digest": protection_inputs.audit.books_digest,
        "firm_profile": protection_inputs.firm_profile.model_dump(mode="json"),
        "projection": protection_inputs.audit.model_dump(mode="json"),
        "reserve": compute_reserve(protection_inputs.reserve, rules).model_dump(mode="json"),
        "pab_reserve": compute_reserve(protection_inputs.pab_reserve, rules).model_dump(
            mode="json"
        ),
        "net_capital": compute_net_capital(protection_inputs.net_capital, rules).model_dump(
            mode="json"
        ),
        "possession_or_control": check_possession_or_control(
            protection_inputs.control, rules
        ).model_dump(mode="json"),
    }
    profile = MarketProfile(
        market_id="NSCC_CNS_SYNTHETIC",
        settlement_cycle_days=1,
        close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
        close_out_deadline_days=1,
        processing_date_rule=ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE,
        provenance="synthetic EQ-1B NSCC profile",
    )
    net = net_positions(
        (("ACME", Decimal(-10)),), market_id=profile.market_id, settlement_date_offset_days=1
    )
    cns = settle_net_position(net[0], profile, allocated_quantity=Decimal(-5), aged_days=1)
    rule_204 = assess_rule_204(
        Rule204Fail(
            security="ACME",
            trade_date=taken_at.date(),
            settlement_date=calendar.add_settlement_days(taken_at.date(), 1),
            fail_quantity=Decimal(5),
            origin_class=Rule204Origin.SHORT_OR_GENERAL,
            originating_order_id="ord_EQ1_SHORT",
            locate_id="LOC-EQ1-1",
        ),
        evaluated_at=taken_at,
        calendar=calendar,
        regular_trading_open=time(9, 30, tzinfo=UTC),
    )
    locates = LocateDocument(
        as_of=taken_at,
        locates=(
            LocateRecord(
                locate_id="LOC-EQ1-1",
                source="SYNTHETIC_LENDER",
                located_at=taken_at,
                expires_at=taken_at + timedelta(hours=8),
                issue="ACME",
                quantity=Decimal(10),
            ),
        ),
    )
    stock = books.quantities()
    books_document = {
        "schema_version": "atreides.equities_books/2",
        "as_of": taken_at.isoformat(),
        "synthetic": True,
        "journal_digest": journal_digest,
        "posting_sources": [
            source.value for source in PostingSource if source is not PostingSource.REVERSAL
        ],
        "stock_record": {
            issue: {side.value: str(quantity) for side, quantity in sides.items()}
            for issue, sides in stock.items()
        },
        "balanced": not books.breaks,
        "cns": {
            "disposition": cns.disposition.value,
            "residual": str(cns.residual.quantity) if cns.residual else None,
        },
        "rule_204": rule_204.model_dump(mode="json"),
    }
    initial_by_id = {r.account_id: r for r in initial_results}
    moved_by_id = {r.account_id: r for r in moved_results}
    return {
        "equities-account-capacity.json": _json(attest_capacity(capacity)),
        "equities-locates.json": _json(attest_locates(locates)),
        "equities-books.json": _json(books_document),
        "equities-margin.json": _json(
            {
                "schema_version": "atreides.equities_margin/2",
                "as_of": taken_at.isoformat(),
                "synthetic": True,
                "journal_digest": journal_digest,
                "initial": initial_by_id["CUSTOMER-1"].model_dump(mode="json"),
                "after_price_move": moved_by_id["CUSTOMER-1"].model_dump(mode="json"),
                "accounts_initial": [r.model_dump(mode="json") for r in initial_results],
                "accounts_after_price_move": [r.model_dump(mode="json") for r in moved_results],
            }
        ),
        "equities-protection-from-books.json": _json(
            {
                "schema_version": "atreides.equities_protection_from_books/3",
                "as_of": taken_at.isoformat(),
                "synthetic": True,
                **protection,
            }
        ),
    }
