"""Deterministic price-time market used only by SIM-1.

17 CFR 242.612(b)(2), pinned in ``simulator/sources/17-CFR-242.612.txt``:
"No ... broker or dealer shall display, rank, or accept ... a bid or offer, an order,
or an indication of interest ... in an increment smaller than required."  The paragraph
governs those items, not execution prices. Tests cite the same paragraph.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from simulator.model import AssetClass, Order, Print

CENT = Decimal("0.01")


def allocate_largest_remainder(quantity: int, weights: tuple[int, ...]) -> tuple[int, ...]:
    """Allocate every share once; the stable account order breaks equal remainders."""
    if quantity < 0 or not weights or any(weight <= 0 for weight in weights):
        raise ValueError("quantity and positive account weights are required")
    total = sum(weights)
    floors = [quantity * weight // total for weight in weights]
    remainder = quantity - sum(floors)
    ranks = sorted(range(len(weights)), key=lambda i: (-(quantity * weights[i] % total), i))
    for index in ranks[:remainder]:
        floors[index] += 1
    return tuple(floors)


def treasury_consideration(
    *, asset_class: AssetClass, par: int, price: Decimal, accrued_interest: Decimal | None
) -> Decimal:
    """Round once after applying the stated Treasury basis."""
    if asset_class is AssetClass.TREASURY_NOTE:
        if accrued_interest is None:
            raise ValueError("a note requires accrued interest; missing is not zero")
        raw = Decimal(par) * price / Decimal(100) + accrued_interest
    elif asset_class is AssetClass.TREASURY_BILL:
        if accrued_interest is not None:
            raise ValueError("a bill uses discount basis and has no accrued-interest input")
        raw = Decimal(par) * price / Decimal(100)
    else:
        raise ValueError("Treasury consideration requires a Treasury asset class")
    return raw.quantize(CENT, rounding=ROUND_HALF_EVEN)


class PriceTimeBook:
    """One synthetic venue; no protected-quote or best-execution claim."""

    def __init__(self) -> None:
        self._resting: dict[Decimal, list[tuple[Order, int]]] = defaultdict(list)
        self.halted: set[str] = set()

    def rest(self, order: Order, *, size_ahead: int = 0) -> None:
        if order.issue in self.halted:
            raise ValueError("market access refused: declared synthetic halt")
        if size_ahead < 0:
            raise ValueError("size ahead cannot be negative")
        if size_ahead:
            ahead = order.model_copy(
                update={"order_id": f"AHEAD-{order.order_id}", "quantity": size_ahead}
            )
            self._resting[order.limit_price].append((ahead, size_ahead))
        self._resting[order.limit_price].append((order, order.quantity))

    def execute(
        self,
        *,
        price: Decimal,
        quantity: int,
        matched_at: datetime,
        report_delay: int = 0,
        execution_price: Decimal | None = None,
    ) -> tuple[Print, ...]:
        from datetime import timedelta

        remaining = quantity
        prints: list[Print] = []
        queue = self._resting[price]
        while queue and remaining:
            order, open_quantity = queue[0]
            filled = min(open_quantity, remaining)
            open_quantity -= filled
            remaining -= filled
            if not order.order_id.startswith("AHEAD-"):
                prints.append(
                    Print(
                        print_id=f"P-{len(prints)}-{order.order_id}",
                        order_id=order.order_id,
                        issue=order.issue,
                        quantity=filled,
                        price=execution_price if execution_price is not None else price,
                        matched_at=matched_at,
                        reported_at=matched_at + timedelta(seconds=report_delay),
                    )
                )
            if open_quantity:
                queue[0] = (order, open_quantity)
            else:
                queue.pop(0)
        return tuple(prints)

    def halt(self, issue: str, *, cancel_resting: bool) -> None:
        self.halted.add(issue)
        if cancel_resting:
            for price in tuple(self._resting):
                self._resting[price] = [(o, q) for o, q in self._resting[price] if o.issue != issue]


def auction_print(*, order: Order, clearing_price: Decimal, imbalance: int, session: str) -> Print:
    """One declared-imbalance auction adds a print without replacing the tape."""
    if session not in {"OPEN_AUCTION", "CLOSE_AUCTION"}:
        raise ValueError("auction session must be open or close")
    if abs(imbalance) >= order.quantity:
        raise ValueError("declared imbalance must be smaller than auction interest")
    return Print(
        print_id=f"{session}-{order.order_id}",
        order_id=order.order_id,
        issue=order.issue,
        quantity=order.quantity - abs(imbalance),
        price=clearing_price,
        matched_at=order.arrived_at,
        reported_at=order.arrived_at,
        session=session,
    )
