"""Regulation T and FINRA Rule 4210 margin, with pinned-source provenance.

FINRA is a self-regulatory organization (SRO); its rulebook is not the eCFR.
Special memorandum accounts, portfolio margin, day-trading requirements,
options margin and fixed-income margin are declared, not built.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from cannae_kernel.disposition import Disposition
from pydantic import BaseModel, ConfigDict, Field

from atreides.deadlines.calendar import DeadlineCalendar


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarginPosition(_Frozen):
    issue: str = Field(min_length=1)
    quantity: Decimal
    price: Decimal = Field(gt=0)
    new_trade: bool = False


class MarginAccount(_Frozen):
    account_id: str = Field(min_length=1)
    cash_balance: Decimal
    positions: tuple[MarginPosition, ...]


class MarginCall(_Frozen):
    kind: str
    amount: Decimal
    due_date: date | None
    authority: str


class LiquidationRecommendation(_Frozen):
    advisory_only: bool = True
    positions: tuple[str, ...]
    estimated_proceeds: Decimal
    reason: str


class RuleTrace(_Frozen):
    rule_id: str
    citation: str
    source_sha256: str
    value: Decimal


class MarginResult(_Frozen):
    account_id: str
    disposition: Disposition
    long_market_value: Decimal
    short_market_value: Decimal
    debit_balance: Decimal
    credit_balance: Decimal
    equity: Decimal
    reg_t_initial_requirement: Decimal | None
    finra_maintenance_requirement: Decimal | None
    house_requirement: Decimal | None
    excess_or_deficiency: Decimal | None
    calls: tuple[MarginCall, ...]
    liquidation: LiquidationRecommendation | None
    rules_used: tuple[RuleTrace, ...]
    missing_rules: tuple[str, ...]


def _load_rules() -> tuple[dict[str, Decimal], tuple[RuleTrace, ...], tuple[str, ...]]:
    base = Path(__file__).with_name("rules")
    document = json.loads((base / "table.json").read_text(encoding="utf-8"))
    values: dict[str, Decimal] = {}
    traces: list[RuleTrace] = []
    missing: list[str] = []
    for row in document["items"]:
        source = base / "sources" / row["source_file"]
        actual = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else ""
        if actual != row["source_sha256"]:
            missing.append(row["rule_id"])
            continue
        value = Decimal(row["value"])
        values[row["rule_id"]] = value
        traces.append(
            RuleTrace(
                rule_id=row["rule_id"],
                citation=row["citation"],
                source_sha256=actual,
                value=value,
            )
        )
    return values, tuple(traces), tuple(missing)


def compute_margin(
    account: MarginAccount,
    *,
    trade_date: date,
    calendar: DeadlineCalendar,
    house_maintenance_rate: Decimal,
) -> MarginResult:
    values, traces, missing = _load_rules()
    long_value = sum(
        (
            position.quantity * position.price
            for position in account.positions
            if position.quantity > 0
        ),
        Decimal(0),
    )
    short_value = sum(
        (
            -position.quantity * position.price
            for position in account.positions
            if position.quantity < 0
        ),
        Decimal(0),
    )
    debit = max(-account.cash_balance, Decimal(0))
    credit = max(account.cash_balance, Decimal(0))
    equity = long_value + credit - short_value - debit
    required = {
        "reg_t.initial",
        "reg_t.payment_period",
        "finra.long_maintenance",
        "finra.short_under_5_percent",
        "finra.short_under_5_per_share",
        "finra.short_5_plus_percent",
        "finra.short_5_plus_per_share",
    }
    missing_required = tuple(sorted(required - values.keys()))
    all_missing = tuple(sorted(set(missing) | set(missing_required)))
    if all_missing:
        return MarginResult(
            account_id=account.account_id,
            disposition=Disposition.INDETERMINATE,
            long_market_value=long_value,
            short_market_value=short_value,
            debit_balance=debit,
            credit_balance=credit,
            equity=equity,
            reg_t_initial_requirement=None,
            finra_maintenance_requirement=None,
            house_requirement=None,
            excess_or_deficiency=None,
            calls=(),
            liquidation=None,
            rules_used=traces,
            missing_rules=all_missing,
        )
    new_long = sum(
        (p.quantity * p.price for p in account.positions if p.new_trade and p.quantity > 0),
        Decimal(0),
    )
    new_short = sum(
        (-p.quantity * p.price for p in account.positions if p.new_trade and p.quantity < 0),
        Decimal(0),
    )
    initial = (new_long + new_short) * values["reg_t.initial"]
    maintenance = long_value * values["finra.long_maintenance"]
    for position in account.positions:
        if position.quantity >= 0:
            continue
        shares = -position.quantity
        market = shares * position.price
        if position.price < Decimal(5):
            maintenance += max(
                market * values["finra.short_under_5_percent"],
                shares * values["finra.short_under_5_per_share"],
            )
        else:
            maintenance += max(
                market * values["finra.short_5_plus_percent"],
                shares * values["finra.short_5_plus_per_share"],
            )
    house = (long_value + short_value) * house_maintenance_rate
    governing = max(maintenance, house)
    deficiency = governing - equity
    calls: list[MarginCall] = []
    if initial > max(equity, Decimal(0)):
        calls.append(
            MarginCall(
                kind="REG_T",
                amount=initial - max(equity, Decimal(0)),
                due_date=calendar.add_business_days(
                    trade_date, int(values["reg_t.payment_period"])
                ),
                authority="12 CFR Part 220",
            )
        )
    if equity < maintenance:
        calls.append(
            MarginCall(
                kind="MAINTENANCE",
                amount=maintenance - equity,
                due_date=None,
                authority="FINRA Rule 4210(c)",
            )
        )
    if house > maintenance and equity < house:
        calls.append(
            MarginCall(
                kind="HOUSE",
                amount=house - equity,
                due_date=None,
                authority="INTERNAL_POLICY",
            )
        )
    liquidation = None
    if deficiency > 0:
        ordered = tuple(
            p.issue
            for p in sorted(
                account.positions, key=lambda p: abs(p.quantity * p.price), reverse=True
            )
        )
        liquidation = LiquidationRecommendation(
            positions=ordered,
            estimated_proceeds=min(long_value, deficiency),
            reason="advisory positions ordered by absolute market value to cure deficiency",
        )
    return MarginResult(
        account_id=account.account_id,
        disposition=Disposition.HOLD if deficiency > 0 else Disposition.PASS,
        long_market_value=long_value,
        short_market_value=short_value,
        debit_balance=debit,
        credit_balance=credit,
        equity=equity,
        reg_t_initial_requirement=initial,
        finra_maintenance_requirement=maintenance,
        house_requirement=house,
        excess_or_deficiency=equity - governing,
        calls=tuple(calls),
        liquidation=liquidation,
        rules_used=traces,
        missing_rules=(),
    )
