"""Synthetic month-end FOCUS tie-out and 17a-3 books-and-records inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
)
from atreides.books.projections import ProtectionInputs, project_customer_protection
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    ComputationMode,
    LineBalance,
    compute_reserve,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from simulator.conversion import _posting
from simulator.estate import _complete_reserve_inputs


@dataclass(frozen=True)
class FocusLines:
    net_capital: Decimal | None
    reserve_total_credits: Decimal | None
    reserve_total_debits: Decimal | None
    possession_or_control_shortfall: Decimal | None


def _capital_books(day: date, capital: Decimal) -> EquitiesBooks:
    books = EquitiesBooks(break_owner="CONV_4_REGULATORY_REPORTING")
    event = 730_000_000 + day.month
    books.post(
        JournalEntry(
            entry_id=f"CONV-4-CAPITAL-{day.isoformat()}",
            source_event_id=f"evt_{event:026d}",
            source=PostingSource.CASH_MOVEMENT,
            effective_date=day,
            effective_date_basis="VALUE_DATE",
            authority="CONV-4_SYNTHETIC_CAPITAL_BOOK",
            synthetic=True,
            lines=(
                LedgerLine(
                    account_id="SYN-FIRM-CASH",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=capital,
                ),
                LedgerLine(
                    account_id="SYN-FIRM-EQUITY",
                    account_type=AccountType.FIRM_PROPRIETARY,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-capital,
                ),
            ),
            posting=_posting(event, day),
        )
    )
    return books


def _sum_lines(lines: tuple[LineBalance, ...], ids: tuple[str, ...]) -> Decimal | None:
    amounts = [line.amount for line in lines if line.rule_id in ids]
    return None if any(value is None for value in amounts) else sum(
        (value for value in amounts if value is not None), Decimal()
    )


def _books_net_capital(books: EquitiesBooks) -> Decimal:
    return -sum(
        (
            line.money
            for entry in books.entries
            for line in entry.lines
            if line.account_type is AccountType.FIRM_PROPRIETARY
            and line.record_side is RecordSide.MONEY
        ),
        Decimal(),
    )


def _books_control_shortfall(projected: ProtectionInputs) -> Decimal | None:
    control = projected.control
    shortfalls: list[Decimal] = []
    for issue in control.issues:
        if issue.fully_paid is None or issue.excess_margin is None:
            return None
        controlled = sum(
            (holding.quantity for holding in issue.holdings if holding.location in {"DTC", "BANK"}),
            Decimal(),
        )
        shortfalls.append(max(issue.fully_paid + issue.excess_margin - controlled, Decimal()))
    return sum(shortfalls, Decimal())


def run_focus(
    *, mutation: Literal["net-capital-engine-lie"] | None = None
) -> dict[str, object]:
    """Run three month ends and independently tie book lines to engine results.

    17 CFR 240.17a-3(a)(1) requires an itemized daily record of securities,
    cash receipts/disbursements, and other debits/credits. The records list
    below reports only what this journal actually holds; it does not invent
    absent order, personnel, or communication records.
    """
    closes: list[dict[str, object]] = []
    rules = load_rule_table()
    for day in (date(2026, 9, 30), date(2026, 10, 31), date(2026, 11, 30)):
        books = _capital_books(day, Decimal("1000000"))
        book_capital = _books_net_capital(books)
        projected = project_customer_protection(
            books,
            as_of=day,
            prices={},
            net_worth=book_capital,
            calendar=MarketCalendar.load(Market.US_EQUITIES),
            margin_results=(),
        )
        reserve_inputs = _complete_reserve_inputs(
            projected.reserve,
            average_total_credits=Decimal(),
            daily_requirement_effective_date=None,
            computation_mode=ComputationMode.WEEKLY,
            previously_daily_required=False,
            daily_exit_notice_date=None,
        )
        reserve = compute_reserve(reserve_inputs, rules)
        capital = compute_net_capital(
            projected.net_capital.model_copy(
                update={
                    "reports_lending_activity_monthly": False,
                    "securities_loaned_and_repo_payable": Decimal(),
                    "securities_borrowed_and_reverse_repo_value": Decimal(),
                }
            ),
            rules,
        )
        control = check_possession_or_control(projected.control, rules)
        engine_capital = capital.net_capital
        if mutation == "net-capital-engine-lie" and engine_capital is not None:
            engine_capital += Decimal("0.01")
        book_lines = FocusLines(
            net_capital=book_capital,
            reserve_total_credits=_sum_lines(reserve_inputs.lines, EXHIBIT_A_CREDITS),
            reserve_total_debits=_sum_lines(reserve_inputs.lines, EXHIBIT_A_DEBITS),
            possession_or_control_shortfall=_books_control_shortfall(projected),
        )
        engine_lines = FocusLines(
            net_capital=engine_capital,
            reserve_total_credits=reserve.total_credits,
            reserve_total_debits=reserve.total_debits,
            possession_or_control_shortfall=(
                None
                if any(item.shortfall is None for item in control.issues)
                else sum(
                    (item.shortfall for item in control.issues if item.shortfall is not None),
                    Decimal(),
                )
            ),
        )
        differences = {
            name: "CONV_4_REGULATORY_REPORTING"
            for name, value in asdict(book_lines).items()
            if value != asdict(engine_lines)[name]
        }
        closes.append(
            {
                "month_end": day.isoformat(),
                "focus_lines_from_books": {
                    key: None if value is None else str(value)
                    for key, value in asdict(book_lines).items()
                },
                "engine_lines": {
                    key: None if value is None else str(value)
                    for key, value in asdict(engine_lines).items()
                },
                "break_owners": differences,
                "invariants": {"I13_FOCUS_TIE_OUT": not differences},
                "17a_3_records": {
                    "produced": [
                        "daily cash blotter",
                        "general ledger",
                        "account ledger",
                        "securities record by issue and location",
                    ],
                    "not_produced": [
                        "order memoranda",
                        "associated-person records",
                        "customer communications",
                    ],
                },
            }
        )
    return {
        "schema_version": "sim.focus/1",
        "synthetic": True,
        "source_pin_status": "INDETERMINATE",
        "source_pin_reason": "official pages verified; local byte retrieval refused by hosts",
        "closes": closes,
    }


def attack_focus() -> dict[str, bool]:
    """Make the net-capital engine report one cent high, rerun, and observe I13 fail."""
    result = run_focus(mutation="net-capital-engine-lie")
    closes = result["closes"]
    if not isinstance(closes, list):
        raise TypeError("FOCUS run did not return closes")
    return {
        "net-capital-engine-lie": all(
            isinstance(close, dict)
            and isinstance(close.get("invariants"), dict)
            and close["invariants"].get("I13_FOCUS_TIE_OUT") is False
            for close in closes
        )
    }
