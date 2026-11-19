"""PS-1 dated-book projections and independent reconciliation sources.

The journal is the only store of positions, money and tax lots. External statements in this
module accept instructions and outcomes only, never ``EquitiesBooks``.

Securities-count scope follows the pinned 17 CFR 240.17a-13 source, checksum
85c88c8a834c42d508252964dd069d2099bb01a42a0d1ef8a5e6030630838f5b. Paragraphs (b)(2)
and (b)(3) require comparison of securities in transfer, in transit, pledged, loaned,
borrowed, deposited or otherwise subject to the broker-dealer's control or direction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from atreides.books.ledger import AccountType, EquitiesBooks, JournalEntry, RecordSide
from atreides.deadlines.calendar import Market, MarketCalendar

SPECIFIC_IDENTIFICATION_TIME_TEXT = (
    "For purposes of this paragraph (c), an adequate identification of stock is made at the "
    "time of sale, transfer, delivery, or distribution if the identification is made no later "
    "than the earlier of the settlement date or the time for settlement required by Rule "
    "15c6-1 under the Securities Exchange Act of 1934, 17 CFR 240.15c6-1 (or its successor). "
    "A standing order or instruction for the specific identification of stock is treated as an "
    "adequate identification made at the time of sale, transfer, delivery, or distribution."
)

TAX_LOT_RULES: tuple[dict[str, str], ...] = (
    {
        "rule": "FIFO",
        "citation": "26 CFR 1.1012-1(c)(1)(i)",
        "decision": "APPLIED",
        "source_sha256": "60c2777dd63c3c38aff9663c0912ac21fc133e6cf223546b8f3eac9418b97d2e",
    },
    {
        "rule": "specific identification deadline",
        "citation": "26 CFR 1.1012-1(c)(8)",
        "decision": "APPLIED_FROM_SETTLEMENT_JOURNAL_ENTRY",
        "source_sha256": "60c2777dd63c3c38aff9663c0912ac21fc133e6cf223546b8f3eac9418b97d2e",
    },
    {
        "rule": "broker basis reporting",
        "citation": "26 CFR 1.6045-1(d)(2)(i)(A)",
        "decision": "LOT_BASIS_AND_GAIN_PROJECTED",
        "source_sha256": "6fd50383d0e85d4789494366c1e260d36b8fd58f445d846868d44bf521bfcac8",
    },
    {
        "rule": "wash-sale basis adjustment",
        "citation": "26 CFR 1.1091-1(a)-(d); 26 CFR 1.6045-1(d)(6)(iii)",
        "decision": "TO_VERIFY",
        "reason": "The journal has an internal issue name, not a verified CUSIP or other "
        "covered-security identifier, so it cannot deterministically apply the pinned "
        "same-account rule. No wash-sale adjustment is built.",
        "source_sha256": "4bdf7218169a95f1b4a51dce86e39e776e2afeba215427df9381adcbea3e9604",
    },
)


ACCOUNT_TREATMENT_ROWS: tuple[dict[str, str], ...] = (
    {
        "account_type": "PENDING_SETTLEMENT",
        "status": "TO_VERIFY_AGAINST_PRIMARY_TEXT",
        "citation": "17 CFR 240.15c3-3(a)(8)-(10); 17 CFR 240.15c3-3a Item 1",
        "quote": "Free credit balances and other credit balances in customers' security accounts.",
        "open_question": "The pinned text classifies customer cash liabilities, but does not "
        "name a pending-settlement securities location account.",
    },
    {
        "account_type": "CLEARING_PAYABLE",
        "status": "TO_VERIFY_AGAINST_PRIMARY_TEXT",
        "citation": "17 CFR 240.15c3-3a Item 3 and Note C",
        "quote": "Monies payable against customers' securities loaned",
        "open_question": "The pinned payable text is specific to securities loaned and does not "
        "settle placement of an ordinary purchase settlement payable.",
    },
    {
        "account_type": "CLEARING_RECEIVABLE",
        "status": "TO_VERIFY_AGAINST_PRIMARY_TEXT",
        "citation": "17 CFR 240.15c3-3a Item 4 and Note D",
        "quote": "Customers' securities failed to receive",
        "open_question": "The pinned receivable text addresses failed securities, not the "
        "ordinary pre-settlement receivable created by a trade.",
    },
)


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


class InstructionLog:
    """Append-only outside instruction record that has no books dependency."""

    def __init__(self) -> None:
        self._instructions: list[MoneyInstruction] = []
        self._ids: set[str] = set()

    @property
    def instructions(self) -> tuple[MoneyInstruction, ...]:
        return tuple(self._instructions)

    def append(self, instruction: MoneyInstruction) -> None:
        if instruction.instruction_id in self._ids:
            raise ValueError("DUPLICATE_OUTSIDE_INSTRUCTION")
        self._ids.add(instruction.instruction_id)
        self._instructions.append(instruction)

    def statement(
        self,
        name: str,
        as_of: date,
        *,
        kinds: frozenset[InstructionKind],
        account_ids: frozenset[str] | None = None,
    ) -> ExternalMoneyStatement:
        return build_money_statement(
            name,
            tuple(
                item
                for item in self._instructions
                if item.kind in kinds and (account_ids is None or item.account_id in account_ids)
            ),
            as_of,
        )


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

    @property
    def name(self) -> str:
        return "synthetic depository and other-location confirmations"


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
    cause: str


@dataclass(frozen=True, slots=True)
class ControlResult:
    item_id: str
    status: str
    breaks: tuple[ControlBreak, ...]
    sources_read: tuple[str, ...]


def _calendar_owner(item_id: str) -> str:
    path = Path(__file__).parents[2] / "simulator/reconciliation_calendar.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    row = next((item for item in rows if item["id"] == item_id), None)
    if row is None:
        raise ValueError(f"UNKNOWN_RECONCILIATION_CONTROL: {item_id}")
    return str(row["owner_role"])


def _compare(
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
            missing_instruction = not sources_read
            cause = (
                "TIMING"
                if previous is not None and previous.opened_at < as_of
                else "MISSING_INSTRUCTION"
                if missing_instruction
                else "QUANTITY_DIFFERENCE"
                if difference != 0
                else "UNKNOWN"
            )
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
                    cause,
                )
            )
    return ControlResult(item_id, "FAILED" if breaks else "COMPLETED", tuple(breaks), sources_read)


def reconcile(
    item_id: str,
    books: EquitiesBooks,
    outside_source: ExternalMoneyStatement | SecuritiesCount,
    as_of: date,
    *,
    prior_breaks: tuple[ControlBreak, ...] = (),
) -> ControlResult:
    """Build both comparison sides and record the sources actually read."""
    if outside_source.as_of != as_of:
        raise ValueError("OUTSIDE_SOURCE_CLOSE_DATE_MISMATCH")
    owner = _calendar_owner(item_id)
    if item_id == "cash-to-bank" and isinstance(outside_source, ExternalMoneyStatement):
        books_values = book_money_balances(
            books, as_of, frozenset({AccountType.CASH, AccountType.BANK_CONTROL})
        )
        outside_values = outside_source.balances
    elif item_id == "reserve-bank-to-books" and isinstance(outside_source, ExternalMoneyStatement):
        books_values = book_money_balances(
            books,
            as_of,
            frozenset({AccountType.RESERVE_BANK_CUSTOMER, AccountType.RESERVE_BANK_PAB}),
        )
        outside_values = outside_source.balances
    elif item_id == "securities-count" and isinstance(outside_source, SecuritiesCount):
        books_values = book_location_balances(books, as_of)
        outside_values = {
            f"{issue}@{location}": quantity
            for (issue, location), quantity in outside_source.positions.items()
        }
    else:
        raise TypeError(f"OUTSIDE_SOURCE_TYPE_MISMATCH: {item_id}")
    outside_evidence = (
        outside_source.received_instruction_ids
        if isinstance(outside_source, ExternalMoneyStatement)
        else outside_source.confirmation_ids
    )
    if books_values and not outside_evidence:
        raise ValueError(f"{item_id}: EMPTY_OUTSIDE_SOURCE_WITH_BOOK_BALANCE")
    return _compare(
        item_id=item_id,
        books_values=books_values,
        outside_values=outside_values,
        owner=owner,
        as_of=as_of,
        prior_breaks=prior_breaks,
        sources_read=("Atreides equities books", outside_source.name),
    )


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
    recorded_at: datetime


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
) -> tuple[tuple[TaxLot, ...], tuple[LotRelief, ...]]:
    """Replay journal facts under pinned FIFO and identification-timing rules.

    See ``TAX_LOT_RULES``. Wash-sale adjustment remains explicitly ``TO_VERIFY`` because the
    journal does not contain the covered-security identifier required by the pinned broker rule.
    This declared-synthetic projection is not tax advice.
    """
    lots: list[TaxLot] = []
    relief: list[LotRelief] = []
    election_by_sale = {item.sale_entry_id: item for item in elections}
    settlement_times = {
        entry.settles_entry_id: entry.posting.effective_time
        for entry in entries
        if entry.settles_entry_id is not None
    }
    for entry in sorted(entries, key=lambda item: (item.effective_date, item.entry_id)):
        if entry.settles_entry_id is not None:
            continue
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
                if line.account_id == account_id and line.record_side is RecordSide.MONEY
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
            if election is not None:
                contractual_date = MarketCalendar.load(Market.US_EQUITIES).add_business_days(
                    entry.effective_date, 1
                )
                required_time = datetime.combine(contractual_date, time.max, tzinfo=UTC)
                actual_time = settlement_times.get(entry.entry_id)
                deadline = min(actual_time, required_time) if actual_time else required_time
                if election.recorded_at > deadline:
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
