"""Lifecycle and exception custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Lifecycle and Exception Handling"
— failed trade buy-in, failed trade sell-out, partial settlement,
trade cancellation, trade rebooking. These operations apply across
the asset-class universe; they are exception variants on the per-
asset-class transaction types in the sibling operation modules.

Operational specifications detail per-asset-class handling per
Section V "Architectural Implication: Comprehensive Coverage as
Doctrine Standard". The contracts layer carries the typed substrate.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class LifecycleEventType(StrEnum):
    """Lifecycle and exception event types per AUR-CUSTODY-001 v1.0
    Section V."""

    BUY_IN = "buy_in"
    """Per Section V: 'Failure to deliver securities triggers a forced
    purchase (buy-in) by the counterparty at prevailing market price,
    with the failing party bearing the cost differential.' Per CSDR
    settlement discipline regime in EU; Treasury fails charge in US."""
    SELL_OUT = "sell_out"
    """Per Section V: 'Failure to receive securities triggers a forced
    sale (sell-out) by the counterparty.' Mirror of buy-in."""
    PARTIAL_SETTLEMENT = "partial_settlement"
    """Per Section V: 'Trade partially settles when full quantity is
    unavailable.' Custody operations: partial position update,
    residual fail tracking, eventual completion or cancellation."""
    TRADE_CANCELLATION = "trade_cancellation"
    """Per Section V: 'Trade voided post-execution.' Custody operations:
    cancellation instruction processing, position reversal, cash
    reversal, regulatory reporting amendment."""
    TRADE_REBOOKING = "trade_rebooking"
    """Per Section V: 'Trade modified post-execution (counterparty
    change, quantity adjustment, price correction).' Lineage stamping
    links original and replacement."""


class LifecycleOperation(CustodyOperation):
    """Lifecycle / exception custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["lifecycle"] = "lifecycle"
    event_type: LifecycleEventType = Field(
        description="Lifecycle event type per Section V.",
    )
    original_operation_id: UUID | None = Field(
        default=None,
        description=(
            "Operation identifier of the original operation this event "
            "applies to. Required for TRADE_CANCELLATION and "
            "TRADE_REBOOKING per Section V (lineage stamping links "
            "original and replacement)."
        ),
    )
    partial_quantity: Decimal | None = Field(
        default=None,
        description=(
            "Quantity that actually settled, for PARTIAL_SETTLEMENT. "
            "The residual is tracked separately as a fail. Decimal "
            "(not float) to avoid currency/quantity rounding errors "
            "incompatible with the lineage record's bit-for-bit "
            "comparability per AUR-CANONICAL-001 v1.6 Parity Principle."
        ),
    )
    fail_reason: str | None = Field(
        default=None,
        description=(
            "Free-text reason for BUY_IN / SELL_OUT (e.g., 'failed "
            "delivery — counterparty system outage', 'recall failure'). "
            "Operational specifications structure the reason "
            "vocabulary per asset class."
        ),
    )

    @model_validator(mode="after")
    def _enforce_cancellation_and_rebooking_require_original(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section V: cancellation and
        rebooking events must reference the original operation."""
        if (
            self.event_type
            in {
                LifecycleEventType.TRADE_CANCELLATION,
                LifecycleEventType.TRADE_REBOOKING,
            }
            and self.original_operation_id is None
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section V "
                f"({self.event_type.value}), original_operation_id is "
                f"required so the lineage stamping links original and "
                f"replacement / cancellation."
            )
        return self

    @model_validator(mode="after")
    def _enforce_partial_settlement_requires_quantity(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section V: partial settlement
        requires the actually-settled quantity to be recorded so the
        residual fail can be tracked."""
        if (
            self.event_type is LifecycleEventType.PARTIAL_SETTLEMENT
            and self.partial_quantity is None
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V, PARTIAL_SETTLEMENT "
                "requires partial_quantity (the quantity that actually "
                "settled) so the residual fail can be tracked."
            )
        return self


__all__ = ["LifecycleEventType", "LifecycleOperation"]
