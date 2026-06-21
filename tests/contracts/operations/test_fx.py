"""Tests for ``aureon.contracts.operations.fx``.

Per AUR-CUSTODY-001 v1.0 Section V FX.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.fx import FXOperation, FXTransactionType
from aureon.contracts.settlement import PvPSettlement


class TestFXTransactionTypeCoverage:
    def test_five_types_enumerated(self) -> None:
        # Per Section V FX: spot, forward, NDF, swap, option.
        assert {t.value for t in FXTransactionType} == {
            "spot",
            "forward",
            "non_deliverable_forward",
            "swap",
            "option",
        }


class TestFXConstruction:
    def test_spot(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FXOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FXTransactionType.SPOT,
            base_currency="EUR",
            quote_currency="USD",
            settlement_method=PvPSettlement(via_cls=True),
        )
        assert op.base_currency == "EUR"

    def test_pair_must_be_distinct(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"must differ"
        ):
            FXOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FXTransactionType.SPOT,
                base_currency="USD",
                quote_currency="USD",
            )


class TestForwardValueDateRule:
    def test_forward_without_value_date_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(ValidationError, match=r"value_date"):
            FXOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FXTransactionType.FORWARD,
                base_currency="EUR",
                quote_currency="USD",
            )

    def test_swap_without_value_date_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(ValidationError, match=r"value_date"):
            FXOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FXTransactionType.SWAP,
                base_currency="EUR",
                quote_currency="USD",
            )

    def test_forward_with_value_date_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FXOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FXTransactionType.FORWARD,
            base_currency="EUR",
            quote_currency="USD",
            value_date=date(2026, 6, 1),
        )
        assert op.value_date == date(2026, 6, 1)


class TestNDFFixingDateRule:
    def test_ndf_without_fixing_date_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(ValidationError, match=r"fixing_date"):
            FXOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FXTransactionType.NON_DELIVERABLE_FORWARD,
                base_currency="USD",
                quote_currency="CNY",
            )

    def test_ndf_with_fixing_date_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FXOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FXTransactionType.NON_DELIVERABLE_FORWARD,
            base_currency="USD",
            quote_currency="CNY",
            fixing_date=date(2026, 7, 15),
        )
        assert op.fixing_date == date(2026, 7, 15)
