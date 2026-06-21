"""Tests for ``aureon.contracts.operations.funds``.

Per AUR-CUSTODY-001 v1.0 Section V Funds.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.funds import (
    FundOperation,
    FundTransactionType,
)


class TestFundTransactionTypeCoverage:
    @pytest.mark.parametrize(
        "txn_type",
        [
            FundTransactionType.SUBSCRIPTION,
            FundTransactionType.REDEMPTION,
            FundTransactionType.EXCHANGE,
            FundTransactionType.IN_KIND_SUBSCRIPTION,
            FundTransactionType.IN_KIND_REDEMPTION,
            FundTransactionType.CAPITAL_CALL,
            FundTransactionType.DISTRIBUTION,
            FundTransactionType.SIDE_POCKET,
            FundTransactionType.GATE_IMPOSITION,
            FundTransactionType.SUSPENSION,
            FundTransactionType.MMF_LIQUIDITY_FEE_IMPOSITION,
            FundTransactionType.MMF_GATE_IMPOSITION,
            FundTransactionType.MMF_SWEEP,
        ],
    )
    def test_doctrinal_types_present(
        self, txn_type: FundTransactionType
    ) -> None:
        assert txn_type in FundTransactionType


class TestFundConstruction:
    def test_subscription(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FundOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FundTransactionType.SUBSCRIPTION,
            fund_identifier="VFIAX",
        )
        assert op.kind == "fund"
        assert op.fund_identifier == "VFIAX"

    def test_capital_call(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FundOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=FundTransactionType.CAPITAL_CALL,
            fund_identifier="LP-FUND-2026",
        )
        assert op.transaction_type is FundTransactionType.CAPITAL_CALL


class TestExchangeRule:
    def test_exchange_without_target_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"target_fund_identifier"
        ):
            FundOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FundTransactionType.EXCHANGE,
                fund_identifier="VFIAX",
            )

    def test_exchange_with_target_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FundOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FundTransactionType.EXCHANGE,
            fund_identifier="VFIAX",
            target_fund_identifier="VTSAX",
        )
        assert op.target_fund_identifier == "VTSAX"
