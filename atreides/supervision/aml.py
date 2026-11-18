"""Ongoing anti-money laundering monitoring over system-of-record events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum


class EventKind(StrEnum):
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    TRADE = "TRADE"
    TRANSFER = "TRANSFER"
    SECURITY_DEPOSIT = "SECURITY_DEPOSIT"
    SECURITY_SALE = "SECURITY_SALE"


@dataclass(frozen=True, slots=True)
class MonitoringEvent:
    event_id: str
    customer_id: str
    kind: EventKind
    occurred_on: date
    amount: Decimal
    related_customer_id: str | None = None
    beneficial_owner_id: str | None = None
    security_id: str | None = None


@dataclass(frozen=True, slots=True)
class AMLPolicy:
    movement_threshold: Decimal = Decimal("10000")
    fast_sale_days: int = 5
    filing_days: int = 30
    extension_days: int = 30


@dataclass(frozen=True, slots=True)
class Alert:
    alert_id: str
    customer_id: str
    scenario: str
    detected_on: date
    source_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AMLDecision:
    officer: str
    outcome: str
    reason: str
    decided_on: date


@dataclass(frozen=True, slots=True)
class AMLCase:
    case_id: str
    alert: Alert
    due_on: date
    extended_due_on: date | None = None
    advisory_narrative: str | None = None
    decision: AMLDecision | None = None
    draft_sar: dict[str, str] | None = None


def _alert(customer: str, scenario: str, events: tuple[MonitoringEvent, ...]) -> Alert:
    detection = max(item.occurred_on for item in events)
    return Alert(
        f"ALERT-{customer}-{scenario}",
        customer,
        scenario,
        detection,
        tuple(item.event_id for item in events),
    )


def monitor(
    *,
    customer_id: str,
    books_events: tuple[MonitoringEvent, ...],
    instruction_events: tuple[MonitoringEvent, ...],
    policy: AMLPolicy,
) -> tuple[AMLCase, ...]:
    events = tuple(
        sorted(
            (item for item in books_events + instruction_events if item.customer_id == customer_id),
            key=lambda item: (item.occurred_on, item.event_id),
        )
    )
    alerts: list[Alert] = []
    deposits = [item for item in events if item.kind is EventKind.CASH_DEPOSIT]
    withdrawals = [item for item in events if item.kind is EventKind.CASH_WITHDRAWAL]
    trades = [item for item in events if item.kind is EventKind.TRADE]
    if deposits and withdrawals and not trades:
        moved = sum((item.amount for item in deposits + withdrawals), Decimal())
        if moved >= policy.movement_threshold:
            alerts.append(
                _alert(
                    customer_id,
                    "DEPOSIT_WITHDRAWAL_NO_TRADING",
                    (deposits[0], withdrawals[-1]),
                )
            )
    unrelated = [
        item
        for item in events
        if item.kind is EventKind.TRANSFER
        and item.related_customer_id
        and item.beneficial_owner_id != item.related_customer_id
        and item.amount >= policy.movement_threshold
    ]
    if unrelated:
        alerts.append(_alert(customer_id, "UNRELATED_ACCOUNT_TRANSFER", (unrelated[0],)))
    security_deposits = [item for item in events if item.kind is EventKind.SECURITY_DEPOSIT]
    security_sales = [item for item in events if item.kind is EventKind.SECURITY_SALE]
    for deposit in security_deposits:
        sale = next(
            (
                item
                for item in security_sales
                if item.security_id == deposit.security_id
                and timedelta()
                <= item.occurred_on - deposit.occurred_on
                <= timedelta(days=policy.fast_sale_days)
            ),
            None,
        )
        if sale is not None:
            alerts.append(_alert(customer_id, "SECURITY_DEPOSIT_FAST_SALE", (deposit, sale)))
            break
    return tuple(
        AMLCase(
            f"CASE-{item.alert_id}",
            item,
            item.detected_on + timedelta(days=policy.filing_days),
        )
        for item in alerts
    )


def record_human_decision(
    case: AMLCase,
    *,
    officer: str,
    outcome: str,
    reason: str,
    decided_on: date,
) -> AMLCase:
    if not officer.startswith("HUMAN_AML_OFFICER:"):
        raise ValueError("NAMED_HUMAN_AML_OFFICER_REQUIRED")
    if outcome not in {"SAR", "NO_SAR"} or not reason:
        raise ValueError("SAR_OR_NO_SAR_WITH_REASON_REQUIRED")
    decision = AMLDecision(officer, outcome, reason, decided_on)
    draft = (
        {"status": "DRAFT_NOT_FILED", "case_id": case.case_id}
        if outcome == "SAR"
        else None
    )
    return replace(case, decision=decision, draft_sar=draft)


def close_case(case: AMLCase) -> AMLCase:
    if case.decision is None:
        raise ValueError("HUMAN_DECISION_REQUIRED")
    return case


def missed_clock_exception(case: AMLCase, *, as_of: date) -> bool:
    deadline = case.extended_due_on or case.due_on
    return case.decision is None and as_of > deadline
