"""FIAT Operations Specialist agent — Tier 2 Thifur-J.

Per AUR-CUSTODY-001 v1.0 Section VI (Custody-Specific Roles in the
Aureon Asset-Services Workforce — FIAT Operations Specialist) and
AUR-CANONICAL-001 v1.6 Section II (Thifur-J — JTAC bounded autonomy).

The FIAT Operations Specialist handles FIAT-leg operations within Tier
2 bounded autonomy across the asset-class universe, in 1:1 parity with
the Digital Asset Custody Specialist. The agent's path-selection scope
spans seven dimensions per Section VI lines 618-632; the J-class
guardrails apply to every decision per Section II Thifur-J and Section
VI line 634.

This module exposes:

- :class:`MagnitudeThresholdPolicy` — per-deployment magnitude
  thresholds the agent queries when determining whether an operation
  triggers a material-magnitude inherent-safety surface (per ruling on
  AUR-CUSTODY-001 v1.0 Section VII line 686 deferral to FED-001 /
  INST-001).
- :class:`FIATOperationsSpecialist` — the agent class. Construction
  injects the :class:`~aureon.agents.tier2.routing_tables.RoutingTables`
  registry (Guardrail 1 source) and the
  :class:`MagnitudeThresholdPolicy` (material-magnitude triggering).

Build composition. This module is built incrementally per the
operator-approved sub-commit plan:

- A — agent class skeleton + the five guardrail enforcement methods
  (J-class machinery). **This sub-commit.**
- B — the seven path-selection methods (Dimensions 1-7).
- C — the material-magnitude routing-to-quorum logic (OperationPackage
  assembly producing :class:`QuorumAuthorityRequired`).
- D — integration tests exercising the full agent flow.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.agents.tier2.eligibility import EligibilityInputs, verify_eligibility
from aureon.agents.tier2.outputs import (
    AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST,
    AgentClass,
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
from aureon.agents.tier2.routing_tables import (
    ApprovedPath,
    FinalityModel,
    RoutingTables,
)
from aureon.contracts import (
    CURRENT_DOCTRINE_VERSION,
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    InherentSafetySurface,
)


class MagnitudeThresholdPolicy(BaseModel):
    """Per-deployment magnitude thresholds for material-magnitude
    determination.

    Per AUR-CUSTODY-001 v1.0 Section VII line 686: "the specific
    thresholds are Sovereign- and Federate-specific and will be set
    in INST-001 and FED-001 respectively." Per the operator's ruling
    on the contracts-layer build, the agent enforces structural rules
    (whether a surface triggers based on policy state) but does not
    encode specific dollar values.

    The four threshold maps and the sanctioned-adjacency set are
    populated by the deployment's operational specification. Empty
    maps mean "no policy-triggered material-magnitude on this
    surface" — the agent only routes to quorum when the policy
    explicitly names a threshold the operation crosses.

    .. note::

       The threshold dicts are typed as mutable for ergonomics, but
       the model is frozen — callers should treat the dicts as
       immutable after construction. Doctrine-modifying changes to
       deployment thresholds flow through the propose/approve workflow
       per AUR-CANONICAL-001 v1.6 Section VII.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fiat_settlement_thresholds: dict[str, Decimal] = Field(
        default_factory=dict,
        description=(
            "Per-currency threshold (ISO 4217 → amount) above which a "
            "FIAT settlement triggers the FIAT_SETTLEMENT_MATERIAL "
            "inherent-safety surface (AUR-CUSTODY-001 v1.0 Section IX)."
        ),
    )
    lvps_finality_thresholds: dict[str, Decimal] = Field(
        default_factory=dict,
        description=(
            "Per-currency threshold above which a large-value payment "
            "system operation triggers the LARGE_VALUE_PAYMENT_FINALITY "
            "inherent-safety surface."
        ),
    )
    fx_bundled_thresholds: dict[str, Decimal] = Field(
        default_factory=dict,
        description=(
            "Per-currency threshold above which an FX bundled "
            "settlement triggers the FX_BUNDLED_SETTLEMENT inherent-"
            "safety surface."
        ),
    )
    sanctioned_adjacency_jurisdictions: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "ISO 3166-1 codes of jurisdictions whose cross-border "
            "adjacency triggers material-magnitude treatment per "
            "AUR-CUSTODY-001 v1.0 Section VI line 636 (cross-border "
            "settlements involving sanctioned-jurisdiction adjacency)."
        ),
    )

    def is_fiat_settlement_material(self, currency: str, amount: Decimal) -> bool:
        """Per FIAT_SETTLEMENT_MATERIAL surface: True when the per-
        currency threshold is set and the amount meets or exceeds it."""
        threshold = self.fiat_settlement_thresholds.get(currency)
        return threshold is not None and amount >= threshold

    def is_lvps_finality_material(self, currency: str, amount: Decimal) -> bool:
        """Per LARGE_VALUE_PAYMENT_FINALITY surface: True when the
        per-currency threshold is set and the amount meets or exceeds
        it."""
        threshold = self.lvps_finality_thresholds.get(currency)
        return threshold is not None and amount >= threshold

    def is_fx_bundled_material(self, currency: str, amount: Decimal) -> bool:
        """Per FX_BUNDLED_SETTLEMENT surface: True when the per-currency
        threshold is set and the amount meets or exceeds it."""
        threshold = self.fx_bundled_thresholds.get(currency)
        return threshold is not None and amount >= threshold

    def is_sanctioned_adjacent(self, jurisdiction: str) -> bool:
        """True when the jurisdiction is in the sanctioned-adjacency
        set, per AUR-CUSTODY-001 v1.0 Section VI line 636."""
        return jurisdiction in self.sanctioned_adjacency_jurisdictions

    @model_validator(mode="after")
    def _validate_thresholds_positive(self) -> Self:
        """Per Guardrail 4 / Section VII: a non-positive threshold is
        meaningless (every operation would cross it). The validator
        rejects any policy with non-positive entries."""
        for label, mapping in (
            ("fiat_settlement_thresholds", self.fiat_settlement_thresholds),
            ("lvps_finality_thresholds", self.lvps_finality_thresholds),
            ("fx_bundled_thresholds", self.fx_bundled_thresholds),
        ):
            for currency, value in mapping.items():
                if value <= Decimal(0):
                    raise ValueError(
                        f"MagnitudeThresholdPolicy.{label} entry for "
                        f"{currency!r} is {value!r}; thresholds must "
                        f"be positive (a non-positive threshold would "
                        f"trigger on every operation, defeating the "
                        f"material-magnitude distinction per "
                        f"AUR-CUSTODY-001 v1.0 Section VII)."
                    )
        return self


