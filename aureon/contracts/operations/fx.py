"""FX (Foreign Exchange) custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "FX (Foreign Exchange)" — spot,
forward, NDF (Non-Deliverable Forward), FX swap, FX option.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class FXTransactionType(StrEnum):
    """FX transaction types per AUR-CUSTODY-001 v1.0 Section V."""

    SPOT = "spot"
    """Per Section V: T+2 for major pairs, T+1 for USD/CAD, T+0 for
    some emerging markets."""
    FORWARD = "forward"
    """FX trade settling at agreed future date."""
    NON_DELIVERABLE_FORWARD = "non_deliverable_forward"
    """Per Section V: Used for restricted-currency exposures (CNY,
    KRW, BRL, INR, others). Cash settlement of fixing-rate
    differential."""
    SWAP = "swap"
    """Combination of spot and forward in opposite directions."""
    OPTION = "option"
    """Currency option (call or put)."""


class FXOperation(CustodyOperation):
    """FX custody operation per AUR-CUSTODY-001 v1.0 Section V."""

    kind: Literal["fx"] = "fx"
    transaction_type: FXTransactionType = Field(
        description="FX transaction type per Section V.",
    )
    base_currency: str = Field(
        min_length=3,
        max_length=3,
        description=(
            "ISO 4217 base currency code (e.g., 'EUR' in EUR/USD)."
        ),
    )
    quote_currency: str = Field(
        min_length=3,
        max_length=3,
        description=(
            "ISO 4217 quote currency code (e.g., 'USD' in EUR/USD)."
        ),
    )
    value_date: date | None = Field(
        default=None,
        description=(
            "Value date (settlement date) for the FX trade. Required "
            "for FORWARD and SWAP per Section V (settling at agreed "
            "future date). For SPOT it may be left None and inferred "
            "from the conventional T+1 / T+2 settlement window."
        ),
    )
    fixing_date: date | None = Field(
        default=None,
        description=(
            "Fixing date for NDF cash-settlement determination. "
            "Required for NON_DELIVERABLE_FORWARD per Section V "
            "('fixing date determination, cash settlement of "
            "fixing-rate differential')."
        ),
    )

    @model_validator(mode="after")
    def _enforce_pairs_distinct(self) -> Self:
        if self.base_currency.upper() == self.quote_currency.upper():
            raise ValueError(
                "Base and quote currencies must differ for an FX "
                "transaction (per AUR-CUSTODY-001 v1.0 Section V FX "
                "definition — a currency pair has two distinct legs)."
            )
        return self

    @model_validator(mode="after")
    def _enforce_forward_requires_value_date(self) -> Self:
        if (
            self.transaction_type
            in {FXTransactionType.FORWARD, FXTransactionType.SWAP}
            and self.value_date is None
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section V (FX), "
                f"{self.transaction_type.value} requires value_date "
                f"(settlement date)."
            )
        return self

    @model_validator(mode="after")
    def _enforce_ndf_requires_fixing_date(self) -> Self:
        if (
            self.transaction_type
            is FXTransactionType.NON_DELIVERABLE_FORWARD
            and self.fixing_date is None
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V (FX), "
                "NON_DELIVERABLE_FORWARD requires fixing_date for the "
                "cash-settlement determination."
            )
        return self


__all__ = ["FXOperation", "FXTransactionType"]
