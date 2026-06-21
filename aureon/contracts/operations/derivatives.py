"""Derivatives custody operations (listed and OTC).

Per AUR-CUSTODY-001 v1.0 Section V "Derivatives" — listed futures and
options; OTC give-up, allocation, novation, compression, termination,
exercise/assignment, expiry; margin operations (initial, variation,
margin call, close-out).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class DerivativeTransactionType(StrEnum):
    """Derivative transaction types per AUR-CUSTODY-001 v1.0
    Section V."""

    LISTED_FUTURE_TRADE = "listed_future_trade"
    LISTED_FUTURE_VARIATION_MARGIN = "listed_future_variation_margin"
    LISTED_FUTURE_EXPIRY = "listed_future_expiry"
    LISTED_OPTION_TRADE = "listed_option_trade"
    LISTED_OPTION_EXERCISE = "listed_option_exercise"
    LISTED_OPTION_ASSIGNMENT = "listed_option_assignment"
    LISTED_OPTION_EXPIRY = "listed_option_expiry"
    OTC_GIVE_UP = "otc_give_up"
    """Trade executed by one broker but cleared and held at another."""
    OTC_ALLOCATION = "otc_allocation"
    """Block trade allocated across multiple beneficial owner
    accounts."""
    OTC_NOVATION = "otc_novation"
    """Existing OTC contract transferred between counterparties."""
    OTC_COMPRESSION = "otc_compression"
    """Multiple offsetting positions netted into smaller residual
    positions per EMIR / Dodd-Frank reporting."""
    OTC_TERMINATION = "otc_termination"
    OTC_EXERCISE = "otc_exercise"
    OTC_ASSIGNMENT = "otc_assignment"
    OTC_EXPIRY = "otc_expiry"
    INITIAL_MARGIN = "initial_margin"
    VARIATION_MARGIN = "variation_margin"
    MARGIN_CALL = "margin_call"
    CLOSE_OUT = "close_out"


class DerivativeOperation(CustodyOperation):
    """Derivative custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["derivative"] = "derivative"
    transaction_type: DerivativeTransactionType = Field(
        description="Derivative transaction type per Section V.",
    )
    contract_identifier: str = Field(
        min_length=1,
        description=(
            "Derivative contract identifier — exchange contract code "
            "for listed, ISDA contract reference for OTC, or USI/UTI "
            "for cleared OTC."
        ),
    )
    novation_target_counterparty_id: str | None = Field(
        default=None,
        description=(
            "Target counterparty for novation. Required for "
            "OTC_NOVATION per Section V ('contract initiation at new "
            "counterparty')."
        ),
    )
    allocation_account_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Beneficial owner account identifiers for block-trade "
            "allocation. Required for OTC_ALLOCATION per Section V "
            "('per-account position update')."
        ),
    )

    @model_validator(mode="after")
    def _enforce_novation_target(self) -> Self:
        if (
            self.transaction_type is DerivativeTransactionType.OTC_NOVATION
            and not self.novation_target_counterparty_id
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V (Derivatives), "
                "OTC_NOVATION requires novation_target_counterparty_id."
            )
        return self

    @model_validator(mode="after")
    def _enforce_allocation_accounts(self) -> Self:
        if self.transaction_type is DerivativeTransactionType.OTC_ALLOCATION:
            if (
                self.allocation_account_ids is None
                or len(self.allocation_account_ids) == 0
            ):
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section V "
                    "(Derivatives), OTC_ALLOCATION requires at least "
                    "one allocation_account_id (block trade allocated "
                    "across multiple beneficial owner accounts)."
                )
        return self


__all__ = ["DerivativeOperation", "DerivativeTransactionType"]
