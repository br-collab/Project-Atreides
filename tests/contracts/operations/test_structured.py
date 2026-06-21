"""Tests for ``aureon.contracts.operations.structured``.

Per AUR-CUSTODY-001 v1.0 Section V Structured Products.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.structured import (
    StructuredOperation,
    StructuredTransactionType,
)


class TestStructuredTransactionTypeCoverage:
    def test_five_types_enumerated(self) -> None:
        # Per Section V Structured Products: subscription, paydown,
        # call, contingent acceleration, restructuring.
        assert {t.value for t in StructuredTransactionType} == {
            "subscription",
            "paydown",
            "call",
            "contingent_acceleration",
            "restructuring",
        }


class TestStructuredConstruction:
    def test_subscription(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = StructuredOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=StructuredTransactionType.SUBSCRIPTION,
            product_identifier="STR-NOTE-2026-001",
        )
        assert op.kind == "structured"


class TestContingentAccelerationRule:
    def test_acceleration_without_event_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"triggering_event"
        ):
            StructuredOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RM,
                transaction_type=(
                    StructuredTransactionType.CONTINGENT_ACCELERATION
                ),
                product_identifier="STR-NOTE-2026-001",
            )

    def test_acceleration_with_event_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = StructuredOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=(
                StructuredTransactionType.CONTINGENT_ACCELERATION
            ),
            product_identifier="STR-NOTE-2026-001",
            triggering_event="knockout barrier breach",
        )
        assert op.triggering_event == "knockout barrier breach"
