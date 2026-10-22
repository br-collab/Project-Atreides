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
    customer_debits = Decimal(0)
    positions: dict[str, Decimal] = {}
    holdings: dict[str, list[Holding]] = {}
    ownership: dict[str, Decimal] = {}
    for entry in books.entries:
        for line in entry.lines:
            if line.account_type is AccountType.CUSTOMER_MARGIN and line.currency == "USD":
                customer_debits += max(-line.money, Decimal(0))
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
    lines[str(mapping["customer_margin_debit_rule_id"])] = customer_debits
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
