"""Equity custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Equities" — long buy/sell, short
sale and short cover, securities lending (lender and borrower side),
rights subscription and warrant exercise, conversion, exchange and
tender, in-kind transfer, restricted-stock release.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from aureon.contracts.operations.base import CustodyOperation


class EquityTransactionType(StrEnum):
    """Equity transaction types per AUR-CUSTODY-001 v1.0 Section V."""

    LONG_BUY = "long_buy"
    LONG_SELL = "long_sell"
    SHORT_SALE = "short_sale"
    """Per Section V: 'Sale of borrowed equity. Custody operations:
    locate confirmation before sale, borrow execution and pledge, sale
    settlement, ongoing borrow rate accrual, recall risk monitoring.'
    Reg SHO requires the locate confirmation to be in place before the
    sale."""
    SHORT_COVER = "short_cover"
    SECURITIES_LENDING_LENDER = "securities_lending_lender"
    SECURITIES_LENDING_BORROWER = "securities_lending_borrower"
    RIGHTS_SUBSCRIPTION = "rights_subscription"
    """Per Section V: rights subscription and warrant exercise."""
    CONVERSION = "conversion"
    EXCHANGE_OFFER = "exchange_offer"
    TENDER_OFFER = "tender_offer"
    IN_KIND_TRANSFER = "in_kind_transfer"
    RESTRICTED_STOCK_RELEASE = "restricted_stock_release"


class EquityOperation(CustodyOperation):
    """Equity custody operation.

    Per AUR-CUSTODY-001 v1.0 Section V Equities. The base
    ``CustodyOperation`` carries the shared fields (lineage, custody
    object, failure mode, inherent safety, quorum, settlement); this
    subclass adds the equity-specific transaction-type discriminator
    and the short-sale locate confirmation field that Reg SHO requires.
    """

    kind: Literal["equity"] = "equity"
    transaction_type: EquityTransactionType = Field(
        description=(
            "Equity transaction type per AUR-CUSTODY-001 v1.0 Section "
            "V. Determines the custody-operation mechanics."
        ),
    )
    locate_confirmation_id: str | None = Field(
        default=None,
        description=(
            "Locate confirmation identifier per Reg SHO. Required for "
            "SHORT_SALE per Section V: 'locate confirmation before "
            "sale'. None for non-short-sale transaction types."
        ),
    )

    @model_validator(mode="after")
    def _enforce_short_sale_requires_locate(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section V (Equities) and Reg SHO:
        short sale requires a locate confirmation before sale."""
        if (
            self.transaction_type is EquityTransactionType.SHORT_SALE
            and not self.locate_confirmation_id
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section V (Equities) and "
                "Reg SHO, SHORT_SALE requires a locate_confirmation_id "
                "before the sale settles."
            )
        return self


__all__ = ["EquityOperation", "EquityTransactionType"]
