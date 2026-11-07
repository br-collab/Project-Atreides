"""Synthetic account transfers driven by the real ACATS deadline engine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest_bytes
from cannae_kernel.ids import ActorId

from atreides.account_lifecycle import (
    AccountLifecycleStore,
    ActorRegistryApproverVerifier,
    FirstPermittedTradeRecord,
    KYCDecisionReference,
    TransferInRecord,
)
from atreides.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
)
from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
)
from atreides.deadlines.acats import AcatsTransfer, assess_acats
from atreides.deadlines.calendar import Market, MarketCalendar
from simulator.conversion import STATEMENT, StatementLine, _posting

TransferVariant = Literal["clean", "reject", "partial-residual", "late"]
TRANSFER_VARIANTS: tuple[TransferVariant, ...] = (
    "clean",
    "reject",
    "partial-residual",
    "late",
)
FINRA_LICENSE_GATE = "INDETERMINATE"


def _lifecycle_actor() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01K00000000000000000000000"),
        actor_kind=ActorKind.HUMAN,
        role="synthetic transfer approver",
        entitlement_refs=("SIM-1-ACATS",),
        authenticated=True,
    )


def _approval_evidence(at: datetime) -> tuple[KYCDecisionReference, EligibilityVerification]:
    payload = '{"path_id":"KYC_ELIGIBLE_CLEAR"}'
    return (
        KYCDecisionReference(
            record_id="SIM-1-KYC",
            path_id="KYC_ELIGIBLE_CLEAR",
            decided_at=at,
            maximum_age_seconds=300,
            payload=payload,
            payload_digest=digest_bytes(payload.encode()),
        ),
        EligibilityVerification(
            checks=tuple(
                EligibilityCheck(kind=kind, passed=True, verified_at=at)
                for kind in EligibilityCheckKind
            )
        ),
    )


@dataclass(frozen=True)
class TransferPolicy:
    """Declared synthetic rates, not results inferred from the engine."""

    reject_rate: Decimal
    partial_rate: Decimal
    residual_sweep_rate: Decimal


@dataclass(frozen=True)
class TransferClose:
    transfer_id: str
    account: str
    disposition: str
    reasons: tuple[str, ...]
    posted_quantity: Decimal
    posted_cash: Decimal
    i10_migration_conserved: bool | None
    i10_reason: str
    lifecycle_status: str
    exception_owner: str | None


POLICIES = {
    "clean": TransferPolicy(Decimal("0"), Decimal("0"), Decimal("0")),
    "reject": TransferPolicy(Decimal("1"), Decimal("0"), Decimal("0")),
    "partial-residual": TransferPolicy(Decimal("0"), Decimal("1"), Decimal("1")),
    "late": TransferPolicy(Decimal("0"), Decimal("0"), Decimal("0")),
}


def _post_transfer(
    books: EquitiesBooks,
    line: StatementLine,
    *,
    transfer_id: str,
    sequence: int,
    quantity: Decimal,
    cash: Decimal,
    day: date,
) -> None:
    event = 720_000_000 + sequence
    lines: list[LedgerLine] = []
    if quantity:
        lines.extend(
            (
                LedgerLine(
                    account_id=line.account,
                    account_type=AccountType.CUSTOMER_CASH,
                    record_side=RecordSide.OWNERSHIP,
                    issue=line.issue,
                    quantity=quantity,
                ),
                LedgerLine(
                    account_id="SYN-DTC",
                    account_type=AccountType.DTC,
                    record_side=RecordSide.LOCATION,
                    issue=line.issue,
                    quantity=-quantity,
                ),
            )
        )
    if cash:
        lines.extend(
            (
                LedgerLine(
                    account_id=line.account,
                    account_type=AccountType.CUSTOMER_CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=cash,
                ),
                LedgerLine(
                    account_id="SYN-CONVERSION-FUNDING",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-cash,
                ),
            )
        )
    if not lines:
        return
    books.post(
        JournalEntry(
            entry_id=f"{transfer_id}-{sequence}",
            source_event_id=f"evt_{event:026d}",
            source=PostingSource.CASH_MOVEMENT,
            effective_date=day,
            effective_date_basis="VALUE_DATE",
            authority="CONV-2_SYNTHETIC_ACCOUNT_TRANSFER",
            synthetic=True,
            lines=tuple(lines),
            posting=_posting(event, day),
        )
    )


def _account_totals(books: EquitiesBooks, line: StatementLine) -> tuple[Decimal, Decimal]:
    quantity = Decimal()
    cash = Decimal()
    for entry in books.entries:
        for posted in entry.lines:
            if (
                posted.account_id != line.account
                or posted.account_type is not AccountType.CUSTOMER_CASH
            ):
                continue
            if posted.record_side is RecordSide.OWNERSHIP and posted.issue == line.issue:
                quantity += posted.quantity
            if posted.record_side is RecordSide.MONEY and posted.currency == "USD":
                cash += posted.money
    return quantity, cash


def run_account_transfers(  # noqa: PLR0915
    variant: TransferVariant, *, mutation: Literal["drop-residual"] | None = None
) -> dict[str, object]:
    """Run transfers; all deadline dispositions come from ``assess_acats``.

    FINRA Rule 11870(b)(1) and (e) are identified by number/title only here.
    Reproduction permission was not established, so the legal-source gate stays
    INDETERMINATE even when the already-pinned deadline engine can be exercised.
    """
    if variant not in TRANSFER_VARIANTS:
        raise ValueError(f"unknown transfer variant: {variant}")
    policy = POLICIES[variant]
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    instruction_at = datetime(2026, 10, 1, 14, tzinfo=UTC)
    validation_at = datetime(2026, 10, 2, 14, tzinfo=UTC)
    evaluated_at = datetime(2026, 10, 9 if variant == "late" else 5, 14, tzinfo=UTC)
    books = EquitiesBooks(break_owner="CONV_2_TRANSFER_OPS")
    closes: list[TransferClose] = []
    lifecycle_actor = _lifecycle_actor()
    lifecycle = AccountLifecycleStore(
        ActorRegistryApproverVerifier({str(lifecycle_actor.actor_id): lifecycle_actor})
    )

    for index, line in enumerate(STATEMENT, 1):
        transfer_id = f"SYN-ACATS-{index:04d}"
        kyc_evidence, eligibility = _approval_evidence(instruction_at)
        lifecycle.apply(line.account)
        lifecycle.transition(
            line.account,
            AccountStatus.APPROVED,
            actor=lifecycle_actor,
            timestamp=instruction_at,
            reason="synthetic account approved before transfer",
            evidence_refs=(kyc_evidence.record_id, "SIM-1-ELIGIBILITY", "SIM-1-HUMAN"),
            kyc_evidence=kyc_evidence,
            eligibility=eligibility,
            human_approval_ref="SIM-1-HUMAN",
        )
        assessment = assess_acats(
            AcatsTransfer(
                transfer_id=transfer_id,
                instruction_at=instruction_at,
                validation_at=validation_at,
            ),
            evaluated_at=evaluated_at,
            calendar=calendar,
        )
        rejected = policy.reject_rate == Decimal("1")
        if not rejected:
            if policy.partial_rate == Decimal("1"):
                main_quantity = (line.quantity * Decimal("0.61")).quantize(Decimal("1"))
                main_cash = (line.cash_credit * Decimal("0.61")).quantize(Decimal("0.01"))
                _post_transfer(
                    books,
                    line,
                    transfer_id=transfer_id,
                    sequence=index * 10,
                    quantity=main_quantity,
                    cash=main_cash,
                    day=date(2026, 10, 5),
                )
                if policy.residual_sweep_rate == Decimal("1") and mutation != "drop-residual":
                    _post_transfer(
                        books,
                        line,
                        transfer_id=transfer_id,
                        sequence=index * 10 + 1,
                        quantity=line.quantity - main_quantity,
                        cash=line.cash_credit - main_cash,
                        day=date(2026, 10, 6),
                    )
            else:
                _post_transfer(
                    books,
                    line,
                    transfer_id=transfer_id,
                    sequence=index * 10,
                    quantity=line.quantity,
                    cash=line.cash_credit,
                    day=date(2026, 10, 5),
                )
        quantity, cash = _account_totals(books, line)
        reasons = list(assessment.breaches)
        if rejected:
            reasons.append("declared synthetic reject")
            invariant: bool | None = None
            invariant_reason = "rejected transfer never posts; reconciliation not applicable"
        else:
            invariant = quantity == line.quantity and cash == line.cash_credit
            invariant_reason = "statement compared independently with posted share and cent totals"
        disposition = "HOLD" if reasons or rejected else assessment.disposition.value
        if variant == "clean" and invariant:
            lifecycle.transition(
                line.account,
                AccountStatus.FUNDED,
                actor=lifecycle_actor,
                timestamp=evaluated_at,
                reason="completed synthetic transfer-in",
                evidence_refs=(transfer_id,),
                transfer=TransferInRecord(
                    record_id=transfer_id, completed=True, completed_at=evaluated_at
                ),
            )
            trade_time = evaluated_at.replace(minute=evaluated_at.minute + index)
            lifecycle.transition(
                line.account,
                AccountStatus.ACTIVE,
                actor=lifecycle_actor,
                timestamp=trade_time,
                reason="first permitted synthetic L.C. trade",
                evidence_refs=(f"SYN-LC-TRADE-{index:04d}",),
                first_trade=FirstPermittedTradeRecord(
                    record_id=f"SYN-LC-TRADE-{index:04d}",
                    permitted=True,
                    traded_at=trade_time,
                ),
            )
            lifecycle_status = lifecycle.status(line.account).value
            exception_owner = None
        elif variant == "partial-residual" and invariant:
            lifecycle.transition(
                line.account,
                AccountStatus.FUNDED,
                actor=lifecycle_actor,
                timestamp=evaluated_at,
                reason="completed transfer-in with owned residual",
                evidence_refs=(transfer_id,),
                transfer=TransferInRecord(
                    record_id=transfer_id, completed=True, completed_at=evaluated_at
                ),
            )
            lifecycle_status = lifecycle.status(line.account).value
            exception_owner = "ACATS_RESIDUAL_OPERATIONS"
        else:
            lifecycle_status = "APPROVED"
            exception_owner = "ACATS_TRANSFER_OPERATIONS"
        closes.append(
            TransferClose(
                transfer_id=transfer_id,
                account=line.account,
                disposition=disposition,
                reasons=tuple(reasons),
                posted_quantity=quantity,
                posted_cash=cash,
                i10_migration_conserved=invariant,
                i10_reason=invariant_reason,
                lifecycle_status=lifecycle_status,
                exception_owner=exception_owner,
            )
        )

    return {
        "schema_version": "sim.account-transfers/1",
        "synthetic": True,
        "variant": variant,
        "declared_policy": {key: str(value) for key, value in asdict(policy).items()},
        "finra_license_gate": FINRA_LICENSE_GATE,
        "finra_claim_reason": "reproduction permission not established; existing pin retained",
        "approved_to_first_funded_trade_seconds": list(
            lifecycle.approval_to_first_funded_trade_seconds()
        ),
        "transfers": [
            {
                **asdict(close),
                "posted_quantity": str(close.posted_quantity),
                "posted_cash": str(close.posted_cash),
            }
            for close in closes
        ],
    }


def attack_account_transfers() -> dict[str, bool]:
    """Drop the residual posting, rerun, and report the resulting I10 failure."""
    attacked = run_account_transfers("partial-residual", mutation="drop-residual")
    transfers = attacked["transfers"]
    if not isinstance(transfers, list):
        raise TypeError("transfer run did not return a transfer list")
    return {
        "drop-residual": any(
            isinstance(item, dict) and item.get("i10_migration_conserved") is False
            for item in transfers
        )
    }


def publish_account_transfers(run: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "run-summary.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
