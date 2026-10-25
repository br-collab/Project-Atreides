"""FIX-11: required protection outcomes derived from the books, never from an engine.

I6 compares what each engine produced with what the declared inputs and the books require.
The reserve legs already take their required outcome from the SIM-1G deposit outcome.
This module does the same for net capital and possession or control. It reads journal
lines and pinned rule values directly; it does not call the projection, the margin
engine, the net capital engine or the control engine, and it never reads an engine's
disposition, breaches, reasons or missing inputs.

It is a second implementation of the same pinned rules (an N-version oracle), kept
deliberately small: equities only, the alternative standard, and the firm-run shapes.
Anything outside those shapes returns ``None`` so the caller can refuse instead of guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from atreides.books.ledger import AccountType, EquitiesBooks, RecordSide
from atreides.customer_protection.rules.model import RuleTable

ZERO = Decimal(0)
CUSTOMER_TYPES = frozenset({AccountType.CUSTOMER_CASH, AccountType.CUSTOMER_MARGIN})
CONTROL_TYPES = frozenset({AccountType.DTC, AccountType.BANK_CONTROL})

EXCESS_MARGIN_THRESHOLD = "15c3-3.a5.excess_margin_threshold"
EQUITY_RATE = "15c3-1.c2viJ.rate"
EQUITY_LESSER_THRESHOLD = "15c3-1.c2viJ.lesser_threshold"
EQUITY_EXCESS_RATE = "15c3-1.c2viJ.excess_rate"
ALT_FLOOR = "15c3-1.a1ii.alternative_floor"
ALT_PERCENT = "15c3-1.a1ii.alternative_debit_percent"
CARRYING_MINIMUM = "15c3-1.a2i.minimum.carrying"
WARN_ALT = "17a-11.b2.alternative_warning"
WARN_MINIMUM = "17a-11.b3.minimum_warning"


def _value(table: RuleTable, rule_id: str) -> Decimal | None:
    item = table.get(rule_id)
    return None if item is None else item.value


@dataclass(frozen=True, slots=True)
class _BookView:
    customer_cash: dict[str, Decimal]
    customer_positions: dict[str, dict[str, Decimal]]
    issue_positions: dict[str, Decimal]
    in_control: dict[str, Decimal]


def _read(books: EquitiesBooks) -> _BookView:
    customer_cash: dict[str, Decimal] = {}
    customer_positions: dict[str, dict[str, Decimal]] = {}
    issue_positions: dict[str, Decimal] = {}
    control_balances: dict[str, Decimal] = {}
    for entry in books.entries:
        for line in entry.lines:
            customer = line.account_type in CUSTOMER_TYPES
            if customer and line.record_side is RecordSide.MONEY and line.currency == "USD":
                customer_cash[line.account_id] = (
                    customer_cash.get(line.account_id, ZERO) + line.money
                )
            if line.issue is None:
                continue
            if line.record_side is RecordSide.OWNERSHIP:
                issue_positions[line.issue] = issue_positions.get(line.issue, ZERO) + line.quantity
                if customer:
                    held = customer_positions.setdefault(line.account_id, {})
                    held[line.issue] = held.get(line.issue, ZERO) + line.quantity
            elif line.record_side is RecordSide.LOCATION and line.account_type in CONTROL_TYPES:
                control_balances[line.issue] = (
                    control_balances.get(line.issue, ZERO) + line.quantity
                )
    return _BookView(
        customer_cash=customer_cash,
        customer_positions=customer_positions,
        issue_positions=issue_positions,
        # A long street position is recorded as a negative location balance.
        in_control={issue: abs(balance) for issue, balance in control_balances.items()},
    )


@dataclass(frozen=True, slots=True)
class ControlRequirement:
    required: dict[str, Decimal]
    in_control: dict[str, Decimal]
    short_issues: tuple[str, ...]

    @property
    def outcome(self) -> str:
        return "HOLD" if self.short_issues else "PASS"


def required_control(
    books: EquitiesBooks, prices: dict[str, Decimal], table: RuleTable
) -> ControlRequirement | None:
    """Rule 15c3-3(b)(1) and (d): fully paid plus excess margin securities must be in control."""
    threshold = _value(table, EXCESS_MARGIN_THRESHOLD)
    if threshold is None:
        return None
    view = _read(books)
    required: dict[str, Decimal] = {}
    for account_id, held in view.customer_positions.items():
        longs = {issue: quantity for issue, quantity in held.items() if quantity > 0}
        if not longs:
            continue
        debit = max(-view.customer_cash.get(account_id, ZERO), ZERO)
        if debit == 0:
            for issue, quantity in longs.items():
                required[issue] = required.get(issue, ZERO) + quantity
            continue
        if any(issue not in prices for issue in longs):
            return None
        long_value = sum((quantity * prices[issue] for issue, quantity in longs.items()), ZERO)
        excess_value = max(long_value - threshold * debit, ZERO)
        share = ZERO if long_value <= 0 else excess_value / long_value
        for issue, quantity in longs.items():
            excess = min(quantity, (quantity * share).to_integral_value(rounding=ROUND_CEILING))
            required[issue] = required.get(issue, ZERO) + excess
    short = tuple(
        sorted(
            issue
            for issue, quantity in required.items()
            if quantity > view.in_control.get(issue, ZERO)
        )
    )
    return ControlRequirement(required=required, in_control=view.in_control, short_issues=short)


@dataclass(frozen=True, slots=True)
class CapitalRequirement:
    net_capital: Decimal
    minimum: Decimal
    reasons: tuple[str, ...]

    @property
    def outcome(self) -> str:
        return "HOLD" if self.reasons else "PASS"


def required_net_capital(
    books: EquitiesBooks,
    prices: dict[str, Decimal],
    net_worth: Decimal,
    table: RuleTable,
) -> CapitalRequirement | None:
    """Rule 15c3-1 alternative standard for a carrying equities firm, from the books."""
    rate = _value(table, EQUITY_RATE)
    lesser = _value(table, EQUITY_LESSER_THRESHOLD)
    excess_rate = _value(table, EQUITY_EXCESS_RATE)
    floor = _value(table, ALT_FLOOR)
    percent = _value(table, ALT_PERCENT)
    activity = _value(table, CARRYING_MINIMUM)
    warn_alt = _value(table, WARN_ALT)
    warn_minimum = _value(table, WARN_MINIMUM)
    values = (rate, lesser, excess_rate, floor, percent, activity, warn_alt, warn_minimum)
    if any(value is None for value in values):
        return None
    assert rate is not None and lesser is not None and excess_rate is not None
    assert floor is not None and percent is not None and activity is not None
    assert warn_alt is not None and warn_minimum is not None
    view = _read(books)
    haircuts = ZERO
    for issue, quantity in view.issue_positions.items():
        if not quantity:
            continue
        if issue not in prices:
            return None
        long_value = max(quantity, ZERO) * prices[issue]
        short_value = max(-quantity, ZERO) * prices[issue]
        greater = max(long_value, short_value)
        smaller = min(long_value, short_value)
        haircuts += rate * greater + excess_rate * max(smaller - lesser * greater, ZERO)
    net_capital = net_worth - haircuts
    debits = sum((max(-cash, ZERO) for cash in view.customer_cash.values()), ZERO)
    ratio = max(floor, percent * debits)
    minimum = max(ratio, activity)
    reasons: list[str] = []
    if net_capital < activity:
        reasons.append("net capital is below the Rule 15c3-1(a)(2) carrying minimum")
    if net_capital < ratio:
        reasons.append("net capital is below the Rule 15c3-1(a)(1)(ii) requirement")
    if net_capital < warn_alt * debits:
        reasons.append("Rule 17a-11(b)(2) early warning")
    if net_capital < warn_minimum * minimum:
        reasons.append("Rule 17a-11(b)(3) early warning")
    return CapitalRequirement(net_capital=net_capital, minimum=minimum, reasons=tuple(reasons))
