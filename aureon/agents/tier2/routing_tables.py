"""Kaladan-managed approved-paths registry for the FIAT Operations Specialist.

Per AUR-CANONICAL-001 v1.6 Section II (Thifur-J Guardrail "approved
paths only — J selects from the Kaladan-defined routing and lifecycle
set, never generates new") and AUR-CUSTODY-001 v1.0 Section VI line
634 (FIAT-leg rendering of the approved-paths-only guardrail).

Doctrine basis. Per AUR-CANONICAL-001 v1.6 Section IV (Layer 2 —
Kaladan — Lifecycle Orchestration), Kaladan owns the "governed intent
packet" and the path/lifecycle inventory the execution agents select
from. The FIAT Operations Specialist consults this registry on every
path-selection decision (Guardrail 1) and produces an
:class:`~aureon.agents.tier2.outputs.EscalationRequired` with
``failed_guardrail = APPROVED_PATHS_ONLY`` when no approved path
matches the operation requirements.

Scope of this module. Per the build prompt: "start with a
representative non-exhaustive set; flag exhaustive enumeration as
out-of-scope follow-up." Exhaustive enumeration of all eligible
correspondent banks, all sub-custodian relationships, all MMF
destinations, and all global large-value systems requires external
data sources (SWIFT BIC directory, depository membership rosters,
fund-vendor data). Tracked in ``FOLLOW-UPS.md``.

What this module guarantees structurally:

- Every approved path declares the path-selection dimension(s) it
  serves (paths can serve multiple — e.g., Fedwire is both a
  multi-currency rail under Dimension 1 and a large-value payment
  system under Dimension 5).
- Path identifiers are unique within a registry instance (the agent's
  ``chosen_path`` field on a :class:`RoutingDecision` resolves to at
  most one approved path).
- Rail-class paths (Dimensions 1 and 5) declare their finality model
  (per AUR-CUSTODY-001 v1.0 Section V settlement methods); the agent's
  Dimension 5 selection logic queries on finality profile.
- Correspondent banking paths (Dimension 2) declare a BIC.
- The registry is frozen — once constructed, the path inventory does
  not mutate. Doctrine-modifying changes to the inventory (adding,
  removing, or modifying approved paths) flow through the
  propose/approve workflow per AUR-CANONICAL-001 v1.6 Section VII.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.agents.tier2.outputs import PathSelectionDimension


class FinalityModel(StrEnum):
    """Settlement finality profile per AUR-CUSTODY-001 v1.0 Section V.

    Used on rail-class paths (Dimensions 1 and 5) to support the
    Dimension 5 selection criterion: "settlement risk profile (Fedwire
    is gross-real-time-final; CHIPS uses bilateral and multilateral
    net with finality at end of day; SWIFT correspondent depends on
    correspondent bank operational status)."
    """

    RTGS_FINAL = "rtgs_final"
    """Gross real-time settlement with immediate finality. Examples:
    Fedwire (US), Target2 (Eurozone), CHAPS (UK)."""

    NET_FINAL_EOD = "net_final_eod"
    """Multilateral or bilateral net settlement with finality at end
    of day or end of cycle. Examples: CHIPS (US), Zengin (Japan)."""

    BATCH_FINAL = "batch_final"
    """Batch settlement with finality on batch posting. Examples:
    ACH (US, multiple settlement windows per day)."""

    CORRESPONDENT_DEPENDENT = "correspondent_dependent"
    """Finality depends on correspondent bank operational status and
    timing. Examples: SWIFT MT103 / MT202 routed through correspondent
    banking arrangements."""

    ATOMIC_PVP = "atomic_pvp"
    """Atomic payment-versus-payment settlement. Examples: CLS
    (Continuous Linked Settlement) for eligible currency pairs."""


class OperationalHours(StrEnum):
    """Operational hours profile of an approved path.

    Used by the Dimension 1 selection logic when matching urgency to
    eligible paths. Per AUR-CUSTODY-001 v1.0 Section X (Forward-State
    Framework), 24/7 operational continuity is the forward-state
    default; the agent supports 24/7 paths today and continues to
    support business-hours paths during transition.
    """

    BUSINESS_HOURS = "business_hours"
    """Standard business-hours window with cutoffs. Examples: ACH,
    most correspondent banking arrangements."""

    EXTENDED_HOURS = "extended_hours"
    """Extended operational window (e.g., Fedwire's ~21-hour daily
    operating window)."""

    CONTINUOUS_24_7 = "continuous_24_7"
    """Continuous 24/7/365 operation. Examples: FedNow, atomic
    settlement on tokenized rails."""


_RAIL_DIMENSIONS: frozenset[PathSelectionDimension] = frozenset(
    {
        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
    }
)


class ApprovedPath(BaseModel):
    """A single approved path managed by the Kaladan routing tables.

    Per AUR-CANONICAL-001 v1.6 Section II Thifur-J Guardrail "approved
    paths only" and AUR-CUSTODY-001 v1.0 Section VI line 634 (FIAT-leg
    rendering). The FIAT Operations Specialist's path-selection
    methods enumerate paths from the registry; they never construct
    new paths at decision time.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    path_id: str = Field(
        min_length=1,
        description=(
            "Canonical identifier of the path. Unique within a "
            ":class:`RoutingTables` instance. The agent's "
            "``chosen_path`` field on a "
            ":class:`~aureon.agents.tier2.outputs.RoutingRecommendation` "
            "must match a ``path_id`` in the registry."
        ),
    )
    dimensions: frozenset[PathSelectionDimension] = Field(
        description=(
            "The path-selection dimension(s) this path serves. A path "
            "may serve multiple dimensions — Fedwire is both a "
            "multi-currency rail (Dimension 1) and a large-value "
            "payment system (Dimension 5)."
        ),
    )
    description: str = Field(
        min_length=1,
        description=(
            "Short doctrine-cited description of the path. Names the "
            "doctrine subsection that justifies the path's inclusion "
            "in the registry."
        ),
    )
    eligible_currencies: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "ISO 4217 currency codes the path can settle. Empty for "
            "paths that are currency-agnostic (e.g., depository "
            "membership operations on a securities-only path)."
        ),
    )
    eligible_jurisdictions: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "ISO 3166-1 alpha-2 / alpha-3 jurisdictions the path "
            "operates within. Empty for paths that are "
            "jurisdiction-agnostic (e.g., CLS PvP, which operates "
            "across CLS member jurisdictions globally)."
        ),
    )
    finality_model: FinalityModel | None = Field(
        default=None,
        description=(
            "Settlement finality profile. Required for rail-class "
            "paths (Dimensions 1 and 5) per AUR-CUSTODY-001 v1.0 "
            "Section V; None for paths where finality is not the "
            "primary characteristic (e.g., depository membership)."
        ),
    )
    operational_hours: OperationalHours = Field(
        default=OperationalHours.BUSINESS_HOURS,
        description="Operational hours profile of the path.",
    )
    correspondent_bic: str | None = Field(
        default=None,
        description=(
            "BIC of the correspondent bank for paths that route "
            "through correspondent banking. Required for Dimension 2 "
            "(correspondent banking coordination) paths; None for "
            "non-correspondent paths."
        ),
    )
    pvp_eligible_pairs: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "Currency pairs the path supports for PvP settlement, "
            "expressed as 'XXX/YYY' uppercase strings (e.g., "
            "'EUR/USD'). Populated for Dimension 3 PvP paths (CLS "
            "and analogous); empty for non-FX-PvP paths."
        ),
    )

    @model_validator(mode="after")
    def _validate_dimensions_non_empty(self) -> Self:
        """A path that serves no dimension is meaningless. Per
        Guardrail 1 the agent enumerates paths *by dimension*; a
        dimensionless path is unreachable from any selection method."""
        if not self.dimensions:
            raise ValueError(
                f"ApprovedPath {self.path_id!r} must serve at least "
                f"one path-selection dimension; per AUR-CANONICAL-001 "
                f"v1.6 Section II Thifur-J Guardrail 1 the agent "
                f"enumerates paths by dimension."
            )
        return self

    @model_validator(mode="after")
    def _validate_rail_paths_carry_finality(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section V: rail-class paths
        (Dimensions 1 and 5) must declare their finality model so the
        Dimension 5 selection logic can match on settlement risk
        profile."""
        if self.dimensions & _RAIL_DIMENSIONS and self.finality_model is None:
            raise ValueError(
                f"ApprovedPath {self.path_id!r} serves a rail-class "
                f"dimension (MULTI_CURRENCY_RAIL_ROUTING or "
                f"LARGE_VALUE_PAYMENT_SYSTEM) but does not declare a "
                f"finality_model. Per AUR-CUSTODY-001 v1.0 Section V "
                f"and Section VI Dimension 5 (settlement risk profile "
                f"selection), every rail-class path must declare its "
                f"finality profile."
            )
        return self

    @model_validator(mode="after")
    def _validate_correspondent_paths_carry_bic(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VI Dimension 2:
        correspondent-banking-coordination paths must identify the
        correspondent bank (BIC) so the agent's selection records
        which correspondent was chosen."""
        if (
            PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION in self.dimensions
            and not self.correspondent_bic
        ):
            raise ValueError(
                f"ApprovedPath {self.path_id!r} serves "
                f"CORRESPONDENT_BANKING_COORDINATION but does not "
                f"declare a correspondent_bic. Per AUR-CUSTODY-001 "
                f"v1.0 Section VI Dimension 2, correspondent-banking "
                f"paths must identify the correspondent bank."
            )
        return self

    @model_validator(mode="after")
    def _validate_pvp_pairs_only_on_fx_dimension(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VI Dimension 3:
        ``pvp_eligible_pairs`` is only meaningful on cross-border FX
        leg coordination paths; populating it on a non-FX path is a
        modeling error."""
        if (
            self.pvp_eligible_pairs
            and PathSelectionDimension.CROSS_BORDER_FX_LEG not in self.dimensions
        ):
            raise ValueError(
                f"ApprovedPath {self.path_id!r} declares "
                f"pvp_eligible_pairs but does not serve "
                f"CROSS_BORDER_FX_LEG. PvP eligibility is only "
                f"meaningful on Dimension 3 paths per AUR-CUSTODY-001 "
                f"v1.0 Section VI."
            )
        return self


class RoutingTables(BaseModel):
    """The Kaladan-managed approved-paths registry.

    Per AUR-CANONICAL-001 v1.6 Section IV (Layer 2 — Kaladan —
    Lifecycle Orchestration). The agent injects a registry instance at
    construction (subsequent build module:
    :mod:`aureon.agents.tier2.fiat_operations_specialist`); per-decision
    queries enumerate matching paths or return empty (which the agent
    converts to an
    :class:`~aureon.agents.tier2.outputs.EscalationRequired` with
    ``failed_guardrail = APPROVED_PATHS_ONLY``).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    paths: tuple[ApprovedPath, ...] = Field(
        description=(
            "All approved paths in the registry. Path identifiers are "
            "unique across the registry."
        ),
    )

    @model_validator(mode="after")
    def _validate_unique_path_ids(self) -> Self:
        """Per Guardrail 1 / Guardrail 3 (no settlement without
        approval lineage): the agent's ``chosen_path`` must resolve
        to at most one approved path so the lineage is unambiguous."""
        seen: set[str] = set()
        for path in self.paths:
            if path.path_id in seen:
                raise ValueError(
                    f"RoutingTables contains duplicate path_id "
                    f"{path.path_id!r}; path identifiers must be "
                    f"unique so the agent's chosen_path resolves to "
                    f"exactly one approved path per Guardrail 3."
                )
            seen.add(path.path_id)
        return self

    def find_path(self, path_id: str) -> ApprovedPath | None:
        """Return the approved path with the given identifier, or
        None if no such path exists.

        Used by the agent to verify that a candidate ``chosen_path``
        is in the registry before emitting a
        :class:`~aureon.agents.tier2.outputs.RoutingDecision`.
        """
        for path in self.paths:
            if path.path_id == path_id:
                return path
        return None

    def is_approved(
        self,
        path_id: str,
        dimension: PathSelectionDimension,
    ) -> bool:
        """Return True when the given path identifier is approved for
        the given dimension.

        Per Guardrail 1: a path approved for one dimension is not
        automatically approved for another. The agent's selection
        logic checks both that the path exists and that it serves
        the dimension the agent is selecting in.
        """
        path = self.find_path(path_id)
        return path is not None and dimension in path.dimensions

    def for_dimension(
        self,
        dimension: PathSelectionDimension,
    ) -> tuple[ApprovedPath, ...]:
        """Return all approved paths that serve the given dimension."""
        return tuple(p for p in self.paths if dimension in p.dimensions)

    def find_rail_paths(
        self,
        currency: str,
        jurisdiction: str | None = None,
        finality_model: FinalityModel | None = None,
    ) -> tuple[ApprovedPath, ...]:
        """Dimension 1 / Dimension 5 query: rail paths matching the
        criteria.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimensions 1 and 5: the
        agent selects among rail paths by currency, jurisdiction
        (when constrained), and optionally finality profile (Dimension
        5). Returns the eligible candidate set; the agent's selection
        logic chooses the best fit.
        """
        candidates = tuple(
            p
            for p in self.paths
            if p.dimensions & _RAIL_DIMENSIONS
            and currency in p.eligible_currencies
            and (jurisdiction is None or jurisdiction in p.eligible_jurisdictions)
            and (finality_model is None or p.finality_model is finality_model)
        )
        return candidates

    def find_correspondent_paths(
        self,
        currency: str,
        jurisdiction: str | None = None,
    ) -> tuple[ApprovedPath, ...]:
        """Dimension 2 query: correspondent banking paths matching
        the criteria.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 2: when direct
        large-value system access is impractical for a jurisdiction,
        the agent selects a correspondent bank routing.
        """
        return tuple(
            p
            for p in self.paths
            if PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION in p.dimensions
            and currency in p.eligible_currencies
            and (jurisdiction is None or jurisdiction in p.eligible_jurisdictions)
        )

    def find_fx_pvp_paths(
        self,
        currency_pair: str,
    ) -> tuple[ApprovedPath, ...]:
        """Dimension 3 query: cross-border FX paths supporting PvP
        for the given currency pair.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 3: select among
        CLS PvP (for eligible pairs), on-us, bilateral PvP, and
        traditional gross when PvP is unavailable. Pair format is
        ``'XXX/YYY'`` uppercase ISO 4217.
        """
        normalized = currency_pair.upper()
        return tuple(
            p
            for p in self.paths
            if PathSelectionDimension.CROSS_BORDER_FX_LEG in p.dimensions
            and normalized in p.pvp_eligible_pairs
        )

    def find_depository_paths(
        self,
        jurisdiction: str,
    ) -> tuple[ApprovedPath, ...]:
        """Dimension 4 query: depository / sub-custodian paths
        operating within the given jurisdiction.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 4: for
        jurisdictions where Aureon-governed custody can access either
        direct depository membership or sub-custodian intermediation,
        the routing decision involves both options.
        """
        return tuple(
            p
            for p in self.paths
            if PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN in p.dimensions
            and jurisdiction in p.eligible_jurisdictions
        )

    def find_fed_operation_paths(self) -> tuple[ApprovedPath, ...]:
        """Dimension 6 query: Federal Reserve operation paths.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 6: Discount
        Window, SRF, RRF, Federal Reserve account operations.
        """
        return self.for_dimension(PathSelectionDimension.FED_RELATED_OPERATION)

    def find_cash_sweep_paths(
        self,
        currency: str,
    ) -> tuple[ApprovedPath, ...]:
        """Dimension 7 query: cash sweep destinations supporting the
        given currency.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 7: MMFs (CNAV /
        FNAV, government / prime), bank deposit programs, repo
        vehicles, tri-party repo arrangements.
        """
        return tuple(
            p
            for p in self.paths
            if PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT in p.dimensions
            and currency in p.eligible_currencies
        )


def default_routing_tables() -> RoutingTables:
    """A representative non-exhaustive set of approved paths.

    Per the build prompt: "start with a representative non-exhaustive
    set; flag exhaustive enumeration as out-of-scope follow-up."
    Exhaustive enumeration of all eligible correspondent banks, all
    sub-custodian relationships, all MMF destinations, and all global
    large-value systems requires external data sources and is deferred
    to operational specifications (FED-001 / INST-001) per
    ``FOLLOW-UPS.md``.

    The set covers all seven path-selection dimensions so the agent's
    structural behavior (selecting from approved paths only,
    escalating on no-match) is exercisable without needing the
    exhaustive registry.
    """
    return RoutingTables(
        paths=(
            # ---------------------------------------------------------
            # Dimensions 1 + 5 — Multi-currency rails / LVPS
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimensions 1, 5.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="fedwire",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description=(
                    "US Federal Reserve large-value RTGS — gross "
                    "real-time finality per AUR-CUSTODY-001 v1.0 "
                    "Section VI Dimension 5."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
                finality_model=FinalityModel.RTGS_FINAL,
                operational_hours=OperationalHours.EXTENDED_HOURS,
            ),
            ApprovedPath(
                path_id="chips",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description=(
                    "US Clearing House Interbank Payments System — "
                    "bilateral and multilateral net with finality at "
                    "end of day per AUR-CUSTODY-001 v1.0 Section VI "
                    "Dimension 5."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
                finality_model=FinalityModel.NET_FINAL_EOD,
            ),
            ApprovedPath(
                path_id="ach",
                dimensions=frozenset({PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING}),
                description=(
                    "US Automated Clearing House — batch settlement "
                    "across multiple windows per day per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 1."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
                finality_model=FinalityModel.BATCH_FINAL,
            ),
            ApprovedPath(
                path_id="target2",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description=(
                    "Eurozone large-value RTGS per AUR-CUSTODY-001 "
                    "v1.0 Section VI Dimension 5."
                ),
                eligible_currencies=frozenset({"EUR"}),
                eligible_jurisdictions=frozenset(
                    {"DE", "FR", "IT", "ES", "NL", "BE", "AT", "IE", "PT", "FI"}
                ),
                finality_model=FinalityModel.RTGS_FINAL,
            ),
            ApprovedPath(
                path_id="chaps",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description=(
                    "UK Clearing House Automated Payment System — "
                    "large-value RTGS per AUR-CUSTODY-001 v1.0 "
                    "Section VI Dimension 5."
                ),
                eligible_currencies=frozenset({"GBP"}),
                eligible_jurisdictions=frozenset({"GB"}),
                finality_model=FinalityModel.RTGS_FINAL,
            ),
            ApprovedPath(
                path_id="zengin",
                dimensions=frozenset({PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING}),
                description=(
                    "Japan Zengin domestic retail and business "
                    "payment system per AUR-CUSTODY-001 v1.0 Section "
                    "VI Dimension 1."
                ),
                eligible_currencies=frozenset({"JPY"}),
                eligible_jurisdictions=frozenset({"JP"}),
                finality_model=FinalityModel.NET_FINAL_EOD,
            ),
            ApprovedPath(
                path_id="swift_mt202_global",
                dimensions=frozenset(
                    {
                        PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING,
                        PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM,
                    }
                ),
                description=(
                    "SWIFT MT202 general financial institution "
                    "transfer for international correspondent "
                    "settlement per AUR-CUSTODY-001 v1.0 Section VI "
                    "Dimension 1."
                ),
                eligible_currencies=frozenset(
                    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"}
                ),
                eligible_jurisdictions=frozenset(),
                finality_model=FinalityModel.CORRESPONDENT_DEPENDENT,
            ),
            # ---------------------------------------------------------
            # Dimension 2 — Correspondent banking coordination
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimension 2.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="correspondent_citi_ny_usd",
                dimensions=frozenset(
                    {PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION}
                ),
                description=(
                    "Citi New York USD correspondent — global "
                    "correspondent for USD international settlement "
                    "per AUR-CUSTODY-001 v1.0 Section VI Dimension 2."
                ),
                eligible_currencies=frozenset({"USD"}),
                correspondent_bic="CITIUS33",
            ),
            ApprovedPath(
                path_id="correspondent_deutsche_bank_eur",
                dimensions=frozenset(
                    {PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION}
                ),
                description=(
                    "Deutsche Bank Frankfurt EUR correspondent per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 2."
                ),
                eligible_currencies=frozenset({"EUR"}),
                correspondent_bic="DEUTDEFF",
            ),
            ApprovedPath(
                path_id="correspondent_hsbc_london_gbp",
                dimensions=frozenset(
                    {PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION}
                ),
                description=(
                    "HSBC London GBP correspondent per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 2."
                ),
                eligible_currencies=frozenset({"GBP"}),
                correspondent_bic="HBUKGB4B",
            ),
            # ---------------------------------------------------------
            # Dimension 3 — Cross-border FX leg coordination
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimension 3.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="cls_pvp_g10",
                dimensions=frozenset({PathSelectionDimension.CROSS_BORDER_FX_LEG}),
                description=(
                    "CLS Continuous Linked Settlement PvP for G10 "
                    "currency pairs per AUR-CUSTODY-001 v1.0 Section "
                    "VI Dimension 3 (Herstatt-risk elimination)."
                ),
                finality_model=FinalityModel.ATOMIC_PVP,
                pvp_eligible_pairs=frozenset(
                    {
                        "EUR/USD",
                        "GBP/USD",
                        "USD/JPY",
                        "USD/CHF",
                        "USD/CAD",
                        "AUD/USD",
                        "EUR/GBP",
                        "EUR/JPY",
                    }
                ),
            ),
            # ---------------------------------------------------------
            # Dimension 4 — Depository vs sub-custodian routing
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimension 4.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="dtcc_us_direct",
                dimensions=frozenset({PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN}),
                description=(
                    "DTCC direct depository membership for US "
                    "securities per AUR-CUSTODY-001 v1.0 Section VI "
                    "Dimension 4."
                ),
                eligible_jurisdictions=frozenset({"US"}),
            ),
            ApprovedPath(
                path_id="euroclear_be_direct",
                dimensions=frozenset({PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN}),
                description=(
                    "Euroclear Bank Brussels direct depository "
                    "membership for European securities per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 4."
                ),
                eligible_jurisdictions=frozenset(
                    {"BE", "DE", "FR", "IT", "ES", "NL", "AT", "IE", "PT", "FI"}
                ),
            ),
            ApprovedPath(
                path_id="sub_custodian_emerging_markets",
                dimensions=frozenset({PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN}),
                description=(
                    "Sub-custodian network for emerging markets "
                    "where direct depository access is impractical "
                    "per AUR-CUSTODY-001 v1.0 Section VI Dimension 4."
                ),
                eligible_jurisdictions=frozenset(
                    {"BR", "MX", "ZA", "TR", "ID", "TH", "PH", "MY", "VN"}
                ),
            ),
            # ---------------------------------------------------------
            # Dimension 6 — Fed-related operations
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimension 6.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="fed_discount_window",
                dimensions=frozenset({PathSelectionDimension.FED_RELATED_OPERATION}),
                description=(
                    "Federal Reserve Discount Window borrowing — "
                    "primary credit, secondary credit, seasonal "
                    "credit per AUR-CUSTODY-001 v1.0 Section VI "
                    "Dimension 6."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
            ),
            ApprovedPath(
                path_id="fed_srf",
                dimensions=frozenset({PathSelectionDimension.FED_RELATED_OPERATION}),
                description=(
                    "Federal Reserve Standing Repo Facility per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 6."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
            ),
            ApprovedPath(
                path_id="fed_rrp",
                dimensions=frozenset({PathSelectionDimension.FED_RELATED_OPERATION}),
                description=(
                    "Federal Reserve Reverse Repo Facility per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 6."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
            ),
            ApprovedPath(
                path_id="fed_master_account",
                dimensions=frozenset({PathSelectionDimension.FED_RELATED_OPERATION}),
                description=(
                    "Federal Reserve master account operations for "
                    "entities with direct access per AUR-CUSTODY-001 "
                    "v1.0 Section VI Dimension 6."
                ),
                eligible_currencies=frozenset({"USD"}),
                eligible_jurisdictions=frozenset({"US"}),
            ),
            # ---------------------------------------------------------
            # Dimension 7 — Cash sweep and short-term investment
            # Per AUR-CUSTODY-001 v1.0 Section VI Dimension 7.
            # ---------------------------------------------------------
            ApprovedPath(
                path_id="mmf_government_cnav",
                dimensions=frozenset(
                    {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                ),
                description=(
                    "Government MMF — constant NAV per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 7."
                ),
                eligible_currencies=frozenset({"USD"}),
            ),
            ApprovedPath(
                path_id="mmf_prime_fnav",
                dimensions=frozenset(
                    {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                ),
                description=(
                    "Prime MMF — floating NAV per AUR-CUSTODY-001 "
                    "v1.0 Section VI Dimension 7."
                ),
                eligible_currencies=frozenset({"USD"}),
            ),
            ApprovedPath(
                path_id="bank_deposit_sweep",
                dimensions=frozenset(
                    {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                ),
                description=(
                    "FDIC-insured bank deposit sweep program per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 7."
                ),
                eligible_currencies=frozenset({"USD"}),
            ),
            ApprovedPath(
                path_id="tri_party_repo_bny",
                dimensions=frozenset(
                    {PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT}
                ),
                description=(
                    "BNY Mellon tri-party repo arrangement per "
                    "AUR-CUSTODY-001 v1.0 Section VI Dimension 7."
                ),
                eligible_currencies=frozenset({"USD"}),
            ),
        )
    )


__all__ = [
    "ApprovedPath",
    "FinalityModel",
    "OperationalHours",
    "RoutingTables",
    "default_routing_tables",
]
