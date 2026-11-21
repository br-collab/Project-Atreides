"""Ongoing anti-money laundering monitoring over system-of-record events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum

from cannae_kernel.signed_attestation import (
    AttestationVerificationError,
    sign_attestation,
    verify_attestation,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atreides.trust_anchors import (
    TrustAnchorError,
    require_anchor_valid_at,
    resolve_pinned_anchor,
)

AML_OFFICER_PRODUCER = "synthetic-aml-officer"
AML_OFFICER_KEY_ID = "synthetic-aml-officer-1"
_OFFICER_SEED_LABEL = b"synthetic-aml-officer-phase-a"
SAR_DECISION_PURPOSE = "SAR_DECISION"
EXTENSION_PURPOSE = "UNIDENTIFIED_SUSPECT_EXTENSION"
_NO_SUSPECT_BASIS = "no suspect was identified on the date of initial detection"
_DECISION_CONTROL = "SAR decision attestation control"


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
    # Synthetic policy data, not a rule: an account whose trading is below this share of the
    # cash it moved counts as "no trading" for the deposit-withdrawal scenario.
    trading_share_floor: Decimal = Decimal("0.10")


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
    extension_officer: str | None = None
    extension_attestation: bytes | None = None
    extension_decided_on: date | None = None
    extension_basis: str | None = None


def unidentified_suspect_basis(detected_on: date) -> str:
    """The stated basis an extension must carry: no suspect on the detection date."""

    return f"{_NO_SUSPECT_BASIS} {detected_on.isoformat()}"


def _officer_private_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(_OFFICER_SEED_LABEL).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def sign_aml_officer_attestation(payload: Mapping[str, str]) -> bytes:
    """Sign a synthetic AML officer payload. Decision functions accept only the wire."""

    body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sign_attestation(
        body,
        producer=AML_OFFICER_PRODUCER,
        key_id=AML_OFFICER_KEY_ID,
        private_key=_officer_private_key(),
    )


def _verified_officer_bytes(wire: bytes) -> bytes:
    anchor, registry = resolve_pinned_anchor(wire, expected_producer=AML_OFFICER_PRODUCER)
    payload = verify_attestation(
        wire,
        expected_producer=AML_OFFICER_PRODUCER,
        registry=registry,
    )
    document = json.loads(payload)
    if not isinstance(document, dict) or "decided_on" not in document:
        raise ValueError(_DECISION_CONTROL)
    decided_on = date.fromisoformat(str(document["decided_on"]))
    require_anchor_valid_at(anchor, datetime.combine(decided_on, time.min, tzinfo=UTC))
    return bytes(payload)


def _decision_document(wire: bytes) -> dict[str, str]:
    try:
        payload = _verified_officer_bytes(wire)
    except (
        TrustAnchorError,
        AttestationVerificationError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(_DECISION_CONTROL) from exc
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError(_DECISION_CONTROL)
    return {str(key): str(value) for key, value in document.items()}


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
    moved = sum((item.amount for item in deposits + withdrawals), Decimal())
    traded = sum((item.amount for item in trades), Decimal())
    if deposits and withdrawals and traded < moved * policy.trading_share_floor:
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


def record_human_decision(case: AMLCase, wire: bytes) -> AMLCase:
    """Record a suspicious activity report decision read from a verified attestation.

    Phase A: neither run calls this yet. Officer, outcome, reason and date come from the
    verified payload. An unsigned or unverifiable wire is refused.
    """

    document = _decision_document(wire)
    if document.get("purpose") != SAR_DECISION_PURPOSE:
        raise ValueError(_DECISION_CONTROL)
    officer = document.get("officer", "")
    outcome = document.get("outcome", "")
    reason = document.get("reason", "")
    if not officer.startswith("HUMAN_AML_OFFICER:"):
        raise ValueError("NAMED_HUMAN_AML_OFFICER_REQUIRED")
    if outcome not in {"SAR", "NO_SAR"} or not reason:
        raise ValueError("SAR_OR_NO_SAR_WITH_REASON_REQUIRED")
    decided_on = date.fromisoformat(document["decided_on"])
    decision = AMLDecision(officer, outcome, reason, decided_on)
    draft = {"status": "DRAFT_NOT_FILED", "case_id": case.case_id} if outcome == "SAR" else None
    return replace(case, decision=decision, draft_sar=draft)


def close_case(case: AMLCase) -> AMLCase:
    if case.decision is None:
        raise ValueError("HUMAN_DECISION_REQUIRED")
    return case


def _extension_facts_present(
    case: AMLCase,
    attestation: bytes,
    decision_date: date | None,
    basis: str,
) -> bool:
    if not attestation or decision_date is None or not basis:
        return False
    if basis != unidentified_suspect_basis(case.alert.detected_on):
        return False
    try:
        payload = _verified_officer_bytes(attestation)
        document = json.loads(payload)
    except (
        TrustAnchorError,
        AttestationVerificationError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ):
        return False
    if not isinstance(document, dict):
        return False
    return bool(
        document.get("purpose") == EXTENSION_PURPOSE
        and str(document.get("officer", "")).startswith("HUMAN_AML_OFFICER:")
        and document.get("decided_on") == decision_date.isoformat()
        and document.get("basis") == basis
    )


def extend_for_unidentified_suspect(
    case: AMLCase,
    attestation: bytes,
    decision_date: date,
    basis: str,
    *,
    policy: AMLPolicy,
) -> AMLCase:
    """Use the extra period 31 CFR 1023.320(b)(3) allows when no suspect is identified.

    The filing period runs from initial detection. The extension adds ``extension_days`` and
    the outer limit is detection plus both periods (60 calendar days at the defaults).
    Phase A: no run calls this yet. The officer attestation, the decision date and the stated
    basis are recorded on the case. An extension without them, or made after day 30, is refused.
    """

    if case.extended_due_on is not None:
        raise ValueError("SAR_CLOCK_ALREADY_EXTENDED")
    if not _extension_facts_present(case, attestation, decision_date, basis):
        raise ValueError("unidentified suspect extension control")
    if decision_date > case.alert.detected_on + timedelta(days=policy.filing_days):
        raise ValueError("unidentified suspect day 30 control")
    document = json.loads(_verified_officer_bytes(attestation))
    return replace(
        case,
        extended_due_on=case.alert.detected_on
        + timedelta(days=policy.filing_days + policy.extension_days),
        extension_officer=str(document["officer"]),
        extension_attestation=attestation,
        extension_decided_on=decision_date,
        extension_basis=basis,
    )


def missed_clock_exception(case: AMLCase, *, as_of: date) -> bool:
    """The SAR clock runs to filing, not to the decision.

    A NO_SAR decision stops the clock. A SAR decision does not: the simulator never files, so
    a SAR draft past its deadline is an exception, because a real filing would be late.
    """

    deadline = case.extended_due_on or case.due_on
    if as_of <= deadline:
        return False
    return case.decision is None or case.decision.outcome == "SAR"
