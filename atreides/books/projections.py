"""Versioned, synthetic projections from the equities books into existing engines."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from atreides.books.ledger import AccountType, EquitiesBooks, RecordSide, ReserveActivity
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
from atreides.deadlines.calendar import MarketCalendar
from atreides.margin.engine import MarginAccount, MarginPosition, MarginResult


class SyntheticFirmProfile(BaseModel):
    """Declared elections for the synthetic broker-dealer used in publications."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_name: str
    synthetic: Literal[True] = True
    net_capital_standard: NetCapitalStandard
    broker_dealer_category: BrokerDealerCategory


SYNTHETIC_FIRM_PROFILE = SyntheticFirmProfile(
    profile_name="ATREIDES_EQ1_SYNTHETIC_CARRYING_ALTERNATIVE",
    net_capital_standard=NetCapitalStandard.ALTERNATIVE,
    broker_dealer_category=BrokerDealerCategory.CARRYING,
)

# 17 CFR 240.15c3-3a, Exhibit A, quoted from the pinned source beside the
# projection that implements each line.
EXHIBIT_A_PARAGRAPHS = {
    "15c3-3a.item.01": (
        "Free credit balances and other credit balances in customers' security accounts."
    ),
    "15c3-3a.item.04": "Customers' securities failed to receive",
    "15c3-3a.item.10": (
        "Debit balances in customers' cash and margin accounts excluding unsecured accounts "
        "and accounts doubtful of collection."
    ),
    "15c3-3a.item.11": (
        "Securities borrowed to effectuate short sales by customers and securities borrowed "
        "to make delivery on customers' securities failed to deliver"
    ),
    "15c3-3a.item.12": (
        "Failed to deliver of customers' securities not older than 30 calendar days"
    ),
}


class ProjectionExclusion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_event_id: str
    account_type: AccountType
    issue: str
    activity: ReserveActivity
    reason: str
    age_calendar_days: int | None = None


class ProjectionAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mapping_version: str
    derived: tuple[str, ...]
    not_derived: tuple[str, ...]
    reasons: dict[str, str]
    books_digest: str
    review_label: Literal["FINOP review required"] = "FINOP review required"
    exclusions: tuple[ProjectionExclusion, ...] = ()
    derived_values: dict[str, Decimal] = Field(default_factory=dict)
    synthetic_firm_profile: str


class ProtectionInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reserve: ReserveInputs
    pab_reserve: ReserveInputs
    net_capital: NetCapitalInputs
    control: ControlInputs
    audit: ProjectionAudit
    firm_profile: SyntheticFirmProfile


