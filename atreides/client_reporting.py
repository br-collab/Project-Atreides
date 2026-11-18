"""Synthetic client reports derived from immutable trade and books records."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from cannae_kernel.account import AccountStatus
from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from cannae_kernel.envelopes import ExecutionEvent
from emulators.venue import VenueExecutionReport  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from atreides.books.ledger import AccountType, EquitiesBooks, JournalEntry, RecordSide
from atreides.books.ps1 import project_tax_lots
from atreides.customer_protection.rules import load_rule_table

_REQUIREMENTS_PATH = Path(__file__).with_name("client_reporting_requirements.json")
_CONFIRMATION_TERMS_RULE = "10b-10.a1.transaction_terms"
_CONFIRMATION_NOTIFICATION_RULE = "10b-10.a.notification"


class StatementTieOutError(ValueError):
    """A draft statement did not reproduce the books."""


class ReportingProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    source_record_id: str
    rule_id: str
    citation: str
    source_file: str
    source_sha256: str
    quote: str


class ConfirmationField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    name: str
    value: str
    provenance: ReportingProvenance


class TradeConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    confirmation_id: str
    account_id: str
    trade_id: str
    book_entry_id: str
    fields: tuple[ConfirmationField, ...]
    replaces_confirmation_id: str | None = None
    correction_kind: Literal["ORIGINAL", "CORRECTION", "CANCELLATION"] = "ORIGINAL"
    correction_reason: str | None = None
    not_claimed: tuple[str, ...] = (
        "Rule 10b-10(a)(2) capacity and remuneration",
        "cost basis",
        "tax lots",
        "tax forms",
        "fee billing beyond posted books lines",
        "delivery to a real person",
    )


class FurnishedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    furnished_event_id: str
    confirmation_id: str
    furnished_at: datetime
    recipient_id: str
    channel: Literal["SYNTHETIC_PORTAL"]
    provenance: ReportingProvenance


class StatementActivity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    activity_id: str
    journal_entry_id: str
    source_event_id: str
    effective_date: date
    source: str
    account_type: str
    record_side: str
    issue: str | None
    currency: str | None
    quantity: Decimal
    money: Decimal


class StatementDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    account_id: str
    account_status: AccountStatus
    period_start: date
    period_end: date
    opening_cash: Decimal
    closing_cash: Decimal
    opening_margin: Decimal
    closing_margin: Decimal
    opening_positions: dict[str, Decimal]
    closing_positions: dict[str, Decimal]
    cost_basis: dict[str, Decimal] = Field(default_factory=dict)
    unrealized_gain_loss: dict[str, Decimal | None] = Field(default_factory=dict)
    settlement_status: dict[str, str] = Field(default_factory=dict)
    tax_disclaimer: str = "Synthetic illustration only; not tax advice"
    activity: tuple[StatementActivity, ...]
    replaces_statement_id: str | None = None


class AccountStatement(StatementDraft):
    statement_id: str
    issued_at: datetime
    finra_requirements: tuple[dict[str, str], ...]
    not_claimed: tuple[str, ...] = (
        "FINRA Rule 2231 compliance",
        "tax forms",
        "fee billing beyond posted books lines",
        "delivery to a real person",
    )


class CustomerSideFacts(BaseModel):
    """Independent expected customer balances from instructions, fills and confirmations."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    deposit_instructions: tuple[Decimal, ...]
    venue_fills: tuple[tuple[str, Decimal, Decimal], ...]
    confirmations: tuple[tuple[str, Decimal], ...]


def _rule_provenance(rule_id: str, source_record_id: str) -> ReportingProvenance:
    rule = load_rule_table().get(rule_id)
    if rule is None:
        raise ValueError(f"pinned reporting rule is unavailable: {rule_id}")
    return ReportingProvenance(
        source_record_id=source_record_id,
        rule_id=rule.id,
        citation=rule.citation,
        source_file=rule.source_file,
        source_sha256=rule.sha256,
        quote=rule.quote,
    )


