"""Synthetic clearing and settlement cycles with separate street messages."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from atreides.deadlines.calendar import MarketCalendar
from simulator.model import Movement

CENT = Decimal("0.01")

RULE_204_PARAGRAPH = (
    "17 CFR 242.204(a): by no later than the beginning of regular trading hours on "
    "the settlement day following the settlement date; paragraphs (a)(1) and (a)(3): "
    "the third consecutive settlement day for a demonstrated long sale or bona fide "
    "market making. Rule 204(b): restrict further short sales without borrowing or "
    "arranging to borrow until the close-out settles."
)


def rule_204_deadline(*, settlement_date: date, sale_kind: str, calendar: MarketCalendar) -> date:
    """Implement the pinned Rule 204 paragraph quoted above; there is no 30-day clock."""
    days = 1 if sale_kind == "SHORT" else 3
    if sale_kind not in {"SHORT", "LONG", "MARKET_MAKING"}:
        raise ValueError("sale kind must be known before a Rule 204 deadline exists")
    return calendar.add_settlement_days(settlement_date, days)


def cns_cycles(
    *, issue: str, quantity: int, mark_price: Decimal, night_capacity: int
) -> tuple[Movement, Movement]:
    night_quantity = min(quantity, night_capacity)
    day_quantity = quantity - night_quantity
    return (
        Movement(
            message_name="CNS_NIGHT_CYCLE",
            issue=issue,
            securities=night_quantity,
            money=(Decimal(night_quantity) * mark_price).quantize(CENT, rounding=ROUND_HALF_EVEN),
            status="SETTLED" if not day_quantity else "PARTIAL",
        ),
        Movement(
            message_name="CNS_DAY_CYCLE",
            issue=issue,
            securities=day_quantity,
            money=(Decimal(day_quantity) * mark_price).quantize(CENT, rounding=ROUND_HALF_EVEN),
            status="SETTLED" if day_quantity else "NONE",
        ),
    )


def gsd_messages(
    *,
    issue: str,
    quantity: int,
    principal: Decimal,
    invoice: Decimal,
    coupon: Decimal,
    mark: Decimal,
) -> tuple[Movement, Movement]:
    return (
        Movement(
            message_name="GSD_SECURITIES_NET",
            issue=issue,
            securities=quantity,
            money=principal.quantize(CENT),
            status="SETTLED",
        ),
        Movement(
            message_name="GSD_FUNDS_ONLY",
            issue=issue,
            securities=0,
            money=(invoice + coupon + mark).quantize(CENT),
            status="SETTLED",
        ),
    )


def dtc_dvp_status(
    *, issue: str, quantity: int, money: Decimal, net_debit_cap: Decimal, collateral: Decimal
) -> Movement:
    available = min(net_debit_cap, collateral)
    settled_money = money.quantize(CENT, rounding=ROUND_HALF_EVEN)
    return Movement(
        message_name="DTC_DVP_STATUS",
        issue=issue,
        securities=quantity if settled_money <= available else 0,
        money=settled_money if settled_money <= available else Decimal(0),
        status="SETTLED" if settled_money <= available else "HELD_CAP_OR_COLLATERAL",
    )


def cash_rail_movement(*, issue: str, money: Decimal) -> Movement:
    return Movement(
        message_name="CASH_RAIL_MOVEMENT",
        issue=issue,
        securities=0,
        money=money.quantize(CENT),
        status="SETTLED",
    )


def buy_in_cash_difference(
    *, quantity: int, original_price: Decimal, buy_in_price: Decimal
) -> Decimal:
    """Post the buy-in price difference as profit or loss; it never disappears."""
    return (Decimal(quantity) * (buy_in_price - original_price)).quantize(CENT)


def short_sale_restricted(*, deadline: date, close_date: date, closeout_settled: bool) -> bool:
    """Rule 204(b), quoted in ``RULE_204_PARAGRAPH``, binds until close-out settles."""
    return close_date >= deadline and not closeout_settled
