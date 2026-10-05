"""Entitlement arithmetic for the deterministic event classes (ORDER SC-1, WP-2).

EXPERIMENTAL (charter section 18.6). A computation, not a book of record, and
never a statement that anyone has been paid.

WHAT IS COMPUTED
----------------
Three classes, where the announcement states the arithmetic and it is
unambiguous:

- cash dividend: the eligible balance times the cash rate per share, in the
  announced currency;
- stock dividend: the eligible balance times the additional shares per share;
- split: the additional shares a forward split distributes, the eligible
  balance times ``(new - old) / old`` for a split announced as ``new`` for
  ``old``.

Every other class, and a split that does not increase the position, is
INDETERMINATE by name. The basis is the eligible balance of the depository's
own record-date vocabulary (:class:`~atreides.rails.cns.RecordDatePosition`).

WHAT IS REFUSED, AND WHY
------------------------
Where depository guidance states a condition but not its treatment, no number
is returned for the holder concerned, and the reason is typed
(:class:`UnavailableTreatment`):

- the eligible and settled balances diverge, or a delivery or receipt is
  pending, across the record date. The guidance carries both sides and does
  not say who is owed what (see
  :func:`~atreides.rails.cns.absent_entitlement_treatment`);
- a share distribution would leave a fraction of a share. Whether that is paid
  as cash in lieu, rounded, or something else is not stated;
- the holder is short.

NO ROUNDING
-----------
Every quantity is exact. Arithmetic runs on rational numbers, and a cash
amount is reported to as many places as the rate and the balance produce,
because the announcement does not state the payment's rounding convention and
choosing one would be inventing it. Totals that do not terminate as decimals,
which a split such as 4-for-3 can produce, are kept as exact fractions.

CONSERVATION
------------
``allocated_total + residual == event_total`` exactly, where ``event_total``
is the factor times every eligible balance given, ``allocated_total`` sums
the holders who received a number, and ``residual`` is the quantity
attributable to the holders who did not. Nothing is lost and nothing is made.

DISPOSITION
-----------
The Atreides advisory convention
(:func:`~atreides.customer_protection.common.decide`): a treatment or a term
the evidence does not supply is INDETERMINATE when it is a gap in the rules,
and HOLD when it is a missing input such as an unstated rate. PASS means only
that every holder received a number from stated terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Literal

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import BeforeValidator, field_validator, model_validator

from atreides.corporate_actions.events import CorporateActionEvent, EventType
from atreides.customer_protection.common import Frozen, decide
from atreides.customer_protection.rules.model import CLAIM_LABEL
from atreides.rails.cns import RecordDatePosition, absent_entitlement_treatment

__all__ = [
    "COMPUTED_EVENT_TYPES",
    "EntitlementResult",
    "HolderEntitlement",
    "HolderPosition",
    "UnavailableTreatment",
    "compute_entitlements",
]

ZERO = Fraction(0)

#: The classes whose arithmetic this module computes.
COMPUTED_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.CASH_DIVIDEND, EventType.STOCK_DIVIDEND, EventType.SPLIT}
)


def _no_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("an exact quantity cannot be a binary float")
    return value


#: An exact rational quantity. Serialises as ``"p/q"``; a binary float is refused.
ExactFraction = Annotated[Fraction, BeforeValidator(_no_float)]


class UnavailableTreatment(StrEnum):
    """Why a holder received no number."""

    RECORD_DATE_DIVERGENCE = "record_date_divergence"
    """Eligible and settled balances differ across the record date. Guidance states the
    condition, not who is owed what."""
    PENDING_DELIVERY_OR_RECEIPT = "pending_delivery_or_receipt"
    """A fail short or fail long is open across the record date. Due bills and claims are
    not stated."""
    FRACTIONAL_SHARES = "fractional_shares"
    """The distribution leaves a fraction of a share, and its treatment is not stated."""
    SHORT_POSITION = "short_position"
    """The eligible balance is negative. A short holder's obligation is not computed here."""


class HolderPosition(Frozen):
    """One account's record-date balances in the event's security."""

    account_id: str
    position: RecordDatePosition

    @field_validator("account_id")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value:
            raise ValueError("account_id is required")
        return value

    @model_validator(mode="after")
    def _exact_balances(self) -> HolderPosition:
        for name in (
            "eligible_balance", "settlement_balance",
            "pending_delivery_balance", "pending_receipt_balance",
        ):
            value = getattr(self.position, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be a finite Decimal, not {value!r}")
        return self


class HolderEntitlement(Frozen):
    """One holder's entitlement, or why there is none."""

    account_id: str
    eligible_balance: Decimal
    #: The entitlement, exact. ``None`` where any treatment is unavailable.
    quantity: Decimal | None
    unavailable: tuple[UnavailableTreatment, ...] = ()
    explanation: str | None = None

    @model_validator(mode="after")
    def _a_number_or_a_reason(self) -> HolderEntitlement:
        if (self.quantity is None) == (not self.unavailable):
            raise ValueError("a holder has a quantity or a reason it has none, never both")
        if self.quantity is not None and self.quantity < 0:
            raise ValueError("an entitlement is never negative")
        return self


class EntitlementResult(Frozen):
    """Every holder's entitlement for one event, the totals, and the disposition."""

    engine: Literal["entitlement"] = "entitlement"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    event_id: str
    event_type: EventType
    #: What the quantities count. ``None`` where nothing was computed.
    unit: Literal["cash", "shares"] | None
    currency: str | None
    #: Entitlement per unit of eligible balance. ``None`` where nothing was computed.
    factor: ExactFraction | None
    disposition: Disposition
    holders: tuple[HolderEntitlement, ...]
    allocated_total: ExactFraction | None
    residual: ExactFraction | None
    event_total: ExactFraction | None
    #: Event-level gaps in the rules: why nothing was computed for anyone.
    unavailable_rules: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)

    @model_validator(mode="after")
    def _conserved(self) -> EntitlementResult:
        totals = (self.allocated_total, self.residual, self.event_total)
        if any(t is None for t in totals) != all(t is None for t in totals):
            raise ValueError("the totals are all stated or none is")
        if self.allocated_total is not None and self.residual is not None and (
            self.allocated_total + self.residual != self.event_total
        ):
            raise ValueError("allocated plus residual must equal the event total")
        return self