def generate_trade_confirmation(
    *,
    account_id: str,
    book_entry: JournalEntry,
    execution_event: ExecutionEvent,
    execution_report: VenueExecutionReport,
    replaces: TradeConfirmation | None = None,
    correction_kind: Literal["ORIGINAL", "CORRECTION", "CANCELLATION"] = "ORIGINAL",
    correction_reason: str | None = None,
) -> TradeConfirmation:
    """Build a confirmation from the execution and its posted books entry."""
    ownership = tuple(
        line
        for line in book_entry.lines
        if line.account_id == account_id and line.record_side is RecordSide.OWNERSHIP
    )
    if len(ownership) != 1 or abs(ownership[0].quantity) != execution_report.quantity:
        raise ValueError("trade confirmation does not match the posted customer position")
    if execution_event.payload_digest != digest_bytes(canonical_bytes_of(execution_report)):
        raise ValueError("execution event does not attest the supplied execution report")
    book_money = sum(
        (
            line.money
            for line in book_entry.lines
            if line.account_id == account_id and line.record_side is RecordSide.MONEY
        ),
        Decimal(),
    )
    reported_consideration = (execution_report.quantity * execution_report.price).quantize(
        Decimal("0.01")
    )
    if abs(book_money) != reported_consideration:
        raise ValueError("trade confirmation consideration does not match the posted books money")
    issue = ownership[0].issue
    if issue is None:
        raise ValueError("posted customer position does not identify its security")
    side = "BUY" if ownership[0].quantity > 0 else "SELL"
    trade_id = execution_report.execution_id
    executed_at = execution_event.times.event_time
    quantity = execution_report.quantity
    price = execution_report.price
    if correction_kind == "ORIGINAL" and replaces is not None:
        raise ValueError("an original confirmation cannot replace another confirmation")
    if correction_kind != "ORIGINAL" and replaces is None:
        raise ValueError("a correction or cancellation must reference its original")
    source_id = trade_id
    values = (
        ("transaction_date", executed_at.date().isoformat()),
        ("transaction_time", executed_at.astimezone(UTC).time().isoformat()),
        ("security_identity", issue),
        ("side", side),
        ("price", str(price)),
        ("quantity", str(quantity)),
    )
    fields = tuple(
        ConfirmationField(
            name=name,
            value=value,
            provenance=_rule_provenance(_CONFIRMATION_TERMS_RULE, source_id),
        )
        for name, value in values
    )
    identity = digest_bytes(
        canonical_bytes_of(
            {
                "trade_id": trade_id,
                "book_entry_id": book_entry.entry_id,
                "replaces": None if replaces is None else replaces.confirmation_id,
                "kind": correction_kind,
                "reason": correction_reason,
                "fields": [item.model_dump(mode="json") for item in fields],
            }
        )
    )
    return TradeConfirmation(
        confirmation_id=f"CONF-{identity.removeprefix('sha256:')[:24]}",
        account_id=account_id,
        trade_id=trade_id,
        book_entry_id=book_entry.entry_id,
        fields=fields,
        replaces_confirmation_id=None if replaces is None else replaces.confirmation_id,
        correction_kind=correction_kind,
        correction_reason=correction_reason,
    )


def find_book_entry_for_execution(
    books: EquitiesBooks, execution_event: ExecutionEvent
) -> JournalEntry:
    """Resolve the posting by the execution identifier recorded on the books."""
    matches = tuple(
        entry
        for entry in books.entries
        if entry.source_event_id == str(execution_event.event_id)
    )
    if len(matches) != 1:
        raise ValueError("execution does not link to exactly one posted books entry")
    return matches[0]


def record_furnished(
    confirmation: TradeConfirmation,
    *,
    furnished_at: datetime,
    recipient_id: str,
) -> FurnishedEvent:
    identity = digest_bytes(
        canonical_bytes_of(
            {
                "confirmation_id": confirmation.confirmation_id,
                "furnished_at": furnished_at,
                "recipient_id": recipient_id,
                "channel": "SYNTHETIC_PORTAL",
            }
        )
    )
    return FurnishedEvent(
        furnished_event_id=f"FURN-{identity.removeprefix('sha256:')[:24]}",
        confirmation_id=confirmation.confirmation_id,
        furnished_at=furnished_at,
        recipient_id=recipient_id,
        channel="SYNTHETIC_PORTAL",
        provenance=_rule_provenance(
            _CONFIRMATION_NOTIFICATION_RULE, confirmation.confirmation_id
        ),
    )


