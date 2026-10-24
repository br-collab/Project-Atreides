"""Synthetic introducing-to-carrying conversion control rehearsal.

The real Atreides books and protection engines produce the scenario result.
I9 separately derives what that result must be from declared evidence and facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

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
from atreides.books.projections import project_customer_protection, reserve_bank_balances
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
from simulator.estate import (
    DepositDraw,
    DepositPolicy,
    ReserveDeposit,
    _actor,
    _complete_reserve_inputs,
    _post_reserve_deposits,
)
from simulator.runner import deposit_breach

SEED = 20261024
VARIANTS = (
    "clean",
    "short-first-deposit",
    "late-first-deposit",
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
GATE_RULES = {
    "G1": "15c3-3.f.bank_written_notification",
    "G2": "15c3-3.e5.affiliated_bank_excluded",
    "G3": "15c3-1.a2i.minimum.carrying",
    "G4": "15c3-3.control.c1",
}
Mutation = Literal[
    "forced-hold-funded",
    "forced-pass-short",
    "cleared-gate-let-through",
    "affiliated-counted-eligible",
    "prior-clearer-as-control",
    "drop-one-share",
]


@dataclass(frozen=True)
class StatementLine:
    account: str
    issue: str
    quantity: Decimal
    cash_credit: Decimal


@dataclass(frozen=True)
class ReadinessRecord:
    bank_notification: str | None
    non_affiliation: str | None
    pre_conversion_capital_plan: str | None
    control_location_arrangement: str | None

    def gates(self) -> dict[str, str | None]:
        return {
            "G1": self.bank_notification,
            "G2": self.non_affiliation,
            "G3": self.pre_conversion_capital_plan,
            "G4": self.control_location_arrangement,
        }


STATEMENT = (
    StatementLine("SYN-CUST-101", "SYN-EQ-ALPHA", Decimal("137"), Decimal("123456.79")),
    StatementLine("SYN-CUST-202", "SYN-EQ-BETA", Decimal("211"), Decimal("87654.32")),
)
PRICES = {"SYN-EQ-ALPHA": Decimal("101.37"), "SYN-EQ-BETA": Decimal("47.83")}


def readiness_record(variant: str) -> ReadinessRecord:
    """Return declared synthetic evidence, never an engine result relabelled as evidence."""
    return ReadinessRecord(
        None if variant == "missing-f-letter" else "SYN-F-NOTICE-001",
        None if variant == "affiliated-bank" else "SYN-NONAFFILIATION-001",
        None if variant == "capital-short" else "SYN-CAPITAL-PLAN-001",
        "SYN-CONTROL-ARRANGEMENT-001",
    )


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
    expected_q = {(x.account, x.issue): x.quantity for x in lines}
    expected_c = {x.account: x.cash_credit for x in lines}
    actual_q: dict[tuple[str, str], Decimal] = {}
    actual_c: dict[str, Decimal] = {}
    for entry in books.entries:
        for line in entry.lines:
            if (
                line.account_type is AccountType.CUSTOMER_CASH
                and line.record_side is RecordSide.OWNERSHIP
                and line.issue
            ):
                key = (line.account_id, line.issue)
                actual_q[key] = actual_q.get(key, Decimal()) + line.quantity
            if line.account_type is AccountType.CUSTOMER_CASH and line.currency == "USD":
                actual_c[line.account_id] = actual_c.get(line.account_id, Decimal()) + line.money
    return actual_q == expected_q and actual_c == expected_c


def _business_days(start: date, count: int) -> list[date]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    result: list[date] = []
    while len(result) < count:
        if calendar.is_business_day(start):
            result.append(start)
        start += timedelta(days=1)
    return result


def _policy(variant: str) -> DepositPolicy:
    outcome = {"short-first-deposit": "SHORT", "late-first-deposit": "LATE"}.get(variant, "ON_TIME")
    return DepositPolicy(
        customer=DepositDraw(outcome=outcome, short_fraction=Decimal("0.27")),
        pab=DepositDraw(outcome="ON_TIME", short_fraction=Decimal("0.27")),
        bank_equity_capital=Decimal("10000000"),
    )


def _gate_reasons(record: ReadinessRecord) -> list[str]:
    return [f"{gate}:{GATE_RULES[gate]}" for gate, value in record.gates().items() if value is None]


def _required_reasons(
    *,
    day: date,
    conversion_day: date,
    transfer_day: date,
    record: ReadinessRecord,
    deposit: ReserveDeposit,
    affiliated: bool,
    requirement: Decimal,
    net_worth: Decimal,
    carrying_minimum: Decimal,
) -> list[str]:
    """Derive the required outcome without reading any engine disposition.

    17 CFR 240.15c3-3(e)(3)(i)(A), pinned source c7d7067f..., says the deposit
    "must be made no later than one hour after the opening of banking business
    on the second following business day." A SHORT or LATE first deposit holds.
    The pinned 15c3-1(a)(2)(i) carrying minimum is an upper-bound test because
    net capital cannot exceed the separately declared net worth.
    """
    if day < conversion_day:
        return []
    reasons = _gate_reasons(record)
    if deposit_breach(deposit) or (affiliated and requirement > 0):
        reasons.append("reserve shortfall")
    if day < transfer_day:
        reasons.append("possession or control")
    if net_worth < carrying_minimum:
        reasons.append("net capital")
    return sorted(set(reasons))


def _produced_reasons(
    record: ReadinessRecord, *, after: bool, reserve: str, pab: str, control: str, capital: str
) -> list[str]:
    if not after:
        return []
    reasons = _gate_reasons(record)
    if reserve != "PASS" or pab != "PASS":
        reasons.append("reserve shortfall")
    if control != "PASS":
        reasons.append("possession or control")
    if capital != "PASS":
        reasons.append("net capital")
    return sorted(set(reasons))


def run_conversion_variant(  # noqa: PLR0915 - one close keeps independent sources visible
    variant: str, *, mutation: Mutation | None = None
) -> dict[str, object]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown conversion variant: {variant}")
    rules = load_rule_table()
    minimum = rules.get("15c3-1.a2i.minimum.carrying")
    if minimum is None or minimum.value is None:
        raise ValueError("pinned carrying minimum is unavailable")
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    days = _business_days(date(2027, 1, 4), 6)
    conversion_day = days[2]
    transfer_day = days[5] if variant == "late-transfer" else days[3]
    declared = readiness_record(variant)
    net_worth = Decimal("100000") if variant == "capital-short" else Decimal("1000000")
    closes: list[dict[str, object]] = []
    for index, day in enumerate(days):
        after = day >= conversion_day
        transferred = after and day >= transfer_day
        lines = STATEMENT
        if mutation == "drop-one-share" and after:
            lines = (
                StatementLine(
                    STATEMENT[0].account,
                    STATEMENT[0].issue,
                    STATEMENT[0].quantity - 1,
                    STATEMENT[0].cash_credit,
                ),
                STATEMENT[1],
            )
        if mutation == "prior-clearer-as-control" and day == conversion_day:
            transferred = True
        books = (
            migration_books(lines, day, transferred=transferred)
            if after
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
                    calendar=calendar,
                    house_maintenance_rate=Decimal("0.30"),
                    maintenance_call_due_business_days=3,
                )
                for x in lines
            )
            if after
            else ()
        )
        projected = project_customer_protection(
            books,
            as_of=day,
            prices=PRICES,
            net_worth=net_worth,
            calendar=calendar,
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
        sized_pab = compute_reserve(with_customer_excess_debits(pab_input, sized), rules)
        deadline = calendar.add_business_days(conversion_day, 2)
        deposit = ReserveDeposit(
            computation="customer",
            opening_balance=Decimal(),
            requirement=None,
            needed=None,
            drawn_outcome="NOT_APPLICABLE",
            outcome="NOT_APPLICABLE",
            amount=Decimal(),
            deposit_date=None,
            deadline=deadline,
            balance_at_deadline=Decimal(),
            closing_balance=Decimal(),
        )
        reserve, pab = sized, sized_pab
        if after:
            reserve, pab, deposits = _post_reserve_deposits(
                books=books,
                run_number=80_000 + VARIANTS.index(variant) * 100 + index,
                business_date=conversion_day,
                calendar=calendar,
                actor=_actor(),
                rules=rules,
                reserve_inputs=reserve_input,
                pab_reserve_inputs=pab_input,
                sized_from=(sized, sized_pab),
                opening=(Decimal(), Decimal()),
                policy=_policy(variant),
            )
            deposit = deposits[0]
            if variant == "affiliated-bank" and mutation != "affiliated-counted-eligible":
                balance = reserve_bank_balances(books, through=deadline)[
                    AccountType.RESERVE_BANK_CUSTOMER
                ]
                affiliated_input = reserve_input.model_copy(
                    update={
                        "cash_deposits": (
                            BankCashDeposit(
                                bank="SYNTHETIC AFFILIATED RESERVE BANK",
                                amount=balance,
                                affiliated=True,
                                bank_equity_capital=Decimal("10000000"),
                            ),
                        )
                    }
                )
                reserve = compute_reserve(affiliated_input, rules)
                pab = compute_reserve(with_customer_excess_debits(pab_input, reserve), rules)
        control = check_possession_or_control(projected.control, rules)
        capital = compute_net_capital(
            projected.net_capital.model_copy(
                update={
                    "category": (
                        BrokerDealerCategory.CARRYING if after else BrokerDealerCategory.INTRODUCING
                    ),
                    "reports_lending_activity_monthly": False,
                    "securities_loaned_and_repo_payable": Decimal(),
                    "securities_borrowed_and_reverse_repo_value": Decimal(),
                }
            ),
            rules,
        )
        required_record = declared
        if mutation == "cleared-gate-let-through" and day == days[3]:
            required_record = ReadinessRecord(
                None,
                declared.non_affiliation,
                declared.pre_conversion_capital_plan,
                declared.control_location_arrangement,
            )
        produced_reasons = _produced_reasons(
            declared,
            after=after,
            reserve=reserve.disposition.value,
            pab=pab.disposition.value,
            control=control.disposition.value,
            capital=capital.disposition.value,
        )
        produced = "HOLD" if produced_reasons else "PASS"
        if mutation == "forced-hold-funded" and day == days[3]:
            produced, produced_reasons = "HOLD", ["reserve shortfall"]
        if mutation == "forced-pass-short" and day == conversion_day:
            produced, produced_reasons = "PASS", []
        required_reasons = _required_reasons(
            day=day,
            conversion_day=conversion_day,
            transfer_day=transfer_day,
            record=required_record,
            deposit=deposit,
            affiliated=variant == "affiliated-bank",
            requirement=sized.requirement_after_customer_excess_debits or Decimal(),
            net_worth=net_worth,
            carrying_minimum=minimum.value,
        )
        required = "HOLD" if required_reasons else "PASS"
        i9 = produced == required and produced_reasons == required_reasons
        i10 = not after or migration_conserved(books, STATEMENT)
        closes.append(
            {
                "business_date": day.isoformat(),
                "phase": "carrying" if after else "introducing",
                "conversion_disposition": produced,
                "conversion_reasons": produced_reasons,
                "required_conversion_disposition": required,
                "required_conversion_reasons": required_reasons,
                "readiness_evidence": required_record.gates(),
                "invariants": {"I9_CONVERSION_GATED": i9, "I10_MIGRATION_CONSERVED": i10},
                "first_deposit": {
                    "outcome": deposit.outcome,
                    "amount": str(deposit.amount),
                    "deadline": deposit.deadline.isoformat(),
                    "balance_at_deadline": str(deposit.balance_at_deadline),
                },
                "reserve": {
                    "disposition": reserve.disposition.value,
                    "requirement": str(sized.requirement_after_customer_excess_debits or Decimal()),
                    "shortfall": (
                        str(reserve.shortfall) if reserve.shortfall is not None else None
                    ),
                },
                "pab_reserve": {"disposition": pab.disposition.value},
                "control": {
                    "disposition": control.disposition.value,
                    "reasons": list(control.reasons),
                },
                "net_capital": {
                    "disposition": capital.disposition.value,
                    "net_capital": (
                        str(capital.net_capital) if capital.net_capital is not None else None
                    ),
                    "minimum": (
                        str(capital.minimum_requirement)
                        if capital.minimum_requirement is not None
                        else None
                    ),
                },
            }
        )
    return {
        "schema_version": "sim.conversion/2",
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
    closes = cast(list[dict[str, object]], run["closes"])
    (output / "run-summary.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    (output / "daily-close.json").write_text(
        json.dumps(
            {"schema_version": "sim.conversion-daily-close/2", "closes": closes},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (output / "trend.json").write_text(
        json.dumps(
            {
                "schema_version": "sim.conversion-trend/2",
                "all_invariants_pass": run["all_invariants_pass"],
                "invariants": ["I9", "I10"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    start = next(i for i, c in enumerate(closes) if c["business_date"] == run["conversion_day"])
    rows = []
    for close in closes[start : start + 4]:
        deposit = cast(dict[str, str], close["first_deposit"])
        required = ", ".join(cast(list[str], close["required_conversion_reasons"])) or "none"
        produced = ", ".join(cast(list[str], close["conversion_reasons"])) or "none"
        rows.append(
            f"| {close['business_date']} | {close['required_conversion_disposition']}: "
            f"{required} | {close['conversion_disposition']}: {produced} | "
            f"{deposit['outcome']} | {deposit['deadline']} | "
            f"{deposit['balance_at_deadline']} |"
        )
    d_close = closes[start]
    invariants = cast(dict[str, bool], d_close["invariants"])
    (output / "SUMMARY.md").write_text(
        "SYNTHETIC CONTROL REHEARSAL — not evidence of production correctness\n\n"
        f"# CONV-1 {run['variant']}\n\n- Conversion day: `{run['conversion_day']}`\n"
        f"- D disposition: `{d_close['conversion_disposition']}`\n"
        f"- I9 conversion gated: `{invariants['I9_CONVERSION_GATED']}`\n"
        f"- I10 migration conserved: `{invariants['I10_MIGRATION_CONSERVED']}`\n\n"
        "## D through D+3 evidence\n\n"
        "| Date | Required | Produced | First deposit | Deadline | Balance at deadline |\n"
        "|---|---|---|---|---|---:|\n"
        + "\n".join(rows)
        + "\n\n## Not claimed\n\n- "
        + "\n- ".join(cast(list[str], run["not_claimed"]))
        + "\n"
    )
