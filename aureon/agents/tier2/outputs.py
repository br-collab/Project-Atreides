"""Typed output structures emitted by the FIAT Operations Specialist.

Per AUR-CUSTODY-001 v1.0 Section VI (FIAT Operations Specialist) and
AUR-CANONICAL-001 v1.6 Section II (Thifur-J — JTAC bounded autonomy).
Every path-selection decision the agent makes resolves to one of three
typed outputs:

- :class:`RoutingDecision` — the agent successfully selected an
  approved path; all five J-class guardrails are satisfied; the
  operation can proceed downstream.
- :class:`EscalationRequired` — one of the five J-class guardrails
  fired (no approved path matches; doctrine-over-code hold; missing
  approval lineage; eligibility failure; missing jurisdictional
  attribution); the operation does not proceed and is routed to
  operator review.
- :class:`QuorumAuthorityRequired` — the operation is on an
  inherent-safety surface owned by this agent (per the operator's
  ruling on Section IX surface ownership: ``FIAT_SETTLEMENT_MATERIAL``,
  ``CORRESPONDENT_BANKING_INTEGRITY``, ``LARGE_VALUE_PAYMENT_FINALITY``,
  ``FX_BUNDLED_SETTLEMENT``, ``DEPOSITORY_MEMBERSHIP``) and requires
  N-of-M signatures per AUR-CUSTODY-001 v1.0 Section VII; the agent
  assembles the operation package and stops at package assembly.

The three outputs form a discriminated union exposed as
:data:`FIATOperationsOutput`. Downstream consumers (DSOR record
assembly, the quorum ceremony state machine, rail integration) match
on the ``kind`` discriminator and route accordingly.

This module is the typed target every other module in
``aureon.agents.tier2`` produces. It depends only on the contracts
substrate (``aureon.contracts``) and on its own enumerations.

Citation note for guardrail 5: AUR-CUSTODY-001 v1.0 Section VI line
634 cites "AUR-CANONICAL-001 v1.6 Section VIII" as the authority for
Verana jurisdictional attribution. That is a known doctrine erratum
— the correct citation is AUR-CANONICAL-001 v1.6 Section II (Layer 0
— Verana — Network Governance) and Axiom 8 (Verana Autonomous Block).
This module uses the corrected citation in code comments and error
messages; the erratum is tracked in ``FOLLOW-UPS.md`` for the next
custody doctrine iteration.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.contracts import (
    CURRENT_DOCTRINE_VERSION,
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    FailureModeClass,
    InherentSafetySurface,
    SettlementMethod,
)

# SHA-256 lowercase hex digest pattern. Same as the contracts layer's
# DSOR lineage hash format (see aureon.contracts.dsor_stub) so that
# agent telemetry hashes and DSOR state hashes are bit-for-bit
# comparable across the parity boundary (AUR-CANONICAL-001 v1.6
# Section VII Parity Principle).
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

AgentClass = Literal["FIAT_OPERATIONS_SPECIALIST_v1"]

AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST: Final[AgentClass] = "FIAT_OPERATIONS_SPECIALIST_v1"
"""Agent class identifier per the operator's ruling on telemetry hash
scope: the hash domain incorporates the agent class so that future
audits can distinguish FIAT Operations Specialist decisions from
decisions produced by the (forthcoming) Digital Asset Custody
Specialist or other agent classes that will eventually exist.

