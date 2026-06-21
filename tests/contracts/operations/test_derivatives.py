"""Tests for ``aureon.contracts.operations.derivatives``.

Per AUR-CUSTODY-001 v1.0 Section V Derivatives.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.derivatives import (
    DerivativeOperation,
    DerivativeTransactionType,
)
from aureon.contracts.settlement import CCPClearedSettlement


class TestDerivativeTransactionTypeCoverage:
    def test_listed_and_otc_types_present(self) -> None:
        # Per Section V Derivatives: listed (futures, options) + OTC
        # (give-up, allocation, novation, compression, termination,
        # exercise/assignment, expiry) + margin operations.
        listed_types = {
            DerivativeTransactionType.LISTED_FUTURE_TRADE,
            DerivativeTransactionType.LISTED_OPTION_TRADE,
            DerivativeTransactionType.LISTED_OPTION_EXERCISE,
        }
        otc_types = {
            DerivativeTransactionType.OTC_GIVE_UP,
            DerivativeTransactionType.OTC_ALLOCATION,
            DerivativeTransactionType.OTC_NOVATION,
            DerivativeTransactionType.OTC_COMPRESSION,
            DerivativeTransactionType.OTC_TERMINATION,
            DerivativeTransactionType.OTC_EXPIRY,
        }
        margin_types = {
            DerivativeTransactionType.INITIAL_MARGIN,
            DerivativeTransactionType.VARIATION_MARGIN,
            DerivativeTransactionType.MARGIN_CALL,
            DerivativeTransactionType.CLOSE_OUT,
        }
        assert listed_types <= set(DerivativeTransactionType)
        assert otc_types <= set(DerivativeTransactionType)
        assert margin_types <= set(DerivativeTransactionType)


class TestDerivativeConstruction:
    def test_listed_future_trade(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = DerivativeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=DerivativeTransactionType.LISTED_FUTURE_TRADE,
            contract_identifier="ZNH26",
            settlement_method=CCPClearedSettlement(ccp="CME_CLEARING"),
        )
        assert op.contract_identifier == "ZNH26"


class TestNovationRule:
    def test_novation_without_target_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"novation_target_counterparty_id",
        ):
            DerivativeOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                transaction_type=DerivativeTransactionType.OTC_NOVATION,
                contract_identifier="ISDA-12345",
            )

    def test_novation_with_target_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = DerivativeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=DerivativeTransactionType.OTC_NOVATION,
            contract_identifier="ISDA-12345",
            novation_target_counterparty_id="CP-NEW-COUNTERPARTY",
        )
        assert (
            op.novation_target_counterparty_id == "CP-NEW-COUNTERPARTY"
        )


class TestAllocationRule:
    def test_allocation_without_accounts_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"allocation_account_id"
        ):
            DerivativeOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                transaction_type=DerivativeTransactionType.OTC_ALLOCATION,
                contract_identifier="ISDA-67890",
            )

    def test_allocation_with_empty_accounts_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"allocation_account_id"
        ):
            DerivativeOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                transaction_type=DerivativeTransactionType.OTC_ALLOCATION,
                contract_identifier="ISDA-67890",
                allocation_account_ids=(),
            )

    def test_allocation_with_accounts_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = DerivativeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=DerivativeTransactionType.OTC_ALLOCATION,
            contract_identifier="ISDA-67890",
            allocation_account_ids=("ACC-1", "ACC-2", "ACC-3"),
        )
        assert len(op.allocation_account_ids or ()) == 3  # noqa: PLR2004