class PathSelectionRequest(BaseModel):
    """Common inputs every path-selection method takes.

    Per AUR-CUSTODY-001 v1.0 Section VI: every path-selection
    decision the FIAT Operations Specialist makes runs the same
    Guardrail 4 → Guardrail 5 → Guardrail 1 sequence over the same
    base inputs. This model factors those inputs out of every
    method's signature so per-dimension parameter lists stay focused
    on dimension-specific selection criteria.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CustodyOperationUnion = Field(
        description="The custody operation being routed.",
    )
    eligibility_inputs: EligibilityInputs = Field(
        description=(
            "Eligibility evidence the agent verifies before any "
            "routing decision (Guardrail 4)."
        ),
    )
    attribution: JurisdictionalAttribution | None = Field(
        default=None,
        description=(
            "Verana-assigned jurisdictional attribution (Guardrail "
            "5). None when attribution is missing — the agent "
            "produces an EscalationRequired in that case rather than "
            "routing past missing attribution."
        ),
    )
    emitted_at: datetime = Field(
        description="UTC timestamp at which the agent emits its output.",
    )
    amount: Decimal | None = Field(
        default=None,
        description=(
            "Monetary amount of the operation, in the operation's "
            "primary currency. Used by the agent's material-magnitude "
            "check (per AUR-CUSTODY-001 v1.0 Section VII line 686 "
            "deferral to FED-001/INST-001 thresholds). None when no "
            "monetary amount applies (e.g., a depository membership "
            "operation), in which case the amount-based material-"
            "magnitude check is skipped — the sanctioned-adjacency "
            "check (per CUS Section VI line 636) still applies "
            "independently of amount."
        ),
    )


class FIATOperationsSpecialist:
    """Tier 2 Thifur-J FIAT Operations Specialist agent.

    Per AUR-CUSTODY-001 v1.0 Section VI and AUR-CANONICAL-001 v1.6
    Section II (Thifur-J). The agent operates between the contracts
    layer (typed substrate it reads from and writes to) and the
    downstream layers (rails, DSOR, quorum). It produces routing
    decisions; it does not execute settlements.

    Construction injects two dependencies: the
    :class:`~aureon.agents.tier2.routing_tables.RoutingTables`
    registry (the Kaladan-managed approved-paths registry, Guardrail
    1 source) and the :class:`MagnitudeThresholdPolicy` (deployment-
    specific material-magnitude thresholds).

    This class is composed across four sub-commits per the operator's
    plan. Sub-commit A (this one) provides the agent class skeleton
    and the five guardrail enforcement methods. Sub-commits B, C, D
    add the path-selection methods, the material-magnitude routing,
    and the integration tests respectively.
    """

    def __init__(
        self,
        *,
        routing_tables: RoutingTables,
        magnitude_threshold_policy: MagnitudeThresholdPolicy,
    ) -> None:
        self._routing_tables = routing_tables
        self._magnitude_threshold_policy = magnitude_threshold_policy

    @property
    def routing_tables(self) -> RoutingTables:
        """The Kaladan-managed approved-paths registry the agent
        selects from per Guardrail 1."""
        return self._routing_tables

    @property
    def magnitude_threshold_policy(self) -> MagnitudeThresholdPolicy:
        """The deployment-specific magnitude thresholds the agent
        queries for material-magnitude determination."""
        return self._magnitude_threshold_policy

    @property
    def agent_class(self) -> AgentClass:
        """Identifier of this agent class — included in every output's
        telemetry hash domain per the operator's ruling on hash scope.
        """
        return AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST

    # ------------------------------------------------------------------
    # Guardrail 1 — Approved paths only
    # ------------------------------------------------------------------

    def enforce_approved_paths_only(
        self,
        path_id: str,
        dimension: PathSelectionDimension,
    ) -> bool:
        """Per AUR-CANONICAL-001 v1.6 Section II Thifur-J Guardrail 1
        and AUR-CUSTODY-001 v1.0 Section VI line 634: True when the
        path is approved for the given dimension in the injected
        routing tables; False otherwise.

        The agent's path-selection methods (sub-commit B) call this
        before emitting a routing decision. False on this method
        produces an :class:`EscalationRequired` with
        ``failed_guardrail = APPROVED_PATHS_ONLY``.
        """
        return self._routing_tables.is_approved(path_id, dimension)

    # ------------------------------------------------------------------
    # Guardrail 4 — Eligibility before routing
    # ------------------------------------------------------------------

    def enforce_eligibility(
        self,
        eligibility_inputs: EligibilityInputs,
    ) -> EligibilityVerification:
        """Per AUR-CUSTODY-001 v1.0 Section VI line 634 (FIAT-leg
        rendering of Guardrail 4): runs the five eligibility checks
        and returns the verification.

        Delegates to :func:`aureon.agents.tier2.eligibility.verify_eligibility`
        — the agent's role is to gather the inputs, call the verifier,
        and route on the result. Verification with
        ``all_passed = False`` produces an :class:`EscalationRequired`
        with ``failed_guardrail = ELIGIBILITY_BEFORE_ROUTING``.
        """
        return verify_eligibility(eligibility_inputs)

    # ------------------------------------------------------------------
    # Guardrail 5 — Jurisdictional attribution before execution
    # ------------------------------------------------------------------

    def enforce_jurisdictional_attribution(
        self,
        attribution: JurisdictionalAttribution | None,
    ) -> bool:
        """Per AUR-CANONICAL-001 v1.6 Section II (Layer 0 — Verana —
        Network Governance, lines 121-129) and Axiom 8 (Verana
        Autonomous Block, line 199): True when Verana has assigned a
        jurisdictional attribution; False when the attribution is
        missing.

        Note on the doctrine erratum: AUR-CUSTODY-001 v1.0 Section VI
        line 634 cites "Section VIII" as the authority for Verana
        jurisdictional attribution. That citation is wrong — Section
        VIII is the Institutional Licensing Thesis. The correct
        citation is Section II Layer 0 plus Axiom 8 as used here.
        Tracked in ``FOLLOW-UPS.md``.

        Per the build prompt: "the agent's output includes the
        jurisdictional attribution; missing attribution fails
        validation." Every routing decision the agent emits carries
        an attribution — domestic operations carry an attribution
        with originating == receiving and no intermediaries; cross-
        border operations carry attribution naming the originating,
        receiving, and any intermediary jurisdictions.
        """
        return attribution is not None

    # ------------------------------------------------------------------
    # Guardrail 3 — No settlement without approval lineage
    # ------------------------------------------------------------------

    def compute_telemetry_hash(
        self,
        operation_id: str,
        decision_kind: str,
        ordered_inputs_signature: tuple[str, ...],
    ) -> str:
        """Per AUR-CANONICAL-001 v1.6 Axiom 1 ("SHA-256 audit hash")
        and the operator's ruling on telemetry hash scope: SHA-256
        over the canonical serialization of (operation_id,
        doctrine_version, decision_kind, agent_class,
        ordered_inputs_signature).

        The agent_class identifier is incorporated so future audits
        can distinguish FIAT Operations Specialist decisions from
        decisions produced by the (forthcoming) Digital Asset Custody
        Specialist or other agent classes that will eventually exist.

        ``ordered_inputs_signature`` is an ordered tuple of strings
        representing the inputs that materially influenced the
        decision (eligibility result identifier, gate consultation
        identifier if present, chosen path identifier, FX leg
        sequencing identifier if applicable). Order matters — same
        inputs in different orders produce different hashes.
        """
        components = (
            operation_id,
            CURRENT_DOCTRINE_VERSION,
            decision_kind,
            self.agent_class,
            *ordered_inputs_signature,
        )
        canonical = "|".join(components)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Guardrail 2 — Doctrine over code (meta-guardrail)
    # ------------------------------------------------------------------

    def build_doctrine_over_code_escalation(
        self,
        *,
        operation_id: str,
        lineage_stub: DSORLineageStub,
        cascade_guardrail: JClassGuardrail,
        cascade_failure_description: str,
        external_instruction: str,
        emitted_at: datetime,
        attempted_dimension: PathSelectionDimension | None = None,
    ) -> EscalationRequired:
        """Per AUR-CANONICAL-001 v1.6 Axiom 5 ("doctrine over code")
        and AUR-CUSTODY-001 v1.0 Section VI line 634 (FIAT-leg
        rendering of Guardrail 2): build an
        :class:`EscalationRequired` for a doctrine-over-code hold.

        Per the operator's ruling on Guardrail 2 as a meta-guardrail:
        Guardrail 2 fires when an external instruction would cause
        one of guardrails 1, 3, 4, or 5 to be violated. The cascade
        names the underlying guardrail; the failure_reason text
        attributes both Guardrail 2 and the cascaded guardrail per
        the format named in the ruling.

        ``cascade_guardrail`` cannot itself be DOCTRINE_OVER_CODE —
        the output schema's validator enforces that at construction.
        """
        failure_reason = (
            f"Doctrine-over-code hold per AUR-CUSTODY-001 v1.0 "
            f"Section VI Guardrail 2: external instruction conflicts "
            f"with {cascade_guardrail.value} — "
            f"{cascade_failure_description}"
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=operation_id,
            decision_kind="escalation_required",
            ordered_inputs_signature=(
                "doctrine_over_code",
                cascade_guardrail.value,
                # Hash a fingerprint of the instruction rather than
                # echoing the full instruction text into the hash —
                # the hash records the agent's response to the
                # instruction class, not the instruction body.
                hashlib.sha256(external_instruction.encode("utf-8")).hexdigest(),
            ),
        )
        return EscalationRequired(
            operation_id=lineage_stub.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=lineage_stub,
            emitted_at=emitted_at,
            failed_guardrail=JClassGuardrail.DOCTRINE_OVER_CODE,
            cascade_guardrail=cascade_guardrail,
            failure_reason=failure_reason,
            # Doctrine-over-code holds escalate to T2 (Compliance
            # Officer / Head of Risk) per CAOM-001 — the agent does
            # not unilaterally override an external instruction, but
            # the resolution of doctrine-vs-instruction conflict is
            # a governance decision.
            escalation_tier=CAOMTier.T2,
            attempted_dimension=attempted_dimension,
            conflicting_external_instruction=external_instruction,
        )

    # ------------------------------------------------------------------
    # Output builders (private — composed by the path-selection methods)
    # ------------------------------------------------------------------

    def _build_eligibility_escalation(
        self,
        *,
        operation: CustodyOperationUnion,
        verification: EligibilityVerification,
        attempted_dimension: PathSelectionDimension,
        emitted_at: datetime,
    ) -> EscalationRequired:
        """Build an EscalationRequired for a Guardrail 4 failure.

        Per AUR-CUSTODY-001 v1.0 Section VI line 634: eligibility
        failures produce escalation, not routing. Routes to T1
        (operational) per CAOM-001 — eligibility-list resolutions
        are routine operational reviews unless they reveal a deeper
        pattern requiring T2 governance review.
        """
        failed = sorted(c.kind.value for c in verification.failed_checks)
        failure_reason = (
            f"Eligibility verification failed for checks: {failed} "
            f"per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 "
            f"(eligibility before routing)."
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=str(operation.lineage.operation_id),
            decision_kind="escalation_required",
            ordered_inputs_signature=(
                "eligibility_failed",
                attempted_dimension.value,
                *failed,
            ),
        )
        return EscalationRequired(
            operation_id=operation.lineage.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=operation.lineage,
            emitted_at=emitted_at,
            failed_guardrail=JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING,
            failure_reason=failure_reason,
            escalation_tier=CAOMTier.T1,
            attempted_dimension=attempted_dimension,
            eligibility_verification=verification,
        )

    def _build_attribution_escalation(
        self,
        *,
        operation: CustodyOperationUnion,
        attempted_dimension: PathSelectionDimension,
        emitted_at: datetime,
    ) -> EscalationRequired:
        """Build an EscalationRequired for a Guardrail 5 failure.

        Per AUR-CANONICAL-001 v1.6 Section II (Layer 0 — Verana —
        Network Governance) and Axiom 8 (Verana Autonomous Block):
        operations reach Tier 2 with attribution already assigned by
        Verana. Missing attribution at the agent layer indicates a
        Verana-level state failure that requires T2 (Governance)
        review.
        """
        failure_reason = (
            "Jurisdictional attribution missing per AUR-CANONICAL-001 "
            "v1.6 Section II (Verana — Network Governance) and Axiom "
            "8 (Verana Autonomous Block); the agent does not route "
            "past missing Verana attribution."
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=str(operation.lineage.operation_id),
            decision_kind="escalation_required",
            ordered_inputs_signature=(
                "attribution_missing",
                attempted_dimension.value,
            ),
        )
        return EscalationRequired(
            operation_id=operation.lineage.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=operation.lineage,
            emitted_at=emitted_at,
            failed_guardrail=JClassGuardrail.JURISDICTIONAL_ATTRIBUTION,
            failure_reason=failure_reason,
            escalation_tier=CAOMTier.T2,
            attempted_dimension=attempted_dimension,
        )

    def _build_approved_paths_escalation(
        self,
        *,
        operation: CustodyOperationUnion,
        attempted_dimension: PathSelectionDimension,
        emitted_at: datetime,
        criteria_summary: str,
    ) -> EscalationRequired:
        """Build an EscalationRequired for a Guardrail 1 failure.

        Per AUR-CANONICAL-001 v1.6 Section II Thifur-J Guardrail 1:
        when no approved path matches the operation requirements,
        the agent escalates rather than improvising. Routes to T1
        (operational) for routing-table review.
        """
        failure_reason = (
            f"No approved path matches operation requirements in "
            f"dimension {attempted_dimension.value!r} ({criteria_summary}) "
            f"per AUR-CANONICAL-001 v1.6 Section II Thifur-J Guardrail "
            f"1 (approved paths only); the agent does not generate new "
            f"paths."
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=str(operation.lineage.operation_id),
            decision_kind="escalation_required",
            ordered_inputs_signature=(
                "no_approved_path",
                attempted_dimension.value,
                criteria_summary,
            ),
        )
        return EscalationRequired(
            operation_id=operation.lineage.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=operation.lineage,
            emitted_at=emitted_at,
            failed_guardrail=JClassGuardrail.APPROVED_PATHS_ONLY,
            failure_reason=failure_reason,
            escalation_tier=CAOMTier.T1,
            attempted_dimension=attempted_dimension,
        )

    def _build_routing_decision(
        self,
        *,
        operation: CustodyOperationUnion,
        chosen_path: ApprovedPath,
        dimension: PathSelectionDimension,
        verification: EligibilityVerification,
        attribution: JurisdictionalAttribution,
        emitted_at: datetime,
        rationale: str | None = None,
    ) -> RoutingDecision:
        """Build a RoutingDecision for a successful path selection.

        Per AUR-CUSTODY-001 v1.0 Section VI: when all five J-class
        guardrails are satisfied, the agent emits a RoutingDecision
        with the chosen path, the eligibility verification, and the
        Verana attribution. The operation's settlement_method is
        echoed onto the recommendation — the agent picks the rail/
        path; the settlement-method decision was made upstream.
        """
        recommendation = RoutingRecommendation(
            path_selection_dimension=dimension,
            chosen_path=chosen_path.path_id,
            settlement_method=operation.settlement_method,
            rationale=rationale or chosen_path.description,
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=str(operation.lineage.operation_id),
            decision_kind="routing_decision",
            ordered_inputs_signature=(
                dimension.value,
                chosen_path.path_id,
                "eligibility_passed",
                attribution.verana_session_id,
            ),
        )
        return RoutingDecision(
            operation_id=operation.lineage.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=operation.lineage,
            emitted_at=emitted_at,
            recommendation=recommendation,
            eligibility_verification=verification,
            jurisdictional_attribution=attribution,
            failure_mode_class=operation.failure_mode_class,
        )

    # ------------------------------------------------------------------
    # Material-magnitude routing to quorum authority (sub-commit C)
    #
    # Per AUR-CUSTODY-001 v1.0 Section VII and the operator's ruling on
    # material-magnitude routing ordering: the material-magnitude
    # check runs BEFORE the G4 → G5 → G1 sequence on every path-
    # selection method. An operation that triggers an inherent-safety
    # surface owned by this agent routes to QuorumAuthorityRequired
    # regardless of eligibility / attribution / approved-path state —
    # inherent-safety architectural protection cannot be relaxed
    # because eligibility failed (eligibility failures can be cured
    # through re-screening; quorum protection is structural per CAN
    # Axiom 10). Pre-quorum analysis (eligibility verification,
    # routing recommendation if determinable) is captured for the
    # OperationPackage so quorum signers see the complete pre-quorum
    # picture per CUS Section VII Step 1.
    # ------------------------------------------------------------------

    def _check_material_magnitude(  # noqa: PLR0911 — one return per trigger / dimension is the clearest dispatch.
        self,
        *,
        request: PathSelectionRequest,
        dimension: PathSelectionDimension,
        currency: str | None = None,
    ) -> InherentSafetySurface | None:
        """Per AUR-CUSTODY-001 v1.0 Section VI line 636 and Section IX:
        determine whether the request triggers a material-magnitude
        inherent-safety surface owned by this agent.

        Three trigger types are checked here (the fourth — correspondent
        banking changes affecting custody routing — requires modeling
        the operation as a "banking change" type at the contracts
        layer; tracked in ``FOLLOW-UPS.md``):

        0. **Operation already pre-classified** — the architectural-
           completeness trigger. UR-F operations *must* declare an
           inherent-safety surface per the contracts-layer validator
           (CUS Section VIII / IX); inherent-safety surfaces require
           quorum authority per AUR-CANONICAL-001 v1.6 Axiom 10
           regardless of amount or jurisdiction. When the operation
           arrives with a non-None ``inherent_safety_surface``, the
           upstream classification is honored and the agent routes to
           quorum on that surface — even if no amount-based or
           sanctioned-adjacency trigger would otherwise fire. Without
           this trigger, a UR-F operation arriving in routine context
           would fall through to ``RoutingDecision`` construction and
           raise on the UR-F validator; Trigger 0 makes the
           architecture composable end-to-end. Out-of-scope surfaces
           (declared but not in :data:`FIAT_SPECIALIST_OWNED_SURFACES`)
           still propagate; the
           :class:`~aureon.agents.tier2.outputs.QuorumAuthorityRequired`
           output validator catches them as a routing error (operation
           should have gone to a different agent).
        1. **Sanctioned-jurisdiction adjacency** (CUS Section VI line
           636). Fires when ``request.attribution`` names any
           jurisdiction in the policy's
           ``sanctioned_adjacency_jurisdictions`` set. Returns
           :attr:`~aureon.contracts.InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL`
           (the most general FIAT-specialist-owned surface for
           cross-border integrity concerns).
        2. **Amount-above-threshold per dimension** (CUS Section VII
           line 686 deferral to FED-001/INST-001). Fires when
           ``request.amount`` and ``currency`` are present and the
           policy's per-dimension threshold map shows a match. Returns
           the dimension-mapped surface
           (FIAT_SETTLEMENT_MATERIAL for Dim 1, LARGE_VALUE_PAYMENT_FINALITY
           for Dim 5, FX_BUNDLED_SETTLEMENT for Dim 3).

        Dimensions without amount-based triggers (Dim 2, 4, 6, 7)
        only check Trigger 0 and sanctioned adjacency (the amount
        path returns None for them).
        """
        policy = self._magnitude_threshold_policy

        # Trigger 0: operation already pre-classified by upstream
        # (UR-F operations and other inherent-safety operations carry
        # a declared surface per CUS Section VIII / IX).
        if request.operation.inherent_safety_surface is not None:
            return request.operation.inherent_safety_surface

        # Trigger 1: sanctioned-jurisdiction adjacency (any dimension)
        if request.attribution is not None:
            jurisdictions = (
                request.attribution.originating_jurisdiction,
                request.attribution.receiving_jurisdiction,
                *request.attribution.intermediary_jurisdictions,
            )
            for juris in jurisdictions:
                if policy.is_sanctioned_adjacent(juris):
                    return InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL

        # Trigger 2: amount-above-threshold per dimension
        if request.amount is None or currency is None:
            return None
        if dimension is PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING:
            if policy.is_fiat_settlement_material(currency, request.amount):
                return InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL
        elif dimension is PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM:
            if policy.is_lvps_finality_material(currency, request.amount):
                return InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY
        elif dimension is PathSelectionDimension.CROSS_BORDER_FX_LEG:
            if policy.is_fx_bundled_material(currency, request.amount):
                return InherentSafetySurface.FX_BUNDLED_SETTLEMENT
        return None

    def _route_to_quorum(
        self,
        *,
        request: PathSelectionRequest,
        triggered_surface: InherentSafetySurface,
        dimension: PathSelectionDimension,
        candidates: tuple[ApprovedPath, ...],
    ) -> QuorumAuthorityRequired:
        """Build the QuorumAuthorityRequired output for a material-
        magnitude operation. Captures pre-quorum eligibility (pass or
        fail) and routing recommendation (when an approved path
        matches the dimension-specific query, else None) so quorum
        signers see the complete pre-quorum picture per CUS Section
        VII Step 1."""
        verification = self.enforce_eligibility(request.eligibility_inputs)
        recommendation: RoutingRecommendation | None
        if candidates:
            recommendation = RoutingRecommendation(
                path_selection_dimension=dimension,
                chosen_path=candidates[0].path_id,
                settlement_method=request.operation.settlement_method,
                rationale=candidates[0].description,
            )
        else:
            recommendation = None
        package = self._assemble_operation_package(
            operation=request.operation,
            verification=verification,
            recommendation=recommendation,
            dimension=dimension,
        )
        return self._build_quorum_authority_required(
            request=request,
            triggered_surface=triggered_surface,
            package=package,
        )

    def _assemble_operation_package(
        self,
        *,
        operation: CustodyOperationUnion,
        verification: EligibilityVerification,
        recommendation: RoutingRecommendation | None,
        dimension: PathSelectionDimension,
    ) -> OperationPackage:
        """Per CUS Section VII Step 1: the eight-component package the
        Tier 2 specialist assembles for quorum routing."""
        pre_lineage = self._build_quorum_pre_operation_lineage(operation)
        projected_post_lineage = self._build_quorum_projected_post_lineage(
            operation,
            dimension,
            recommendation.chosen_path if recommendation is not None else None,
        )
        asset_class = operation.custody_object.asset_class
        asset_identifier = (
            asset_class.asset_identifier
            or f"{asset_class.major_category.value}/{asset_class.sub_category}"
        )
        return OperationPackage(
            operation=operation,
            beneficial_owner_ids=(operation.custody_object.beneficial_owner_id,),
            asset_ids=(asset_identifier,),
            pre_operation_dsor_state_stub=pre_lineage,
            projected_post_operation_dsor_state_stub=projected_post_lineage,
            routing_recommendation=recommendation,
            eligibility_verification=verification,
        )

    def _build_quorum_pre_operation_lineage(
        self,
        operation: CustodyOperationUnion,
    ) -> DSORLineageStub:
        """Re-stamp the operation's lineage with authority_tier=QUORUM
        for use as the OperationPackage's pre-operation DSOR state
        stub. Per CUS Section VII: a quorum-required operation cannot
        be authorized by any single CAOM tier; the package's pre-state
        stub must declare QUORUM authority (the validator on
        OperationPackage enforces this)."""
        return DSORLineageStub(
            operation_id=operation.lineage.operation_id,
            doctrine_version=operation.lineage.doctrine_version,
            caom_mode=operation.lineage.caom_mode,
            authority_tier=CAOMTier.QUORUM,
            authority_id=(
                operation.lineage.authority_id
                if operation.lineage.authority_tier is CAOMTier.QUORUM
                else "pending-ceremony"
            ),
            initiated_at=operation.lineage.initiated_at,
            session_id=operation.lineage.session_id,
            c2_handoff_id=operation.lineage.c2_handoff_id,
            pre_operation_state_hash=operation.lineage.pre_operation_state_hash,
        )

    def _build_quorum_projected_post_lineage(
        self,
        operation: CustodyOperationUnion,
        dimension: PathSelectionDimension,
        chosen_path_id: str | None,
    ) -> DSORLineageStub:
        """Build the projected post-operation DSOR state stub for the
        OperationPackage. The post_operation_state_hash is a
        deterministic projection over the operation's identifying
        fields plus the recommended path; quorum signers verify this
        projection against their understanding of what the operation
        will do, and the actual post-state is reconciled at Section
        VII Step 6."""
        projected_hash = self._project_post_operation_hash(
            operation, dimension, chosen_path_id
        )
        return DSORLineageStub(
            operation_id=operation.lineage.operation_id,
            doctrine_version=operation.lineage.doctrine_version,
            caom_mode=operation.lineage.caom_mode,
            authority_tier=CAOMTier.QUORUM,
            authority_id=(
                operation.lineage.authority_id
                if operation.lineage.authority_tier is CAOMTier.QUORUM
                else "pending-ceremony"
            ),
            initiated_at=operation.lineage.initiated_at,
            session_id=operation.lineage.session_id,
            c2_handoff_id=operation.lineage.c2_handoff_id,
            pre_operation_state_hash=operation.lineage.pre_operation_state_hash,
            post_operation_state_hash=projected_hash,
        )

    def _project_post_operation_hash(
        self,
        operation: CustodyOperationUnion,
        dimension: PathSelectionDimension,
        chosen_path_id: str | None,
    ) -> str:
        """Deterministic SHA-256 projection over the operation's
        identifying fields plus the recommended path. Same operation +
        dimension + path always produces the same projected hash —
        quorum signers can independently recompute and verify."""
        components = (
            str(operation.lineage.operation_id),
            operation.kind,
            operation.failure_mode_class.value,
            dimension.value,
            chosen_path_id or "no_path_recommendation",
        )
        canonical = "|".join(components)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _build_quorum_authority_required(
        self,
        *,
        request: PathSelectionRequest,
        triggered_surface: InherentSafetySurface,
        package: OperationPackage,
    ) -> QuorumAuthorityRequired:
        """Build the QuorumAuthorityRequired output. The output's
        ``lineage_stub`` is the package's pre-operation lineage
        (QUORUM-tier) so the output's own
        ``operation_id``-matches-``lineage_stub.operation_id``
        validator passes."""
        recommendation_path_id = (
            package.routing_recommendation.chosen_path
            if package.routing_recommendation is not None
            else "no_path_determined"
        )
        telemetry_hash = self.compute_telemetry_hash(
            operation_id=str(request.operation.lineage.operation_id),
            decision_kind="quorum_authority_required",
            ordered_inputs_signature=(
                triggered_surface.value,
                recommendation_path_id,
            ),
        )
        return QuorumAuthorityRequired(
            operation_id=request.operation.lineage.operation_id,
            agent_telemetry_hash=telemetry_hash,
            lineage_stub=package.pre_operation_dsor_state_stub,
            emitted_at=request.emitted_at,
            inherent_safety_surface=triggered_surface,
            operation_package=package,
        )

    # ------------------------------------------------------------------
    # Path-selection methods (Dimensions 1-7 per AUR-CUSTODY-001 v1.0
    # Section VI lines 618-632)
    #
    # Per the operator's ruling on material-magnitude routing
    # ordering: each method's flow is
    #
    #   1. Material-magnitude check (BEFORE guardrails); if triggered,
    #      route to QuorumAuthorityRequired.
    #   2. Otherwise: G4 → G5 → G1 → RoutingDecision or
    #      EscalationRequired.
    # ------------------------------------------------------------------

    def _run_pre_path_guardrails(
        self,
        request: PathSelectionRequest,
        attempted_dimension: PathSelectionDimension,
    ) -> tuple[EligibilityVerification, JurisdictionalAttribution] | EscalationRequired:
        """Run G4 then G5. Returns the verified inputs (narrowed) on
        pass; returns the appropriate escalation on fail. Centralises
        the duplicated guardrail-sequencing code so each path-
        selection method can focus on its dimension-specific logic.
        """
        verification = self.enforce_eligibility(request.eligibility_inputs)
        if not verification.all_passed:
            return self._build_eligibility_escalation(
                operation=request.operation,
                verification=verification,
                attempted_dimension=attempted_dimension,
                emitted_at=request.emitted_at,
            )
        if request.attribution is None:
            return self._build_attribution_escalation(
                operation=request.operation,
                attempted_dimension=attempted_dimension,
                emitted_at=request.emitted_at,
            )
        return verification, request.attribution

    def select_multi_currency_rail_routing(
        self,
        request: PathSelectionRequest,
        *,
        currency: str,
        jurisdiction: str | None = None,
        finality_preference: FinalityModel | None = None,
    ) -> FIATOperationsOutput:
        """Dimension 1 — Multi-currency settlement rail routing.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 1: select among
        Fedwire, CHIPS, ACH, SWIFT MT103/MT202, Target2, CHAPS,
        Zengin, and analogous large-value and clearing systems
        globally. Criteria: settlement urgency, finality, fee
        economics, correspondent arrangements, operational hours.

        Sequence: material-magnitude check → Guardrail 4 → Guardrail
        5 → Guardrail 1.
        """
        dimension = PathSelectionDimension.MULTI_CURRENCY_RAIL_ROUTING
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=currency
        )
        if triggered is not None:
            candidates = self._routing_tables.find_rail_paths(
                currency=currency,
                jurisdiction=jurisdiction,
                finality_model=finality_preference,
            )
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        candidates = self._routing_tables.find_rail_paths(
            currency=currency,
            jurisdiction=jurisdiction,
            finality_model=finality_preference,
        )
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=(
                    f"currency={currency!r}, "
                    f"jurisdiction={jurisdiction!r}, "
                    f"finality={finality_preference}"
                ),
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_correspondent_banking_coordination(
        self,
        request: PathSelectionRequest,
        *,
        currency: str,
        jurisdiction: str | None = None,
    ) -> FIATOperationsOutput:
        """Dimension 2 — Correspondent banking coordination.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 2: when direct
        large-value system access is impractical for a jurisdiction,
        select a correspondent bank routing.
        """
        dimension = PathSelectionDimension.CORRESPONDENT_BANKING_COORDINATION
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=currency
        )
        if triggered is not None:
            candidates = self._routing_tables.find_correspondent_paths(
                currency=currency,
                jurisdiction=jurisdiction,
            )
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        candidates = self._routing_tables.find_correspondent_paths(
            currency=currency,
            jurisdiction=jurisdiction,
        )
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=(
                    f"currency={currency!r}, jurisdiction={jurisdiction!r}"
                ),
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_cross_border_fx_leg(
        self,
        request: PathSelectionRequest,
        *,
        currency_pair: str,
    ) -> FIATOperationsOutput:
        """Dimension 3 — Cross-border settlement with FX leg
        coordination.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 3: select among
        CLS PvP (eligible pairs), on-us, bilateral PvP, and
        traditional gross when PvP is unavailable. The default
        routing tables include CLS PvP only; on-us / bilateral /
        gross fallbacks are deferred to FED-001 / INST-001 per
        ``FOLLOW-UPS.md``. Empty candidate set produces an
        APPROVED_PATHS_ONLY escalation, which the operator routes to
        the appropriate fallback path during the deferred-paths
        rollout.
        """
        dimension = PathSelectionDimension.CROSS_BORDER_FX_LEG
        # Use the base currency (first half of the pair) for the
        # amount-based magnitude check. Deployments needing the quote
        # currency to also be checked should configure both in
        # MagnitudeThresholdPolicy.fx_bundled_thresholds.
        base_currency = (
            currency_pair.upper().split("/", 1)[0]
            if "/" in currency_pair
            else currency_pair
        )
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=base_currency
        )
        if triggered is not None:
            candidates = self._routing_tables.find_fx_pvp_paths(currency_pair)
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        candidates = self._routing_tables.find_fx_pvp_paths(currency_pair)
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=f"currency_pair={currency_pair!r}",
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_depository_vs_sub_custodian(
        self,
        request: PathSelectionRequest,
        *,
        jurisdiction: str,
    ) -> FIATOperationsOutput:
        """Dimension 4 — Depository versus sub-custodian routing.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 4: for
        jurisdictions where Aureon-governed custody can access either
        direct depository membership or sub-custodian intermediation,
        the routing decision involves operational efficiency,
        counterparty risk concentration, jurisdictional regulatory
        compliance, and cost economics.
        """
        dimension = PathSelectionDimension.DEPOSITORY_VS_SUB_CUSTODIAN
        # No amount-based trigger for Dim 4; sanctioned-adjacency check
        # still applies via the request's attribution.
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=None
        )
        if triggered is not None:
            candidates = self._routing_tables.find_depository_paths(jurisdiction)
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        candidates = self._routing_tables.find_depository_paths(jurisdiction)
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=f"jurisdiction={jurisdiction!r}",
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_large_value_payment_system(
        self,
        request: PathSelectionRequest,
        *,
        currency: str,
        jurisdiction: str | None = None,
        finality_preference: FinalityModel | None = None,
    ) -> FIATOperationsOutput:
        """Dimension 5 — Large-value payment system selection.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 5: when
        multiple eligible large-value systems can settle a payment
        of material magnitude, select among them based on settlement
        risk profile (Fedwire is gross-real-time-final; CHIPS uses
        bilateral and multilateral net with finality at end of day;
        SWIFT correspondent depends on correspondent bank operational
        status).

        The query reuses ``find_rail_paths`` with the LVPS dimension
        tag — paths that serve both Dimension 1 and Dimension 5 (per
        ``ApprovedPath.dimensions`` multi-membership) match either
        method; selection criteria differ.
        """
        dimension = PathSelectionDimension.LARGE_VALUE_PAYMENT_SYSTEM
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=currency
        )
        if triggered is not None:
            all_rail = self._routing_tables.find_rail_paths(
                currency=currency,
                jurisdiction=jurisdiction,
                finality_model=finality_preference,
            )
            candidates = tuple(p for p in all_rail if dimension in p.dimensions)
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        all_rail_candidates = self._routing_tables.find_rail_paths(
            currency=currency,
            jurisdiction=jurisdiction,
            finality_model=finality_preference,
        )
        # Filter to paths that explicitly serve LVPS, not just the
        # broader Dimension 1.
        candidates = tuple(
            p for p in all_rail_candidates if dimension in p.dimensions
        )
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=(
                    f"currency={currency!r}, "
                    f"jurisdiction={jurisdiction!r}, "
                    f"finality={finality_preference}"
                ),
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_fed_related_operation(
        self,
        request: PathSelectionRequest,
        *,
        fed_facility_path_id: str,
    ) -> FIATOperationsOutput:
        """Dimension 6 — Fed-related operations.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 6: Discount
        Window borrowing collateral coordination, Standing Repo
        Facility operations, Reverse Repo Facility coordination,
        Federal Reserve account operations for entities with direct
        access. The caller names the specific Fed facility by path
        identifier; the agent verifies the facility is in the
        approved Fed paths and emits the routing decision.
        """
        dimension = PathSelectionDimension.FED_RELATED_OPERATION
        # No amount-based trigger for Dim 6 (Fed operations are
        # governed by Fed-specific protocols, not the FIAT material-
        # magnitude policy). Sanctioned-adjacency check still applies.
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=None
        )
        if triggered is not None:
            chosen_or_none = self._routing_tables.find_path(fed_facility_path_id)
            candidates = (
                (chosen_or_none,)
                if chosen_or_none is not None
                and dimension in chosen_or_none.dimensions
                else ()
            )
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        if not self.enforce_approved_paths_only(fed_facility_path_id, dimension):
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=f"fed_facility={fed_facility_path_id!r}",
            )
        # enforce_approved_paths_only returned True, so the path
        # exists in the registry. find_path returns the full record.
        chosen = self._routing_tables.find_path(fed_facility_path_id)
        # Defensive: enforce_approved_paths_only already verified
        # existence; if find_path returns None here, the registry is
        # internally inconsistent (which the registry's own validator
        # prevents). Narrow for mypy.
        assert chosen is not None
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=chosen,
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )

    def select_cash_sweep_and_short_term_investment(
        self,
        request: PathSelectionRequest,
        *,
        currency: str,
    ) -> FIATOperationsOutput:
        """Dimension 7 — Cash sweep and short-term investment routing.

        Per AUR-CUSTODY-001 v1.0 Section VI Dimension 7: select cash
        sweep destinations across MMFs (CNAV / FNAV, government /
        prime), bank deposit programs, repo investment vehicles, and
        tri-party repo arrangements. Criteria: yield, operational
        cutoffs, redemption mechanics, risk concentration.
        """
        dimension = PathSelectionDimension.CASH_SWEEP_AND_SHORT_TERM_INVESTMENT
        # No amount-based trigger for Dim 7 in the current policy
        # shape (sweep thresholds aren't separately configured;
        # deployments wanting a sweep-magnitude trigger should add it
        # to MagnitudeThresholdPolicy in a subsequent build).
        # Sanctioned-adjacency check still applies.
        triggered = self._check_material_magnitude(
            request=request, dimension=dimension, currency=None
        )
        if triggered is not None:
            candidates = self._routing_tables.find_cash_sweep_paths(currency)
            return self._route_to_quorum(
                request=request,
                triggered_surface=triggered,
                dimension=dimension,
                candidates=candidates,
            )

        gate = self._run_pre_path_guardrails(request, dimension)
        if isinstance(gate, EscalationRequired):
            return gate
        verification, attribution = gate

        candidates = self._routing_tables.find_cash_sweep_paths(currency)
        if not candidates:
            return self._build_approved_paths_escalation(
                operation=request.operation,
                attempted_dimension=dimension,
                emitted_at=request.emitted_at,
                criteria_summary=f"currency={currency!r}",
            )
        return self._build_routing_decision(
            operation=request.operation,
            chosen_path=candidates[0],
            dimension=dimension,
            verification=verification,
            attribution=attribution,
            emitted_at=request.emitted_at,
        )


__all__ = [
    "FIATOperationsSpecialist",
    "MagnitudeThresholdPolicy",
    "PathSelectionRequest",
]