Bumping the trailing ``_v1`` is a doctrine-modifying change (the
behavior the audit hash signs has changed) and flows through the
propose/approve workflow per AUR-CANONICAL-001 v1.6 Section VII.
"""


class PathSelectionDimension(StrEnum):
    """The seven path-selection dimensions per AUR-CUSTODY-001 v1.0
    Section VI lines 618-632.

    Each dimension corresponds to a method on the agent class. The
    output structures carry the dimension that produced the decision
    (or that was attempted, in escalation cases) so downstream
    consumers can reconstruct which path-selection logic ran.
    """

    MULTI_CURRENCY_RAIL_ROUTING = "multi_currency_rail_routing"
    """Dimension 1 — Selection among Fedwire, CHIPS, ACH, SWIFT MT103/
    MT202, Target2, CHAPS, Zengin, and analogous large-value and
    clearing systems globally."""

    CORRESPONDENT_BANKING_COORDINATION = "correspondent_banking_coordination"
    """Dimension 2 — Nostro/vostro positioning, cover-vs-serial
    payment, intermediary bank routing where multiple correspondents
    are eligible."""

    CROSS_BORDER_FX_LEG = "cross_border_fx_leg"
    """Dimension 3 — Sequencing FX execution and securities
    settlement; selection among CLS PvP, on-us, bilateral PvP, and
    traditional gross when PvP is unavailable."""

    DEPOSITORY_VS_SUB_CUSTODIAN = "depository_vs_sub_custodian"
    """Dimension 4 — Direct depository membership vs sub-custodian
    intermediation, weighing operational efficiency, counterparty
    risk concentration, jurisdictional regulatory compliance, cost."""

    LARGE_VALUE_PAYMENT_SYSTEM = "large_value_payment_system"
    """Dimension 5 — Selection among multiple eligible large-value
    payment systems (Fedwire RTGS-final vs CHIPS net-final at
    end-of-day vs SWIFT correspondent-dependent) at material
    magnitude."""

    FED_RELATED_OPERATION = "fed_related_operation"
    """Dimension 6 — Discount Window collateral coordination, SRF,
    RRF, Federal Reserve account operations for direct-access
    entities."""

    CASH_SWEEP_AND_SHORT_TERM_INVESTMENT = "cash_sweep_and_short_term_investment"
    """Dimension 7 — Cash sweep destination selection across MMFs
    (CNAV/FNAV, government/prime), bank deposit programs, repo
    vehicles, tri-party repo arrangements."""


class JClassGuardrail(StrEnum):
    """The five J-class guardrails per AUR-CANONICAL-001 v1.6 Section II
    (Thifur-J) and AUR-CUSTODY-001 v1.0 Section VI line 634
    (FIAT-leg rendering).

    Every escalation output names the guardrail that fired. The
    doctrine-over-code guardrail (number 2) is a meta-guardrail: it
    fires when an external system message or instruction would cause
    one of the other four guardrails to be violated. The escalation
    output for guardrail 2 carries a ``cascade_guardrail`` field
    naming the underlying guardrail that the external instruction
    would have violated.
    """

    APPROVED_PATHS_ONLY = "approved_paths_only"
    """Guardrail 1 — The agent selects from path options defined in
    Kaladan-managed routing tables and never generates new paths. No
    matching approved path produces an escalation output."""

    DOCTRINE_OVER_CODE = "doctrine_over_code"
    """Guardrail 2 — Per AUR-CANONICAL-001 v1.6 Axiom 5, smart-
    contract execution and external system message logic never
    override doctrine. For FIAT-leg operations: an automated
    correspondent banking instruction that would cause one of the
    other four guardrails to be violated triggers a Thifur-J hold
    rather than execution."""

    NO_SETTLEMENT_WITHOUT_LINEAGE = "no_settlement_without_lineage"
    """Guardrail 3 — Every routing decision the agent emits carries
    the doctrine version stamp, authority routing, agent telemetry
    hash, and DSOR lineage stub fields populated. Outputs missing any
    of these fail validation at the schema layer."""

    ELIGIBILITY_BEFORE_ROUTING = "eligibility_before_routing"
    """Guardrail 4 — Before any routing decision: KYC/KYB, OFAC
    screening, sanctions list, correspondent-bank compliance must
    pass. Failures produce escalation, never routing."""

    JURISDICTIONAL_ATTRIBUTION = "jurisdictional_attribution"
    """Guardrail 5 — Cross-border FIAT transfers must be
    jurisdictionally attributed via Verana per AUR-CANONICAL-001 v1.6
    Section II (Verana — Network Governance) and Axiom 8 (Verana
    Autonomous Block). Missing attribution fails validation."""


class EligibilityCheckKind(StrEnum):
    """The five eligibility checks the FIAT Operations Specialist
    runs per AUR-CUSTODY-001 v1.0 Section VI line 634.

    The agent verifies these checks before any routing decision; any
    failure produces an :class:`EscalationRequired` output rather
    than a routing decision (Guardrail 4 — eligibility before
    routing).
    """

    KYC = "kyc"
    """Know Your Customer — beneficial owner identity verification."""

    KYB = "kyb"
    """Know Your Business — counterparty entity verification."""

    OFAC = "ofac"
    """OFAC sanctions screening. Verana also enforces this
    autonomously at Layer 0 per AUR-CANONICAL-001 v1.6 Axiom 8;
    the agent's check is a pre-routing gate and does not substitute
    for Verana's autonomous block."""

    SANCTIONS = "sanctions"
    """Non-OFAC sanctions list screening (UN, EU, UK HMT, jurisdiction-
    specific lists)."""

    CORRESPONDENT_BANK_COMPLIANCE = "correspondent_bank_compliance"
    """Correspondent bank compliance verification — current operational
    status, applicable regulatory regime, sanctions compliance of the
    correspondent itself."""


