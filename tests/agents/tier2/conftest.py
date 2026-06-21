"""Shared fixtures for Tier 2 agent tests.

Reused across the FIAT Operations Specialist test modules. Builds
synthetic custody operations, lineage stubs, eligibility verifications,
jurisdictional attributions, routing recommendations, and operation
packages that exercise the doctrinal cross-validators.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from aureon.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
    JurisdictionalAttribution,
    OperationPackage,
    PathSelectionDimension,
    RoutingRecommendation,
)
from aureon.contracts import (
    AssetClass,
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    DvP1Settlement,
    EquityOperation,
    EquityTransactionType,
    FailureModeClass,
    InherentSafetySurface,
    MajorAssetCategory,
    OrdinarySafekeepingObject,
    Representation,
)
from aureon.contracts.quorum import (
    CeremonyState,
    CeremonyStep,
    IndependenceRequirement,
    QuorumAuthority,
    QuorumThreshold,
    Signature,
    SigningAuthority,
)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture
def pre_hash() -> str:
    return _hash("pre-state-fiat")


@pytest.fixture
def post_hash() -> str:
    return _hash("post-state-fiat")


@pytest.fixture
def telemetry_hash() -> str:
    return _hash("telemetry-fiat-v1")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 3, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def lineage_t1(pre_hash: str, now: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="operator-bill",
        initiated_at=now,
        pre_operation_state_hash=pre_hash,
    )


@pytest.fixture
def lineage_quorum(pre_hash: str, now: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.QUORUM,
        authority_id="ceremony-2026-fiat-001",
        initiated_at=now,
        pre_operation_state_hash=pre_hash,
    )


@pytest.fixture
def lineage_quorum_with_post(
    lineage_quorum: DSORLineageStub,
    post_hash: str,
) -> DSORLineageStub:
    """A QUORUM lineage stub carrying both pre and projected-post
    state hashes — used for the projected-post slot of an
    OperationPackage."""
    return lineage_quorum.model_copy(update={"post_operation_state_hash": post_hash})


@pytest.fixture
def quorum_authority_completed() -> QuorumAuthority:
    """A completed 3-of-5 quorum ceremony with the four pool-level
    independence requirements satisfied."""
    pool = tuple(
        SigningAuthority(
            authority_id=f"auth-{i}",
            identity_id=f"person-{i}",
            organizational_unit=org,
            jurisdiction=jur,
            signing_system=f"hsm-{i}",
        )
        for i, (org, jur) in enumerate(
            [
                ("operations", "US"),
                ("risk", "GB"),
                ("compliance", "US"),
                ("treasury", "GB"),
                ("audit", "US"),
            ]
        )
    )
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    signatures = tuple(
        Signature(authority_id=f"auth-{i}", signed_at=base + timedelta(hours=i))
        for i in range(3)
    )
    return QuorumAuthority(
        threshold=QuorumThreshold(n=3, m=5),
        independence_requirements=frozenset(
            {
                IndependenceRequirement.IDENTITY,
                IndependenceRequirement.ORGANIZATIONAL,
                IndependenceRequirement.GEOGRAPHIC,
                IndependenceRequirement.SYSTEM,
            }
        ),
        signing_pool=pool,
        collected_signatures=signatures,
        ceremony_step=CeremonyStep.OPERATION_EXECUTION,
        ceremony_state=CeremonyState.COMPLETED,
        session_id="ceremony-2026-fiat-001",
    )


@pytest.fixture
def equity_asset_fiat() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="Common Stock",
        asset_identifier="AAPL",
    )


@pytest.fixture
def equity_object(equity_asset_fiat: AssetClass) -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=equity_asset_fiat,
    )


@pytest.fixture
def equity_operation_routine(
    equity_object: OrdinarySafekeepingObject,
    lineage_t1: DSORLineageStub,
) -> CustodyOperationUnion:
    """A routine FIAT equity buy — RA failure mode, no inherent-safety
    surface, T1 authority. Used as the input operation for routing-
    decision and escalation tests."""
    return EquityOperation(
        lineage=lineage_t1,
        custody_object=equity_object,
        failure_mode_class=FailureModeClass.RA,
        settlement_method=DvP1Settlement(),
        transaction_type=EquityTransactionType.LONG_BUY,
    )


@pytest.fixture
def equity_operation_quorum(
    equity_object: OrdinarySafekeepingObject,
    lineage_quorum: DSORLineageStub,
    quorum_authority_completed: QuorumAuthority,
) -> CustodyOperationUnion:
    """A material-magnitude FIAT equity operation on
    FIAT_SETTLEMENT_MATERIAL — UR-F failure mode, inherent-safety
    surface declared, QUORUM authority. Used as the input operation
    for quorum-package tests."""
    return EquityOperation(
        lineage=lineage_quorum,
        custody_object=equity_object,
        failure_mode_class=FailureModeClass.UR_F,
        inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
        quorum_authority=quorum_authority_completed,
        settlement_method=DvP1Settlement(),
        transaction_type=EquityTransactionType.LONG_BUY,
    )


def _passing_check(kind: EligibilityCheckKind, when: datetime) -> EligibilityCheck:
    return EligibilityCheck(kind=kind, passed=True, verified_at=when)


def _failing_check(
    kind: EligibilityCheckKind,
    when: datetime,
    reason: str,
) -> EligibilityCheck:
    return EligibilityCheck(
        kind=kind,
        passed=False,
        failure_reason=reason,
        verified_at=when,
    )


@pytest.fixture
def eligibility_all_passed(now: datetime) -> EligibilityVerification:
    return EligibilityVerification(
        checks=tuple(_passing_check(k, now) for k in EligibilityCheckKind),
    )


@pytest.fixture
def eligibility_ofac_failed(now: datetime) -> EligibilityVerification:
    """All checks except OFAC pass; OFAC fails with a doctrine-cited
    reason. Used as the negative-case verification for Guardrail 4."""
    checks = []
    for kind in EligibilityCheckKind:
        if kind is EligibilityCheckKind.OFAC:
            checks.append(
                _failing_check(
                    kind,
                    now,
                    "OFAC screening returned a positive match against "
                    "SDN list per AUR-CUSTODY-001 v1.0 Section VI "
                    "Guardrail 4 (eligibility before routing).",
                )
            )
        else:
            checks.append(_passing_check(kind, now))
    return EligibilityVerification(checks=tuple(checks))


@pytest.fixture
def jurisdictional_domestic(now: datetime) -> JurisdictionalAttribution:
    return JurisdictionalAttribution(
        originating_jurisdiction="US",
        receiving_jurisdiction="US",
        verana_session_id="verana-session-domestic-001",
        attributed_at=now,
    )


@pytest.fixture
def jurisdictional_cross_border(now: datetime) -> JurisdictionalAttribution:
    return JurisdictionalAttribution(
        originating_jurisdiction="US",
        receiving_jurisdiction="GB",
        intermediary_jurisdictions=("DE",),
        verana_session_id="verana-session-cross-border-001",
        attributed_at=now,
    )


@pytest.fixture
def routing_recommendation_fedwire() -> RoutingRecommendation:
    return RoutingRecommendation(
        path_selection_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        chosen_path="fedwire",
        settlement_method=DvP1Settlement(),
        rationale=(
            "Fedwire selected per AUR-CUSTODY-001 v1.0 Section VI "
            "Dimension 1 — gross-real-time-final settlement profile "
            "matches operation urgency and finality requirements."
        ),
    )


@pytest.fixture
def operation_package(
    equity_operation_quorum: CustodyOperationUnion,
    lineage_quorum: DSORLineageStub,
    lineage_quorum_with_post: DSORLineageStub,
    eligibility_all_passed: EligibilityVerification,
    routing_recommendation_fedwire: RoutingRecommendation,
) -> OperationPackage:
    return OperationPackage(
        operation=equity_operation_quorum,
        beneficial_owner_ids=("bo-pension-fund-x",),
        asset_ids=("AAPL",),
        pre_operation_dsor_state_stub=lineage_quorum,
        projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
        routing_recommendation=routing_recommendation_fedwire,
        eligibility_verification=eligibility_all_passed,
    )