def _balances(
    entries: tuple[JournalEntry, ...], account_id: str, through: date
) -> tuple[Decimal, Decimal, dict[str, Decimal]]:
    cash = Decimal()
    margin = Decimal()
    positions: dict[str, Decimal] = {}
    for entry in entries:
        if entry.effective_date > through:
            continue
        for line in entry.lines:
            if line.account_id != account_id:
                continue
            if line.record_side is RecordSide.MONEY:
                if line.account_type is AccountType.CUSTOMER_CASH:
                    cash += line.money
                elif line.account_type is AccountType.CUSTOMER_MARGIN:
                    margin += line.money
            elif line.record_side is RecordSide.OWNERSHIP and line.issue is not None:
                positions[line.issue] = positions.get(line.issue, Decimal()) + line.quantity
    return cash, margin, {
        issue: quantity for issue, quantity in positions.items() if quantity
    }


def _journal_oracle_balances(
    entries: tuple[JournalEntry, ...], account_id: str, through: date
) -> tuple[Decimal, Decimal, dict[str, Decimal]]:
    """Independently total raw journal lines for statement issuance."""
    money = {AccountType.CUSTOMER_CASH: Decimal(), AccountType.CUSTOMER_MARGIN: Decimal()}
    positions: dict[str, Decimal] = {}
    for entry in entries:
        if entry.effective_date > through:
            continue
        for line in entry.lines:
            if line.account_id != account_id:
                continue
            if line.record_side is RecordSide.MONEY and line.account_type in money:
                money[line.account_type] += line.money
            if line.record_side is RecordSide.OWNERSHIP and line.issue is not None:
                positions[line.issue] = positions.get(line.issue, Decimal()) + line.quantity
    return (
        money[AccountType.CUSTOMER_CASH],
        money[AccountType.CUSTOMER_MARGIN],
        {issue: quantity for issue, quantity in positions.items() if quantity},
    )


def build_statement_draft(
    books: EquitiesBooks,
    *,
    account_id: str,
    account_status: AccountStatus,
    period_start: date,
    period_end: date,
    replaces: AccountStatement | None = None,
    market_prices: dict[str, Decimal] | None = None,
) -> StatementDraft:
    if period_end < period_start:
        raise ValueError("statement period end precedes its start")
    entries = books.entries
    opening_cash, opening_margin, opening_positions = _balances(
        entries, account_id, period_start.fromordinal(period_start.toordinal() - 1)
    )
    closing_cash, closing_margin, closing_positions = _balances(
        entries, account_id, period_end
    )
    activity: list[StatementActivity] = []
    for entry in entries:
        if not period_start <= entry.effective_date <= period_end:
            continue
        for index, line in enumerate(entry.lines):
            if line.account_id != account_id:
                continue
            activity.append(
                StatementActivity(
                    activity_id=f"{entry.entry_id}:{index}",
                    journal_entry_id=entry.entry_id,
                    source_event_id=entry.source_event_id,
                    effective_date=entry.effective_date,
                    source=entry.source.value,
                    account_type=line.account_type.value,
                    record_side=line.record_side.value,
                    issue=line.issue,
                    currency=line.currency,
                    quantity=line.quantity,
                    money=line.money,
                )
            )
    cost_basis: dict[str, Decimal] = {}
    for issue in closing_positions:
        lots, _ = project_tax_lots(entries, account_id=account_id, issue=issue)
        cost_basis[issue] = sum((lot.remaining_basis for lot in lots), Decimal())
    pending_by_issue: dict[str, Decimal] = {}
    for entry in entries:
        if entry.effective_date > period_end:
            continue
        for line in entry.lines:
            if (
                line.record_side is RecordSide.LOCATION
                and line.account_type is AccountType.PENDING_SETTLEMENT
                and line.issue is not None
            ):
                pending_by_issue[line.issue] = (
                    pending_by_issue.get(line.issue, Decimal()) - line.quantity
                )
    return StatementDraft(
        account_id=account_id,
        account_status=account_status,
        period_start=period_start,
        period_end=period_end,
        opening_cash=opening_cash,
        closing_cash=closing_cash,
        opening_margin=opening_margin,
        closing_margin=closing_margin,
        opening_positions=opening_positions,
        closing_positions=closing_positions,
        cost_basis=cost_basis,
        unrealized_gain_loss={
            issue: None
            if market_prices is None or issue not in market_prices
            else closing_positions[issue] * market_prices[issue] - cost_basis[issue]
            for issue in closing_positions
        },
        settlement_status={
            issue: "UNSETTLED" if pending_by_issue.get(issue) else "SETTLED"
            for issue in closing_positions
        },
        activity=tuple(activity),
        replaces_statement_id=None if replaces is None else replaces.statement_id,
    )


