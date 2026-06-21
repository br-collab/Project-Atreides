"""Tests for the FIAT Operations Specialist agent class.

This file accumulates across sub-commits A, B, and C of the Module 4
build per the operator-approved sub-commit plan:

- Sub-commit A: agent class skeleton + 5 guardrail enforcement methods.
  Covered in :class:`TestMagnitudeThresholdPolicy`,
  :class:`TestAgentConstruction`, :class:`TestEnforceApprovedPathsOnly`,
  :class:`TestEnforceEligibility`,
  :class:`TestEnforceJurisdictionalAttribution`,
  :class:`TestComputeTelemetryHash`,
  :class:`TestBuildDoctrineOverCodeEscalation`.
- Sub-commit B: the seven path-selection methods (added later).
- Sub-commit C: material-magnitude routing-to-quorum (added later).

Integration tests that exercise the full agent flow live in
:mod:`tests.agents.tier2.test_integration` (sub-commit D).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aureon.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
)
from aureon.agents.tier2.fiat_operations_specialist import (
    FIATOperationsSpecialist,
    MagnitudeThresholdPolicy,
    PathSelectionRequest,
)
from aureon.agents.tier2.outputs import (
    AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST,
    EscalationRequired,
    JClassGuardrail,
    JurisdictionalAttribution,
    PathSelectionDimension,
    QuorumAuthorityRequired,
    RoutingDecision,
    RoutingRecommendation,
)
from aureon.agents.tier2.routing_tables import (
    FinalityModel,
    RoutingTables,
    default_routing_tables,
)
from aureon.contracts import (
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    InherentSafetySurface,
)

_SHA256_HEX_LEN = 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 3, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def empty_policy() -> MagnitudeThresholdPolicy:
    return MagnitudeThresholdPolicy()


@pytest.fixture
def populated_policy() -> MagnitudeThresholdPolicy:
    return MagnitudeThresholdPolicy(
        fiat_settlement_thresholds={
            "USD": Decimal("10000000"),
            "EUR": Decimal("9000000"),
        },
        lvps_finality_thresholds={"USD": Decimal("50000000")},
        fx_bundled_thresholds={"USD": Decimal("25000000")},
        sanctioned_adjacency_jurisdictions=frozenset({"IR", "KP", "SY"}),
    )


@pytest.fixture
def routing_tables() -> RoutingTables:
    return default_routing_tables()


@pytest.fixture
def agent(
    routing_tables: RoutingTables,
    populated_policy: MagnitudeThresholdPolicy,
) -> FIATOperationsSpecialist:
    return FIATOperationsSpecialist(
        routing_tables=routing_tables,
        magnitude_threshold_policy=populated_policy,
    )


@pytest.fixture
def lineage_t1(now: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="operator-bill",
        initiated_at=now,
        pre_operation_state_hash=hashlib.sha256(b"pre").hexdigest(),
    )


# ---------------------------------------------------------------------------
# MagnitudeThresholdPolicy
# ---------------------------------------------------------------------------


class TestMagnitudeThresholdPolicy:
    def test_empty_policy_constructs(self, empty_policy: MagnitudeThresholdPolicy) -> None:
        assert empty_policy.fiat_settlement_thresholds == {}
        assert empty_policy.sanctioned_adjacency_jurisdictions == frozenset()

    def test_empty_policy_returns_false_for_all_checks(
        self,
        empty_policy: MagnitudeThresholdPolicy,
    ) -> None:
        # No threshold set → never material
        assert not empty_policy.is_fiat_settlement_material("USD", Decimal("999999999"))
        assert not empty_policy.is_lvps_finality_material("USD", Decimal("999999999"))
        assert not empty_policy.is_fx_bundled_material("USD", Decimal("999999999"))
        assert not empty_policy.is_sanctioned_adjacent("US")

    def test_amount_at_threshold_is_material(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert populated_policy.is_fiat_settlement_material("USD", Decimal("10000000"))

    def test_amount_above_threshold_is_material(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert populated_policy.is_fiat_settlement_material("USD", Decimal("10000001"))

    def test_amount_below_threshold_is_not_material(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert not populated_policy.is_fiat_settlement_material(
            "USD",
            Decimal("9999999"),
        )

    def test_currency_without_threshold_is_not_material(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        # JPY has no threshold in populated_policy
        assert not populated_policy.is_fiat_settlement_material(
            "JPY",
            Decimal("999999999999"),
        )

    def test_lvps_threshold_distinct_from_fiat(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        # USD LVPS threshold is 50M; 25M is below LVPS but above FIAT
        assert populated_policy.is_fiat_settlement_material(
            "USD",
            Decimal("25000000"),
        )
        assert not populated_policy.is_lvps_finality_material(
            "USD",
            Decimal("25000000"),
        )

    def test_fx_bundled_threshold_independent(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert populated_policy.is_fx_bundled_material("USD", Decimal("25000000"))
        assert not populated_policy.is_fx_bundled_material("USD", Decimal("24999999"))

    def test_sanctioned_adjacency(
        self,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert populated_policy.is_sanctioned_adjacent("IR")
        assert populated_policy.is_sanctioned_adjacent("KP")
        assert not populated_policy.is_sanctioned_adjacent("US")

    def test_negative_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="thresholds must be positive"):
            MagnitudeThresholdPolicy(
                fiat_settlement_thresholds={"USD": Decimal("-1")},
            )

    def test_zero_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="thresholds must be positive"):
            MagnitudeThresholdPolicy(
                lvps_finality_thresholds={"USD": Decimal("0")},
            )

    def test_negative_fx_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="thresholds must be positive"):
            MagnitudeThresholdPolicy(
                fx_bundled_thresholds={"USD": Decimal("-100")},
            )

    def test_policy_is_frozen(self, populated_policy: MagnitudeThresholdPolicy) -> None:
        with pytest.raises(ValidationError):
            populated_policy.sanctioned_adjacency_jurisdictions = frozenset()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


class TestAgentConstruction:
    def test_agent_constructs_with_dependencies(
        self,
        agent: FIATOperationsSpecialist,
        routing_tables: RoutingTables,
        populated_policy: MagnitudeThresholdPolicy,
    ) -> None:
        assert agent.routing_tables is routing_tables
        assert agent.magnitude_threshold_policy is populated_policy

    def test_agent_class_identifier(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        assert agent.agent_class == AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST
        assert agent.agent_class == "FIAT_OPERATIONS_SPECIALIST_v1"


# ---------------------------------------------------------------------------
# Guardrail 1 — Approved paths only
# ---------------------------------------------------------------------------


class TestEnforceApprovedPathsOnly:
    def test_approved_path_for_dimension_passes(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        assert agent.enforce_approved_paths_only(
            "fedwire",
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )

    def test_approved_path_for_other_dimension_passes(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        # Fedwire serves both Dim 1 and Dim 5
        assert agent.enforce_approved_paths_only(
            "fedwire",
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
        )

    def test_approved_path_for_wrong_dimension_fails(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        # Fedwire is not a cash sweep destination
        assert not agent.enforce_approved_paths_only(
            "fedwire",
            PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT,
        )

    def test_unknown_path_fails(self, agent: FIATOperationsSpecialist) -> None:
        assert not agent.enforce_approved_paths_only(
            "not_in_registry",
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )


# ---------------------------------------------------------------------------
# Guardrail 4 — Eligibility before routing
# ---------------------------------------------------------------------------


class TestEnforceEligibility:
    def test_passing_eligibility_returns_all_passed(
        self,
        agent: FIATOperationsSpecialist,
        now: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=now,
            kyc=KYCEvidence(
                beneficial_owner_id="bo-1",
                kyc_reference_id="kyc-1",
                verified_at=now - timedelta(days=30),
                expires_at=now + timedelta(days=335),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id="bo-1",
                    screening_id="ofac-1",
                    matched=False,
                    screened_at=now,
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id="bo-1",
                    screening_id="sanc-1",
                    matched=False,
                    screened_at=now,
                ),
            ),
        )
        result = agent.enforce_eligibility(inputs)
        assert result.all_passed

    def test_failing_eligibility_returns_failed_checks(
        self,
        agent: FIATOperationsSpecialist,
        now: datetime,
    ) -> None:
        # No KYC → fails KYC; no screenings → fails OFAC and sanctions
        inputs = EligibilityInputs(check_time=now, requires_kyb=False)
        result = agent.enforce_eligibility(inputs)
        assert not result.all_passed
        assert len(result.failed_checks) > 0


# ---------------------------------------------------------------------------
# Guardrail 5 — Jurisdictional attribution before execution
# ---------------------------------------------------------------------------


class TestEnforceJurisdictionalAttribution:
    def test_attribution_present_passes(
        self,
        agent: FIATOperationsSpecialist,
        now: datetime,
    ) -> None:
        attr = JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="GB",
            verana_session_id="v-1",
            attributed_at=now,
        )
        assert agent.enforce_jurisdictional_attribution(attr)

    def test_attribution_present_domestic_passes(
        self,
        agent: FIATOperationsSpecialist,
        now: datetime,
    ) -> None:
        attr = JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="US",
            verana_session_id="v-1",
            attributed_at=now,
        )
        assert agent.enforce_jurisdictional_attribution(attr)

    def test_attribution_missing_fails(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        assert not agent.enforce_jurisdictional_attribution(None)


# ---------------------------------------------------------------------------
# Guardrail 3 — Telemetry hash
# ---------------------------------------------------------------------------


class TestComputeTelemetryHash:
    def test_hash_is_64_lowercase_hex(self, agent: FIATOperationsSpecialist) -> None:
        h = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("input-1",),
        )
        assert len(h) == _SHA256_HEX_LEN
        assert h == h.lower()
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_is_deterministic(self, agent: FIATOperationsSpecialist) -> None:
        h1 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("a", "b"),
        )
        h2 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("a", "b"),
        )
        assert h1 == h2

    def test_hash_changes_on_decision_kind(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        h1 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("a",),
        )
        h2 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="escalation_required",
            ordered_inputs_signature=("a",),
        )
        assert h1 != h2

    def test_hash_changes_on_input_order(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        h1 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("a", "b"),
        )
        h2 = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("b", "a"),
        )
        assert h1 != h2

    def test_hash_incorporates_agent_class(
        self,
        agent: FIATOperationsSpecialist,
    ) -> None:
        """Per the operator's ruling on telemetry hash scope: the
        agent_class identifier is part of the hash domain. Two agents
        of different classes producing the same operation/decision/
        inputs should produce different hashes."""
        h_real = agent.compute_telemetry_hash(
            operation_id="op-1",
            decision_kind="routing_decision",
            ordered_inputs_signature=("input-1",),
        )
        # Reconstruct what a different agent class would produce by
        # hashing the same data with a different agent_class string.
        components = (
            "op-1",
            "1.6",
            "routing_decision",
            "DIGITAL_ASSET_CUSTODY_SPECIALIST_v1",  # hypothetical other agent
            "input-1",
        )
        h_other = hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()
        assert h_real != h_other


# ---------------------------------------------------------------------------
# Guardrail 2 — Doctrine over code (meta-guardrail)
# ---------------------------------------------------------------------------


class TestBuildDoctrineOverCodeEscalation:
    def test_builds_valid_escalation(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        now: datetime,
    ) -> None:
        esc = agent.build_doctrine_over_code_escalation(
            operation_id=str(lineage_t1.operation_id),
            lineage_stub=lineage_t1,
            cascade_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
            cascade_failure_description="would route to sanctioned correspondent",
            external_instruction="MT202 instruction routing to sanctioned BIC",
            emitted_at=now,
            attempted_dimension=PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION,
        )
        assert isinstance(esc, EscalationRequired)
        assert esc.failed_guardrail is JClassGuardrail.DOCTRINE_OVER_CODE
        assert esc.cascade_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING
        assert esc.escalation_tier is CAOMTier.T2

    def test_failure_reason_format_matches_ruling(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        now: datetime,
    ) -> None:
        """Per the operator's ruling on doctrine-over-code attribution:
        'Doctrine-over-code hold per AUR-CUSTODY-001 v1.0 Section VI
        Guardrail 2: external instruction conflicts with [Guardrail N]
        — [specific failure]'."""
        esc = agent.build_doctrine_over_code_escalation(
            operation_id=str(lineage_t1.operation_id),
            lineage_stub=lineage_t1,
            cascade_guardrail=JClassGuardrail.JURISDICTIONAL_ATTRIBUTION,
            cascade_failure_description="missing attribution on cross-border leg",
            external_instruction="incoming SWIFT MT103 with no jurisdictional metadata",
            emitted_at=now,
        )
        assert "Doctrine-over-code hold" in esc.failure_reason
        assert "Section VI Guardrail 2" in esc.failure_reason
        assert JClassGuardrail.JURISDICTIONAL_ATTRIBUTION.value in esc.failure_reason
        assert "missing attribution on cross-border leg" in esc.failure_reason

    def test_carries_external_instruction_text(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        now: datetime,
    ) -> None:
        instruction = "Auto-routed correspondent instruction X-Y-Z-123"
        esc = agent.build_doctrine_over_code_escalation(
            operation_id=str(lineage_t1.operation_id),
            lineage_stub=lineage_t1,
            cascade_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
            cascade_failure_description="instructed path not in registry",
            external_instruction=instruction,
            emitted_at=now,
        )
        assert esc.conflicting_external_instruction == instruction

    def test_telemetry_hash_is_present_and_valid(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        now: datetime,
    ) -> None:
        esc = agent.build_doctrine_over_code_escalation(
            operation_id=str(lineage_t1.operation_id),
            lineage_stub=lineage_t1,
            cascade_guardrail=JClassGuardrail.NO_SETTLEMENT_WITHOUT_LINEAGE,
            cascade_failure_description="instruction skips lineage",
            external_instruction="bypass instruction",
            emitted_at=now,
        )
        assert len(esc.agent_telemetry_hash) == _SHA256_HEX_LEN
        assert esc.agent_telemetry_hash == esc.agent_telemetry_hash.lower()


