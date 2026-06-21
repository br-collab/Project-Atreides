"""Structured product custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Structured Products" —
subscription, paydown, call, contingent acceleration, restructuring.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class StructuredTransactionType(StrEnum):
    """Structured product transaction types per AUR-CUSTODY-001 v1.0
    Section V."""

    SUBSCRIPTION = "subscription"
    """Initial purchase of structured product (note, certificate,
    structured deposit)."""
    PAYDOWN = "paydown"
    """Periodic principal repayment per structured product terms."""
    CALL = "call"
    """Issuer exercises call right on callable structured product."""
    CONTINGENT_ACCELERATION = "contingent_acceleration"
    """Per Section V: 'Structured product accelerated payment due to
    triggering event (credit event, knockout barrier, performance
    threshold).'"""
    RESTRUCTURING = "restructuring"
    """Per Section V: 'Structured product terms modified by issuer or
    counterparty action (often in distress).'"""


class StructuredOperation(CustodyOperation):
    """Structured product custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["structured"] = "structured"
    transaction_type: StructuredTransactionType = Field(
        description="Structured product transaction type per Section V.",
    )
    product_identifier: str = Field(
        min_length=1,
        description=(
            "Structured product identifier (issuer CUSIP/ISIN, internal "
            "structured-note reference)."
        ),
    )
    triggering_event: str | None = Field(
        default=None,
        description=(
            "Description of the triggering event for "
            "CONTINGENT_ACCELERATION (e.g., 'knockout barrier breach', "
            "'credit event — issuer downgrade', 'performance threshold "
            "exceeded'). Required for CONTINGENT_ACCELERATION per "
            "Section V."
        ),
    )

    @model_validator(mode="after")
    def _enforce_acceleration_requires_event(self) -> Self:
        if (
            self.transaction_type
            is StructuredTransactionType.CONTINGENT_ACCELERATION
            and not self.triggering_event
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V (Structured "
                "Products), CONTINGENT_ACCELERATION requires "
                "triggering_event identification."
            )
        return self


__all__ = ["StructuredOperation", "StructuredTransactionType"]
