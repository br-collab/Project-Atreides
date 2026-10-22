"""Deterministic EQ-1 Atreides scenario and publication documents."""

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
)
from atreides.books.projections import project_customer_protection
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import compute_reserve
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.deadlines.rule_204 import Rule204Fail, Rule204Origin, assess_rule_204
from atreides.dsor.books import BooksPosting
from atreides.equities.documents import (
    AccountCapacity,
    AccountCapacityDocument,
    AccountPosition,
    LocateDocument,
    LocateRecord,
    attest_capacity,
    attest_locates,
)
from atreides.margin.engine import MarginAccount, MarginPosition, compute_margin
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
    role="eq1-synthetic-books",
    entitlement_refs=(),
    authenticated=True,
)


def _json(value: BaseModel | dict[str, object]) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _entry(
    number: int,
    source: PostingSource,
    lines: tuple[LedgerLine, ...],
    at: datetime,
    basis: str,
    *,
    synthetic: bool = False,
) -> JournalEntry:
    alphabet = "12345678ABCDEFGHJKMNPQRSTVWXYZ"
    event_id = EventId("evt_0" + alphabet[number] * 25)
    entry_id = f"EQ1-{number}"
    return JournalEntry(
        entry_id=entry_id,
        source_event_id=str(event_id),
        source=source,
        effective_date=at.date(),
        effective_date_basis=basis,
        authority="EQ1_SYNTHETIC_OPERATOR",
        lines=lines,
        posting=BooksPosting(
            posted_record_id=entry_id,
            posting_authority=ACTOR,
            effective_time=at,
            source_event_id=event_id,
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=synthetic,
    )


def build_equities_publications(taken_at: datetime) -> dict[str, bytes]:
    """Run settlement, books, margin and protection once and return stable documents."""
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    books = EquitiesBooks(break_owner="EQ1_STOCK_RECORD_CONTROL")
    security_lines = (
        LedgerLine(
            account_id="CUSTOMER-1",
            account_type=AccountType.CUSTOMER_MARGIN,
            record_side=RecordSide.OWNERSHIP,
            issue="ACME",
            quantity=Decimal(10),
        ),
        LedgerLine(
            account_id="DTC",
            account_type=AccountType.DTC,
            record_side=RecordSide.LOCATION,
            issue="ACME",
            quantity=Decimal(-10),
        ),
        LedgerLine(
            account_id="CUSTOMER-1",
            account_type=AccountType.CUSTOMER_MARGIN,
            record_side=RecordSide.MONEY,
            currency="USD",
            money=Decimal(-1000),
        ),
        LedgerLine(
            account_id="NSCC",
            account_type=AccountType.CASH,
            record_side=RecordSide.MONEY,
            currency="USD",
            money=Decimal(1000),
        ),
    )
    books.post(_entry(1, PostingSource.TRADE_CAPTURE, security_lines, taken_at, "TRADE_DATE"))
    for number, source, basis in (
        (2, PostingSource.ALLOCATION, "TRADE_DATE"),
        (3, PostingSource.CNS_SETTLEMENT, "SETTLEMENT_DATE"),
        (4, PostingSource.CNS_FAIL, "SETTLEMENT_DATE"),
        (5, PostingSource.CORPORATE_ACTION, "PAY_DATE"),
        (6, PostingSource.CASH_MOVEMENT, "VALUE_DATE"),
        (7, PostingSource.MARGIN_INTEREST, "VALUE_DATE"),
    ):
        cash = Decimal(number)
        books.post(
            _entry(
                number,
                source,
                (
                    LedgerLine(
                        account_id="CUSTOMER-1",
                        account_type=AccountType.CUSTOMER_MARGIN,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=-cash,
                    ),
                    LedgerLine(
                        account_id="FIRM",
                        account_type=AccountType.CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=cash,
                    ),
                ),
                taken_at,
                basis,
                synthetic=source is PostingSource.MARGIN_INTEREST,
            )
        )
    assert not books.verify_stock_record()

    margin_account = MarginAccount(
        account_id="CUSTOMER-1",
        cash_balance=Decimal(-1027),
        positions=(
            MarginPosition(issue="ACME", quantity=Decimal(10), price=Decimal(100), new_trade=True),
        ),
    )
    initial_margin = compute_margin(
        margin_account,
        trade_date=taken_at.date(),
        calendar=calendar,
        house_maintenance_rate=Decimal("0.30"),
    )
    moved_margin = compute_margin(
        margin_account.model_copy(
            update={
                "positions": (
                    MarginPosition(issue="ACME", quantity=Decimal(10), price=Decimal(60)),
                )
            }
        ),
        trade_date=taken_at.date(),
        calendar=calendar,
        house_maintenance_rate=Decimal("0.30"),
    )
    protection_inputs = project_customer_protection(
        books, as_of=taken_at.date(), prices={"ACME": Decimal(60)}, net_worth=Decimal(10_000_000)
    )
    rules = load_rule_table()
    protection = {
        "books_digest": protection_inputs.audit.books_digest,
        "projection": protection_inputs.audit.model_dump(mode="json"),
        "reserve": compute_reserve(protection_inputs.reserve, rules).model_dump(mode="json"),
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
        provenance="synthetic EQ-1 NSCC profile",
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
    capacity = AccountCapacityDocument(
        as_of=taken_at,
        maximum_age_seconds=300,
        accounts=(
            AccountCapacity(
                account_id="CUSTOMER-1",
                buying_power=Decimal(5000),
                margin_excess=Decimal(1000),
                positions=(AccountPosition(issue="ACME", quantity=Decimal(10)),),
            ),
        ),
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
        "schema_version": "atreides.equities_books/1",
        "as_of": taken_at.isoformat(),
        "synthetic": True,
        "journal_digest": books.digest(),
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
    return {
        "equities-account-capacity.json": _json(attest_capacity(capacity)),
        "equities-locates.json": _json(attest_locates(locates)),
        "equities-books.json": _json(books_document),
        "equities-margin.json": _json(
            {
                "schema_version": "atreides.equities_margin/1",
                "as_of": taken_at.isoformat(),
                "synthetic": True,
                "initial": initial_margin.model_dump(mode="json"),
                "after_price_move": moved_margin.model_dump(mode="json"),
            }
        ),
        "equities-protection-from-books.json": _json(
            {
                "schema_version": "atreides.equities_protection_from_books/1",
                "as_of": taken_at.isoformat(),
                "synthetic": True,
                **protection,
            }
        ),
    }