# ===========================================================================
# Sub-commit B — Path-selection methods + helper builders
# ===========================================================================


# ---------------------------------------------------------------------------
# Sub-commit B fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def passing_eligibility_inputs(now: datetime) -> EligibilityInputs:
    return EligibilityInputs(
        check_time=now,
        kyc=KYCEvidence(
            beneficial_owner_id="bo-1",
            kyc_reference_id="kyc-1",
            verified_at=now - timedelta(days=30),
            expires_at=now + timedelta(days=335),
        ),
        requires_kyb=False,
        ofac_screenings=(
            OFACScreeningEvidence(
                subject_id="bo-1",
                screening_id="ofac-1",
                matched=False,
                screened_at=now,
            ),
        ),
        sanctions_screenings=(
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="sanc-1",
                matched=False,
                screened_at=now,
            ),
        ),
    )


@pytest.fixture
def failing_eligibility_inputs(now: datetime) -> EligibilityInputs:
    """Fails OFAC: matched screening present."""
    return EligibilityInputs(
        check_time=now,
        kyc=KYCEvidence(
            beneficial_owner_id="bo-1",
            kyc_reference_id="kyc-1",
            verified_at=now - timedelta(days=30),
            expires_at=now + timedelta(days=335),
        ),
        requires_kyb=False,
        ofac_screenings=(
            OFACScreeningEvidence(
                subject_id="bo-bad",
                screening_id="ofac-bad",
                matched=True,
                matched_list="SDN",
                screened_at=now,
            ),
        ),
        sanctions_screenings=(
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="sanc-1",
                matched=False,
                screened_at=now,
            ),
        ),
    )


