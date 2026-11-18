"""PS-1 dated-book projections and independent reconciliation sources.

The journal is the only store of positions, money and tax lots. External statements in this
module accept instructions and outcomes only, never ``EquitiesBooks``.

Securities-count scope follows the pinned 17 CFR 240.17a-13 source, checksum
85c88c8a834c42d508252964dd069d2099bb01a42a0d1ef8a5e6030630838f5b. Paragraphs (b)(2)
and (b)(3) require comparison of securities in transfer, in transit, pledged, loaned,
borrowed, deposited or otherwise subject to the broker-dealer's control or direction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from atreides.books.ledger import AccountType, EquitiesBooks, JournalEntry, RecordSide


class InstructionKind(StrEnum):
    OPENING = "OPENING"
    CNS_SETTLEMENT = "CNS_SETTLEMENT"
    CUSTOMER_DEPOSIT = "CUSTOMER_DEPOSIT"
    RESERVE_TRANSFER = "RESERVE_TRANSFER"


@dataclass(frozen=True, slots=True)
class MoneyInstruction:
    instruction_id: str
    effective_date: date
    amount: Decimal
    kind: InstructionKind
    account_id: str = "FIRM_CASH"


@dataclass(frozen=True, slots=True)
class ExternalMoneyStatement:
    name: str
    as_of: date
    balances: dict[str, Decimal]
    received_instruction_ids: tuple[str, ...]


def build_money_statement(
    name: str, instructions: tuple[MoneyInstruction, ...], as_of: date
) -> ExternalMoneyStatement:
    """Project a statement from instructions only. No books object is accepted."""
    balances: dict[str, Decimal] = {}
    received = []
    for item in instructions:
        if item.effective_date <= as_of:
            balances[item.account_id] = balances.get(item.account_id, Decimal()) + item.amount
            received.append(item.instruction_id)
    return ExternalMoneyStatement(name, as_of, balances, tuple(received))


@dataclass(frozen=True, slots=True)
class SecuritiesConfirmation:
    confirmation_id: str
    effective_date: date
    issue: str
    location: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class SecuritiesCount:
    as_of: date
    positions: dict[tuple[str, str], Decimal]
    confirmation_ids: tuple[str, ...]


def build_securities_count(
    confirmations: tuple[SecuritiesConfirmation, ...], as_of: date
) -> SecuritiesCount:
    """Build the outside count exclusively from depository and other confirmations."""
    positions: dict[tuple[str, str], Decimal] = {}
    used = []
    for item in confirmations:
        if item.effective_date <= as_of:
            key = (item.issue, item.location)
            positions[key] = positions.get(key, Decimal()) + item.quantity
            used.append(item.confirmation_id)
    return SecuritiesCount(as_of, positions, tuple(used))


@dataclass(frozen=True, slots=True)
class ControlBreak:
    item_id: str
    key: str
    books_value: Decimal
    outside_value: Decimal
    difference: Decimal
    owner: str
    opened_at: date
    age_calendar_days: int


@dataclass(frozen=True, slots=True)
class ControlResult:
    item_id: str
    status: str
    breaks: tuple[ControlBreak, ...]
    sources_read: tuple[str, ...]


def reconcile_values(
    *,
    item_id: str,
    books_values: dict[str, Decimal],
    outside_values: dict[str, Decimal],
    owner: str,
    as_of: date,
    prior_breaks: tuple[ControlBreak, ...] = (),
    sources_read: tuple[str, ...],
) -> ControlResult:
    prior = {item.key: item for item in prior_breaks if item.item_id == item_id}
    breaks = []
    for key in sorted(set(books_values) | set(outside_values)):
        books_value = books_values.get(key, Decimal())
        outside_value = outside_values.get(key, Decimal())
        difference = books_value - outside_value
        if difference:
            previous = prior.get(key)
            opened_at = previous.opened_at if previous else as_of
            breaks.append(
                ControlBreak(
                    item_id,
                    key,
                    books_value,
                    outside_value,
                    difference,
                    owner,
                    opened_at,
                    (as_of - opened_at).days,
                )
            )
    return ControlResult(item_id, "FAILED" if breaks else "COMPLETED", tuple(breaks), sources_read)


def book_money_balances(
    books: EquitiesBooks, as_of: date, account_types: frozenset[AccountType]
) -> dict[str, Decimal]:
    balances: dict[str, Decimal] = {}
    for entry in books.entries:
        if entry.effective_date > as_of:
            continue
        for line in entry.lines:
            if line.record_side is RecordSide.MONEY and line.account_type in account_types:
                balances[line.account_id] = balances.get(line.account_id, Decimal()) + line.money
    return balances


def book_location_balances(books: EquitiesBooks, as_of: date) -> dict[str, Decimal]:
    balances: dict[str, Decimal] = {}
    for entry in books.entries:
        if entry.effective_date > as_of:
            continue
        for line in entry.lines:
            if line.record_side is RecordSide.LOCATION and line.issue is not None:
                key = f"{line.issue}@{line.account_type.value}"
                balances[key] = balances.get(key, Decimal()) - line.quantity
    return balances


@dataclass(frozen=True, slots=True)
class LotElection:
    sale_entry_id: str
    lot_id: str
    recorded_at: date


@dataclass(frozen=True, slots=True)
class TaxLot:
    lot_id: str
    account_id: str
    issue: str
    acquisition_date: date
    quantity: Decimal
    remaining_quantity: Decimal
    unit_basis: Decimal
    covered: bool

    @property
    def remaining_basis(self) -> Decimal:
        return (self.remaining_quantity * self.unit_basis).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class LotRelief:
    sale_entry_id: str
    quantity: Decimal
    proceeds: Decimal
    basis: Decimal
    realized_gain: Decimal
    method: str


def project_tax_lots(
    entries: tuple[JournalEntry, ...],
    *,
    account_id: str,
    issue: str,
    elections: tuple[LotElection, ...] = (),
    settlement_dates: dict[str, date] | None = None,
) -> tuple[tuple[TaxLot, ...], tuple[LotRelief, ...]]:
    """Replay journal facts using the declared synthetic FIFO policy.

    Tax-rule pinning was unavailable during PS-1 execution. This implementation is labelled
    synthetic and not tax advice; regulatory treatment remains TO_VERIFY.
    """
    lots: list[TaxLot] = []
    relief: list[LotRelief] = []
    election_by_sale = {item.sale_entry_id: item for item in elections}
    settlement_dates = settlement_dates or {}
    for entry in sorted(entries, key=lambda item: (item.effective_date, item.entry_id)):
        ownership = sum(
            (
                line.quantity
                for line in entry.lines
                if line.account_id == account_id
                and line.issue == issue
                and line.record_side is RecordSide.OWNERSHIP
            ),
            Decimal(),
        )
        cash = sum(
            (
                line.money
                for line in entry.lines
                if line.account_id == account_id
                and line.record_side is RecordSide.MONEY
            ),
            Decimal(),
        )
        if ownership > 0:
            lots.append(
                TaxLot(
                    f"LOT-{entry.entry_id}",
                    account_id,
                    issue,
                    entry.effective_date,
                    ownership,
                    ownership,
                    (-cash / ownership).quantize(Decimal("0.0001")),
                    True,
                )
            )
        elif ownership < 0:
            needed = -ownership
            election = election_by_sale.get(entry.entry_id)
            if election is not None and election.recorded_at > settlement_dates.get(
                entry.entry_id, entry.effective_date
            ):
                raise ValueError("LATE_SPECIFIC_IDENTIFICATION_ELECTION")
            ordered = sorted(lots, key=lambda lot: (lot.acquisition_date, lot.lot_id))
            if election is not None:
                ordered.sort(key=lambda lot: lot.lot_id != election.lot_id)
            basis = Decimal()
            for lot in ordered:
                take = min(needed, lot.remaining_quantity)
                if not take:
                    continue
                basis += take * lot.unit_basis
                needed -= take
                lots[lots.index(lot)] = replace(
                    lot, remaining_quantity=lot.remaining_quantity - take
                )
                if not needed:
                    break
            if needed:
                raise ValueError("SALE_EXCEEDS_AVAILABLE_LOTS")
            proceeds = cash.quantize(Decimal("0.01"))
            basis = basis.quantize(Decimal("0.01"))
            relief.append(
                LotRelief(
                    entry.entry_id,
                    -ownership,
                    proceeds,
                    basis,
                    proceeds - basis,
                    "SPECIFIC_IDENTIFICATION" if election else "FIFO",
                )
            )
    return tuple(lots), tuple(relief)