class EligibilityCheck(BaseModel):
    """Result of a single eligibility check.

    Per AUR-CUSTODY-001 v1.0 Section VI line 634 (FIAT-leg eligibility
    rendering). The frozen-and-extra-forbid configuration matches the
    contracts layer convention: every result carries an immutable
    record of what was verified and whether it passed.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    kind: EligibilityCheckKind = Field(
        description="Which of the five eligibility checks this result represents.",
    )
    passed: bool = Field(
        description="True when the check passed; False otherwise.",
    )
    failure_reason: str | None = Field(
        default=None,
        description=(
            "Doctrine-cited failure reason. Required when "
            "``passed`` is False; must be None when ``passed`` is True."
        ),
    )
    verified_at: datetime = Field(
        description="UTC timestamp at which the check was performed.",
    )

    @model_validator(mode="after")
    def _validate_failure_reason_consistency(self) -> Self:
        """Per Guardrail 4: failure must carry a doctrine-cited reason
        for the escalation; success must not carry one."""
        if not self.passed and not self.failure_reason:
            raise ValueError(
                "Failed eligibility check must carry a doctrine-cited "
                "failure_reason per AUR-CUSTODY-001 v1.0 Section VI "
                "Guardrail 4 (eligibility before routing)."
            )
        if self.passed and self.failure_reason is not None:
            raise ValueError(
                "Passed eligibility check must not carry a "
                "failure_reason; the field is reserved for failures."
            )
        return self


class EligibilityVerification(BaseModel):
    """The complete set of eligibility checks performed for an operation.

    Per AUR-CUSTODY-001 v1.0 Section VI line 634, the FIAT Operations
    Specialist runs all five eligibility checks before any routing
    decision. The output schema requires every kind to appear exactly
    once; the agent (in :mod:`aureon.agents.tier2.eligibility`)
    populates the results.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    checks: tuple[EligibilityCheck, ...] = Field(
        description=(
            "All five eligibility checks. Each "
            ":class:`EligibilityCheckKind` must appear exactly once."
        ),
    )

    @property
    def all_passed(self) -> bool:
        """True when every check in the verification passed."""
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> tuple[EligibilityCheck, ...]:
        """Tuple of failed checks (empty when all passed)."""
        return tuple(c for c in self.checks if not c.passed)

    @model_validator(mode="after")
    def _validate_all_kinds_present_exactly_once(self) -> Self:
        """Per Guardrail 4: all five eligibility kinds must be
        verified before a routing decision can issue."""
        seen: set[EligibilityCheckKind] = set()
        for check in self.checks:
            if check.kind in seen:
                raise ValueError(
                    f"EligibilityVerification carries duplicate check "
                    f"of kind {check.kind.value!r}; each kind must "
                    f"appear exactly once."
                )
            seen.add(check.kind)
        missing = set(EligibilityCheckKind) - seen
        if missing:
            missing_names = sorted(k.value for k in missing)
            raise ValueError(
                f"EligibilityVerification missing required check "
                f"kinds: {missing_names}. Per AUR-CUSTODY-001 v1.0 "
                f"Section VI Guardrail 4 (eligibility before "
                f"routing), all five checks must be performed before "
                f"any routing decision."
            )
        return self


