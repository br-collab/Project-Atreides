"""Independent synthetic DTC, CNS fail and stock-loan source production.

The public source builders accept only seed positions, CNS outcomes and declared
instructions. They never accept the books or values projected from the books.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True, slots=True)
class StreetMovement:
    issue: str
    location: str
    quantity: Decimal
    source: str


@dataclass(frozen=True, slots=True)
class DepositoryPosition:
    issue: str
    location: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class SettlementOutcome:
    issue: str
    net_quantity: Decimal
    allocated_quantity: Decimal
    settlement_date: date


@dataclass(frozen=True, slots=True)
class OpenFail:
    fail_id: str
    issue: str
    quantity: Decimal
    cash: Decimal
    opening_settlement_date: date
    contract_price: Decimal


@dataclass(frozen=True, slots=True)
class LoanInstruction:
    instruction_id: str
    issue: str
    quantity: Decimal
    effective_date: date


@dataclass(frozen=True, slots=True)
class PositionSource:
    name: str
    location: str
    as_of: date
    positions: tuple[DepositoryPosition, ...]


@dataclass(frozen=True, slots=True)
class IndependentSourceInputs:
    """Non-book inputs sufficient to reproduce every street source at a close."""

    as_of: date
    opening_depository: tuple[DepositoryPosition, ...]
    settlement_outcomes: tuple[SettlementOutcome, ...]
    open_fails: tuple[OpenFail, ...]
    loan_instructions: tuple[LoanInstruction, ...]


@dataclass(frozen=True, slots=True)
class ObservedSourceReader:
    name: str
    read: Callable[[], PositionSource]


def source_reader(source: PositionSource) -> Callable[[], PositionSource]:
    """Return an observed-source reader with an explicit static type."""
    return lambda: source


class LoanRegister:
    """Declared loan events and their own open balance, independent of books."""

    def __init__(self) -> None:
        self._instructions: list[LoanInstruction] = []

    @property
    def instructions(self) -> tuple[LoanInstruction, ...]:
        return tuple(self._instructions)

    def record(self, instruction: LoanInstruction) -> None:
        self._instructions.append(instruction)

    def open_quantity(self, issue: str, as_of: date) -> Decimal:
        return sum(
            (
                instruction.quantity
                for instruction in self._instructions
                if instruction.issue == issue and instruction.effective_date <= as_of
            ),
            Decimal(),
        )

    def declare_recall(
        self, issue: str, as_of: date, instruction_id: str
    ) -> LoanInstruction | None:
        open_quantity = self.open_quantity(issue, as_of)
        if not open_quantity:
            return None
        instruction = LoanInstruction(instruction_id, issue, -open_quantity, as_of)
        self.record(instruction)
        return instruction


@dataclass(frozen=True, slots=True)
class ReconciliationCompletion:
    item_id: str
    close_date: date
    sources_read: tuple[str, ...]
    break_count: int
    status: Literal["COMPLETED", "FAILED"]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StreetBreak:
    issue: str
    location: str
    books_quantity: Decimal
    street_quantity: Decimal
    difference: Decimal
    owner: str
    opened_at: date
    age_calendar_days: int
    cause: str = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class CalendarRun:
    item_id: str
    close_date: date
    status: Literal["RAN", "FAILED", "NOT_RUN"]
    sources_read: tuple[str, ...]
    break_count: int | None
    reason: str


class SyntheticDepository:
    """DTC statement builder fed by seed positions and CNS outcomes only."""

    def __init__(self, opening: tuple[DepositoryPosition, ...]) -> None:
        if any(item.location != "DTC" for item in opening):
            raise ValueError("DEPOSITORY_SOURCE_REFUSES_NON_DTC_LOCATION")
        self._balances = {(item.issue, item.location): item.quantity for item in opening}

    def apply_settlements(self, outcomes: tuple[SettlementOutcome, ...]) -> None:
        for outcome in outcomes:
            key = (outcome.issue, "DTC")
            self._balances[key] = self._balances.get(key, Decimal()) - outcome.net_quantity

    def apply_instructions(self, instructions: tuple[LoanInstruction, ...]) -> None:
        for instruction in instructions:
            key = (instruction.issue, "DTC")
            self._balances[key] = self._balances.get(key, Decimal()) + instruction.quantity

    def source(self, as_of: date) -> PositionSource:
        return PositionSource(
            name="synthetic DTC position statement",
            location="DTC",
            as_of=as_of,
            positions=tuple(
                DepositoryPosition(issue=issue, location=location, quantity=quantity)
                for (issue, location), quantity in sorted(self._balances.items())
                if quantity
            ),
        )


def cns_fail_source(as_of: date, fails: tuple[OpenFail, ...]) -> PositionSource:
    positions = tuple(
        DepositoryPosition(fail.issue, "FAIL_TO_RECEIVE", -fail.quantity)
        for fail in sorted(fails, key=lambda item: item.fail_id)
        if fail.quantity > 0 and fail.opening_settlement_date <= as_of
    )
    return PositionSource("synthetic CNS open fail statement", "FAIL_TO_RECEIVE", as_of, positions)


def loan_register_source(
    as_of: date, instructions: tuple[LoanInstruction, ...]
) -> PositionSource:
    balances: dict[str, Decimal] = {}
    for instruction in instructions:
        if instruction.effective_date <= as_of:
            balances[instruction.issue] = (
                balances.get(instruction.issue, Decimal()) - instruction.quantity
            )
    return PositionSource(
        "synthetic stock-loan contract register",
        "STOCK_LOANED",
        as_of,
        tuple(
            DepositoryPosition(issue, "STOCK_LOANED", quantity)
            for issue, quantity in sorted(balances.items())
            if quantity
        ),
    )


def build_independent_sources(
    books_guard: object, inputs: IndependentSourceInputs
) -> tuple[PositionSource, PositionSource, PositionSource]:
    """Rebuild all street sources without reading any attribute from books_guard."""
    del books_guard
    depository = SyntheticDepository(inputs.opening_depository)
    depository.apply_settlements(inputs.settlement_outcomes)
    depository.apply_instructions(inputs.loan_instructions)
    return (
        depository.source(inputs.as_of),
        cns_fail_source(inputs.as_of, inputs.open_fails),
        loan_register_source(inputs.as_of, inputs.loan_instructions),
    )


def reconcile(
    books_positions: dict[tuple[str, str], Decimal],
    sources: tuple[PositionSource, ...],
    prior_breaks: tuple[StreetBreak, ...] = (),
    *,
    as_of: date,
    owner: str = "SCF1_SETTLEMENT_CONTROL",
    item_id: str = "stock-record-to-street",
) -> tuple[tuple[StreetBreak, ...], ReconciliationCompletion]:
    observed: dict[tuple[str, str], Decimal] = {}
    sourced_locations = {source.location for source in sources}
    for source in sources:
        if source.as_of != as_of:
            raise ValueError("SOURCE_CLOSE_DATE_MISMATCH")
        for item in source.positions:
            key = (item.issue, item.location)
            observed[key] = observed.get(key, Decimal()) + item.quantity
    opened = {(item.issue, item.location): item.opened_at for item in prior_breaks}
    breaks = []
    for issue, location in sorted(set(books_positions) | set(observed)):
        books_quantity = books_positions.get((issue, location), Decimal())
        street_quantity = observed.get((issue, location), Decimal())
        difference = books_quantity - street_quantity
        unsourced = location not in sourced_locations
        if difference or unsourced:
            opened_at = opened.get((issue, location), as_of)
            breaks.append(
                StreetBreak(
                    issue=issue,
                    location=location,
                    books_quantity=books_quantity,
                    street_quantity=street_quantity,
                    difference=difference,
                    owner=owner,
                    opened_at=opened_at,
                    age_calendar_days=(as_of - opened_at).days,
                    cause="UNSOURCED_LOCATION" if unsourced else "UNCLASSIFIED",
                )
            )
    result = tuple(breaks)
    return result, ReconciliationCompletion(
        item_id=item_id,
        close_date=as_of,
        sources_read=tuple(source.name for source in sources),
        break_count=len(result),
        status="COMPLETED",
    )


def observed_reconcile(
    books_positions: dict[tuple[str, str], Decimal],
    source_readers: tuple[ObservedSourceReader, ...],
    prior_breaks: tuple[StreetBreak, ...] = (),
    *,
    as_of: date,
    item_id: str = "stock-record-to-street",
    failure_location: str = "DTC",
) -> tuple[tuple[StreetBreak, ...], ReconciliationCompletion]:
    """Run source reads and return an observed completion or failure record."""
    source_names = ["Atreides equities books", *(reader.name for reader in source_readers)]
    try:
        sources = []
        for reader in source_readers:
            source = reader.read()
            sources.append(source)
        return reconcile(
            books_positions,
            tuple(sources),
            prior_breaks,
            as_of=as_of,
            item_id=item_id,
        )
    except Exception as error:
        failure = StreetBreak(
            issue="RECONCILIATION",
            location=failure_location,
            books_quantity=Decimal(),
            street_quantity=Decimal(),
            difference=Decimal(),
            owner="SCF1_SETTLEMENT_CONTROL",
            opened_at=as_of,
            age_calendar_days=0,
            cause="RECONCILIATION_FAILED",
        )
        return (failure,), ReconciliationCompletion(
            item_id=item_id,
            close_date=as_of,
            sources_read=tuple(source_names),
            break_count=1,
            status="FAILED",
            error=f"{type(error).__name__}: {error}",
        )


def reconciliation_calendar(
    as_of: date,
    completions: tuple[ReconciliationCompletion, ...] = (),
) -> tuple[CalendarRun, ...]:
    path = Path(__file__).with_name("reconciliation_calendar.json")
    rows = cast(list[dict[str, object]], json.loads(path.read_text(encoding="utf-8")))
    by_id = {item.item_id: item for item in completions if item.close_date == as_of}
    results = []
    for row in rows:
        item_id = str(row["id"])
        completion = by_id.get(item_id)
        if completion is None:
            results.append(CalendarRun(item_id, as_of, "NOT_RUN", (), None, "no completion record"))
        elif completion.status == "FAILED":
            results.append(
                CalendarRun(
                    item_id,
                    as_of,
                    "FAILED",
                    completion.sources_read,
                    completion.break_count,
                    completion.error or "reconciliation failed",
                )
            )
        else:
            results.append(
                CalendarRun(
                    item_id,
                    as_of,
                    "RAN",
                    completion.sources_read,
                    completion.break_count,
                    "reconciliation completed",
                )
            )
    return tuple(results)