def issue_statement(
    draft: StatementDraft,
    books: EquitiesBooks,
    *,
    issued_at: datetime,
    customer_side_facts: CustomerSideFacts | None = None,
) -> AccountStatement:
    entries = books.entries
    if customer_side_facts is None:
        expected_cash, expected_margin, expected_positions = _journal_oracle_balances(
            entries, draft.account_id, draft.period_end
        )
    else:
        expected_cash = sum(customer_side_facts.deposit_instructions, Decimal()) - sum(
            (quantity * price for _, quantity, price in customer_side_facts.venue_fills), Decimal()
        )
        expected_positions = {}
        for issue, quantity in customer_side_facts.confirmations:
            expected_positions[issue] = expected_positions.get(issue, Decimal()) + quantity
        expected_positions = {
            issue: quantity for issue, quantity in expected_positions.items() if quantity
        }
        expected_margin = Decimal()
    activity_cash = sum(
        (
            item.money
            for item in draft.activity
            if item.account_type == AccountType.CUSTOMER_CASH.value
        ),
        Decimal(),
    )
    activity_margin = sum(
        (
            item.money
            for item in draft.activity
            if item.account_type == AccountType.CUSTOMER_MARGIN.value
        ),
        Decimal(),
    )
    activity_positions: dict[str, Decimal] = {}
    for item in draft.activity:
        if item.issue is not None and item.record_side == RecordSide.OWNERSHIP.value:
            activity_positions[item.issue] = (
                activity_positions.get(item.issue, Decimal()) + item.quantity
            )
    issues = set(draft.opening_positions) | set(draft.closing_positions) | set(activity_positions)
    positions_tie = all(
        draft.opening_positions.get(issue, Decimal())
        + activity_positions.get(issue, Decimal())
        == draft.closing_positions.get(issue, Decimal())
        for issue in issues
    )
    if (
        draft.opening_cash + activity_cash != draft.closing_cash
        or draft.opening_margin + activity_margin != draft.closing_margin
        or not positions_tie
        or draft.closing_cash != expected_cash
        or draft.closing_margin != expected_margin
        or draft.closing_positions != expected_positions
    ):
        raise StatementTieOutError("statement refused because it does not tie to the books")
    requirements = json.loads(_REQUIREMENTS_PATH.read_text(encoding="utf-8"))["requirements"]
    identity = digest_bytes(canonical_bytes_of(draft.model_dump(mode="json")))
    return AccountStatement(
        **draft.model_dump(),
        statement_id=f"STMT-{identity.removeprefix('sha256:')[:24]}",
        issued_at=issued_at,
        finra_requirements=tuple(requirements),
    )


__all__ = [
    "AccountStatement",
    "ConfirmationField",
    "FurnishedEvent",
    "StatementActivity",
    "StatementDraft",
    "StatementTieOutError",
    "TradeConfirmation",
    "build_statement_draft",
    "find_book_entry_for_execution",
    "generate_trade_confirmation",
    "issue_statement",
    "record_furnished",
]
