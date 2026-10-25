"""Synthetic account transfers driven by the real ACATS deadline engine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

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


def run_account_transfers(
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

    for index, line in enumerate(STATEMENT, 1):
        transfer_id = f"SYN-ACATS-{index:04d}"
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
            )
        )

    return {
        "schema_version": "sim.account-transfers/1",
        "synthetic": True,
        "variant": variant,
        "declared_policy": {key: str(value) for key, value in asdict(policy).items()},
        "finra_license_gate": FINRA_LICENSE_GATE,
        "finra_claim_reason": "reproduction permission not established; existing pin retained",
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
