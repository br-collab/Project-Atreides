"""Tests for the FIAT Operations Specialist output structures.

Coverage standard matches the contracts layer: every model has positive
and negative tests for every validator. Doctrine-cited validators are
exercised against both their satisfied case (rule holds, output
constructs) and their violated case (rule fails, ValidationError
raised).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from aureon.agents.tier2.outputs import (
    AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST,
    FIAT_SPECIALIST_OWNED_SURFACES,
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
    EscalationRequired,
    FIATOperationsOutput,
    JClassGuardrail,
    JurisdictionalAttribution,
    OperationPackage,
    PathSelectionDimension,
    QuorumAuthorityRequired,
    RoutingDecision,
    RoutingRecommendation,
)
from aureon.contracts import (
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    FailureModeClass,
    InherentSafetySurface,
)

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------


class TestEnumsAndConstants:
    def test_path_selection_dimension_members(self) -> None:
        """Per AUR-CUSTODY-001 v1.0 Section VI lines 618-632: exactly
        seven path-selection dimensions."""
        assert set(PathSelectionDimension) == {
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION,
            PathSelectionDimension.CROSS_BORDER_FX_LEG,
            PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN,
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
            PathSelectionDimension.FED_RELATED_OPERATION,
            PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT,
        }

    def test_jclass_guardrail_members(self) -> None:
        """Per AUR-CANONICAL-001 v1.6 Section II (Thifur-J) and
        AUR-CUSTODY-001 v1.0 Section VI line 634: exactly five
        J-class guardrails."""
        assert set(JClassGuardrail) == {
            JClassGuardrail.APPROVED_PATHS_ONLY,
            JClassGuardrail.DOCTRINE_OVER_CODE,
            JClassGuardrail.NO_SETTLEMENT_WITHOUT_LINEAGE,
            JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
            JClassGuardrail.JURISDICTIONAL_ATTRIBUTION,
        }

    def test_eligibility_check_kind_members(self) -> None:
        """Per AUR-CUSTODY-001 v1.0 Section VI line 634: the FIAT
        Operations Specialist runs five eligibility checks."""
        assert set(EligibilityCheckKind) == {
            EligibilityCheckKind.KYC,
            EligibilityCheckKind.KYB,
            EligibilityCheckKind.OFAC,
            EligibilityCheckKind.SANCTIONS,
            EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
        }

    def test_agent_class_constant_value(self) -> None:
        assert AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST == "FIAT_OPERATIONS_SPECIALIST_v1"

    def test_fiat_specialist_owned_surfaces_membership(self) -> None:
        """Per the operator's ruling on Section IX surface ownership:
        the FIAT Operations Specialist owns exactly five surfaces."""
        assert FIAT_SPECIALIST_OWNED_SURFACES == frozenset(
            {
                InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
                InherentSafetySurface.CORRESPONDENT_BANKING_INTEGRITY,
                InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY,
                InherentSafetySurface.FX_BUNDLED_SETTLEMENT,
                InherentSafetySurface.DEPOSITORY_MEMBERSHIP,
            }
        )

    def test_owned_surfaces_excludes_digital_and_common(self) -> None:
        for excluded in [
            InherentSafetySurface.NATIVE_DIGITAL_ASSET_MATERIAL,
            InherentSafetySurface.KEY_CEREMONY,
            InherentSafetySurface.COLD_STORAGE,
            InherentSafetySurface.BENEFICIAL_OWNER_IDENTITY_CHANGE,
            InherentSafetySurface.QUORUM_ENROLLMENT_CHANGE,
            InherentSafetySurface.TOKENIZED_ASSET_ISSUER,
        ]:
            assert excluded not in FIAT_SPECIALIST_OWNED_SURFACES


# ---------------------------------------------------------------------------
# EligibilityCheck
# ---------------------------------------------------------------------------


class TestEligibilityCheck:
    def test_passing_check_constructs(self, now: datetime) -> None:
        check = EligibilityCheck(
            kind=EligibilityCheckKind.OFAC,
            passed=True,
            verified_at=now,
        )
        assert check.passed
        assert check.failure_reason is None

    def test_failing_check_with_reason_constructs(self, now: datetime) -> None:
        check = EligibilityCheck(
            kind=EligibilityCheckKind.OFAC,
            passed=False,
            failure_reason="OFAC SDN match",
            verified_at=now,
        )
        assert not check.passed
        assert check.failure_reason == "OFAC SDN match"

    def test_failing_check_without_reason_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            EligibilityCheck(
                kind=EligibilityCheckKind.OFAC,
                passed=False,
                verified_at=now,
            )

    def test_passing_check_with_reason_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            EligibilityCheck(
                kind=EligibilityCheckKind.OFAC,
                passed=True,
                failure_reason="should not be here",
                verified_at=now,
            )

    def test_check_is_frozen(self, now: datetime) -> None:
        check = EligibilityCheck(
            kind=EligibilityCheckKind.OFAC,
            passed=True,
            verified_at=now,
        )
        with pytest.raises(ValidationError):
            check.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EligibilityVerification
# ---------------------------------------------------------------------------


class TestEligibilityVerification:
    def test_all_kinds_present_constructs(
        self,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        assert eligibility_all_passed.all_passed
        assert eligibility_all_passed.failed_checks == ()

    def test_one_failed_reports_failed_checks(
        self,
        eligibility_ofac_failed: EligibilityVerification,
    ) -> None:
        assert not eligibility_ofac_failed.all_passed
        assert len(eligibility_ofac_failed.failed_checks) == 1
        assert eligibility_ofac_failed.failed_checks[0].kind is EligibilityCheckKind.OFAC

    def test_duplicate_kind_rejected(self, now: datetime) -> None:
        checks = [
            EligibilityCheck(kind=k, passed=True, verified_at=now)
            for k in EligibilityCheckKind
        ]
        # duplicate the OFAC check
        checks.append(
            EligibilityCheck(
                kind=EligibilityCheckKind.OFAC,
                passed=True,
                verified_at=now,
            )
        )
        with pytest.raises(ValidationError, match="duplicate"):
            EligibilityVerification(checks=tuple(checks))

    def test_missing_kind_rejected(self, now: datetime) -> None:
        # Drop OFAC.
        checks = tuple(
            EligibilityCheck(kind=k, passed=True, verified_at=now)
            for k in EligibilityCheckKind
            if k is not EligibilityCheckKind.OFAC
        )
        with pytest.raises(ValidationError, match="missing required check"):
            EligibilityVerification(checks=checks)


# ---------------------------------------------------------------------------
# JurisdictionalAttribution
# ---------------------------------------------------------------------------


class TestJurisdictionalAttribution:
    def test_domestic_is_not_cross_border(
        self,
        jurisdictional_domestic: JurisdictionalAttribution,
    ) -> None:
        assert not jurisdictional_domestic.is_cross_border

    def test_different_jurisdictions_is_cross_border(
        self,
        jurisdictional_cross_border: JurisdictionalAttribution,
    ) -> None:
        assert jurisdictional_cross_border.is_cross_border

    def test_same_jurisdiction_with_intermediary_is_cross_border(
        self,
        now: datetime,
    ) -> None:
        attr = JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="US",
            intermediary_jurisdictions=("CA",),
            verana_session_id="v-001",
            attributed_at=now,
        )
        assert attr.is_cross_border

    def test_short_jurisdiction_code_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            JurisdictionalAttribution(
                originating_jurisdiction="X",
                receiving_jurisdiction="US",
                verana_session_id="v-001",
                attributed_at=now,
            )

    def test_long_jurisdiction_code_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            JurisdictionalAttribution(
                originating_jurisdiction="USAA",
                receiving_jurisdiction="US",
                verana_session_id="v-001",
                attributed_at=now,
            )


# ---------------------------------------------------------------------------
# RoutingRecommendation
# ---------------------------------------------------------------------------


class TestRoutingRecommendation:
    def test_full_recommendation_constructs(
        self,
        routing_recommendation_fedwire: RoutingRecommendation,
    ) -> None:
        assert routing_recommendation_fedwire.chosen_path == "fedwire"
        assert routing_recommendation_fedwire.settlement_method is not None

    def test_recommendation_without_settlement_method(self) -> None:
        rec = RoutingRecommendation(
            path_selection_dimension=PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT,
            chosen_path="mmf-government",
            rationale="Cash sweep to government MMF per Dimension 7.",
        )
        assert rec.settlement_method is None

    def test_empty_chosen_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRecommendation(
                path_selection_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                chosen_path="",
                rationale="empty path test",
            )

    def test_empty_rationale_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRecommendation(
                path_selection_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                chosen_path="fedwire",
                rationale="",
            )


# ---------------------------------------------------------------------------
# OperationPackage
# ---------------------------------------------------------------------------


class TestOperationPackage:
    def test_valid_package_constructs(
        self,
        operation_package: OperationPackage,
    ) -> None:
        assert operation_package.routing_recommendation is not None
        assert operation_package.eligibility_verification.all_passed

    def test_package_without_routing_recommendation(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_quorum: DSORLineageStub,
        lineage_quorum_with_post: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        pkg = OperationPackage(
            operation=equity_operation_quorum,
            beneficial_owner_ids=("bo-pension-fund-x",),
            asset_ids=("AAPL",),
            pre_operation_dsor_state_stub=lineage_quorum,
            projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
            eligibility_verification=eligibility_all_passed,
        )
        assert pkg.routing_recommendation is None

    def test_pre_state_with_t1_authority_rejected(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_t1: DSORLineageStub,
        lineage_quorum_with_post: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        with pytest.raises(ValidationError, match="authority_tier=QUORUM"):
            OperationPackage(
                operation=equity_operation_quorum,
                beneficial_owner_ids=("bo-pension-fund-x",),
                asset_ids=("AAPL",),
                pre_operation_dsor_state_stub=lineage_t1,
                projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
                eligibility_verification=eligibility_all_passed,
            )

    def test_projected_post_without_post_hash_rejected(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_quorum: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        with pytest.raises(ValidationError, match="post_operation_state_hash"):
            OperationPackage(
                operation=equity_operation_quorum,
                beneficial_owner_ids=("bo-pension-fund-x",),
                asset_ids=("AAPL",),
                pre_operation_dsor_state_stub=lineage_quorum,
                # Same as pre — has no post hash
                projected_post_operation_dsor_state_stub=lineage_quorum,
                eligibility_verification=eligibility_all_passed,
            )

    def test_eligibility_failed_accepted(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_quorum: DSORLineageStub,
        lineage_quorum_with_post: DSORLineageStub,
        eligibility_ofac_failed: EligibilityVerification,
    ) -> None:
        """Per the operator's ruling on material-magnitude routing
        ordering: the package carries whatever pre-quorum eligibility
        analysis the agent performed, even when checks failed. Quorum
        signers see the full pre-quorum picture and decide. Eligibility
        failures on non-material operations route to
        EscalationRequired, not to a quorum package; on material
        operations the inherent-safety architectural protection
        cannot be relaxed because eligibility failed."""
        pkg = OperationPackage(
            operation=equity_operation_quorum,
            beneficial_owner_ids=("bo-pension-fund-x",),
            asset_ids=("AAPL",),
            pre_operation_dsor_state_stub=lineage_quorum,
            projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
            eligibility_verification=eligibility_ofac_failed,
        )
        assert not pkg.eligibility_verification.all_passed
        assert len(pkg.eligibility_verification.failed_checks) > 0

    def test_empty_beneficial_owner_ids_rejected(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_quorum: DSORLineageStub,
        lineage_quorum_with_post: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        with pytest.raises(ValidationError):
            OperationPackage(
                operation=equity_operation_quorum,
                beneficial_owner_ids=(),
                asset_ids=("AAPL",),
                pre_operation_dsor_state_stub=lineage_quorum,
                projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
                eligibility_verification=eligibility_all_passed,
            )

    def test_empty_asset_ids_rejected(
        self,
        equity_operation_quorum: CustodyOperationUnion,
        lineage_quorum: DSORLineageStub,
        lineage_quorum_with_post: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
    ) -> None:
        with pytest.raises(ValidationError):
            OperationPackage(
                operation=equity_operation_quorum,
                beneficial_owner_ids=("bo-pension-fund-x",),
                asset_ids=(),
                pre_operation_dsor_state_stub=lineage_quorum,
                projected_post_operation_dsor_state_stub=lineage_quorum_with_post,
                eligibility_verification=eligibility_all_passed,
            )


# ---------------------------------------------------------------------------
# _OutputBase shared validators (exercised through concrete subclasses)
# ---------------------------------------------------------------------------


class TestOutputBaseValidators:
    def test_invalid_telemetry_hash_rejected(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="64-character lowercase hex"):
            RoutingDecision(
                operation_id=lineage_t1.operation_id,
                agent_telemetry_hash="not-a-real-hash",
                lineage_stub=lineage_t1,
                emitted_at=now,
                recommendation=routing_recommendation_fedwire,
                eligibility_verification=eligibility_all_passed,
                jurisdictional_attribution=jurisdictional_domestic,
                failure_mode_class=FailureModeClass.RA,
            )

    def test_uppercase_telemetry_hash_rejected(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="64-character lowercase hex"):
            RoutingDecision(
                operation_id=lineage_t1.operation_id,
                agent_telemetry_hash=telemetry_hash.upper(),
                lineage_stub=lineage_t1,
                emitted_at=now,
                recommendation=routing_recommendation_fedwire,
                eligibility_verification=eligibility_all_passed,
                jurisdictional_attribution=jurisdictional_domestic,
                failure_mode_class=FailureModeClass.RA,
            )

    def test_operation_id_mismatch_with_lineage_rejected(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="does not match"):
            RoutingDecision(
                operation_id=uuid4(),  # Doesn't match the lineage's operation_id
                agent_telemetry_hash=telemetry_hash,
                lineage_stub=lineage_t1,
                emitted_at=now,
                recommendation=routing_recommendation_fedwire,
                eligibility_verification=eligibility_all_passed,
                jurisdictional_attribution=jurisdictional_domestic,
                failure_mode_class=FailureModeClass.RA,
            )


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_valid_routing_decision_constructs(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        decision = RoutingDecision(
            operation_id=lineage_t1.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_t1,
            emitted_at=now,
            recommendation=routing_recommendation_fedwire,
            eligibility_verification=eligibility_all_passed,
            jurisdictional_attribution=jurisdictional_domestic,
            failure_mode_class=FailureModeClass.RA,
        )
        assert decision.kind == "routing_decision"
        assert decision.agent_class == "FIAT_OPERATIONS_SPECIALIST_v1"
        assert decision.doctrine_version == "1.6"

    def test_routing_decision_with_cross_border_attribution(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_cross_border: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        decision = RoutingDecision(
            operation_id=lineage_t1.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_t1,
            emitted_at=now,
            recommendation=routing_recommendation_fedwire,
            eligibility_verification=eligibility_all_passed,
            jurisdictional_attribution=jurisdictional_cross_border,
            failure_mode_class=FailureModeClass.RM,
        )
        assert decision.jurisdictional_attribution.is_cross_border

    def test_eligibility_failed_rejected(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_ofac_failed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="all eligibility checks to pass"):
            RoutingDecision(
                operation_id=lineage_t1.operation_id,
                agent_telemetry_hash=telemetry_hash,
                lineage_stub=lineage_t1,
                emitted_at=now,
                recommendation=routing_recommendation_fedwire,
                eligibility_verification=eligibility_ofac_failed,
                jurisdictional_attribution=jurisdictional_domestic,
                failure_mode_class=FailureModeClass.RA,
            )

    def test_ur_f_failure_mode_rejected(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="UR-F"):
            RoutingDecision(
                operation_id=lineage_t1.operation_id,
                agent_telemetry_hash=telemetry_hash,
                lineage_stub=lineage_t1,
                emitted_at=now,
                recommendation=routing_recommendation_fedwire,
                eligibility_verification=eligibility_all_passed,
                jurisdictional_attribution=jurisdictional_domestic,
                failure_mode_class=FailureModeClass.UR_F,
            )


# ---------------------------------------------------------------------------
# EscalationRequired
# ---------------------------------------------------------------------------


def _make_escalation(
    *,
    failed_guardrail: JClassGuardrail,
    cascade_guardrail: JClassGuardrail | None = None,
    escalation_tier: CAOMTier = CAOMTier.T2,
    eligibility_verification: EligibilityVerification | None = None,
    jurisdictional_attribution: JurisdictionalAttribution | None = None,
    conflicting_external_instruction: str | None = None,
    attempted_dimension: PathSelectionDimension | None = None,
    lineage_stub: DSORLineageStub,
    telemetry_hash: str,
    now: datetime,
    failure_reason: str = "test failure reason",
) -> EscalationRequired:
    return EscalationRequired(
        operation_id=lineage_stub.operation_id,
        agent_telemetry_hash=telemetry_hash,
        lineage_stub=lineage_stub,
        emitted_at=now,
        failed_guardrail=failed_guardrail,
        cascade_guardrail=cascade_guardrail,
        failure_reason=failure_reason,
        escalation_tier=escalation_tier,
        attempted_dimension=attempted_dimension,
        eligibility_verification=eligibility_verification,
        jurisdictional_attribution=jurisdictional_attribution,
        conflicting_external_instruction=conflicting_external_instruction,
    )


class TestEscalationRequired:
    def test_approved_paths_only_escalation(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        esc = _make_escalation(
            failed_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
            escalation_tier=CAOMTier.T1,
            attempted_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            lineage_stub=lineage_t1,
            telemetry_hash=telemetry_hash,
            now=now,
            failure_reason=(
                "No approved path in routing tables matches the operation "
                "per AUR-CUSTODY-001 v1.0 Section VI Guardrail 1."
            ),
        )
        assert esc.kind == "escalation_required"
        assert esc.cascade_guardrail is None

    def test_eligibility_escalation_with_failed_verification(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        eligibility_ofac_failed: EligibilityVerification,
        now: datetime,
    ) -> None:
        esc = _make_escalation(
            failed_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
            escalation_tier=CAOMTier.T1,
            eligibility_verification=eligibility_ofac_failed,
            lineage_stub=lineage_t1,
            telemetry_hash=telemetry_hash,
            now=now,
            failure_reason="OFAC failed.",
        )
        assert esc.eligibility_verification is not None
        assert not esc.eligibility_verification.all_passed

    def test_doctrine_over_code_escalation_with_cascade_and_instruction(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        esc = _make_escalation(
            failed_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
            cascade_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
            escalation_tier=CAOMTier.T2,
            conflicting_external_instruction=(
                "Automated correspondent banking instruction routed "
                "to BIC for sanctioned jurisdiction; would violate "
                "Guardrail 4 (eligibility before routing)."
            ),
            lineage_stub=lineage_t1,
            telemetry_hash=telemetry_hash,
            now=now,
            failure_reason=(
                "Doctrine-over-code hold per AUR-CUSTODY-001 v1.0 "
                "Section VI Guardrail 2: external instruction "
                "conflicts with Guardrail 4 — would route to "
                "sanctioned correspondent."
            ),
        )
        assert esc.cascade_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_jurisdictional_attribution_escalation(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        esc = _make_escalation(
            failed_guardrail=JClassGuardrail.JURISDICTIONAL_ATTRIBUTION,
            escalation_tier=CAOMTier.T2,
            lineage_stub=lineage_t1,
            telemetry_hash=telemetry_hash,
            now=now,
            failure_reason=(
                "Verana attribution missing on cross-border operation "
                "per AUR-CANONICAL-001 v1.6 Section II (Verana — "
                "Network Governance) and Axiom 8."
            ),
        )
        assert esc.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_quorum_tier_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="cannot be QUORUM"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
                escalation_tier=CAOMTier.QUORUM,
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_doctrine_over_code_without_cascade_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="must name the cascade_guardrail"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
                cascade_guardrail=None,
                conflicting_external_instruction="some instruction",
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_non_doctrine_over_code_with_cascade_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="cascade_guardrail"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
                cascade_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_doctrine_over_code_self_cascade_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="cannot itself be DOCTRINE_OVER_CODE"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
                cascade_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
                conflicting_external_instruction="some instruction",
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_doctrine_over_code_without_instruction_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match="must carry conflicting_external_instruction",
        ):
            _make_escalation(
                failed_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
                cascade_guardrail=JClassGuardrail.JURISDICTIONAL_ATTRIBUTION,
                conflicting_external_instruction=None,
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_eligibility_escalation_without_verification_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="must carry eligibility_verification"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
                eligibility_verification=None,
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )

    def test_eligibility_escalation_with_all_passed_rejected(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        eligibility_all_passed: EligibilityVerification,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="at least one failed check"):
            _make_escalation(
                failed_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
                eligibility_verification=eligibility_all_passed,
                lineage_stub=lineage_t1,
                telemetry_hash=telemetry_hash,
                now=now,
            )


# ---------------------------------------------------------------------------
# QuorumAuthorityRequired
# ---------------------------------------------------------------------------


class TestQuorumAuthorityRequired:
    def test_valid_quorum_output_constructs(
        self,
        lineage_quorum: DSORLineageStub,
        operation_package: OperationPackage,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        out = QuorumAuthorityRequired(
            operation_id=lineage_quorum.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_quorum,
            emitted_at=now,
            inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
            operation_package=operation_package,
        )
        assert out.kind == "quorum_authority_required"

    @pytest.mark.parametrize("surface", sorted(FIAT_SPECIALIST_OWNED_SURFACES))
    def test_each_owned_surface_accepted(
        self,
        surface: InherentSafetySurface,
        lineage_quorum: DSORLineageStub,
        operation_package: OperationPackage,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        out = QuorumAuthorityRequired(
            operation_id=lineage_quorum.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_quorum,
            emitted_at=now,
            inherent_safety_surface=surface,
            operation_package=operation_package,
        )
        assert out.inherent_safety_surface is surface

    @pytest.mark.parametrize(
        "surface",
        [
            InherentSafetySurface.NATIVE_DIGITAL_ASSET_MATERIAL,
            InherentSafetySurface.KEY_CEREMONY,
            InherentSafetySurface.COLD_STORAGE,
            InherentSafetySurface.BENEFICIAL_OWNER_IDENTITY_CHANGE,
            InherentSafetySurface.QUORUM_ENROLLMENT_CHANGE,
            InherentSafetySurface.PHYSICAL_COMMODITY_VAULT_MATERIAL,
            InherentSafetySurface.TOKENIZED_ASSET_ISSUER,
        ],
    )
    def test_non_owned_surface_rejected(
        self,
        surface: InherentSafetySurface,
        lineage_quorum: DSORLineageStub,
        operation_package: OperationPackage,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="not owned by the FIAT"):
            QuorumAuthorityRequired(
                operation_id=lineage_quorum.operation_id,
                agent_telemetry_hash=telemetry_hash,
                lineage_stub=lineage_quorum,
                emitted_at=now,
                inherent_safety_surface=surface,
                operation_package=operation_package,
            )

    def test_operation_id_mismatch_with_package_rejected(
        self,
        lineage_quorum: DSORLineageStub,
        operation_package: OperationPackage,
        telemetry_hash: str,
        pre_hash: str,
        now: datetime,
    ) -> None:
        # Construct a different lineage with a different operation_id
        # but matching it to the output's operation_id, so the
        # mismatch is between the output's id and the package's id.
        other_lineage = DSORLineageStub(
            authority_tier=CAOMTier.QUORUM,
            authority_id="ceremony-other",
            initiated_at=now,
            pre_operation_state_hash=pre_hash,
        )
        with pytest.raises(ValidationError, match="does not match"):
            QuorumAuthorityRequired(
                operation_id=other_lineage.operation_id,
                agent_telemetry_hash=telemetry_hash,
                lineage_stub=other_lineage,
                emitted_at=now,
                inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
                operation_package=operation_package,
            )


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------


class TestFIATOperationsOutputUnion:
    def test_routing_decision_round_trips(
        self,
        lineage_t1: DSORLineageStub,
        eligibility_all_passed: EligibilityVerification,
        jurisdictional_domestic: JurisdictionalAttribution,
        routing_recommendation_fedwire: RoutingRecommendation,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        decision = RoutingDecision(
            operation_id=lineage_t1.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_t1,
            emitted_at=now,
            recommendation=routing_recommendation_fedwire,
            eligibility_verification=eligibility_all_passed,
            jurisdictional_attribution=jurisdictional_domestic,
            failure_mode_class=FailureModeClass.RA,
        )
        round_tripped = adapter.validate_python(decision.model_dump(mode="python"))
        assert isinstance(round_tripped, RoutingDecision)

    def test_escalation_round_trips(
        self,
        lineage_t1: DSORLineageStub,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        esc = _make_escalation(
            failed_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
            escalation_tier=CAOMTier.T1,
            lineage_stub=lineage_t1,
            telemetry_hash=telemetry_hash,
            now=now,
        )
        round_tripped = adapter.validate_python(esc.model_dump(mode="python"))
        assert isinstance(round_tripped, EscalationRequired)

    def test_quorum_required_round_trips(
        self,
        lineage_quorum: DSORLineageStub,
        operation_package: OperationPackage,
        telemetry_hash: str,
        now: datetime,
    ) -> None:
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        out = QuorumAuthorityRequired(
            operation_id=lineage_quorum.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_quorum,
            emitted_at=now,
            inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
            operation_package=operation_package,
        )
        round_tripped = adapter.validate_python(out.model_dump(mode="python"))
        assert isinstance(round_tripped, QuorumAuthorityRequired)

    def test_unknown_kind_rejected(self) -> None:
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        with pytest.raises(ValidationError):
            adapter.validate_python({"kind": "fictional_output_kind"})
