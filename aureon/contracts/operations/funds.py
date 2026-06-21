"""Fund custody operations (mutual funds, ETFs, hedge funds, private
equity, private credit, MMF).

Per AUR-CUSTODY-001 v1.0 Section V "Funds" — subscription, redemption,
exchange, in-kind subscription/redemption, capital call, distribution,
side pocket, gating and suspension, money-market fund operations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class FundTransactionType(StrEnum):
    """Fund transaction types per AUR-CUSTODY-001 v1.0 Section V."""

    SUBSCRIPTION = "subscription"
    REDEMPTION = "redemption"
    EXCHANGE = "exchange"
    """Same-family exchange — typical mutual fund operation."""
    IN_KIND_SUBSCRIPTION = "in_kind_subscription"
    """Subscription paid in securities rather than cash. Typical ETF
    creation."""
    IN_KIND_REDEMPTION = "in_kind_redemption"
    """Redemption paid in securities rather than cash. Typical ETF
    redemption."""
    CAPITAL_CALL = "capital_call"
    """Per Section V: 'Private fund calls committed but undrawn capital
    from limited partners.'"""
    DISTRIBUTION = "distribution"
    SIDE_POCKET = "side_pocket"
    """Per Section V: 'Private fund segregates illiquid or distressed
    assets into separate accounting structure.'"""
    GATE_IMPOSITION = "gate_imposition"
    SUSPENSION = "suspension"
    MMF_LIQUIDITY_FEE_IMPOSITION = "mmf_liquidity_fee_imposition"
    MMF_GATE_IMPOSITION = "mmf_gate_imposition"
    MMF_SWEEP = "mmf_sweep"


class FundOperation(CustodyOperation):
    """Fund custody operation per AUR-CUSTODY-001 v1.0 Section V."""

    kind: Literal["fund"] = "fund"
    transaction_type: FundTransactionType = Field(
        description="Fund transaction type per Section V.",
    )
    fund_identifier: str = Field(
        min_length=1,
        description=(
            "Fund identifier — CUSIP/ISIN/ticker for registered funds, "
            "internal LP identifier for private funds."
        ),
    )
    target_fund_identifier: str | None = Field(
        default=None,
        description=(
            "Target fund identifier for EXCHANGE — the fund being "
            "exchanged into. Required for EXCHANGE per Section V "
            "('simultaneous redemption and subscription, no net cash "
            "if same-day same-family exchange')."
        ),
    )

    @model_validator(mode="after")
    def _enforce_exchange_target(self) -> Self:
        if (
            self.transaction_type is FundTransactionType.EXCHANGE
            and not self.target_fund_identifier
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V (Funds), EXCHANGE "
                "requires target_fund_identifier (the fund being "
                "exchanged into)."
            )
        return self


__all__ = ["FundOperation", "FundTransactionType"]