class JurisdictionalAttribution(BaseModel):
    """Verana-assigned jurisdictional attribution for a FIAT operation.

    Per AUR-CANONICAL-001 v1.6 Section II (Layer 0 — Verana — Network
    Governance) and Axiom 8 (Verana Autonomous Block): cross-border
    FIAT transfers must carry Verana-attributed jurisdictional
    identification before execution. AUR-CUSTODY-001 v1.0 Section VI
    line 634 cites "Section VIII" — that citation is a known doctrine
    erratum (Section VIII is the Institutional Licensing Thesis); the
    correct authority is Section II Layer 0 plus Axiom 8 as cited
    here.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    originating_jurisdiction: str = Field(
        min_length=2,
        max_length=3,
        description=(
            "ISO 3166-1 alpha-2 or alpha-3 country code for the "
            "originating jurisdiction of the FIAT operation."
        ),
    )
    receiving_jurisdiction: str = Field(
        min_length=2,
        max_length=3,
        description=(
            "ISO 3166-1 alpha-2 or alpha-3 country code for the "
            "receiving jurisdiction of the FIAT operation."
        ),
    )
    intermediary_jurisdictions: tuple[str, ...] = Field(
        default=(),
        description=(
            "ISO 3166-1 alpha-2/alpha-3 codes for intermediary "
            "jurisdictions traversed (correspondent routing). Empty "
            "for direct settlement; populated for correspondent or "
            "multi-hop paths."
        ),
    )
    verana_session_id: str = Field(
        min_length=1,
        description=(
            "Verana session identifier under which the attribution "
            "was assigned (CAOM-001 Section V Step 1)."
        ),
    )
    attributed_at: datetime = Field(
        description="UTC timestamp at which Verana attributed the operation.",
    )

    @property
    def is_cross_border(self) -> bool:
        """True when the operation crosses a jurisdictional boundary.

        A same-jurisdiction operation with no intermediaries is
        domestic; any other configuration is cross-border. Verana's
        Jurisdictional Boundary Engine (Section II Verana
        responsibilities) determines the underlying classification.
        """
        return (
            self.originating_jurisdiction != self.receiving_jurisdiction
            or len(self.intermediary_jurisdictions) > 0
        )


class RoutingRecommendation(BaseModel):
    """Path-selection recommendation produced by the agent.

    Carried directly on a :class:`RoutingDecision` and optionally
    embedded in a :class:`QuorumAuthorityRequired` operation package
    (per AUR-CUSTODY-001 v1.0 Section VII Step 1: "the routing
    recommendation if one was determinable").
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    path_selection_dimension: PathSelectionDimension = Field(
        description="Which of the seven path-selection dimensions produced this recommendation.",
    )
    chosen_path: str = Field(
        min_length=1,
        description=(
            "Identifier of the chosen approved path within the "
            "dimension (e.g., 'fedwire', 'chips', 'swift_mt202', "
            "'cls_pvp', 'tri_party_repo_bny'). Must reference a path "
            "in the Kaladan-managed routing tables (Guardrail 1)."
        ),
    )
    settlement_method: SettlementMethod | None = Field(
        default=None,
        description=(
            "Settlement method per AUR-CUSTODY-001 v1.0 Section V "
            "when one applies. None for routing recommendations that "
            "do not have a per-leg settlement method (e.g., cash "
            "sweep destination selection)."
        ),
    )
    rationale: str = Field(
        min_length=1,
        description=(
            "Short doctrine-cited rationale for the recommendation. "
            "Names the criteria from Section VI lines 618-632 that "
            "drove the selection."
        ),
    )


class OperationPackage(BaseModel):
    """The eight-component operation package per AUR-CUSTODY-001 v1.0
    Section VII Step 1.

    Assembled by the agent when an operation falls on an inherent-
    safety surface owned by this agent (per the operator's ruling on
    Section IX surface ownership) and routed to quorum authority. The
    downstream quorum ceremony module (out of scope at this build
    layer) consumes the package and runs the six-step ceremony.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    operation: CustodyOperationUnion = Field(
        description="The custody operation specification (Section VII Step 1, component 1).",
    )
    beneficial_owner_ids: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Identifiers of the beneficial owners affected by the "
            "operation (component 2). At least one is required — a "
            "custody operation always has at least one beneficial "
            "owner per the agency-relationship grounding in "
            "AUR-CUSTODY-001 v1.0 Section II."
        ),
    )
    asset_ids: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Identifiers of the assets affected by the operation "
            "(component 3). At least one asset is required."
        ),
    )
    doctrine_version: str = Field(
        default=CURRENT_DOCTRINE_VERSION,
        description="Doctrine version stamp (component 4).",
    )
    pre_operation_dsor_state_stub: DSORLineageStub = Field(
        description=(
            "Pre-operation DSOR state stub (component 5). The "
            "lineage's authority_tier must be QUORUM since this "
            "package routes to quorum authority."
        ),
    )
    projected_post_operation_dsor_state_stub: DSORLineageStub = Field(
        description=(
            "Projected post-operation DSOR state stub (component 6). "
            "The lineage's ``post_operation_state_hash`` must be set "
            "(non-None) since it represents the projected end state "
            "the ceremony signers will verify."
        ),
    )
    routing_recommendation: RoutingRecommendation | None = Field(
        default=None,
        description=(
            "Routing recommendation if one was determinable "
            "(component 7). None when the agent could not determine "
            "a recommendation prior to quorum (e.g., the path "
            "selection itself depends on quorum-supplied input)."
        ),
    )
    eligibility_verification: EligibilityVerification = Field(
        description=(
            "Supporting eligibility verification results (component 8). "
            "Per the operator's ruling on material-magnitude routing "
            "ordering: the package carries whatever pre-quorum "
            "eligibility analysis the agent performed, even when "
            "checks failed. Quorum signers see the full pre-quorum "
            "picture (eligibility passed/failed, routing recommendation "
            "if any) so they can evaluate the material-magnitude "
            "operation with complete context. Inherent-safety "
            "architectural protection cannot be relaxed because "
            "eligibility failed; conversely, eligibility failures on "
            "non-material operations route to "
            ":class:`EscalationRequired`, not to a quorum package."
        ),
    )

    @model_validator(mode="after")
    def _validate_pre_state_authority_is_quorum(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VII and AUR-CANONICAL-001
        v1.6 Section V: a quorum-required operation cannot be
        authorized by any single CAOM tier; the pre-operation state
        stub's authority_tier must be QUORUM."""
        if self.pre_operation_dsor_state_stub.authority_tier is not CAOMTier.QUORUM:
            raise ValueError(
                f"OperationPackage.pre_operation_dsor_state_stub "
                f"must carry authority_tier=QUORUM (got "
                f"{self.pre_operation_dsor_state_stub.authority_tier.value!r}); "
                f"per AUR-CUSTODY-001 v1.0 Section VII a quorum-"
                f"required operation cannot be authorized by any "
                f"single CAOM tier."
            )
        return self

    @model_validator(mode="after")
    def _validate_projected_post_state_carries_hash(self) -> Self:
        """The projected post-operation state stub must carry a
        post_operation_state_hash so ceremony signers can verify the
        predicted outcome (Section VII Step 6)."""
        if self.projected_post_operation_dsor_state_stub.post_operation_state_hash is None:
            raise ValueError(
                "OperationPackage.projected_post_operation_dsor_state_stub "
                "must carry post_operation_state_hash (non-None); the "
                "hash represents the projected end state ceremony "
                "signers verify per AUR-CUSTODY-001 v1.0 Section VII "
                "Step 6 (post-operation reconciliation)."
            )
        return self

FIAT_SPECIALIST_OWNED_SURFACES: Final[frozenset[InherentSafetySurface]] = frozenset(
    {
        InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
        InherentSafetySurface.CORRESPONDENT_BANKING_INTEGRITY,
        InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY,
        InherentSafetySurface.FX_BUNDLED_SETTLEMENT,
        InherentSafetySurface.DEPOSITORY_MEMBERSHIP,
    }
)
"""Per the operator's ruling on Section IX surface ownership: the FIAT
Operations Specialist owns trigger detection for these five surfaces
that fall within its seven path-selection dimensions. The other
Section IX surfaces (beneficial owner identity changes, quorum
enrollment changes, key ceremonies, cold storage, custodian-of-
custodian operations, tokenized asset issuer operations, native
digital asset operations, and the asset-class-specific surfaces for
commodities/real-estate/IP/insurance/ILS/carbon/authentication) are
owned by other roles or by layers above this agent.

Note: depository membership *changes* themselves are operator-direct
events, not agent-triggered. The agent's ownership of
DEPOSITORY_MEMBERSHIP is for routing decisions that depend on a
depository membership state (e.g., dimension 4 — depository vs sub-
custodian routing) — the agent assembles a quorum package when its
routing decision would itself constitute a depository membership
change.
"""


class _OutputBase(BaseModel):
    """Common frozen-and-extra-forbid base for the three output types.

    Carries the four fields the build prompt names as required on
    every output the agent emits: doctrine version stamp, agent class
    identifier, agent telemetry hash, and the DSOR lineage stub. The
    presence of these fields is what makes Guardrail 3 ("no
    settlement without approval lineage") schema-checkable.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    operation_id: UUID = Field(
        description=(
            "Identifier of the operation this output references. "
            "Matches ``DSORLineageStub.operation_id`` on the input "
            "operation."
        ),
    )
    doctrine_version: str = Field(
        default=CURRENT_DOCTRINE_VERSION,
        description="Doctrine version stamp per AUR-CANONICAL-001 v1.6 Axiom 1.",
    )
    agent_class: AgentClass = Field(
        default=AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST,
        description=(
            "Agent class identifier (per the operator's ruling on "
            "telemetry hash scope). Distinguishes outputs produced by "
            "this agent from outputs produced by other agent classes "
            "(e.g., the forthcoming Digital Asset Custody Specialist)."
        ),
    )
    agent_telemetry_hash: str = Field(
        description=(
            "SHA-256 hex digest computed over the canonical "
            "serialization of (operation_id, doctrine_version, "
            "decision_kind, agent_class, ordered list of inputs that "
            "materially influenced the decision). The hash domain is "
            "agent-class-scoped; bumping ``agent_class`` is a "
            "doctrine-modifying change because the behavior the hash "
            "signs has changed."
        ),
    )
    lineage_stub: DSORLineageStub = Field(
        description=(
            "Embedded copy of the input operation's DSOR lineage "
            "stub. Per Axiom 4 (one lineage record), the unified "
            "lineage is assembled by Thifur-C2; this field is the "
            "agent's preserved view of the lineage at decision time."
        ),
    )
    emitted_at: datetime = Field(
        description="UTC timestamp at which the agent emitted this output.",
    )

    @model_validator(mode="after")
    def _validate_telemetry_hash_format(self) -> Self:
        """Per the contracts layer SHA-256 invariant: telemetry hashes
        are 64-character lowercase hex (matches DSOR state hash
        format for cross-parity comparability)."""
        if not _SHA256_HEX.match(self.agent_telemetry_hash):
            raise ValueError(
                "agent_telemetry_hash must be a 64-character "
                "lowercase hex SHA-256 digest per AUR-CANONICAL-001 "
                "v1.6 Axiom 1 (matches DSOR state hash format)."
            )
        return self

    @model_validator(mode="after")
    def _validate_operation_id_matches_lineage(self) -> Self:
        """The output's ``operation_id`` must match the embedded
        lineage stub's ``operation_id``. Mismatch implies the agent
        attached the wrong lineage to a decision — a Guardrail 3
        violation."""
        if self.operation_id != self.lineage_stub.operation_id:
            raise ValueError(
                f"Output operation_id ({self.operation_id}) does not "
                f"match embedded lineage_stub.operation_id "
                f"({self.lineage_stub.operation_id}). Per Guardrail 3, "
                f"every output carries the lineage of the operation "
                f"it references; mismatch is a doctrine integrity "
                f"violation."
            )
        return self


class RoutingDecision(_OutputBase):
    """The agent successfully selected an approved path; all five
    J-class guardrails are satisfied.

    Emitted on path-selection success. Downstream rail integration
    (out of scope at this build layer) consumes the recommendation
    and effects the actual settlement instruction.
    """

    kind: Literal["routing_decision"] = "routing_decision"
    recommendation: RoutingRecommendation = Field(
        description="The selected path and supporting rationale.",
    )
    eligibility_verification: EligibilityVerification = Field(
        description=(
            "All five eligibility checks (Guardrail 4). Must show "
            "all passed; failed eligibility produces "
            ":class:`EscalationRequired` instead."
        ),
    )
    jurisdictional_attribution: JurisdictionalAttribution = Field(
        description=(
            "Verana-assigned jurisdictional attribution (Guardrail "
            "5). Required on every routing decision; the attribution "
            "may classify the operation as domestic, but the field "
            "itself is never optional — missing attribution fails "
            "validation per AUR-CANONICAL-001 v1.6 Section II "
            "(Verana — Network Governance) and Axiom 8."
        ),
    )
    failure_mode_class: FailureModeClass = Field(
        description=(
            "Failure-mode class carried through from the input "
            "operation per AUR-CUSTODY-001 v1.0 Section VIII. "
            "Routing decisions cannot issue on UR-F operations — "
            "those are inherent-safety surfaces and route to "
            ":class:`QuorumAuthorityRequired`."
        ),
    )

    @model_validator(mode="after")
    def _validate_eligibility_all_passed(self) -> Self:
        """Per Guardrail 4: a routing decision only issues when every
        eligibility check passed."""
        if not self.eligibility_verification.all_passed:
            failed = sorted(
                c.kind.value
                for c in self.eligibility_verification.failed_checks
            )
            raise ValueError(
                f"RoutingDecision requires all eligibility checks to "
                f"pass per Guardrail 4; these checks failed: "
                f"{failed}. Eligibility failures must produce "
                f"EscalationRequired, never a routing decision."
            )
        return self

    @model_validator(mode="after")
    def _validate_failure_mode_not_ur_f(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VIII and Section IX: UR-F
        operations are inherent-safety surfaces and route to quorum
        package assembly, never to direct routing decisions."""
        if self.failure_mode_class is FailureModeClass.UR_F:
            raise ValueError(
                "RoutingDecision cannot issue on UR-F operations per "
                "AUR-CUSTODY-001 v1.0 Section VIII; UR-F operations "
                "are inherent-safety surfaces and must route to "
                "QuorumAuthorityRequired with a quorum ceremony."
            )
        return self


class EscalationRequired(_OutputBase):
    """One of the five J-class guardrails fired; the operation does
    not proceed and is routed to operator review.

    Per AUR-CANONICAL-001 v1.6 Section II (Thifur-J): "code does not
    override doctrine: when smart-contract logic conflicts with
    Mentat doctrine, J holds execution and escalates to C2." For this
    agent, "smart-contract logic" generalizes to any external system
    instruction (correspondent banking message, settlement-system
    message, automated routing instruction).
    """

    kind: Literal["escalation_required"] = "escalation_required"
    failed_guardrail: JClassGuardrail = Field(
        description="Which of the five J-class guardrails fired.",
    )
    cascade_guardrail: JClassGuardrail | None = Field(
        default=None,
        description=(
            "Set only when ``failed_guardrail`` is "
            "``DOCTRINE_OVER_CODE`` (Guardrail 2). Names the "
            "underlying guardrail (1, 3, 4, or 5) that the external "
            "instruction would have caused to be violated. Per the "
            "operator's ruling on doctrine-over-code as a meta-"
            "guardrail: this agent does not invent separate failure "
            "modes for Guardrail 2; it explicitly names why the "
            "external instruction would have violated doctrine."
        ),
    )
    failure_reason: str = Field(
        min_length=1,
        description=(
            "Doctrine-cited failure reason. Format: "
            "'<short description> per AUR-CUSTODY-001 v1.0 Section "
            "VI Guardrail N — <specific failure>'. For "
            "DOCTRINE_OVER_CODE escalations: 'Doctrine-over-code "
            "hold per AUR-CUSTODY-001 v1.0 Section VI Guardrail 2: "
            "external instruction conflicts with [Guardrail N] — "
            "[specific failure]'."
        ),
    )
    escalation_tier: CAOMTier = Field(
        description=(
            "CAOM-001 tier the escalation is routed to. Per Section "
            "V: typically T1 for routine eligibility/path failures, "
            "T2 for doctrine-over-code holds and jurisdictional "
            "attribution failures. Never QUORUM — quorum-required "
            "operations produce QuorumAuthorityRequired, not "
            "escalations."
        ),
    )
    attempted_dimension: PathSelectionDimension | None = Field(
        default=None,
        description=(
            "The path-selection dimension the agent was attempting "
            "when the guardrail fired. None when the guardrail fires "
            "before any dimension-specific logic (e.g., eligibility "
            "fails before path selection begins)."
        ),
    )
    eligibility_verification: EligibilityVerification | None = Field(
        default=None,
        description=(
            "Eligibility verification results. Required when "
            "``failed_guardrail`` is ``ELIGIBILITY_BEFORE_ROUTING``; "
            "optional otherwise (an escalation in another guardrail "
            "may still want to record the eligibility state)."
        ),
    )
    jurisdictional_attribution: JurisdictionalAttribution | None = Field(
        default=None,
        description=(
            "Jurisdictional attribution if it was performed before "
            "the escalation. Required when ``failed_guardrail`` is "
            "``JURISDICTIONAL_ATTRIBUTION`` and the escalation is "
            "for a malformed (rather than missing) attribution; None "
            "when the guardrail fires because attribution is absent."
        ),
    )
    conflicting_external_instruction: str | None = Field(
        default=None,
        description=(
            "Description of the external instruction that conflicted "
            "with doctrine. Required when ``failed_guardrail`` is "
            "``DOCTRINE_OVER_CODE``; None otherwise."
        ),
    )

    @model_validator(mode="after")
    def _validate_escalation_tier_is_not_quorum(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VII: quorum-required
        operations produce ``QuorumAuthorityRequired``, not an
        escalation. The escalation_tier on an EscalationRequired
        output is never QUORUM."""
        if self.escalation_tier is CAOMTier.QUORUM:
            raise ValueError(
                "EscalationRequired.escalation_tier cannot be QUORUM; "
                "quorum-required operations produce "
                "QuorumAuthorityRequired per AUR-CUSTODY-001 v1.0 "
                "Section VII, not an escalation."
            )
        return self

    @model_validator(mode="after")
    def _validate_cascade_guardrail_only_for_doctrine_over_code(self) -> Self:
        """Per the operator's ruling on doctrine-over-code as a meta-
        guardrail: ``cascade_guardrail`` is meaningful only when
        Guardrail 2 fires; for any other failed guardrail the field
        must be None. Conversely, when Guardrail 2 fires, the
        cascade must be named (the doctrine-over-code hold cannot be
        attributed only to itself)."""
        is_doctrine_over_code = self.failed_guardrail is JClassGuardrail.DOCTRINE_OVER_CODE
        if is_doctrine_over_code and self.cascade_guardrail is None:
            raise ValueError(
                "EscalationRequired with failed_guardrail="
                "DOCTRINE_OVER_CODE must name the cascade_guardrail "
                "(the underlying Guardrail 1/3/4/5 the external "
                "instruction would have violated). Per the operator "
                "ruling on doctrine-over-code as a meta-guardrail."
            )
        if not is_doctrine_over_code and self.cascade_guardrail is not None:
            raise ValueError(
                f"EscalationRequired carries cascade_guardrail="
                f"{self.cascade_guardrail.value!r} but "
                f"failed_guardrail is "
                f"{self.failed_guardrail.value!r}, not "
                f"DOCTRINE_OVER_CODE. Cascade is only meaningful for "
                f"Guardrail 2."
            )
        if is_doctrine_over_code and self.cascade_guardrail is JClassGuardrail.DOCTRINE_OVER_CODE:
            raise ValueError(
                "EscalationRequired.cascade_guardrail cannot itself "
                "be DOCTRINE_OVER_CODE; the cascade must name a "
                "different guardrail (1, 3, 4, or 5) that the "
                "external instruction would have violated."
            )
        return self

    @model_validator(mode="after")
    def _validate_doctrine_over_code_carries_instruction(self) -> Self:
        """Per Guardrail 2: doctrine-over-code holds must record the
        conflicting external instruction so operators can review what
        the agent rejected."""
        is_doctrine_over_code = self.failed_guardrail is JClassGuardrail.DOCTRINE_OVER_CODE
        if is_doctrine_over_code and not self.conflicting_external_instruction:
            raise ValueError(
                "EscalationRequired with failed_guardrail="
                "DOCTRINE_OVER_CODE must carry "
                "conflicting_external_instruction; operators need to "
                "review what the agent rejected."
            )
        return self

    @model_validator(mode="after")
    def _validate_eligibility_failure_carries_verification(self) -> Self:
        """Per Guardrail 4: eligibility failures must carry the
        verification record showing which checks failed."""
        is_eligibility = self.failed_guardrail is JClassGuardrail.ELIGIBILITY_BEFORE_ROUTING
        if is_eligibility and self.eligibility_verification is None:
            raise ValueError(
                "EscalationRequired with failed_guardrail="
                "ELIGIBILITY_BEFORE_ROUTING must carry "
                "eligibility_verification showing which checks "
                "failed."
            )
        if (
            is_eligibility
            and self.eligibility_verification is not None
            and self.eligibility_verification.all_passed
        ):
            raise ValueError(
                "EscalationRequired with failed_guardrail="
                "ELIGIBILITY_BEFORE_ROUTING must carry an "
                "eligibility_verification with at least one failed "
                "check; all-passed verification cannot fail "
                "Guardrail 4."
            )
        return self


class QuorumAuthorityRequired(_OutputBase):
    """The operation is on an inherent-safety surface owned by this
    agent and requires N-of-M signatures per AUR-CUSTODY-001 v1.0
    Section VII.

    The agent assembles the operation package and stops at package
    assembly. The downstream quorum ceremony module (out of scope at
    this build layer) consumes the package, runs the six-step
    ceremony per Section VII, and emits the signed authorization.
    """

    kind: Literal["quorum_authority_required"] = "quorum_authority_required"
    inherent_safety_surface: InherentSafetySurface = Field(
        description=(
            "The inherent-safety surface that triggered the quorum "
            "requirement. Must be one of the five surfaces in "
            ":data:`FIAT_SPECIALIST_OWNED_SURFACES` (per the "
            "operator's ruling on Section IX surface ownership)."
        ),
    )
    operation_package: OperationPackage = Field(
        description="The eight-component operation package per Section VII Step 1.",
    )

    @model_validator(mode="after")
    def _validate_surface_is_owned_by_agent(self) -> Self:
        """Per the operator's ruling on Section IX surface ownership:
        the FIAT Operations Specialist owns five Section IX surfaces;
        any other surface routes to a different role or layer."""
        if self.inherent_safety_surface not in FIAT_SPECIALIST_OWNED_SURFACES:
            owned_names = sorted(s.value for s in FIAT_SPECIALIST_OWNED_SURFACES)
            raise ValueError(
                f"QuorumAuthorityRequired.inherent_safety_surface "
                f"{self.inherent_safety_surface.value!r} is not owned "
                f"by the FIAT Operations Specialist. Per the "
                f"operator's ruling on AUR-CUSTODY-001 v1.0 Section "
                f"IX surface ownership, this agent owns: "
                f"{owned_names}. Other Section IX surfaces are owned "
                f"by other roles (Custody Operations Analyst at Tier "
                f"1, Digital Asset Custody Specialist, Collateral "
                f"Operations Specialist) or by layers above this "
                f"agent."
            )
        return self

    @model_validator(mode="after")
    def _validate_package_operation_id_matches(self) -> Self:
        """The operation_id on the output must match the operation_id
        on the embedded package's pre-state stub. Mismatch implies
        the agent attached the wrong package to a quorum
        notification."""
        package_op_id = self.operation_package.pre_operation_dsor_state_stub.operation_id
        if self.operation_id != package_op_id:
            raise ValueError(
                f"QuorumAuthorityRequired.operation_id "
                f"({self.operation_id}) does not match "
                f"operation_package.pre_operation_dsor_state_stub."
                f"operation_id ({package_op_id})."
            )
        return self


FIATOperationsOutput = RoutingDecision | EscalationRequired | QuorumAuthorityRequired
"""Discriminated union of the three FIAT Operations Specialist outputs.

Downstream consumers pattern-match on the ``kind`` discriminator:
``"routing_decision"``, ``"escalation_required"``, or
``"quorum_authority_required"``.
"""


__all__ = [
    "AGENT_CLASS_FIAT_OPERATIONS_SPECIALIST",
    "FIAT_SPECIALIST_OWNED_SURFACES",
    "AgentClass",
    "EligibilityCheck",
    "EligibilityCheckKind",
    "EligibilityVerification",
    "EscalationRequired",
    "FIATOperationsOutput",
    "JClassGuardrail",
    "JurisdictionalAttribution",
    "OperationPackage",
    "PathSelectionDimension",
    "QuorumAuthorityRequired",
    "RoutingDecision",
    "RoutingRecommendation",
]
