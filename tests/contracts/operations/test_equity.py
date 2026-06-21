"""Tests for ``aureon.contracts.operations.equity``.

Per AUR-CUSTODY-001 v1.0 Section V Equities.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.equity import (
    EquityOperation,
    EquityTransactionType,
)
from aureon.contracts.settlement import DvP1Settlement


class TestEquityTransactionTypeCoverage:
    @pytest.mark.parametrize(
        "txn_type",
        [
            EquityTransactionType.LONG_BUY,
            EquityTransactionType.LONG_SELL,
            EquityTransactionType.SHORT_SALE,
            EquityTransactionType.SHORT_COVER,
            EquityTransactionType.SECURITIES_LENDING_LENDER,
            EquityTransactionType.SECURITIES_LENDING_BORROWER,
            EquityTransactionType.RIGHTS_SUBSCRIPTION,
            EquityTransactionType.CONVERSION,
            EquityTransactionType.EXCHANGE_OFFER,
            EquityTransactionType.TENDER_OFFER,
            EquityTransactionType.IN_KIND_TRANSFER,
            EquityTransactionType.RESTRICTED_STOCK_RELEASE,
        ],
    )
    def test_doctrinal_transaction_types_all_present(
        self, txn_type: EquityTransactionType
    ) -> None:
        assert txn_type in EquityTransactionType


class TestEquityOperationConstruction:
    def test_long_buy(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_equity: OrdinarySafekeepingObject,
    ) -> None:
        op = EquityOperation(
            lineage=lineage_t1,
            custody_object=ordinary_equity,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=EquityTransactionType.LONG_BUY,
            settlement_method=DvP1Settlement(),
        )
        assert op.kind == "equity"
        assert op.transaction_type is EquityTransactionType.LONG_BUY


class TestShortSaleLocateRule:
    """Per AUR-CUSTODY-001 v1.0 Section V Equities and Reg SHO: short
    sale requires locate confirmation before settlement."""

    def test_short_sale_without_locate_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_equity: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"locate_confirmation_id"
        ):
            EquityOperation(
                lineage=lineage_t1,
                custody_object=ordinary_equity,
                failure_mode_class=FailureModeClass.RM,
                transaction_type=EquityTransactionType.SHORT_SALE,
            )

    def test_short_sale_with_locate_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_equity: OrdinarySafekeepingObject,
    ) -> None:
        op = EquityOperation(
            lineage=lineage_t1,
            custody_object=ordinary_equity,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=EquityTransactionType.SHORT_SALE,
            locate_confirmation_id="LOCATE-2026-12345",
        )
        assert op.locate_confirmation_id == "LOCATE-2026-12345"

    def test_locate_not_required_for_long_buy(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_equity: OrdinarySafekeepingObject,
    ) -> None:
        # Locate confirmation is short-sale-specific.
        op = EquityOperation(
            lineage=lineage_t1,
            custody_object=ordinary_equity,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=EquityTransactionType.LONG_BUY,
        )
        assert op.locate_confirmation_id is None
