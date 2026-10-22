"""Versioned, synthetic projections from the equities books into existing engines."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict

from atreides.books.ledger import AccountType, EquitiesBooks, RecordSide
from atreides.customer_protection.control import ControlInputs, Holding, IssueRequirement
from atreides.customer_protection.net_capital import (
    AssetClass,
    BrokerDealerCategory,
    NetCapitalInputs,
    Position,
)
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    ComputationMode,
    LineBalance,
    NetCapitalStandard,
    ReserveAccounts,
    ReserveInputs,
)
from atreides.margin.engine import MarginAccount, MarginPosition


class ProjectionAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mapping_version: str
    derived: tuple[str, ...]
    not_derived: tuple[str, ...]
    reasons: dict[str, str]
    books_digest: str


class ProtectionInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reserve: ReserveInputs
    net_capital: NetCapitalInputs
    control: ControlInputs
    audit: ProjectionAudit


def _mapping() -> dict[str, object]:
    path = Path(__file__).with_name("exhibit_a_mapping.json")
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def project_customer_protection(
    books: EquitiesBooks,
    *,
    as_of: date,
    prices: dict[str, Decimal],
    net_worth: Decimal,
) -> ProtectionInputs:
    """Build all three engine inputs from the same journal replay."""
    mapping = _mapping()
    lines: dict[str, Decimal | None] = {
        rule_id: None for rule_id in (*EXHIBIT_A_CREDITS, *EXHIBIT_A_DEBITS)
    }
    customer_cash: dict[str, Decimal] = {}
    positions: dict[str, Decimal] = {}
    holdings: dict[str, list[Holding]] = {}
    ownership: dict[str, Decimal] = {}
    for entry in books.entries:
        for line in entry.lines:
            if (
                line.account_type
                in {
                    AccountType.CUSTOMER_CASH,
                    AccountType.CUSTOMER_MARGIN,
                }
                and line.currency == "USD"
            ):
                customer_cash[line.account_id] = (
                    customer_cash.get(line.account_id, Decimal(0)) + line.money
                )
            if line.issue is not None and line.record_side is RecordSide.OWNERSHIP:
                ownership[line.issue] = ownership.get(line.issue, Decimal(0)) + line.quantity
                positions[line.issue] = positions.get(line.issue, Decimal(0)) + line.quantity
            if line.issue is not None and line.record_side is RecordSide.LOCATION:
                location_rule = {
                    AccountType.DTC: "15c3-3.control.c1",
                    AccountType.BANK_CONTROL: "15c3-3.control.c5",
                    AccountType.FAIL_TO_DELIVER: "15c3-3.noncontrol.d2",
                    AccountType.STOCK_LOANED: "15c3-3.noncontrol.d1",
                    AccountType.IN_TRANSFER: "15c3-3.noncontrol.d4",
                }.get(line.account_type, "UNMAPPED_LOCATION")
                holdings.setdefault(line.issue, []).append(
                    Holding(location=location_rule, quantity=abs(line.quantity))
                )
    customer_debits = sum(
        (max(-balance, Decimal(0)) for balance in customer_cash.values()), Decimal(0)
    )
    free_credits = sum((max(balance, Decimal(0)) for balance in customer_cash.values()), Decimal(0))
    fail_to_receive = Decimal(0)
    stock_borrowed = Decimal(0)
    fail_to_deliver = Decimal(0)
    for entry in books.entries:
        for line in entry.lines:
            if line.issue is None:
                continue
            market_value = abs(line.quantity) * prices[line.issue]
            if line.account_type is AccountType.FAIL_TO_RECEIVE:
                fail_to_receive += market_value
            elif line.account_type is AccountType.STOCK_BORROWED:
                stock_borrowed += market_value
            elif line.account_type is AccountType.FAIL_TO_DELIVER:
                fail_to_deliver += market_value
    lines[str(mapping["customer_free_credit_rule_id"])] = free_credits
    lines[str(mapping["customer_fail_to_receive_rule_id"])] = fail_to_receive
    lines[str(mapping["customer_margin_debit_rule_id"])] = customer_debits
    lines[str(mapping["customer_stock_borrowed_rule_id"])] = stock_borrowed
    lines[str(mapping["customer_fail_to_deliver_rule_id"])] = fail_to_deliver
    derived = tuple(sorted(rule_id for rule_id, value in lines.items() if value is not None))
    not_derived = tuple(sorted(rule_id for rule_id, value in lines.items() if value is None))
    reasons = {
        rule_id: "not derivable from currently wired equities sources" for rule_id in not_derived
    }
    reserve = ReserveInputs(
        accounts=ReserveAccounts.CUSTOMER,
        as_of=as_of,
        standard=NetCapitalStandard.ALTERNATIVE,
        mode=ComputationMode.WEEKLY,
        lines=tuple(LineBalance(rule_id=key, amount=value) for key, value in lines.items()),
        average_total_credits=None,
        qualified_securities_deposit=None,
    )
    net_positions = tuple(
        Position(
            issue=issue,
            asset_class=AssetClass.EQUITY,
            long_market_value=max(quantity, Decimal(0)) * prices[issue],
            short_market_value=max(-quantity, Decimal(0)) * prices[issue],
        )
        for issue, quantity in sorted(positions.items())
    )
    net_capital = NetCapitalInputs(
        as_of=as_of,
        standard=NetCapitalStandard.ALTERNATIVE,
        category=BrokerDealerCategory.CARRYING,
        net_worth=net_worth,
        positions=net_positions,
        aggregate_debit_items=customer_debits,
        reports_lending_activity_monthly=True,
        securities_loaned_and_repo_payable=Decimal(0),
        securities_borrowed_and_reverse_repo_value=Decimal(0),
    )
    control = ControlInputs(
        as_of=as_of,
        issues=tuple(
            IssueRequirement(
                issue=issue,
                fully_paid=max(quantity, Decimal(0)),
                excess_margin=Decimal(0),
                books_total=quantity,
                holdings=tuple(holdings.get(issue, ())),
            )
            for issue, quantity in sorted(ownership.items())
        ),
    )
    audit = ProjectionAudit(
        mapping_version=str(mapping["mapping_version"]),
        derived=derived,
        not_derived=not_derived,
        reasons=reasons,
        books_digest=books.digest(),
    )
    return ProtectionInputs(reserve=reserve, net_capital=net_capital, control=control, audit=audit)


def project_margin_accounts(
    books: EquitiesBooks,
    *,
    prices: dict[str, Decimal],
    new_trades: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[MarginAccount, ...]:
    """Project customer cash and positions from one canonical journal replay."""
    cash: dict[str, Decimal] = {}
    positions: dict[str, dict[str, Decimal]] = {}
    customer_types = {AccountType.CUSTOMER_CASH, AccountType.CUSTOMER_MARGIN}
    for entry in books.entries:
        for line in entry.lines:
            if line.account_type not in customer_types:
                continue
            if line.currency == "USD":
                cash[line.account_id] = cash.get(line.account_id, Decimal(0)) + line.money
            if line.issue is not None and line.record_side is RecordSide.OWNERSHIP:
                account_positions = positions.setdefault(line.account_id, {})
                account_positions[line.issue] = (
                    account_positions.get(line.issue, Decimal(0)) + line.quantity
                )
    account_ids = sorted(set(cash) | set(positions))
    return tuple(
        MarginAccount(
            account_id=account_id,
            cash_balance=cash.get(account_id, Decimal(0)),
            positions=tuple(
                MarginPosition(
                    issue=issue,
                    quantity=quantity,
                    price=prices[issue],
                    new_trade=(account_id, issue) in new_trades,
                )
                for issue, quantity in sorted(positions.get(account_id, {}).items())
                if quantity
            ),
        )
        for account_id in account_ids
    )
