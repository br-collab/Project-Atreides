"""Tests for ``aureon.contracts.operations.base.CustodyOperation``.

The base operation is abstract — it carries the four architectural
cross-validators that the per-asset-class operation models inherit. To
test the cross-validators directly we need a concrete subclass; this
file defines a minimal one and uses it to exercise every doctrinal
rule.

Per AUR-CUSTODY-001 v1.0 Sections IV, V, VII, VIII, IX and
AUR-CANONICAL-001 v1.6 Axiom 10.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.inherent_safety import InherentSafetySurface
from aureon.contracts.operations.base import CustodyOperation
from aureon.contracts.quorum import QuorumAuthority
from aureon.contracts.settlement import DvP1Settlement


class _MinimalOperation(CustodyOperation):
    """Concrete minimal subclass used to exercise the base
    cross-validators in isolation. Real per-asset-class operations
    live in the sibling modules (equity, fixed_income, etc.)."""

    kind: Literal["test_minimal"] = "test_minimal"


class TestBaseConstruction:
    def test_minimal_non_inherent_safety_operation(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
        )
        assert op.failure_mode_class is FailureModeClass.RA
        assert op.inherent_safety_surface is None
        assert op.quorum_authority is None

    def test_with_settlement_method(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            settlement_method=DvP1Settlement(),
        )
        assert isinstance(op.settlement_method, DvP1Settlement)


class TestUrFRequiresInherentSafety:
    """Per AUR-CUSTODY-001 v1.0 Section VIII: UR-F operations on
    non-inherent-safety surfaces are doctrine integrity gaps."""

    def test_ur_f_without_inherent_safety_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"UR-F must declare an inherent-safety surface",
        ):
            _MinimalOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.UR_F,
            )

    def test_ur_f_with_inherent_safety_and_quorum_accepted(
        self,
        lineage_quorum: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_quorum,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=(
                InherentSafetySurface.PLEDGED_ASSET_MATERIAL
            ),
            quorum_authority=quorum_3_of_5_completed,
        )
        assert op.failure_mode_class is FailureModeClass.UR_F


class TestUrRDoesNotRequireInherentSafety:
    """UR-R has bounded economic exposure through external recovery —
    it does not by itself force inherent-safety placement per
    AUR-CUSTODY-001 v1.0 Section VIII."""

    def test_ur_r_without_inherent_safety_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.UR_R,
        )
        assert op.failure_mode_class is FailureModeClass.UR_R


class TestInherentSafetyRequiresQuorum:
    """Per AUR-CUSTODY-001 v1.0 Section IX and AUR-CANONICAL-001 v1.6
    Axiom 10: inherent-safety surfaces require quorum routing."""

    def test_inherent_safety_without_quorum_rejected(
        self,
        lineage_quorum: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"require quorum_authority routing",
        ):
            _MinimalOperation(
                lineage=lineage_quorum,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.UR_R,
                inherent_safety_surface=(
                    InherentSafetySurface.KEY_CEREMONY
                ),
            )

    def test_inherent_safety_with_quorum_accepted(
        self,
        lineage_quorum: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_quorum,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.UR_R,
            inherent_safety_surface=(
                InherentSafetySurface.KEY_CEREMONY
            ),
            quorum_authority=quorum_3_of_5_completed,
        )
        assert (
            op.inherent_safety_surface is InherentSafetySurface.KEY_CEREMONY
        )


class TestInherentSafetyRequiresQuorumTier:
    """Per AUR-CUSTODY-001 v1.0 Section VII: an inherent-safety
    operation cannot ride a single CAOM tier — the lineage authority
    tier must be QUORUM."""

    def test_inherent_safety_with_t1_tier_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"authority_tier=QUORUM",
        ):
            _MinimalOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.UR_R,
                inherent_safety_surface=(
                    InherentSafetySurface.KEY_CEREMONY
                ),
                quorum_authority=quorum_3_of_5_completed,
            )


class TestQuorumFieldConsistency:
    """When quorum_authority is set, lineage.authority_tier must be
    QUORUM, and conversely. The two cannot disagree."""

    def test_quorum_record_with_t3_tier_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"authority_tier must be QUORUM",
        ):
            _MinimalOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                quorum_authority=quorum_3_of_5_completed,
            )

    def test_quorum_tier_without_quorum_record_rejected(
        self,
        lineage_quorum: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=r"must carry a quorum_authority ceremony record",
        ):
            _MinimalOperation(
                lineage=lineage_quorum,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
            )


class TestImmutability:
    def test_operation_is_frozen(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = _MinimalOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
        )
        with pytest.raises(ValidationError):
            op.failure_mode_class = FailureModeClass.RM  # type: ignore[misc]