def _mapping() -> dict[str, object]:
    path = Path(__file__).with_name("exhibit_a_mapping.json")
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def project_customer_protection(  # noqa: PLR0915 - each projection source remains explicit
    books: EquitiesBooks,
    *,
    as_of: date,
    prices: dict[str, Decimal],
    net_worth: Decimal,
    calendar: MarketCalendar,
    margin_results: tuple[MarginResult, ...],
    firm_profile: SyntheticFirmProfile = SYNTHETIC_FIRM_PROFILE,
) -> ProtectionInputs:
    """Build all three engine inputs from the same journal replay."""
    mapping = _mapping()
    customer_lines: dict[str, Decimal | None] = {
        rule_id: None for rule_id in (*EXHIBIT_A_CREDITS, *EXHIBIT_A_DEBITS)
    }
    pab_lines = customer_lines.copy()
    customer_cash: dict[str, Decimal] = {}
    positions: dict[str, Decimal] = {}
    # Location lines are journal movements. Aggregate their signed balances before
    # taking the holding magnitude; summing ``abs(line.quantity)`` over history
    # double-counts every movement and can manufacture a control break.
    location_balances: dict[tuple[str, str], Decimal] = {}
    ownership: dict[str, Decimal] = {}
    customer_positions: dict[str, dict[str, Decimal]] = {}
    stock_loaned_market_value = Decimal(0)
    stock_borrowed_contract_value = Decimal(0)
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
                if line.account_type in {
                    AccountType.CUSTOMER_CASH,
                    AccountType.CUSTOMER_MARGIN,
                }:
                    by_issue = customer_positions.setdefault(line.account_id, {})
                    by_issue[line.issue] = by_issue.get(line.issue, Decimal(0)) + line.quantity
            if line.issue is not None and line.record_side is RecordSide.LOCATION:
                location_rule = {
                    AccountType.DTC: "15c3-3.control.c1",
                    AccountType.BANK_CONTROL: "15c3-3.control.c5",
                    AccountType.FAIL_TO_DELIVER: "15c3-3.noncontrol.d2",
                    AccountType.STOCK_LOANED: "15c3-3.noncontrol.d1",
                    AccountType.IN_TRANSFER: "15c3-3.noncontrol.d4",
                }.get(line.account_type, "UNMAPPED_LOCATION")
                key = (line.issue, location_rule)
                location_balances[key] = location_balances.get(key, Decimal(0)) + line.quantity
    holdings: dict[str, list[Holding]] = {}
    for (issue, location), balance in location_balances.items():
        if balance:
            holdings.setdefault(issue, []).append(
                Holding(location=location, quantity=abs(balance))
            )
    customer_debits = sum(
        (max(-balance, Decimal(0)) for balance in customer_cash.values()), Decimal(0)
    )
    free_credits = sum((max(balance, Decimal(0)) for balance in customer_cash.values()), Decimal(0))
    exclusions: list[ProjectionExclusion] = []
    special_rule = {
        AccountType.FAIL_TO_RECEIVE: str(mapping["customer_fail_to_receive_rule_id"]),
        AccountType.STOCK_BORROWED: str(mapping["customer_stock_borrowed_rule_id"]),
        AccountType.FAIL_TO_DELIVER: str(mapping["customer_fail_to_deliver_rule_id"]),
    }

    def add_line(target: dict[str, Decimal | None], rule_id: str, amount: Decimal) -> None:
        target[rule_id] = (target[rule_id] or Decimal(0)) + amount

    for entry in books.entries:
        source_facts = {
            (fact.account_type, fact.issue): fact for fact in entry.reserve_source_facts
        }
        for line in entry.lines:
            if line.issue is None or line.account_type not in special_rule:
                continue
            fact = source_facts[(line.account_type, line.issue)]
            if not calendar.is_business_day(fact.settlement_date):
                raise ValueError("reserve source settlement date must be a loaded business day")
            age = (as_of - fact.settlement_date).days
            if age < 0:
                raise ValueError("reserve source settlement date cannot be after the computation")
            contract_value = abs(line.quantity) * fact.contract_price
            if line.account_type is AccountType.STOCK_BORROWED:
                stock_borrowed_contract_value += contract_value
            if line.account_type is AccountType.FAIL_TO_DELIVER and age > 30:
                exclusions.append(
                    ProjectionExclusion(
                        source_event_id=entry.source_event_id,
                        account_type=line.account_type,
                        issue=line.issue,
                        activity=fact.activity,
                        reason="fail to deliver older than 30 calendar days excluded from item 12",
                        age_calendar_days=age,
                    )
                )
                continue
            value = contract_value
            if line.account_type is AccountType.FAIL_TO_RECEIVE and age > 30:
                market_value = abs(line.quantity) * prices[line.issue]
                value += max(market_value - contract_value, Decimal(0))
            target = (
                customer_lines
                if fact.activity is ReserveActivity.CUSTOMER
                else pab_lines
                if fact.activity is ReserveActivity.PAB
                else None
            )
            if target is None:
                exclusions.append(
                    ProjectionExclusion(
                        source_event_id=entry.source_event_id,
                        account_type=line.account_type,
                        issue=line.issue,
                        activity=fact.activity,
                        reason="firm proprietary activity is outside customer and PAB computations",
                        age_calendar_days=age,
                    )
                )
                continue
            add_line(target, special_rule[line.account_type], value)
    for entry in books.entries:
        for line in entry.lines:
            if line.account_type is AccountType.STOCK_LOANED and line.issue is not None:
                stock_loaned_market_value += abs(line.quantity) * prices[line.issue]
    customer_lines[str(mapping["customer_free_credit_rule_id"])] = free_credits
    customer_lines[str(mapping["customer_margin_debit_rule_id"])] = customer_debits
    derived = tuple(
        sorted(rule_id for rule_id, value in customer_lines.items() if value is not None)
    )
    not_derived = tuple(
        sorted(rule_id for rule_id, value in customer_lines.items() if value is None)
    )
    reasons = {
        rule_id: "not derivable from currently wired equities sources" for rule_id in not_derived
    }
    reasons.update(
        {
            "17a-11.reports_lending_activity_monthly": (
                "the books do not state whether the firm files monthly lending reports"
            ),
            "17a-11.securities_loaned_and_repo_payable": (
                "stock-loan value is derived, but repo payable is not wired to the equities books"
            ),
            "17a-11.securities_borrowed_and_reverse_repo_value": (
                "stock-borrow value is derived, but reverse-repo value is not wired to the "
                "equities books"
            ),
        }
    )
    reserve = ReserveInputs(
        accounts=ReserveAccounts.CUSTOMER,
        as_of=as_of,
        standard=firm_profile.net_capital_standard,
        mode=ComputationMode.WEEKLY,
        lines=tuple(
            LineBalance(rule_id=key, amount=value) for key, value in customer_lines.items()
        ),
        average_total_credits=None,
        qualified_securities_deposit=None,
    )
    pab_reserve = ReserveInputs(
        accounts=ReserveAccounts.PAB,
        as_of=as_of,
        standard=firm_profile.net_capital_standard,
        mode=ComputationMode.WEEKLY,
        lines=tuple(LineBalance(rule_id=key, amount=value) for key, value in pab_lines.items()),
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
        standard=firm_profile.net_capital_standard,
        category=firm_profile.broker_dealer_category,
        net_worth=net_worth,
        positions=net_positions,
        aggregate_debit_items=customer_debits,
        reports_lending_activity_monthly=None,
        # The equities journal can value the securities component, but it has no
        # authoritative repo/reverse-repo source. The combined Rule 17a-11 inputs
        # therefore remain absent instead of silently treating the missing leg as zero.
        securities_loaned_and_repo_payable=None,
        securities_borrowed_and_reverse_repo_value=None,
    )
    margin_by_account = {result.account_id: result for result in margin_results}
    fully_paid_by_issue: dict[str, Decimal] = {}
    excess_margin_by_issue: dict[str, Decimal | None] = {}
    for account_id, by_issue in customer_positions.items():
        result = margin_by_account.get(account_id)
        for issue, quantity in by_issue.items():
            if quantity <= 0:
                continue
            if result is None:
                excess_margin_by_issue[issue] = None
                reasons[f"15c3-3.excess_margin[{issue}]"] = (
                    f"margin result for account {account_id} is absent"
                )
            elif result.debit_balance == 0:
                fully_paid_by_issue[issue] = fully_paid_by_issue.get(issue, Decimal(0)) + quantity
            else:
                # The margin engine computes money requirements, not the security
                # quantity that is "excess margin" under Rule 15c3-3. Do not invent it.
                excess_margin_by_issue[issue] = None
                reasons[f"15c3-3.excess_margin[{issue}]"] = (
                    "the margin result computes money requirements but not excess-margin "
                    "security quantity"
                )
    control = ControlInputs(
        as_of=as_of,
        issues=tuple(
            IssueRequirement(
                issue=issue,
                fully_paid=fully_paid_by_issue.get(issue, Decimal(0)),
                excess_margin=excess_margin_by_issue.get(issue, Decimal(0)),
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
        exclusions=tuple(exclusions),
        derived_values={
            "stock_loaned_market_value": stock_loaned_market_value,
            "stock_borrowed_contract_value": stock_borrowed_contract_value,
        },
        synthetic_firm_profile=firm_profile.profile_name,
    )
    return ProtectionInputs(
        reserve=reserve,
        pab_reserve=pab_reserve,
        net_capital=net_capital,
        control=control,
        audit=audit,
        firm_profile=firm_profile,
    )


def reserve_bank_balances(books: EquitiesBooks, *, through: date) -> dict[AccountType, Decimal]:
    """Cash in each reserve bank account, from entries effective on or before ``through``.

    SIM-1G. 17 CFR 240.15c3-3(e)(3)(i)(A): "the deposit so computed must be made no
    later than one hour after the opening of banking business on the second following
    business day." The caller passes that deadline as ``through``, so a deposit
    effective after it does not count toward the computation it was made for. Only
    USD money lines on the two reserve bank account types are read.
    """
    balances = {
        AccountType.RESERVE_BANK_CUSTOMER: Decimal(0),
        AccountType.RESERVE_BANK_PAB: Decimal(0),
    }
    for entry in books.entries:
        if entry.effective_date > through:
            continue
        for line in entry.lines:
            if line.account_type in balances and line.currency == "USD":
                balances[line.account_type] += line.money
    return balances


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
