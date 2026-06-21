"""Tests for ``aureon.contracts.operations.lifecycle``.

Per AUR-CUSTODY-001 v1.0 Section V Lifecycle and Exception Handling.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.lifecycle import (
    LifecycleEventType,
    LifecycleOperation,
)


class TestLifecycleEventTypeCoverage:
    def test_five_types_enumerated(self) -> None:
        # Per Section V Lifecycle: buy-in, sell-out, partial
        # settlement, cancellation, rebooking.
        assert {e.value for e in LifecycleEventType} == {
            "buy_in",
            "sell_out",
            "partial_settlement",
            "trade_cancellation",
            "trade_rebooking",
        }


class TestLifecycleConstruction:
    def test_buy_in(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = LifecycleOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            event_type=LifecycleEventType.BUY_IN,
            fail_reason="failed delivery — counterparty system outage",
        )
        assert op.kind == "lifecycle"


class TestCancellationRule:
    def test_cancellation_without_original_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"original_operation_id"
        ):
            LifecycleOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                event_type=LifecycleEventType.TRADE_CANCELLATION,
            )

    def test_cancellation_with_original_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        original = uuid4()
        op = LifecycleOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            event_type=LifecycleEventType.TRADE_CANCELLATION,
            original_operation_id=original,
        )
        assert op.original_operation_id == original


class TestRebookingRule:
    def test_rebooking_without_original_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"original_operation_id"
        ):
            LifecycleOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                event_type=LifecycleEventType.TRADE_REBOOKING,
            )


class TestPartialSettlementRule:
    def test_partial_without_quantity_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"partial_quantity"
        ):
            LifecycleOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                event_type=LifecycleEventType.PARTIAL_SETTLEMENT,
            )

    def test_partial_with_quantity_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = LifecycleOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            event_type=LifecycleEventType.PARTIAL_SETTLEMENT,
            partial_quantity=Decimal("750000.50"),
        )
        assert op.partial_quantity == Decimal("750000.50")
