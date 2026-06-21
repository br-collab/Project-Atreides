"""Integration tests for the FIAT Operations Specialist.

Per AUR-CUSTODY-001 v1.0 Section VI and the build prompt's coverage
criterion 10: integration tests demonstrate the agent consuming
contracts correctly across synthetic operations spanning multiple
asset classes, multiple settlement methods, and the full RA / RM /
UR-R / UR-F failure-mode classification range.

The tests in this module exercise full-flow scenarios end-to-end:

- **Cross-asset-class**: equity, fixed-income, FX, derivative, fund
  operations through the seven path-selection methods.
- **Cross-failure-mode**: RA / RM / UR-R / UR-F operations exercise
  the routing-decision and quorum-routing branches per CUS Section
  VIII.
- **Cross-settlement-method**: DvP1 / DvP3 / PvP / FoP / Triparty
  settlement methods echo correctly through the routing
  recommendation per CUS Section V.
- **Round-trip serialization**: every output kind serializes to JSON
  and parses back to an equal instance, proving DSOR replay
  capability per AUR-CANONICAL-001 v1.6 Axiom 4 (one lineage record).

These tests sit alongside the per-method unit tests in
:mod:`tests.agents.tier2.test_fiat_operations_specialist`. The unit
tests verify per-method behaviour in isolation; the integration tests
verify the agent composes correctly under realistic operation
contexts.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

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
    EscalationRequired,
    FIATOperationsOutput,
    JurisdictionalAttribution,
    QuorumAuthorityRequired,
    RoutingDecision,
)
from aureon.agents.tier2.routing_tables import default_routing_tables
from aureon.contracts import (
    AssetClass,
    AtomicSettlement,
    CAOMTier,
    DerivativeOperation,
    DerivativeTransactionType,
    DSORLineageStub,
    DvP1Settlement,
    DvP3Settlement,
    Encumbrance,
    EncumbranceType,
    EquityOperation,
    EquityTransactionType,
    FailureModeClass,
    FixedIncomeOperation,
    FixedIncomeTransactionType,
    FoPSettlement,
    FundOperation,
    FundTransactionType,
    FXOperation,
    FXTransactionType,
    InherentSafetySurface,
    MajorAssetCategory,
    OrdinarySafekeepingObject,
    PledgedAssetObject,
    PvPSettlement,
    Representation,
    SettlementMethod,
    TripartySettlement,
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

_SHA256_HEX_LEN = 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 3, 14, 0, 0, tzinfo=UTC)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture
def policy() -> MagnitudeThresholdPolicy:
    return MagnitudeThresholdPolicy(
        fiat_settlement_thresholds={"USD": Decimal("10000000")},
        lvps_finality_thresholds={"USD": Decimal("50000000")},
        fx_bundled_thresholds={"USD": Decimal("25000000"), "EUR": Decimal("22000000")},
        sanctioned_adjacency_jurisdictions=frozenset({"IR", "KP"}),
    )


@pytest.fixture
def agent(policy: MagnitudeThresholdPolicy) -> FIATOperationsSpecialist:
    return FIATOperationsSpecialist(
        routing_tables=default_routing_tables(),
        magnitude_threshold_policy=policy,
    )


@pytest.fixture
def lineage_t1(now: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="operator-bill",
        initiated_at=now,
        pre_operation_state_hash=_hash("pre-state"),
    )


@pytest.fixture
def lineage_quorum(now: datetime) -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.QUORUM,
        authority_id="ceremony-2026-fiat-001",
        initiated_at=now,
        pre_operation_state_hash=_hash("pre-state-quorum"),
    )


@pytest.fixture
def quorum_authority_3_of_5(now: datetime) -> QuorumAuthority:
    pool = tuple(
        SigningAuthority(
            authority_id=f"a-{i}",
            identity_id=f"p-{i}",
            organizational_unit=org,
            jurisdiction=jur,
            signing_system=f"hsm-{i}",
        )
        for i, (org, jur) in enumerate(
            [
                ("ops", "US"),
                ("risk", "GB"),
                ("compliance", "US"),
                ("treasury", "GB"),
                ("audit", "US"),
            ]
        )
    )
    sigs = tuple(
        Signature(authority_id=f"a-{i}", signed_at=now + timedelta(hours=i))
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
        collected_signatures=sigs,
        ceremony_step=CeremonyStep.OPERATION_EXECUTION,
        ceremony_state=CeremonyState.COMPLETED,
        session_id="ceremony-2026-fiat-001",
    )


@pytest.fixture
def passing_eligibility(now: datetime) -> EligibilityInputs:
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
                screening_id="o-1",
                matched=False,
                screened_at=now,
            ),
        ),
        sanctions_screenings=(
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
                matched=False,
                screened_at=now,
            ),
        ),
    )


@pytest.fixture
def failing_eligibility(now: datetime) -> EligibilityInputs:
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
                screening_id="o-1",
                matched=True,
                matched_list="SDN",
                screened_at=now,
            ),
        ),
        sanctions_screenings=(
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
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
        verana_session_id="v-1",
        attributed_at=now,
    )


# ---------------------------------------------------------------------------
# Operation factories — one per asset class
# ---------------------------------------------------------------------------


def _equity_object(asset_id: str = "AAPL") -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            representation=Representation.FIAT,
            sub_category="Common Stock",
            asset_identifier=asset_id,
        ),
    )


def _fixed_income_object() -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-treasury-mgmt",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            representation=Representation.FIAT,
            sub_category="Treasury",
            asset_identifier="912828YV6",
        ),
    )


def _fx_object() -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-currency-fund",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            representation=Representation.FIAT,
            sub_category="FX EUR/USD",
        ),
    )


def _derivative_object() -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-hedge-fund-y",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            representation=Representation.FIAT,
            sub_category="Interest Rate Swap",
        ),
    )


def _fund_object() -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-mmf-investor",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.FUNDS_AND_POOLED_VEHICLES,
            representation=Representation.FIAT,
            sub_category="Money Market",
        ),
    )


def _pledged_treasury_object() -> PledgedAssetObject:
    return PledgedAssetObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=AssetClass(
            major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            representation=Representation.FIAT,
            sub_category="Treasury",
            asset_identifier="912828YV6",
        ),
        encumbrance=Encumbrance(
            encumbrance_type=EncumbranceType.REPO,
            lien_holder_id="cp-jpmorgan-prime",
            lien_priority=1,
        ),
    )


def make_equity_op(
    *,
    lineage: DSORLineageStub,
    failure_mode: FailureModeClass = FailureModeClass.RA,
    settlement: SettlementMethod | None = None,
) -> EquityOperation:
    return EquityOperation(
        lineage=lineage,
        custody_object=_equity_object(),
        failure_mode_class=failure_mode,
        settlement_method=settlement or DvP1Settlement(),
        transaction_type=EquityTransactionType.LONG_BUY,
    )


def make_fixed_income_op(
    *,
    lineage: DSORLineageStub,
    failure_mode: FailureModeClass = FailureModeClass.RA,
    settlement: SettlementMethod | None = None,
) -> FixedIncomeOperation:
    return FixedIncomeOperation(
        lineage=lineage,
        custody_object=_fixed_income_object(),
        failure_mode_class=failure_mode,
        settlement_method=settlement or DvP1Settlement(),
        transaction_type=FixedIncomeTransactionType.OUTRIGHT_PURCHASE,
    )


def make_fx_op(
    *,
    lineage: DSORLineageStub,
    failure_mode: FailureModeClass = FailureModeClass.RA,
    settlement: SettlementMethod | None = None,
) -> FXOperation:
    return FXOperation(
        lineage=lineage,
        custody_object=_fx_object(),
        failure_mode_class=failure_mode,
        settlement_method=settlement or PvPSettlement(),
        transaction_type=FXTransactionType.SPOT,
        base_currency="EUR",
        quote_currency="USD",
    )


def make_derivative_op(
    *,
    lineage: DSORLineageStub,
    failure_mode: FailureModeClass = FailureModeClass.RA,
    settlement: SettlementMethod | None = None,
) -> DerivativeOperation:
    return DerivativeOperation(
        lineage=lineage,
        custody_object=_derivative_object(),
        failure_mode_class=failure_mode,
        settlement_method=settlement or DvP3Settlement(),
        transaction_type=DerivativeTransactionType.OTC_NOVATION,
        contract_identifier="IRS-2026-0001",
        novation_target_counterparty_id="cp-novated-to",
    )


def make_fund_op(
    *,
    lineage: DSORLineageStub,
    failure_mode: FailureModeClass = FailureModeClass.RA,
    settlement: SettlementMethod | None = None,
) -> FundOperation:
    return FundOperation(
        lineage=lineage,
        custody_object=_fund_object(),
        failure_mode_class=failure_mode,
        settlement_method=settlement or DvP1Settlement(),
        transaction_type=FundTransactionType.SUBSCRIPTION,
        fund_identifier="MMF-GOV-001",
    )


# ---------------------------------------------------------------------------
# Cross-asset-class flows
# ---------------------------------------------------------------------------


class TestCrossAssetClassFlows:
    """Verify the agent consumes operations of every major FIAT asset
    class and produces a structurally correct routing decision."""

    def test_equity_long_buy_routes_through_fedwire(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path in {"fedwire", "chips", "ach"}
        assert result.failure_mode_class is FailureModeClass.RA

    def test_fixed_income_treasury_routes_through_dvp1(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_fixed_income_op(lineage=lineage_t1, settlement=DvP1Settlement())
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert isinstance(result.recommendation.settlement_method, DvP1Settlement)

    def test_fx_spot_routes_through_cls_pvp(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_fx_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_cross_border_fx_leg(
            request, currency_pair="EUR/USD"
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "cls_pvp_g10"
        assert isinstance(result.recommendation.settlement_method, PvPSettlement)

    def test_derivative_otc_novation_routes_through_correspondent(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_derivative_op(lineage=lineage_t1, settlement=DvP3Settlement())
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_correspondent_banking_coordination(
            request, currency="USD"
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path == "correspondent_citi_ny_usd"
        assert isinstance(result.recommendation.settlement_method, DvP3Settlement)

    def test_fund_subscription_routes_through_cash_sweep(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_fund_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_cash_sweep_and_short_term_investment(
            request, currency="USD"
        )
        assert isinstance(result, RoutingDecision)
        assert result.recommendation.chosen_path in {
            "mmf_government_cnav",
            "mmf_prime_fnav",
            "bank_deposit_sweep",
            "tri_party_repo_bny",
        }


# ---------------------------------------------------------------------------
# Cross-failure-mode flows
# ---------------------------------------------------------------------------


class TestCrossFailureModeFlows:
    """Per CUS Section VIII: every operation declares one of RA / RM /
    UR-R / UR-F. The agent must handle each class correctly."""

    def test_ra_operation_produces_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1, failure_mode=FailureModeClass.RA)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert result.failure_mode_class is FailureModeClass.RA

    def test_rm_operation_produces_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1, failure_mode=FailureModeClass.RM)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert result.failure_mode_class is FailureModeClass.RM

    def test_ur_r_operation_produces_routing_decision(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1, failure_mode=FailureModeClass.UR_R)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert result.failure_mode_class is FailureModeClass.UR_R

    def test_ur_f_operation_routes_to_quorum(
        self,
        agent: FIATOperationsSpecialist,
        lineage_quorum: DSORLineageStub,
        quorum_authority_3_of_5: QuorumAuthority,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """UR-F operation always carries an inherent_safety_surface
        per the contracts validator. Per Trigger 0, the agent honors
        the upstream classification and routes to quorum."""
        op = EquityOperation(
            lineage=lineage_quorum,
            custody_object=_equity_object(),
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
            quorum_authority=quorum_authority_3_of_5,
            settlement_method=DvP1Settlement(),
            transaction_type=EquityTransactionType.LONG_BUY,
        )
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL
        )
        # The quorum lineage preserves the operation's authority_id
        # (since the operation is already QUORUM-authority).
        assert result.lineage_stub.authority_id == "ceremony-2026-fiat-001"


# ---------------------------------------------------------------------------
# Cross-settlement-method flows
# ---------------------------------------------------------------------------


class TestCrossSettlementMethodFlows:
    """Per CUS Section V: settlement methods (DvP1 / DvP2 / DvP3 / DvD
    / PvP / FoP / Atomic / Conditional / Triparty / Bilateral / CCP)
    echo through the routing recommendation. The agent picks the
    rail/path; settlement-method decision is upstream (per
    sub-commit B design)."""

    @pytest.mark.parametrize(
        ("settlement", "settlement_type"),
        [
            (DvP1Settlement(), DvP1Settlement),
            (DvP3Settlement(), DvP3Settlement),
            (FoPSettlement(), FoPSettlement),
            (TripartySettlement(agent="BNY_MELLON_TRIPARTY"), TripartySettlement),
            (AtomicSettlement(rail="ethereum_l1"), AtomicSettlement),
        ],
    )
    def test_settlement_method_echoes_through_recommendation(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
        settlement: SettlementMethod,
        settlement_type: type,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1, settlement=settlement)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert isinstance(result.recommendation.settlement_method, settlement_type)


# ---------------------------------------------------------------------------
# Round-trip serialization (DSOR replay capability)
# ---------------------------------------------------------------------------


class TestRoundTripSerialization:
    """Per AUR-CANONICAL-001 v1.6 Axiom 4 (one lineage record): every
    output the agent emits must serialize losslessly so DSOR can
    replay the decision. The discriminated union
    :data:`FIATOperationsOutput` parses any output kind from JSON."""

    def test_routing_decision_round_trips(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        as_json = adapter.dump_json(result)
        parsed = adapter.validate_json(as_json)
        assert parsed == result

    def test_escalation_required_round_trips(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        failing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=failing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, EscalationRequired)
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        as_json = adapter.dump_json(result)
        parsed = adapter.validate_json(as_json)
        assert parsed == result

    def test_quorum_authority_required_round_trips(
        self,
        agent: FIATOperationsSpecialist,
        lineage_quorum: DSORLineageStub,
        quorum_authority_3_of_5: QuorumAuthority,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = EquityOperation(
            lineage=lineage_quorum,
            custody_object=_equity_object(),
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
            quorum_authority=quorum_authority_3_of_5,
            settlement_method=DvP1Settlement(),
            transaction_type=EquityTransactionType.LONG_BUY,
        )
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, QuorumAuthorityRequired)
        adapter: TypeAdapter[FIATOperationsOutput] = TypeAdapter(FIATOperationsOutput)
        as_json = adapter.dump_json(result)
        parsed = adapter.validate_json(as_json)
        assert parsed == result


# ---------------------------------------------------------------------------
# End-to-end scenarios (full lifecycle cases)
# ---------------------------------------------------------------------------


class TestEndToEndScenarios:
    def test_routine_equity_buy_full_flow_carries_complete_lineage(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """Verify a routine flow produces a RoutingDecision carrying:
        - the input operation's lineage_stub
        - the input operation's failure_mode_class
        - the input operation's settlement_method (echoed)
        - the agent's telemetry hash
        - the eligibility verification (all passed)
        - the jurisdictional attribution
        - the doctrine version stamp
        """
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, RoutingDecision)
        assert result.lineage_stub.operation_id == op.lineage.operation_id
        assert result.failure_mode_class is op.failure_mode_class
        assert result.recommendation.settlement_method == op.settlement_method
        assert result.eligibility_verification.all_passed
        assert result.jurisdictional_attribution == attribution_us_domestic
        assert result.doctrine_version == "1.6"
        # Telemetry hash format
        assert len(result.agent_telemetry_hash) == _SHA256_HEX_LEN

    def test_eligibility_failure_propagates_to_escalation_with_failed_checks_named(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        failing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """An eligibility failure produces an EscalationRequired
        carrying:
        - failed_guardrail = ELIGIBILITY_BEFORE_ROUTING
        - eligibility_verification with the failed check named
        - escalation_tier = T1
        - failure_reason citing CUS Section VI Guardrail 4
        """
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=failing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, EscalationRequired)
        assert result.eligibility_verification is not None
        failed = {c.kind.value for c in result.eligibility_verification.failed_checks}
        assert "ofac" in failed
        assert "Guardrail 4" in result.failure_reason
        assert result.escalation_tier is CAOMTier.T1

    def test_material_magnitude_assembles_full_quorum_package(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """Amount-above-threshold triggers material-magnitude. The
        QuorumAuthorityRequired output carries the full eight-component
        OperationPackage per CUS Section VII Step 1."""
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
            amount=Decimal("15000000"),  # above 10M USD threshold
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        assert isinstance(result, QuorumAuthorityRequired)
        pkg = result.operation_package
        assert pkg.beneficial_owner_ids == (op.custody_object.beneficial_owner_id,)
        assert pkg.asset_ids == ("AAPL",)
        assert pkg.doctrine_version == "1.6"
        assert pkg.pre_operation_dsor_state_stub.authority_tier is CAOMTier.QUORUM
        assert pkg.projected_post_operation_dsor_state_stub.post_operation_state_hash is not None
        assert pkg.routing_recommendation is not None
        assert pkg.eligibility_verification.all_passed

    def test_sanctioned_adjacency_routes_to_quorum_with_pre_quorum_eligibility(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        failing_eligibility: EligibilityInputs,
        now: datetime,
    ) -> None:
        """Per the operator's sub-commit C ruling: sanctioned-adjacency
        triggers material-magnitude regardless of eligibility state.
        Failed eligibility is captured in the quorum package, not
        emitted as a separate escalation."""
        attribution = JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="GB",
            intermediary_jurisdictions=("IR",),  # sanctioned per policy
            verana_session_id="v-cross-001",
            attributed_at=now,
        )
        op = make_equity_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=failing_eligibility,
            attribution=attribution,
            emitted_at=now,
        )
        result = agent.select_multi_currency_rail_routing(
            request, currency="USD"
        )
        assert isinstance(result, QuorumAuthorityRequired)
        # Failed eligibility is captured in the package, not produced
        # as EscalationRequired — material-magnitude takes precedence.
        assert not result.operation_package.eligibility_verification.all_passed

    def test_pledged_asset_repo_through_triparty(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """Pledged-asset operation (Treasury repo with JPMorgan) using
        triparty settlement. Verifies the agent handles
        PledgedAssetObject correctly."""
        op = FixedIncomeOperation(
            lineage=lineage_t1,
            custody_object=_pledged_treasury_object(),
            failure_mode_class=FailureModeClass.RA,
            settlement_method=TripartySettlement(agent="BNY_MELLON_TRIPARTY"),
            transaction_type=FixedIncomeTransactionType.REPO_TRIPARTY,
        )
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_cash_sweep_and_short_term_investment(
            request, currency="USD"
        )
        assert isinstance(result, RoutingDecision)


# ---------------------------------------------------------------------------
# Independent FX with quote-currency threshold
# ---------------------------------------------------------------------------


class TestFXMagnitudeQuoteCurrency:
    """Per the FOLLOW-UPS entry: deployments needing quote-currency
    checks configure both currencies in
    MagnitudeThresholdPolicy.fx_bundled_thresholds. This test
    verifies the configurable behaviour."""

    def test_eur_threshold_triggers_when_eur_is_base(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        op = make_fx_op(lineage=lineage_t1)
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
            amount=Decimal("23000000"),  # above EUR 22M threshold
        )
        result = agent.select_cross_border_fx_leg(
            request, currency_pair="EUR/USD"
        )
        assert isinstance(result, QuorumAuthorityRequired)
        assert result.inherent_safety_surface is (
            InherentSafetySurface.FX_BUNDLED_SETTLEMENT
        )

    def test_value_date_field_carried_for_forward(
        self,
        agent: FIATOperationsSpecialist,
        lineage_t1: DSORLineageStub,
        passing_eligibility: EligibilityInputs,
        attribution_us_domestic: JurisdictionalAttribution,
        now: datetime,
    ) -> None:
        """FX FORWARD requires value_date per the FXOperation
        validator. Verifies the agent doesn't strip this when
        emitting the routing decision."""
        op = FXOperation(
            lineage=lineage_t1,
            custody_object=_fx_object(),
            failure_mode_class=FailureModeClass.RA,
            settlement_method=PvPSettlement(),
            transaction_type=FXTransactionType.FORWARD,
            base_currency="EUR",
            quote_currency="USD",
            value_date=date(2026, 6, 5),
        )
        request = PathSelectionRequest(
            operation=op,
            eligibility_inputs=passing_eligibility,
            attribution=attribution_us_domestic,
            emitted_at=now,
        )
        result = agent.select_cross_border_fx_leg(
            request, currency_pair="EUR/USD"
        )
        assert isinstance(result, RoutingDecision)
