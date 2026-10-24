"""CONV-1 synthetic introducing-to-carrying conversion scenario.

This is a control rehearsal, not a legal conclusion or a submission workflow.
It posts the synthetic statement into the real Atreides books and evaluates the
real reserve, possession/control, and net-capital engines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from cannae_kernel.ids import EventId
from cannae_kernel.provenance import Provenance

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
from atreides.customer_protection.net_capital import BrokerDealerCategory, compute_net_capital
from atreides.customer_protection.reserve import (
    BankCashDeposit,
    ComputationMode,
    compute_reserve,
    with_customer_excess_debits,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from atreides.margin.engine import MarginAccount, MarginPosition, compute_margin
from simulator.estate import _actor, _complete_reserve_inputs

SEED = 20261024
VARIANTS = (
    "clean",
    "short-first-deposit",
    "late-transfer",
    "missing-f-letter",
    "affiliated-bank",
    "capital-short",
)
NOT_CLAIMED = (
    "ACATS or bulk transfer",
    "DTC, NSCC, or FICC membership or clearing-fund sufficiency",
    "FOCUS filing",
    "FINRA continuing membership application approval",
    "legal conclusion",
)

# 17 CFR 240.15c3-3(k)(2)(ii), pinned source c7d7067f...: an introducing
# broker-dealer "promptly transmits all customer funds and securities to the
# clearing broker or dealer". Conversion is held until the evidence below says
# the carrying controls are ready; absence remains None rather than invented.
# Paragraph (f) requires written bank notification for each reserve account.
GATE_RULES = {
    "G1": "15c3-3.f.bank_written_notification",
    "G2": "15c3-3.e5.affiliated_bank_excluded",
    "G3": "15c3-1.a2i.minimum.carrying",
    "G4": "15c3-3.control.c1",
}


@dataclass(frozen=True)
class StatementLine:
    account: str
    issue: str
    quantity: Decimal
    cash_credit: Decimal


STATEMENT = (
    StatementLine("SYN-CUST-101", "SYN-EQ-ALPHA", Decimal("137"), Decimal("123456.79")),
    StatementLine("SYN-CUST-202", "SYN-EQ-BETA", Decimal("211"), Decimal("87654.32")),
)
PRICES = {"SYN-EQ-ALPHA": Decimal("101.37"), "SYN-EQ-BETA": Decimal("47.83")}


def _posting(number: int, day: date) -> BooksPosting:
    event = f"evt_{number:026d}"
    return BooksPosting(
        posted_record_id=f"CONV-1-{number}",
        posting_authority=_actor(),
        effective_time=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_event_id=EventId(event),
        provenance=Provenance.FACT_SYNTHETIC,
    )


def migration_books(
    lines: tuple[StatementLine, ...], day: date, *, transferred: bool
) -> EquitiesBooks:
    """Replay the prior-clearer statement through the append-only real book."""
    books = EquitiesBooks(break_owner="CONV_1_SETTLEMENT_OPS")
    for index, line in enumerate(lines, 1):
        location = AccountType.DTC if transferred else AccountType.FIRM_PROPRIETARY
        event = 710_000_000 + index
        books.post(
            JournalEntry(
                entry_id=f"CONV-1-MIGRATION-{index}",
                source_event_id=f"evt_{event:026d}",
                source=PostingSource.CASH_MOVEMENT,
                effective_date=day,
                effective_date_basis="VALUE_DATE",
                authority="CONV-1_SYNTHETIC_PRIOR_CLEARER_STATEMENT",
                synthetic=True,
                lines=(
                    LedgerLine(
                        account_id=line.account,
                        account_type=AccountType.CUSTOMER_CASH,
                        record_side=RecordSide.OWNERSHIP,
                        issue=line.issue,
                        quantity=line.quantity,
                    ),
                    LedgerLine(
                        account_id="SYN-PRIOR-CLEARER",
                        account_type=location,
                        record_side=RecordSide.LOCATION,
                        issue=line.issue,
                        quantity=-line.quantity,
                    ),
                    LedgerLine(
                        account_id=line.account,
                        account_type=AccountType.CUSTOMER_CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=line.cash_credit,
                    ),
                    LedgerLine(
                        account_id="SYN-CONVERSION-FUNDING",
                        account_type=AccountType.CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=-line.cash_credit,
                    ),
                ),
                posting=_posting(event, day),
            )
        )
    return books


def migration_conserved(books: EquitiesBooks, lines: tuple[StatementLine, ...]) -> bool:
    expected_qty = {(x.account, x.issue): x.quantity for x in lines}
    expected_cash = {x.account: x.cash_credit for x in lines}
    actual_qty: dict[tuple[str, str], Decimal] = {}
    actual_cash: dict[str, Decimal] = {}
    for entry in books.entries:
        for line in entry.lines:
            if (
                line.account_type is AccountType.CUSTOMER_CASH
                and line.record_side is RecordSide.OWNERSHIP
                and line.issue
            ):
                actual_qty[(line.account_id, line.issue)] = (
                    actual_qty.get((line.account_id, line.issue), Decimal()) + line.quantity
                )
            if line.account_type is AccountType.CUSTOMER_CASH and line.currency == "USD":
                actual_cash[line.account_id] = (
                    actual_cash.get(line.account_id, Decimal()) + line.money
                )
    return actual_qty == expected_qty and actual_cash == expected_cash


def conversion_gated(disposition: str, after_conversion: bool, reasons: list[str]) -> bool:
    """I9: a carrying conversion with a missing gate or engine hold cannot pass."""
    return (disposition == "HOLD") == bool(after_conversion and reasons)


def _business_days(start: date, count: int) -> list[date]:
    cal = MarketCalendar.load(Market.US_EQUITIES)
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cal.is_business_day(cursor):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def run_conversion_variant(variant: str) -> dict[str, object]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown conversion variant: {variant}")
    rules = load_rule_table()
    cal = MarketCalendar.load(Market.US_EQUITIES)
    days = _business_days(date(2027, 1, 4), 6)
    conversion_day = days[2]
    closes: list[dict[str, object]] = []
    for day in days:
        after_conversion = day >= conversion_day
        transfer_day = days[5] if variant == "late-transfer" else days[3]
        transferred = after_conversion and day >= transfer_day
        books = (
            migration_books(STATEMENT, day, transferred=transferred)
            if after_conversion
            else EquitiesBooks(break_owner="CONV_1_SETTLEMENT_OPS")
        )
        margins = (
            tuple(
                compute_margin(
                    MarginAccount(
                        account_id=x.account,
                        cash_balance=x.cash_credit,
                        positions=(
                            MarginPosition(
                                issue=x.issue, quantity=x.quantity, price=PRICES[x.issue]
                            ),
                        ),
                    ),
                    trade_date=day,
                    calendar=cal,
                    house_maintenance_rate=Decimal("0.30"),
                    maintenance_call_due_business_days=3,
                )
                for x in STATEMENT
            )
            if after_conversion
            else ()
        )
        projected = project_customer_protection(
            books,
            as_of=day,
            prices=PRICES,
            net_worth=Decimal("100000") if variant == "capital-short" else Decimal("1000000"),
            calendar=cal,
            margin_results=margins,
        )
        reserve_input = _complete_reserve_inputs(
            projected.reserve,
            average_total_credits=Decimal("300000"),
            daily_requirement_effective_date=None,
            computation_mode=ComputationMode.WEEKLY,
            previously_daily_required=False,
            daily_exit_notice_date=None,
        )
        pab_input = _complete_reserve_inputs(
            projected.pab_reserve,
            average_total_credits=Decimal("300000"),
            daily_requirement_effective_date=None,
            computation_mode=ComputationMode.WEEKLY,
            previously_daily_required=False,
            daily_exit_notice_date=None,
        )
        sized = compute_reserve(reserve_input, rules)
        required = sized.requirement_after_customer_excess_debits or Decimal()
        deposit = required
        if variant == "short-first-deposit" and day == conversion_day:
            deposit = (required * Decimal("0.73")).quantize(Decimal("0.01"))
        affiliate = variant == "affiliated-bank"
        banked = (
            reserve_input.model_copy(
                update={
                    "cash_deposits": (
                        BankCashDeposit(
                            bank="SYNTHETIC RESERVE BANK",
                            amount=deposit,
                            affiliated=affiliate,
                            bank_equity_capital=Decimal("10000000"),
                        ),
                    )
                }
            )
            if deposit
            else reserve_input
        )
        reserve = compute_reserve(banked, rules)
        pab = compute_reserve(with_customer_excess_debits(pab_input, reserve), rules)
        control = check_possession_or_control(projected.control, rules)
        capital_input = projected.net_capital.model_copy(
            update={
                "category": BrokerDealerCategory.CARRYING
                if after_conversion
                else BrokerDealerCategory.INTRODUCING,
                "reports_lending_activity_monthly": False,
                "securities_loaned_and_repo_payable": Decimal(),
                "securities_borrowed_and_reverse_repo_value": Decimal(),
            }
        )
        capital = compute_net_capital(capital_input, rules)
        evidence = {
            "G1": None if variant == "missing-f-letter" else "SYN-F-NOTICE-001",
            "G2": None if affiliate else "SYN-NONAFFILIATION-001",
            "G3": None if capital.disposition.value != "PASS" else "SYN-CAPITAL-COMPUTATION-001",
            "G4": None if control.disposition.value != "PASS" else "SYN-CONTROL-ARRANGEMENT-001",
        }
        missing = [
            f"{gate}:{GATE_RULES[gate]}" for gate, value in evidence.items() if value is None
        ]
        engine_holds = []
        if reserve.disposition.value != "PASS":
            engine_holds.append("customer reserve")
        if pab.disposition.value != "PASS":
            engine_holds.append("PAB reserve")
        if control.disposition.value != "PASS":
            engine_holds.append("possession or control")
        if capital.disposition.value != "PASS":
            engine_holds.append("net capital")
        disposition = "HOLD" if after_conversion and (missing or engine_holds) else "PASS"
        i9 = conversion_gated(disposition, after_conversion, missing + engine_holds)
        i10 = not after_conversion or migration_conserved(books, STATEMENT)
        closes.append(
            {
                "business_date": day.isoformat(),
                "phase": "carrying" if after_conversion else "introducing",
                "conversion_disposition": disposition,
                "conversion_reasons": missing + engine_holds,
                "readiness_evidence": evidence,
                "invariants": {"I9_CONVERSION_GATED": i9, "I10_MIGRATION_CONSERVED": i10},
                "first_deposit": str(deposit),
                "reserve": {
                    "disposition": reserve.disposition.value,
                    "requirement": str(required),
                    "shortfall": str(reserve.shortfall) if reserve.shortfall is not None else None,
                },
                "pab_reserve": {
                    "disposition": pab.disposition.value,
                    "requirement": str(pab.requirement_after_customer_excess_debits)
                    if pab.requirement_after_customer_excess_debits is not None
                    else None,
                },
                "control": {
                    "disposition": control.disposition.value,
                    "reasons": list(control.reasons),
                },
                "net_capital": {
                    "disposition": capital.disposition.value,
                    "net_capital": str(capital.net_capital)
                    if capital.net_capital is not None
                    else None,
                    "minimum": str(capital.minimum_requirement)
                    if capital.minimum_requirement is not None
                    else None,
                },
            }
        )
    return {
        "schema_version": "sim.conversion/1",
        "synthetic": True,
        "seed": SEED,
        "variant": variant,
        "conversion_day": conversion_day.isoformat(),
        "closes": closes,
        "not_claimed": list(NOT_CLAIMED),
        "all_invariants_pass": all(
            all(cast(dict[str, bool], c["invariants"]).values()) for c in closes
        ),
    }


def publish_conversion(run: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    closes = run["closes"]
    assert isinstance(closes, list)
    (output / "run-summary.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    (output / "daily-close.json").write_text(
        json.dumps(
            {"schema_version": "sim.conversion-daily-close/1", "closes": closes},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (output / "trend.json").write_text(
        json.dumps(
            {
                "schema_version": "sim.conversion-trend/1",
                "all_invariants_pass": run["all_invariants_pass"],
                "invariants": ["I9", "I10"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    d_close = next(c for c in closes if c["business_date"] == run["conversion_day"])
    invariants = d_close["invariants"]
    (output / "SUMMARY.md").write_text(
        "SYNTHETIC CONTROL REHEARSAL — not evidence of production correctness\n\n"
        f"# CONV-1 {run['variant']}\n\n"
        f"- Conversion day: `{run['conversion_day']}`\n"
        f"- D disposition: `{d_close['conversion_disposition']}`\n"
        f"- I9 conversion gated: `{invariants['I9_CONVERSION_GATED']}`\n"
        f"- I10 migration conserved: `{invariants['I10_MIGRATION_CONSERVED']}`\n"
        f"- First deposit: `${d_close['first_deposit']}`\n\n"
        "## Not claimed\n\n- "
        + "\n- ".join(cast(list[str], run["not_claimed"]))
        + "\n"
    )