def _exact_decimal(value: Fraction) -> Decimal | None:
    """``value`` as an exact Decimal, or ``None`` where it does not terminate."""
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator, twos = denominator // 2, twos + 1
    while denominator % 5 == 0:
        denominator, fives = denominator // 5, fives + 1
    if denominator != 1:
        return None
    places = max(twos, fives)
    return Decimal(f"{value.numerator * 10**places // value.denominator}E-{places}")


def _factor(
    event: CorporateActionEvent,
) -> tuple[Fraction | None, Literal["cash", "shares"] | None, list[str], list[str]]:
    """(factor, unit, unavailable rules, missing inputs) for the event's class."""
    terms = event.terms
    if event.event_type not in COMPUTED_EVENT_TYPES:
        return None, None, [
            f"entitlement arithmetic for {event.event_type.value} is not computed here: "
            f"only cash dividend, stock dividend and forward split"
        ], []
    if event.event_type is EventType.CASH_DIVIDEND:
        if terms.cash_rate_per_share is None:
            return None, None, [], ["terms.cash_rate_per_share"]
        return Fraction(terms.cash_rate_per_share), "cash", [], []
    if event.event_type is EventType.STOCK_DIVIDEND:
        if terms.stock_rate_per_share is None:
            return None, None, [], ["terms.stock_rate_per_share"]
        return Fraction(terms.stock_rate_per_share), "shares", [], []
    if terms.split_new is None or terms.split_old is None:
        return None, None, [], ["terms.split_new", "terms.split_old"]
    if terms.split_new <= terms.split_old:
        return None, None, [
            f"a split announced as {terms.split_new} for {terms.split_old} does not "
            f"increase the position: a reverse split is not computed here"
        ], []
    return Fraction(terms.split_new - terms.split_old, terms.split_old), "shares", [], []


def _holder(
    holding: HolderPosition, factor: Fraction, unit: Literal["cash", "shares"]
) -> tuple[HolderEntitlement, Fraction]:
    """The holder's entitlement, and the exact quantity attributable to the holder."""
    position = holding.position
    attributable = factor * Fraction(position.eligible_balance)
    reasons: list[UnavailableTreatment] = []
    if position.eligible_balance < 0:
        reasons.append(UnavailableTreatment.SHORT_POSITION)
    if position.diverges:
        reasons.append(UnavailableTreatment.RECORD_DATE_DIVERGENCE)
    if position.pending_delivery_balance != 0 or position.pending_receipt_balance != 0:
        reasons.append(UnavailableTreatment.PENDING_DELIVERY_OR_RECEIPT)
    if unit == "shares" and attributable.denominator != 1:
        reasons.append(UnavailableTreatment.FRACTIONAL_SHARES)
    explanation = None
    if {
        UnavailableTreatment.RECORD_DATE_DIVERGENCE,
        UnavailableTreatment.PENDING_DELIVERY_OR_RECEIPT,
    } & set(reasons):
        explanation = absent_entitlement_treatment(position.security_id)
    quantity = None if reasons else _exact_decimal(attributable)
    return (
        HolderEntitlement(
            account_id=holding.account_id,
            eligible_balance=position.eligible_balance,
            quantity=quantity,
            unavailable=tuple(reasons),
            explanation=explanation,
        ),
        attributable,
    )


def compute_entitlements(
    event: CorporateActionEvent, holdings: Sequence[HolderPosition]
) -> EntitlementResult:
    """Every holder's entitlement for ``event``. Pure, and independent of input order.

    Raises ``ValueError`` where a holding is in another security or an account
    appears twice: those are errors in the request, not conditions of the event.
    """
    accounts = [h.account_id for h in holdings]
    if len(set(accounts)) != len(accounts):
        raise ValueError("an account appears more than once")
    for holding in holdings:
        if holding.position.security_id != event.security_id:
            raise ValueError(
                f"account {holding.account_id} holds {holding.position.security_id}, "
                f"not the event's security {event.security_id}"
            )

    factor, unit, unavailable_rules, missing = _factor(event)
    if factor is None or unit is None:
        return EntitlementResult(
            event_id=event.event_id, event_type=event.event_type, unit=None,
            currency=None, factor=None,
            disposition=decide(unavailable_rules, missing, ()),
            holders=(), allocated_total=None, residual=None, event_total=None,
            unavailable_rules=tuple(unavailable_rules), missing_inputs=tuple(missing),
        )

    holders: list[HolderEntitlement] = []
    allocated = residual = ZERO
    for holding in sorted(holdings, key=lambda h: h.account_id):
        entitlement, attributable = _holder(holding, factor, unit)
        holders.append(entitlement)
        if entitlement.quantity is None:
            residual += attributable
        else:
            allocated += attributable
    gaps = sorted({reason.value for h in holders for reason in h.unavailable})
    return EntitlementResult(
        event_id=event.event_id, event_type=event.event_type, unit=unit,
        currency=event.terms.currency if unit == "cash" else None, factor=factor,
        disposition=decide(gaps, (), ()),
        holders=tuple(holders), allocated_total=allocated, residual=residual,
        event_total=allocated + residual,
    )
