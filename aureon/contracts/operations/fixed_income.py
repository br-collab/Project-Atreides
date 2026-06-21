"""Fixed-income custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Fixed Income" — outright
purchase/sale, when-issued, repo (overnight, term, tri-party,
bilateral, GC vs specials), reverse repo, buy-sell-back, coupon strip
and reconstitution, MBS operations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class FixedIncomeTransactionType(StrEnum):
    """Fixed-income transaction types per AUR-CUSTODY-001 v1.0
    Section V."""

    OUTRIGHT_PURCHASE = "outright_purchase"
    OUTRIGHT_SALE = "outright_sale"
    WHEN_ISSUED = "when_issued"
    """Per Section V: 'Trading securities before official issuance.
    Conditional settlement contingent on actual issuance.'"""
    REPO_OVERNIGHT = "repo_overnight"
    REPO_TERM = "repo_term"
    """Multi-day repurchase agreement. Per Section V: requires
    repo_term_days field for term tracking."""
    REPO_TRIPARTY = "repo_triparty"
    REPO_BILATERAL = "repo_bilateral"
    REVERSE_REPO = "reverse_repo"
    BUY_SELL_BACK = "buy_sell_back"
    COUPON_STRIP = "coupon_strip"
    COUPON_RECONSTITUTE = "coupon_reconstitute"
    MBS_TBA = "mbs_tba"
    """To-Be-Announced trading. Pool selection at settlement."""
    MBS_FACTOR_ADJUSTMENT = "mbs_factor_adjustment"
    """Monthly P&I distribution; factor adjustments for principal
    payments."""


class FixedIncomeOperation(CustodyOperation):
    """Fixed-income custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["fixed_income"] = "fixed_income"
    transaction_type: FixedIncomeTransactionType = Field(
        description="Fixed-income transaction type per Section V.",
    )
    repo_term_days: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Term length in days for term repo. Required for REPO_TERM "
            "per Section V (multi-day repurchase agreement). None for "
            "non-term repo and non-repo transactions."
        ),
    )

    @model_validator(mode="after")
    def _enforce_repo_term_requires_days(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section V (Repo — term): term
        repo requires the term length to be specified."""
        if (
            self.transaction_type is FixedIncomeTransactionType.REPO_TERM
            and self.repo_term_days is None
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V, REPO_TERM "
                "requires repo_term_days to be set (multi-day "
                "repurchase agreement requires term length)."
            )
        return self


__all__ = ["FixedIncomeOperation", "FixedIncomeTransactionType"]