@pytest.fixture
def attribution_us_domestic(now: datetime) -> JurisdictionalAttribution:
    return JurisdictionalAttribution(
        originating_jurisdiction="US",
        receiving_jurisdiction="US",
        verana_session_id="verana-session-001",
        attributed_at=now,
    )


@pytest.fixture
def request_passing(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
    )


@pytest.fixture
def request_eligibility_fails(
    equity_operation_routine: CustodyOperationUnion,
    failing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=failing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
    )


@pytest.fixture
def request_attribution_missing(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    now: datetime,
) -> PathSelectionRequest:
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=None,
        emitted_at=now,
    )


# ---------------------------------------------------------------------------
# PathSelectionRequest model
# ---------------------------------------------------------------------------


class TestPathSelectionRequest:
    def test_constructs_with_all_fields(
        self,
        request_passing: PathSelectionRequest,
    ) -> None:
        assert request_passing.attribution is not None
        assert request_passing.emitted_at is not None

    def test_attribution_defaults_to_none(
        self,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
        now: datetime,
    ) -> None:
        req = PathSelectionRequest(
            operation=equity_operation_routine,
            eligibility_inputs=passing_eligibility_inputs,
            emitted_at=now,
        )
        assert req.attribution is None


# ---------------------------------------------------------------------------
# Per-dimension path-selection methods
# Pattern per dimension: positive (G4+G5+G1 all pass) + 3 negatives.
# ---------------------------------------------------------------------------


