"""Tests for the FIAT Operations Specialist routing tables registry.

Coverage standard matches the contracts layer: every model has positive
and negative tests for every validator. The default factory is
exercised against every dimension to confirm the representative set
covers the agent's seven path-selection dimensions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.agents.tier2.outputs import PathSelectionDimension
from aureon.agents.tier2.routing_tables import (
    ApprovedPath,
    FinalityModel,
    OperationalHours,
    RoutingTables,
    default_routing_tables,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_finality_model_members(self) -> None:
        """Per AUR-CUSTODY-001 v1.0 Section V settlement methods: the
        finality profiles the agent distinguishes."""
        assert set(FinalityModel) == {
            FinalityModel.RTGS_FINAL,
            FinalityModel.NET_FINAL_EOD,
            FinalityModel.BATCH_FINAL,
            FinalityModel.CORRESPONDENT_DEPENDENT,
            FinalityModel.ATOMIC_PVP,
        }

    def test_operational_hours_members(self) -> None:
        assert set(OperationalHours) == {
            OperationalHours.BUSINESS_HOURS,
            OperationalHours.EXTENDED_HOURS,
            OperationalHours.CONTINUOUS_24_7,
        }


# ---------------------------------------------------------------------------
# ApprovedPath validators
# ---------------------------------------------------------------------------


class TestApprovedPathValidators:
    def test_minimal_valid_path_constructs(self) -> None:
        path = ApprovedPath(
            path_id="test_path",
            dimensions=frozenset({PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}),
            description="Test path for cash sweep dimension.",
        )
        assert path.path_id == "test_path"
        assert path.operational_hours is OperationalHours.BUSINESS_HOURS

    def test_empty_dimensions_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must serve at least one"):
            ApprovedPath(
                path_id="bad",
                dimensions=frozenset(),
                description="Path with no dimension.",
            )

    def test_rail_dimension_without_finality_rejected(self) -> None:
        with pytest.raises(ValidationError, match="finality_model"):
            ApprovedPath(
                path_id="bad_rail",
                dimensions=frozenset({PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING}),
                description="Rail path missing finality.",
                eligible_currencies=frozenset({"USD"}),
            )

    def test_lvps_dimension_without_finality_rejected(self) -> None:
        with pytest.raises(ValidationError, match="finality_model"):
            ApprovedPath(
                path_id="bad_lvps",
                dimensions=frozenset({PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM}),
                description="LVPS path missing finality.",
                eligible_currencies=frozenset({"USD"}),
            )

    def test_rail_dimension_with_finality_accepted(self) -> None:
        path = ApprovedPath(
            path_id="ok_rail",
            dimensions=frozenset({PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING}),
            description="Rail path with finality.",
            eligible_currencies=frozenset({"USD"}),
            finality_model=FinalityModel.RTGS_FINAL,
        )
        assert path.finality_model is FinalityModel.RTGS_FINAL

    def test_correspondent_dimension_without_bic_rejected(self) -> None:
        with pytest.raises(ValidationError, match="correspondent_bic"):
            ApprovedPath(
                path_id="bad_correspondent",
                dimensions=frozenset({PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION}),
                description="Correspondent path missing BIC.",
                eligible_currencies=frozenset({"USD"}),
            )

    def test_correspondent_dimension_with_bic_accepted(self) -> None:
        path = ApprovedPath(
            path_id="ok_correspondent",
            dimensions=frozenset({PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION}),
            description="Correspondent path with BIC.",
            eligible_currencies=frozenset({"USD"}),
            correspondent_bic="ABCDUS33",
        )
        assert path.correspondent_bic == "ABCDUS33"

    def test_pvp_pairs_on_non_fx_dimension_rejected(self) -> None:
        with pytest.raises(ValidationError, match="pvp_eligible_pairs"):
            ApprovedPath(
                path_id="bad_pvp",
                dimensions=frozenset({PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING}),
                description="Non-FX path with PvP pairs.",
                eligible_currencies=frozenset({"USD"}),
                finality_model=FinalityModel.RTGS_FINAL,
                pvp_eligible_pairs=frozenset({"EUR/USD"}),
            )

    def test_pvp_pairs_on_fx_dimension_accepted(self) -> None:
        path = ApprovedPath(
            path_id="ok_pvp",
            dimensions=frozenset({PathSelectionDimension.CROSS_BORDER_FX_LEG}),
            description="FX path with PvP pairs.",
            pvp_eligible_pairs=frozenset({"EUR/USD"}),
        )
        assert "EUR/USD" in path.pvp_eligible_pairs

    def test_path_serves_multiple_dimensions(self) -> None:
        """A path can serve multiple dimensions — Fedwire is both
        Dimension 1 (multi-currency rail) and Dimension 5 (LVPS)."""
        path = ApprovedPath(
            path_id="multi_dim",
            dimensions=frozenset(
                {
                    PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                    PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                }
            ),
            description="Multi-dimension path.",
            eligible_currencies=frozenset({"USD"}),
            finality_model=FinalityModel.RTGS_FINAL,
        )
        assert path.dimensions == {
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
        }

    def test_empty_path_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApprovedPath(
                path_id="",
                dimensions=frozenset({PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}),
                description="Empty id test.",
            )

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApprovedPath(
                path_id="test",
                dimensions=frozenset({PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}),
                description="",
            )

    def test_path_is_frozen(self) -> None:
        path = ApprovedPath(
            path_id="frozen_test",
            dimensions=frozenset({PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}),
            description="Frozen test.",
        )
        with pytest.raises(ValidationError):
            path.path_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RoutingTables registry behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def small_registry() -> RoutingTables:
    """A two-path registry covering Dimension 1 (Fedwire) and
    Dimension 7 (one MMF) for focused query tests."""
    return RoutingTables(
        paths=(
            ApprovedPath(
                path_id="fedwire_small",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description="Fedwire — small registry test.",
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
                finality_model=FinalityModel.RTGS_FINAL,
            ),
            ApprovedPath(
                path_id="mmf_small",
                dimensions=frozenset(
                    {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                ),
                description="MMF — small registry test.",
                eligible_currencies=frozenset({"USD"}),
            ),
        )
    )


class TestRoutingTablesRegistry:
    def test_duplicate_path_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate path_id"):
            RoutingTables(
                paths=(
                    ApprovedPath(
                        path_id="dup",
                        dimensions=frozenset(
                            {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                        ),
                        description="First.",
                    ),
                    ApprovedPath(
                        path_id="dup",
                        dimensions=frozenset(
                            {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                        ),
                        description="Second.",
                    ),
                )
            )

    def test_find_path_returns_match(self, small_registry: RoutingTables) -> None:
        path = small_registry.find_path("fedwire_small")
        assert path is not None
        assert path.path_id == "fedwire_small"

    def test_find_path_returns_none_for_unknown(
        self,
        small_registry: RoutingTables,
    ) -> None:
        assert small_registry.find_path("not_in_registry") is None

    def test_is_approved_true_for_matching_dimension(
        self,
        small_registry: RoutingTables,
    ) -> None:
        assert small_registry.is_approved(
            "fedwire_small",
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )
        assert small_registry.is_approved(
            "fedwire_small",
            PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
        )

    def test_is_approved_false_for_non_matching_dimension(
        self,
        small_registry: RoutingTables,
    ) -> None:
        """Per Guardrail 1: a path approved for one dimension is not
        automatically approved for another."""
        assert not small_registry.is_approved(
            "fedwire_small",
            PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT,
        )

    def test_is_approved_false_for_unknown_path(
        self,
        small_registry: RoutingTables,
    ) -> None:
        assert not small_registry.is_approved(
            "not_in_registry",
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        )

    def test_for_dimension_filters(self, small_registry: RoutingTables) -> None:
        rail_paths = small_registry.for_dimension(
            PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING
        )
        assert len(rail_paths) == 1
        assert rail_paths[0].path_id == "fedwire_small"

    def test_for_dimension_empty_when_no_match(
        self,
        small_registry: RoutingTables,
    ) -> None:
        # Small registry has no Dimension 6 paths
        fed_paths = small_registry.for_dimension(
            PathSelectionDimension.FED_RELATED_OPERATION
        )
        assert fed_paths == ()

    def test_registry_is_frozen(self, small_registry: RoutingTables) -> None:
        with pytest.raises(ValidationError):
            small_registry.paths = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Per-dimension query methods on the default registry
# ---------------------------------------------------------------------------


@pytest.fixture
def default_registry() -> RoutingTables:
    return default_routing_tables()


class TestPerDimensionQueries:
    def test_find_rail_paths_usd_us(self, default_registry: RoutingTables) -> None:
        """Dimension 1 query: USD rails operating in the US.
        Should return Fedwire, CHIPS, ACH (not Target2 / CHAPS /
        Zengin)."""
        paths = default_registry.find_rail_paths(currency="USD", jurisdiction="US")
        ids = {p.path_id for p in paths}
        assert ids == {"fedwire", "chips", "ach"}

    def test_find_rail_paths_usd_no_jurisdiction(
        self,
        default_registry: RoutingTables,
    ) -> None:
        """Without a jurisdiction filter, USD-eligible rail paths
        include the global SWIFT MT202."""
        paths = default_registry.find_rail_paths(currency="USD")
        ids = {p.path_id for p in paths}
        assert "swift_mt202_global" in ids

    def test_find_rail_paths_with_finality_filter(
        self,
        default_registry: RoutingTables,
    ) -> None:
        """Dimension 5 query: USD RTGS-final rails — only Fedwire."""
        paths = default_registry.find_rail_paths(
            currency="USD",
            jurisdiction="US",
            finality_model=FinalityModel.RTGS_FINAL,
        )
        ids = {p.path_id for p in paths}
        assert ids == {"fedwire"}

    def test_find_rail_paths_unknown_currency_returns_empty(
        self,
        default_registry: RoutingTables,
    ) -> None:
        """Per Guardrail 1: no-match returns empty so the agent
        produces APPROVED_PATHS_ONLY escalation."""
        paths = default_registry.find_rail_paths(currency="ZZZ", jurisdiction="ZZ")
        assert paths == ()

    def test_find_rail_paths_eur_returns_target2(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_rail_paths(currency="EUR", jurisdiction="DE")
        ids = {p.path_id for p in paths}
        assert "target2" in ids

    def test_find_correspondent_paths_usd(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_correspondent_paths(currency="USD")
        ids = {p.path_id for p in paths}
        assert "correspondent_citi_ny_usd" in ids
        # Eur/Gbp correspondents should not match a USD query
        assert "correspondent_deutsche_bank_eur" not in ids

    def test_find_correspondent_paths_eur(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_correspondent_paths(currency="EUR")
        ids = {p.path_id for p in paths}
        assert ids == {"correspondent_deutsche_bank_eur"}

    def test_find_correspondent_paths_unknown_currency(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_correspondent_paths(currency="ZZZ")
        assert paths == ()

    def test_find_fx_pvp_paths_eligible_pair(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_fx_pvp_paths("EUR/USD")
        ids = {p.path_id for p in paths}
        assert ids == {"cls_pvp_g10"}

    def test_find_fx_pvp_paths_normalises_case(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_fx_pvp_paths("eur/usd")
        ids = {p.path_id for p in paths}
        assert ids == {"cls_pvp_g10"}

    def test_find_fx_pvp_paths_ineligible_pair(
        self,
        default_registry: RoutingTables,
    ) -> None:
        """Per Dimension 3: when PvP is unavailable the agent falls
        back to other settlement; the registry returns empty so the
        agent's selection logic handles the fallback."""
        paths = default_registry.find_fx_pvp_paths("USD/ZZZ")
        assert paths == ()

    def test_find_depository_paths_us(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_depository_paths("US")
        ids = {p.path_id for p in paths}
        assert ids == {"dtcc_us_direct"}

    def test_find_depository_paths_emerging_market(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_depository_paths("BR")
        ids = {p.path_id for p in paths}
        assert ids == {"sub_custodian_emerging_markets"}

    def test_find_depository_paths_unknown_jurisdiction(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_depository_paths("ZZ")
        assert paths == ()

    def test_find_fed_operation_paths(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_fed_operation_paths()
        ids = {p.path_id for p in paths}
        assert ids == {
            "fed_discount_window",
            "fed_srf",
            "fed_rrp",
            "fed_master_account",
        }

    def test_find_cash_sweep_paths_usd(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_cash_sweep_paths("USD")
        ids = {p.path_id for p in paths}
        assert ids == {
            "mmf_government_cnav",
            "mmf_prime_fnav",
            "bank_deposit_sweep",
            "tri_party_repo_bny",
        }

    def test_find_cash_sweep_paths_unknown_currency(
        self,
        default_registry: RoutingTables,
    ) -> None:
        paths = default_registry.find_cash_sweep_paths("ZZZ")
        assert paths == ()


# ---------------------------------------------------------------------------
# default_routing_tables coverage
# ---------------------------------------------------------------------------


class TestDefaultRoutingTables:
    @pytest.mark.parametrize("dimension", list(PathSelectionDimension))
    def test_every_dimension_has_at_least_one_path(
        self,
        dimension: PathSelectionDimension,
        default_registry: RoutingTables,
    ) -> None:
        """Per the build prompt: the representative set covers all
        seven path-selection dimensions so the agent's structural
        behavior is exercisable."""
        paths = default_registry.for_dimension(dimension)
        assert len(paths) > 0, f"Dimension {dimension.value!r} has no approved paths"

    def test_default_registry_path_ids_unique(
        self,
        default_registry: RoutingTables,
    ) -> None:
        ids = [p.path_id for p in default_registry.paths]
        assert len(ids) == len(set(ids))

    def test_default_registry_includes_fedwire(
        self,
        default_registry: RoutingTables,
    ) -> None:
        path = default_registry.find_path("fedwire")
        assert path is not None
        assert path.finality_model is FinalityModel.RTGS_FINAL
        assert path.operational_hours is OperationalHours.EXTENDED_HOURS

    def test_default_registry_includes_cls_pvp(
        self,
        default_registry: RoutingTables,
    ) -> None:
        path = default_registry.find_path("cls_pvp_g10")
        assert path is not None
        assert "EUR/USD" in path.pvp_eligible_pairs
        assert path.finality_model is FinalityModel.ATOMIC_PVP

    def test_default_registry_correspondents_carry_bics(
        self,
        default_registry: RoutingTables,
    ) -> None:
        for path in default_registry.for_dimension(
            PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION
        ):
            assert path.correspondent_bic is not None
