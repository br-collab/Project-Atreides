"""Shared fixtures for DSOR tests.

Builds the minimum FIATOperationsOutput instances needed by both
test_record.py and test_store.py. Each output fixture creates its own
independent DSORLineageStub (with a fresh uuid4 operation_id) so that
tests can append multiple outputs to the same store without triggering
the append-only constraint.
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

from aureon.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
    EscalationRequired,
    JClassGuardrail,
    JurisdictionalAttribution,
    PathSelectionDimension,
    RoutingDecision,
    RoutingRecommendation,
)
from aureon.contracts import CAOMTier, DSORLineageStub, FailureModeClass
from aureon.dsor import DSORStore


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture
def dtg() -> datetime:
    return datetime(2026, 6, 20, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def pre_hash() -> str:
    return _sha("dsor-test-pre-state")


@pytest.fixture
def telemetry_hash() -> str:
    return _sha("dsor-test-telemetry")


def _routing_lineage(pre_hash: str, dtg: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="op-routing-001",
        initiated_at=dtg,
        pre_operation_state_hash=pre_hash,
    )


def _escalation_lineage(pre_hash: str, dtg: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="op-escalation-001",
        initiated_at=dtg,
        pre_operation_state_hash=pre_hash,
    )


def _build_routing_decision(
    lineage: DSORLineageStub,
    telemetry_hash: str,
    dtg: datetime,
) -> RoutingDecision:
    checks = tuple(
        EligibilityCheck(kind=k, passed=True, verified_at=dtg) for k in EligibilityCheckKind
    )
    return RoutingDecision(
        operation_id=lineage.operation_id,
        agent_telemetry_hash=telemetry_hash,
        lineage_stub=lineage,
        emitted_at=dtg,
        recommendation=RoutingRecommendation(
            path_selection_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            chosen_path="fedwire",
            rationale=(
                "Fedwire selected per AUR-CUSTODY-001 v1.0 Section VI "
                "Dimension 1 — RTGS gross-final settlement."
            ),
        ),
        eligibility_verification=EligibilityVerification(checks=checks),
        jurisdictional_attribution=JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="US",
            verana_session_id="verana-dsor-test-001",
            attributed_at=dtg,
        ),
        failure_mode_class=FailureModeClass.RA,
    )


def _build_escalation_required(
    lineage: DSORLineageStub,
    telemetry_hash: str,
    dtg: datetime,
) -> EscalationRequired:
    checks = []
    for k in EligibilityCheckKind:
        if k is EligibilityCheckKind.OFAC:
            checks.append(
                EligibilityCheck(
                    kind=k,
                    passed=False,
                    failure_reason=(
                        "OFAC SDN match per AUR-CUSTODY-001 v1.0 Section VI "
                        "Guardrail 4 (eligibility before routing)."
                    ),
                    verified_at=dtg,
                )
            )
        else:
            checks.append(EligibilityCheck(kind=k, passed=True, verified_at=dtg))
    return EscalationRequired(
        operation_id=lineage.operation_id,
        agent_telemetry_hash=telemetry_hash,
        lineage_stub=lineage,
        emitted_at=dtg,
        failed_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
        failure_reason=(
            "OFAC SDN match per AUR-CUSTODY-001 v1.0 Section VI "
            "Guardrail 4 (eligibility before routing)."
        ),
        escalation_tier=CAOMTier.T1,
        eligibility_verification=EligibilityVerification(checks=tuple(checks)),
    )


@pytest.fixture
def routing_decision_output(pre_hash: str, telemetry_hash: str, dtg: datetime) -> RoutingDecision:
    """RoutingDecision with its own independent lineage (unique operation_id)."""
    lineage = _routing_lineage(pre_hash, dtg)
    return _build_routing_decision(lineage, telemetry_hash, dtg)


@pytest.fixture
def escalation_output(pre_hash: str, telemetry_hash: str, dtg: datetime) -> EscalationRequired:
    """EscalationRequired with its own independent lineage (unique operation_id)."""
    lineage = _escalation_lineage(pre_hash, dtg)
    return _build_escalation_required(lineage, telemetry_hash, dtg)


@pytest.fixture
def mem_store() -> Generator[DSORStore, None, None]:
    """In-memory DSORStore — fast, no cleanup needed."""
    with DSORStore(":memory:") as store:
        yield store