class TestSelectMultiCurrencyRailRouting:
    def test_passes_returns_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.path_selection_dimension is (
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING
        )
        assert result.recommendation.chosen_path in {"fedwire", "chips", "ach"}

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_eligibility_fails,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING
        assert result.escalation_tier is CAOMTier.T1

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_attribution_missing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION
        assert result.escalation_tier is CAOMTier.T2

    def test_no_approved_path_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="ZZZ",
            jurisdiction="ZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY

    def test_finality_filter_narrows_candidates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        # Only Fedwire is RTGS-final among USD/US rails
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="USD",
            jurisdiction="US",
            finality_preference=FinalityModel.RTGS_FINAL,
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "fedwire"


class TestSelectCorrespondentBankingCoordination:
    def test_passes_returns_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_correspondent_banking_coordination(
            request_passing,
            currency="USD",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "correspondent_citi_ny_usd"

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_correspondent_banking_coordination(
            request_eligibility_fails,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_correspondent_banking_coordination(
            request_attribution_missing,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_no_approved_path_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_correspondent_banking_coordination(
            request_passing,
            currency="ZZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY


class TestSelectCrossBorderFXLeg:
    def test_passes_returns_routing_decision_for_cls_pair(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_cross_border_fx_leg(
            request_passing,
            currency_pair="EUR/USD",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "cls_pvp_g10"

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_cross_border_fx_leg(
            request_eligibility_fails,
            currency_pair="EUR/USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_cross_border_fx_leg(
            request_attribution_missing,
            currency_pair="EUR/USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_non_pvp_pair_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        # USD/ZZZ is not in CLS-eligible pairs
        result = agent.select_cross_border_fx_leg(
            request_passing,
            currency_pair="USD/ZZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY


class TestSelectDepositoryVsSubCustodian:
    def test_passes_returns_routing_decision_for_us(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_depository_vs_sub_custodian(
            request_passing,
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "dtcc_us_direct"

    def test_passes_returns_routing_decision_for_emerging_market(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_depository_vs_sub_custodian(
            request_passing,
            jurisdiction="BR",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "sub_custodian_emerging_markets"

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_depository_vs_sub_custodian(
            request_eligibility_fails,
            jurisdiction="US",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_depository_vs_sub_custodian(
            request_attribution_missing,
            jurisdiction="US",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_unknown_jurisdiction_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_depository_vs_sub_custodian(
            request_passing,
            jurisdiction="ZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY


class TestSelectLargeValuePaymentSystem:
    def test_passes_returns_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_large_value_payment_system(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.path_selection_dimension is (
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM
        )
        # Only Fedwire and CHIPS are tagged LVPS in default tables;
        # ACH is Dim-1-only
        assert result.recommendation.chosen_path in {"fedwire", "chips"}

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_large_value_payment_system(
            request_eligibility_fails,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_large_value_payment_system(
            request_attribution_missing,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_unknown_currency_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_large_value_payment_system(
            request_passing,
            currency="ZZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY

    def test_filters_to_lvps_tagged_paths_only(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        """ACH is Dim-1 only (not LVPS-tagged); Dim-5 query must
        exclude it even though it's a USD/US rail."""
        result = agent.select_large_value_payment_system(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path != "ach"


class TestSelectFedRelatedOperation:
    def test_passes_with_known_facility(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_fed_related_operation(
            request_passing,
            fed_facility_path_id="fed_discount_window",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "fed_discount_window"

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_fed_related_operation(
            request_eligibility_fails,
            fed_facility_path_id="fed_srf",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_fed_related_operation(
            request_attribution_missing,
            fed_facility_path_id="fed_srf",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_unknown_facility_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_fed_related_operation(
            request_passing,
            fed_facility_path_id="not_a_real_fed_facility",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY

    def test_facility_for_wrong_dimension_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        """Fedwire is in the registry but as a Dim 1/5 rail, not Dim
        6 Fed operation. The agent rejects."""
        result = agent.select_fed_related_operation(
            request_passing,
            fed_facility_path_id="fedwire",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY


class TestSelectCashSweepAndShortTermInvestment:
    def test_passes_returns_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_cash_sweep_and_short_term_investment(
            request_passing,
            currency="USD",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.path_selection_dimension is (
            PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT
        )

    def test_eligibility_failure_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_eligibility_fails: PathSelectionRequest,
    ) -> None:
        result = agent.select_cash_sweep_and_short_term_investment(
            request_eligibility_fails,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING

    def test_attribution_missing_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_attribution_missing: PathSelectionRequest,
    ) -> None:
        result = agent.select_cash_sweep_and_short_term_investment(
            request_attribution_missing,
            currency="USD",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.JURISDICTIONAL_ATTRIBUTION

    def test_unknown_currency_escalates(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_cash_sweep_and_short_term_investment(
            request_passing,
            currency="ZZZ",
        )
        assert isinstance(result, EscalationRequired)
        assert result.failed_guardrail is JClassGuardrail.APPROVED_PATHS_ONLY


# ---------------------------------------------------------------------------
# Routing decision shared properties (across dimensions)
# ---------------------------------------------------------------------------


class TestRoutingDecisionStructure:
    def test_decision_carries_all_required_fields(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.doctrine_version == "1.6"
        assert result.agent_class == AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST
        assert len(result.agent_telemetry_hash) == _SHA256_HEX_LEN
        assert result.lineage_stub is not None
        assert result.eligibility_verification.all_passed
        assert result.jurisdictional_attribution is not None

    def test_decision_carries_operation_failure_mode_class(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.failure_mode_class is equity_operation_routine.failure_mode_class

    def test_decision_echoes_operation_settlement_method(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        result = agent.select_multi_currency_rail_routing(
            request_passing,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.settlement_method == (
            equity_operation_routine.settlement_method
        )


# ===========================================================================
# Sub-commit C — Material-magnitude routing to quorum authority
# ===========================================================================


# ---------------------------------------------------------------------------
# Sub-commit C fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def request_above_fiat_settlement_threshold(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    """Request with amount above the populated_policy USD FIAT
    settlement threshold (10M)."""
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
        amount=Decimal("15000000"),
    )


@pytest.fixture
def request_above_lvps_threshold(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    """Request with amount above the populated_policy USD LVPS
    finality threshold (50M)."""
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
        amount=Decimal("75000000"),
    )


@pytest.fixture
def request_above_fx_bundled_threshold(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    """Request with amount above the populated_policy USD FX bundled
    threshold (25M)."""
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
        amount=Decimal("30000000"),
    )


@pytest.fixture
def attribution_with_sanctioned_intermediary(now: datetime) -> JurisdictionalAttribution:
    """Cross-border attribution naming Iran (in populated_policy
    sanctioned_adjacency_jurisdictions) as an intermediary."""
    return JurisdictionalAttribution(
        originating_jurisdiction="US",
        receiving_jurisdiction="GB",
        intermediary_jurisdictions=("IR",),
        verana_session_id="verana-session-cross-002",
        attributed_at=now,
    )


@pytest.fixture
def request_with_sanctioned_adjacency(
    equity_operation_routine: CustodyOperationUnion,
    passing_eligibility_inputs: EligibilityInputs,
    attribution_with_sanctioned_intermediary: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=passing_eligibility_inputs,
        attribution=attribution_with_sanctioned_intermediary,
        emitted_at=now,
        amount=Decimal("100"),
    )


@pytest.fixture
def request_material_with_failed_eligibility(
    equity_operation_routine: CustodyOperationUnion,
    failing_eligibility_inputs: EligibilityInputs,
    attribution_us_domestic: JurisdictionalAttribution,
    now: datetime,
) -> PathSelectionRequest:
    """Material-magnitude operation with failing eligibility — used
    to verify the material-magnitude check takes precedence per the
    operator's ruling."""
    return PathSelectionRequest(
        operation=equity_operation_routine,
        eligibility_inputs=failing_eligibility_inputs,
        attribution=attribution_us_domestic,
        emitted_at=now,
        amount=Decimal("15000000"),
    )


# ---------------------------------------------------------------------------
# _check_material_magnitude
# ---------------------------------------------------------------------------


class TestCheckMaterialMagnitude:
    def test_no_amount_no_attribution_returns_none(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
        now: datetime,
    ) -> None:
        request = PathSelectionRequest(
            operation=equity_operation_routine,
            eligibility_inputs=passing_eligibility_inputs,
            attribution=None,
            emitted_at=now,
        )
        result = agent._check_material_magnitude(
            request=request,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            currency="USD",
        )
        assert result is None

    def test_below_threshold_returns_none(
        self,
        agent: FIATOperationsSpecialist,
        request_passing: PathSelectionRequest,
    ) -> None:
        # request_passing has no amount set
        result = agent._check_material_magnitude(
            request=request_passing,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            currency="USD",
        )
        assert result is None

    def test_amount_above_fiat_settlement_threshold_triggers(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fiat_settlement_threshold: PathSelectionRequest,
    ) -> None:
        result = agent._check_material_magnitude(
            request=request_above_fiat_settlement_threshold,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            currency="USD",
        )
        assert result is InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL

    def test_amount_above_lvps_threshold_triggers_lvps_surface(
        self,
        agent: FIATOperationsSpecialist,
        request_above_lvps_threshold: PathSelectionRequest,
    ) -> None:
        result = agent._check_material_magnitude(
            request=request_above_lvps_threshold,
            dimension=PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
            currency="USD",
        )
        assert result is InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY

    def test_amount_above_fx_bundled_threshold_triggers_fx_surface(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fx_bundled_threshold: PathSelectionRequest,
    ) -> None:
        result = agent._check_material_magnitude(
            request=request_above_fx_bundled_threshold,
            dimension=PathSelectionDimension.CROSS_BORDER_FX_LEG,
            currency="USD",
        )
        assert result is InherentSafetySurface.FX_BUNDLED_SETTLEMENT

    def test_sanctioned_adjacency_triggers_regardless_of_amount(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:
        result = agent._check_material_magnitude(
            request=request_with_sanctioned_adjacency,
            dimension=PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT,
            currency="USD",
        )
        assert result is InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL

    def test_sanctioned_adjacency_triggers_with_no_currency(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:
        result = agent._check_material_magnitude(
            request=request_with_sanctioned_adjacency,
            dimension=PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN,
            currency=None,
        )
        assert result is InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL

    def test_operation_pre_classified_surface_triggers(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_quorum: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """Per Trigger 0: an operation arriving with a non-None
        inherent_safety_surface (UR-F operations always have one per
        the contracts validator) is honored as material-magnitude
        even when no amount or sanctioned-adjacency context exists."""
        request = PathSelectionRequest(
            operation=equity_operation_quorum,
            eligibility_inputs=passing_eligibility_inputs,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent._check_material_magnitude(
            request=request,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            currency="USD",
        )
        assert result is InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL

    def test_dim_2_no_amount_trigger_only_sanctioned(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fiat_settlement_threshold: PathSelectionRequest,
    ) -> None:
        # request has amount above FIAT threshold but Dim 2 has no
        # amount-based check; attribution is US domestic so no
        # sanctioned trigger either.
        result = agent._check_material_magnitude(
            request=request_above_fiat_settlement_threshold,
            dimension=PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION,
            currency="USD",
        )
        assert result is None


# ---------------------------------------------------------------------------
# _project_post_operation_hash
# ---------------------------------------------------------------------------


class TestProjectPostOperationHash:
    def test_hash_is_64_lowercase_hex(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        h = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        assert len(h) == _SHA256_HEX_LEN
        assert h == h.lower()

    def test_hash_is_deterministic(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        h1 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        h2 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        assert h1 == h2

    def test_hash_changes_on_dimension(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        h1 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        h2 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
            "fedwire",
        )
        assert h1 != h2

    def test_hash_changes_on_chosen_path(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        h1 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        h2 = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "chips",
        )
        assert h1 != h2

    def test_hash_with_no_path_uses_placeholder(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        h_none = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            None,
        )
        h_placeholder = agent._project_post_operation_hash(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "no_path_recommendation",
        )
        # Both should produce identical hashes (None resolves to the
        # placeholder)
        assert h_none == h_placeholder


# ---------------------------------------------------------------------------
# Quorum lineage builders
# ---------------------------------------------------------------------------


class TestQuorumLineageBuilders:
    def test_pre_lineage_carries_quorum_tier(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        pre = agent._build_quorum_pre_operation_lineage(equity_operation_routine)
        assert pre.authority_tier is CAOMTier.QUORUM
        assert pre.authority_id == "pending-ceremony"
        assert pre.operation_id == equity_operation_routine.lineage.operation_id
        assert pre.post_operation_state_hash is None

    def test_pre_lineage_preserves_other_fields(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        pre = agent._build_quorum_pre_operation_lineage(equity_operation_routine)
        assert pre.doctrine_version == equity_operation_routine.lineage.doctrine_version
        assert pre.initiated_at == equity_operation_routine.lineage.initiated_at
        assert pre.pre_operation_state_hash == (
            equity_operation_routine.lineage.pre_operation_state_hash
        )

    def test_projected_post_lineage_has_post_hash(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
    ) -> None:
        post = agent._build_quorum_projected_post_lineage(
            equity_operation_routine,
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            "fedwire",
        )
        assert post.authority_tier is CAOMTier.QUORUM
        assert post.post_operation_state_hash is not None
        assert len(post.post_operation_state_hash) == _SHA256_HEX_LEN


# ---------------------------------------------------------------------------
# _assemble_operation_package
# ---------------------------------------------------------------------------


class TestAssembleOperationPackage:
    def test_assembles_with_recommendation(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
    ) -> None:
        verification = agent.enforce_eligibility(passing_eligibility_inputs)

        rec = RoutingRecommendation(
            path_selection_dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            chosen_path="fedwire",
            rationale="test",
        )
        pkg = agent._assemble_operation_package(
            operation=equity_operation_routine,
            verification=verification,
            recommendation=rec,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )
        assert pkg.routing_recommendation is rec
        assert pkg.eligibility_verification.all_passed
        assert pkg.beneficial_owner_ids == (
            equity_operation_routine.custody_object.beneficial_owner_id,
        )
        assert pkg.pre_operation_dsor_state_stub.authority_tier is CAOMTier.QUORUM

    def test_assembles_without_recommendation(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
    ) -> None:
        verification = agent.enforce_eligibility(passing_eligibility_inputs)
        pkg = agent._assemble_operation_package(
            operation=equity_operation_routine,
            verification=verification,
            recommendation=None,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )
        assert pkg.routing_recommendation is None

    def test_assembles_with_failing_eligibility(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        failing_eligibility_inputs: EligibilityInputs,
    ) -> None:
        """Per the operator's ruling on material-magnitude routing
        ordering: the OperationPackage carries failed eligibility for
        quorum signers to evaluate."""
        verification = agent.enforce_eligibility(failing_eligibility_inputs)
        pkg = agent._assemble_operation_package(
            operation=equity_operation_routine,
            verification=verification,
            recommendation=None,
            dimension=PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )
        assert not pkg.eligibility_verification.all_passed


# ---------------------------------------------------------------------------
# Each path-selection method's material-magnitude path
# ---------------------------------------------------------------------------


class TestMaterialMagnitudeRoutingPerDimension:
    def test_dim_1_amount_trigger_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fiat_settlement_threshold: PathSelectionRequest,
    ) -> None:

        result = agent.select_multi_currency_rail_routing(
            request_above_fiat_settlement_threshold,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL
        )
        assert result.operation_package.routing_recommendation is not None

    def test_dim_2_sanctioned_adjacency_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:

        result = agent.select_correspondent_banking_coordination(
            request_with_sanctioned_adjacency,
            currency="USD",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL
        )

    def test_dim_3_amount_trigger_routes_to_quorum_with_fx_surface(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fx_bundled_threshold: PathSelectionRequest,
    ) -> None:

        result = agent.select_cross_border_fx_leg(
            request_above_fx_bundled_threshold,
            currency_pair="USD/EUR",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.FX_BUNDLED_SETTLEMENT
        )

    def test_dim_4_sanctioned_adjacency_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:

        result = agent.select_depository_vs_sub_custodian(
            request_with_sanctioned_adjacency,
            jurisdiction="GB",
        )
        assert isinstance(result, QuorumAuthorityRequired)

    def test_dim_5_amount_trigger_routes_to_quorum_with_lvps_surface(
        self,
        agent: FIATOperationsSpecialist,
        request_above_lvps_threshold: PathSelectionRequest,
    ) -> None:

        result = agent.select_large_value_payment_system(
            request_above_lvps_threshold,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY
        )

    def test_dim_6_sanctioned_adjacency_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:

        result = agent.select_fed_related_operation(
            request_with_sanctioned_adjacency,
            fed_facility_path_id="fed_discount_window",
        )
        assert isinstance(result, QuorumAuthorityRequired)

    def test_dim_7_sanctioned_adjacency_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_with_sanctioned_adjacency: PathSelectionRequest,
    ) -> None:

        result = agent.select_cash_sweep_and_short_term_investment(
            request_with_sanctioned_adjacency,
            currency="USD",
        )
        assert isinstance(result, QuorumAuthorityRequired)


# ---------------------------------------------------------------------------
# Material-magnitude takes precedence over guardrail failures
# ---------------------------------------------------------------------------


class TestMaterialMagnitudeTakesPrecedence:
    def test_material_with_failed_eligibility_still_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        request_material_with_failed_eligibility: PathSelectionRequest,
    ) -> None:
        """Per the operator's ruling: an ineligible material-magnitude
        operation must produce QuorumAuthorityRequired, not
        EscalationRequired (eligibility failure). Inherent-safety
        architectural protection cannot be relaxed because eligibility
        failed."""

        result = agent.select_multi_currency_rail_routing(
            request_material_with_failed_eligibility,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        # Pre-quorum eligibility analysis is captured even though it failed
        assert not result.operation_package.eligibility_verification.all_passed

    def test_material_with_missing_attribution_still_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
        attribution_with_sanctioned_intermediary: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """A request with sanctioned-adjacency triggers material-
        magnitude before any G5 attribution check. Even with a normally-
        problematic state (here the attribution itself is the trigger),
        the operation routes to quorum, not to escalation."""

        request = PathSelectionRequest(
            operation=equity_operation_routine,
            eligibility_inputs=passing_eligibility_inputs,
            attribution=attribution_with_sanctioned_intermediary,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request,
            currency="USD",
        )
        assert isinstance(result, QuorumAuthorityRequired)


# ---------------------------------------------------------------------------
# QuorumAuthorityRequired output structure
# ---------------------------------------------------------------------------


class TestQuorumAuthorityRequiredStructure:
    def test_output_carries_all_required_fields(
        self,
        agent: FIATOperationsSpecialist,
        request_above_fiat_settlement_threshold: PathSelectionRequest,
    ) -> None:

        result = agent.select_multi_currency_rail_routing(
            request_above_fiat_settlement_threshold,
            currency="USD",
            jurisdiction="US",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.kind == "quorum_authority_required"
        assert result.agent_class == AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST
        assert len(result.agent_telemetry_hash) == _SHA256_HEX_LEN
        assert result.lineage_stub.authority_tier is CAOMTier.QUORUM
        assert result.operation_package.routing_recommendation is not None

    def test_no_candidates_produces_quorum_with_none_recommendation(
        self,
        agent: FIATOperationsSpecialist,
        equity_operation_routine: CustodyOperationUnion,
        passing_eligibility_inputs: EligibilityInputs,
        attribution_with_sanctioned_intermediary: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """Sanctioned-adjacency triggers quorum, but the unknown
        currency means no approved path matches — package assembles
        with routing_recommendation=None."""

        request = PathSelectionRequest(
            operation=equity_operation_routine,
            eligibility_inputs=passing_eligibility_inputs,
            attribution=attribution_with_sanctioned_intermediary,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request,
            currency="ZZZ",
            jurisdiction="ZZ",
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.operation_package.routing_recommendation is None
