"""What a depository says it will move, or has moved, for one account (ORDER SC-1, WP-4).

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

A :class:`MovementReport` is one movement preliminary advice (the depository's
statement of what it expects to move) or one movement confirmation (what it
posted), for one account and one option, in the depository's own vocabulary:
the eligible balance, the confirmed balance, the pending delivery balance
(fails short), the pending receipt balance (fails long) and the settlement
position. It is the evidence an entitlement is reconciled against.

It holds what the message says and asserts nothing about whether that is
right. Who said it is carried as two fields, as everywhere in this package:
the kind of claim (``FACT_EXTERNAL`` from DTC, ``FACT_SYNTHETIC`` from the
synthetic adapter) and the source.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from cannae_kernel.provenance import Provenance
from pydantic import Field, field_validator, model_validator

from atreides.corporate_actions.events import (
    EVENT_FACT_PROVENANCE,
    EventType,
    OptionType,
    Participation,
    SourceIdentity,
)
from atreides.customer_protection.common import Frozen, Money, NonNegativeMoney

__all__ = [
    "CashMovement",
    "MovementBalances",
    "MovementReport",
    "SecuritiesMovement",
]

#: ISO 6166 shape: two letters, nine letters or digits, one check digit.
ISIN_PATTERN = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"


class MovementBalances(Frozen):
    """Balances as the depository reports them. Signed: negative is short. ``None`` is absent."""

    eligible_balance: Money | None = None
    #: Movement confirmation only: the balance the movement was confirmed against.
    confirmed_balance: Money | None = None
    #: Fails short.
    pending_delivery_balance: Money | None = None
    #: Fails long.
    pending_receipt_balance: Money | None = None
    settlement_position_balance: Money | None = None


class CashMovement(Frozen):
    """A cash amount moved, or to be moved."""

    movement_type: Literal["cash"] = "cash"
    amount: NonNegativeMoney
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class SecuritiesMovement(Frozen):
    """A quantity of securities moved, or to be moved."""

    movement_type: Literal["securities"] = "securities"
    security_id: str = Field(pattern=ISIN_PATTERN)
    quantity: NonNegativeMoney


Movement = Annotated[CashMovement | SecuritiesMovement, Field(discriminator="movement_type")]


class MovementReport(Frozen):
    """One movement advice or confirmation, for one account and one option."""

    stage: Literal["preliminary_advice", "confirmation"]
    event_id: str = Field(min_length=1)
    event_type: EventType
    #: Carried by a preliminary advice. A confirmation does not state it.
    participation: Participation | None = None
    security_id: str = Field(pattern=ISIN_PATTERN)
    account_id: str = Field(min_length=1)
    option_id: str = Field(pattern=r"^[0-9]{3}$")
    option_type: OptionType
    #: Advice only: whether this is the event's default option.
    default_option: bool | None = None
    balances: MovementBalances
    movement: Movement
    direction: Literal["credit", "debit"]
    #: The payment date for an advice, the posting date for a confirmation.
    movement_date: date
    provenance: Provenance
    source: SourceIdentity

    @field_validator("provenance")
    @classmethod
    def _a_fact(cls, value: Provenance) -> Provenance:
        if value not in EVENT_FACT_PROVENANCE:
            raise ValueError(
                "a movement report is a reported fact: FACT_EXTERNAL or FACT_SYNTHETIC, "
                f"not {value}"
            )
        return value

    @model_validator(mode="after")
    def _fits_its_stage(self) -> MovementReport:
        advice = self.stage == "preliminary_advice"
        if advice and (self.participation is None or self.default_option is None):
            raise ValueError("a preliminary advice states participation and the default option")
        if not advice and (self.participation is not None or self.default_option is not None):
            raise ValueError("a confirmation does not state participation or the default option")
        if not advice and self.balances.confirmed_balance is None:
            raise ValueError("a confirmation states the confirmed balance")
        if advice and self.balances.confirmed_balance is not None:
            raise ValueError("a preliminary advice has no confirmed balance")
        return self

    @property
    def quantity(self) -> Decimal:
        """The amount or quantity moved, whichever this movement carries."""
        if isinstance(self.movement, CashMovement):
            return self.movement.amount
        return self.movement.quantity
