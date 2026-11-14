"""Independent synthetic depository statements and stock-record reconciliation.

This module deliberately has no dependency on the Atreides books package. The caller
supplies primitive settlement and depository movements, plus a separately projected
books position map at the comparison boundary.
"""

from __future__ import annotations

import json
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
class SyntheticDepositoryStatement:
    as_of: date
    positions: tuple[DepositoryPosition, ...]


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
    cause: Literal["UNCLASSIFIED"] = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class CalendarRun:
    item_id: str
    status: Literal["RAN", "NOT_RUN"]
    reason: str


class SyntheticDepository:
    """Mutable statement builder fed only by declared street-side movements."""

    def __init__(self, opening: tuple[DepositoryPosition, ...]) -> None:
        self._balances = {(item.issue, item.location): item.quantity for item in opening}

    def apply(self, movements: tuple[StreetMovement, ...]) -> None:
        for movement in movements:
            key = (movement.issue, movement.location)
            self._balances[key] = self._balances.get(key, Decimal()) + movement.quantity

    def statement(self, as_of: date) -> SyntheticDepositoryStatement:
        return SyntheticDepositoryStatement(
            as_of=as_of,
            positions=tuple(
                DepositoryPosition(issue=issue, location=location, quantity=quantity)
                for (issue, location), quantity in sorted(self._balances.items())
                if quantity
            ),
        )


def reconcile(
    books_positions: dict[tuple[str, str], Decimal],
    statement: SyntheticDepositoryStatement,
    prior_breaks: tuple[StreetBreak, ...] = (),
    *,
    owner: str = "SCF1_SETTLEMENT_CONTROL",
) -> tuple[StreetBreak, ...]:
    street = {(item.issue, item.location): item.quantity for item in statement.positions}
    opened = {(item.issue, item.location): item.opened_at for item in prior_breaks}
    breaks = []
    for issue, location in sorted(set(books_positions) | set(street)):
        books_quantity = books_positions.get((issue, location), Decimal())
        street_quantity = street.get((issue, location), Decimal())
        difference = books_quantity - street_quantity
        if difference:
            opened_at = opened.get((issue, location), statement.as_of)
            breaks.append(
                StreetBreak(
                    issue=issue,
                    location=location,
                    books_quantity=books_quantity,
                    street_quantity=street_quantity,
                    difference=difference,
                    owner=owner,
                    opened_at=opened_at,
                    age_calendar_days=(statement.as_of - opened_at).days,
                )
            )
    return tuple(breaks)


def reconciliation_calendar(as_of: date) -> tuple[CalendarRun, ...]:
    """Report the declared calendar item that ran and all items not run."""
    path = Path(__file__).with_name("reconciliation_calendar.json")
    rows = cast(list[dict[str, object]], json.loads(path.read_text(encoding="utf-8")))
    del as_of
    return tuple(
        CalendarRun(
            item_id=str(row["id"]),
            status="RAN" if row["id"] == "stock-record-to-street" else "NOT_RUN",
            reason=(
                "daily stock-record comparison completed"
                if row["id"] == "stock-record-to-street"
                else "source pair is outside this order"
            ),
        )
        for row in rows
    )
