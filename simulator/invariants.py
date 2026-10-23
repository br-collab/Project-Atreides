"""Independent SIM-1B invariant comparisons over estate-produced evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class InvariantEvidence:
    venue_quantity: Decimal
    captured_quantity: Decimal
    allocated_quantity: Decimal
    books_quantity: Decimal
    street_quantity: Decimal
    venue_money: Decimal
    books_money: Decimal
    stock_break_count: int
    difference_ownership: tuple[tuple[str, int], ...]
    residuals_two_sided: bool
    holds: tuple[str, ...]
    protection_dispositions: tuple[str, ...]
    protection_figures: tuple[Decimal | None, ...]
    protection_hold_required: bool
    refusals: tuple[str, ...]
    access_events: tuple[tuple[str | None, str | None], ...]
    deadlines_are_business_days: bool
    source_digest: str
    replay_digest: str


def evaluate_invariants(evidence: InvariantEvidence) -> dict[str, bool]:
    """Compare separately produced sources; no result is supplied by a caller.

    SIM-1B §3: "Each invariant compares two sources that are computed separately."
    """
    quantity_conserves = (
        len(
            {
                evidence.venue_quantity,
                evidence.captured_quantity,
                evidence.allocated_quantity,
                evidence.books_quantity,
                evidence.street_quantity,
            }
        )
        == 1
    )
    money_conserves = evidence.venue_money == evidence.books_money
    return {
        "I1_QUANTITY_MONEY_CONSERVE": quantity_conserves and money_conserves,
        "I2_BOOKED_FROM_REPORTS": money_conserves,
        "I3_STOCK_RECORD_EQUALS_STREET": (
            evidence.stock_break_count == 0 and evidence.books_quantity == evidence.street_quantity
        ),
        "I4_EVERY_DIFFERENCE_OWNED": all(
            bool(owner) and age >= 0 for owner, age in evidence.difference_ownership
        ),
        "I5_RESIDUALS_TWO_SIDED": evidence.residuals_two_sided,
        "I6_DEFAULT_AND_STALE_HOLD": (
            all(value == "HOLD" for value in evidence.protection_dispositions)
            and all(figure is None for figure in evidence.protection_figures)
            if evidence.protection_hold_required
            else "HOLD" not in evidence.protection_dispositions
            and all(figure is not None for figure in evidence.protection_figures)
        ),
        "I7_MARKET_ACCESS_REFUSES": (
            all(expected == actual for expected, actual in evidence.access_events)
            and evidence.deadlines_are_business_days
        ),
        "I8_REPLAY_DIGEST": evidence.source_digest == evidence.replay_digest,
    }
