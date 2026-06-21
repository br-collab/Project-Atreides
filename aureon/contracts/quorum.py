"""Quorum authority typed substrate for custody operations.

Per AUR-CUSTODY-001 v1.0 Section VII (Quorum Authority Operational
Specification) and AUR-CANONICAL-001 v1.6 Section V "Quorum Authority —
Future Mode".

Per the build prompt, the contracts layer holds the **typed substrate
for the ceremony state**, not the ceremony execution itself. The
ceremony state machine, signature collection, cryptographic signing
infrastructure, and architectural enforcement of independence between
signing authorities are subsequent work (out of scope for this build).

What this module exposes:

- ``QuorumThreshold`` — N-of-M structure with default 3-of-5 per
  Section VII, adjustable per operational specification (Sovereign and
  Federate documents tighten or relax within the named ranges).
- ``IndependenceRequirement`` — the five independence requirements
  enumerated in Section VII Step 4 (identity, organizational,
  geographic, system, temporal).
- ``CeremonyStep`` — the six steps of the signature ceremony protocol
  enumerated in Section VII (Operation package assembly through
  Post-operation reconciliation).
- ``CeremonyState`` — high-level ceremony lifecycle state.
- ``SigningAuthority`` — separation-of-duties data per signer (identity,
  organizational unit, jurisdiction, signing system).
- ``Signature`` — collected signature record (authority, timestamp,
  optional commentary).
- ``QuorumAuthority`` — the composite ceremony-state object that
  custody operations carry.

The structural validators enforce:

- N ≥ 1 and N ≤ M
- Signing pool size equals M
- No authority signs more than once
- Every collected signature references a member of the signing pool
- When ``IndependenceRequirement.IDENTITY`` is required, no two pool
  members share an identity identifier (and analogously for
  organizational, geographic, and system)

Temporal independence (signature interval enforcement) is a runtime
ceremony-execution concern; the contracts layer exposes the requirement
flag and the per-signature timestamp but does not enforce intervals.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_THRESHOLD_N: int = 3
"""Default N for the canonical 3-of-5 quorum per AUR-CUSTODY-001 v1.0
Section VII."""

DEFAULT_THRESHOLD_M: int = 5
"""Default M for the canonical 3-of-5 quorum per AUR-CUSTODY-001 v1.0
Section VII."""


class IndependenceRequirement(StrEnum):
    """The five independence requirements for quorum authorities.

    Per AUR-CUSTODY-001 v1.0 Section VII "N-of-M Structure".
    """

    IDENTITY = "identity"
    """No single human individual may hold more than one signing
    authority position. A single individual cannot satisfy multiple
    positions through multiple credentials or roles."""

    ORGANIZATIONAL = "organizational"
    """Signing authorities should span at least three organizational
    units (operations, risk, compliance, treasury, audit) at Sovereign
    deployment; Federate deployments adapt the requirement to smaller
    organizational structures with demonstrable architectural
    separation."""

    GEOGRAPHIC = "geographic"
    """Where feasible, signing authorities should span at least two
    jurisdictions to protect against single-jurisdiction failure modes
    (regulatory action, physical incident, political event)."""

    SYSTEM = "system"
    """The signing infrastructure for each authority must be
    architecturally separated — independent credentials, signing
    devices, authentication infrastructure. Compromise of any single
    signing system must not be sufficient to forge multiple signatures."""

    TEMPORAL = "temporal"
    """For high-magnitude operations, signatures must be collected over
    a defined minimum interval (the doctrine references 1 hour minimum
    between first and last signature) to allow detection of anomalous
    signing patterns. Interval enforcement is a runtime ceremony-
    execution concern; the contracts layer carries the requirement
    flag and the per-signature timestamps."""


class CeremonyStep(StrEnum):
    """The six steps of the signature ceremony protocol.

    Per AUR-CUSTODY-001 v1.0 Section VII "Signature Ceremony Protocol".
    """

    PACKAGE_ASSEMBLY = "step_1_operation_package_assembly"
    """Tier 2 specialist assembles the operation package: custody
    operation specification, beneficial owner identifications, asset
    identifications, doctrine version stamp, pre-operation DSOR state,
    post-operation projected DSOR state, supporting documentation."""

    CEREMONY_INITIATION = "step_2_ceremony_initiation"
    """Operation package submitted to quorum authority infrastructure
    with a session identifier logged to the DSOR."""

    SIGNATURE_COLLECTION = "step_3_signature_collection"
    """Each signing authority independently reviews, performs
    organization-specific verification, and signs. Each signature is
    logged to DSOR with authority identity, timestamp, commentary."""

    QUORUM_VERIFICATION = "step_4_quorum_verification"
    """Quorum authority infrastructure verifies independence criteria
    are satisfied. Verification failure halts the ceremony and
    escalates per CAOM-001 Tier 0 Halt protocol."""

    OPERATION_EXECUTION = "step_5_operation_execution"
    """Custody operation executes through Tier 1 or Tier 2 agent.
    Execution itself is logged to DSOR with the quorum ceremony
    lineage attached."""

    POST_OPERATION_RECONCILIATION = "step_6_post_operation_reconciliation"
    """Post-operation DSOR state verified against the projection from
    Step 1. Any discrepancy triggers immediate escalation per Axiom 6."""


class CeremonyState(StrEnum):
    """High-level ceremony lifecycle state."""

    PENDING = "pending"
    """Ceremony declared but not yet initiated."""

    IN_PROGRESS = "in_progress"
    """Ceremony actively collecting signatures."""

    COMPLETED = "completed"
    """N signatures collected, independence verified, ready for or
    completed execution."""

    FAILED = "failed"
    """Ceremony halted due to verification failure or insufficient
    signatures within deadline."""

    ESCALATED = "escalated"
    """Ceremony escalated to Tier 0 Halt per CAOM-001 protocol."""


class _QuorumModel(BaseModel):
    """Shared configuration for quorum models."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class QuorumThreshold(_QuorumModel):
    """N-of-M signature threshold.

    Per AUR-CUSTODY-001 v1.0 Section VII: default is 3-of-5; the
    operational specification range named in the doctrine spans
    2-of-3 (lowest) to 5-of-7 (highest-magnitude). The contracts layer
    enforces only the structural rules (N ≥ 1, N ≤ M); per-magnitude
    threshold selection is a Sovereign / Federate operational
    specification concern (open item per `AUR-CUSTODY-001 v1.0`
    Section XIII).
    """

    n: int = Field(
        default=DEFAULT_THRESHOLD_N,
        ge=1,
        description=(
            "Required number of signatures. Default 3 per Section VII."
        ),
    )
    m: int = Field(
        default=DEFAULT_THRESHOLD_M,
        ge=1,
        description=(
            "Total number of signing authorities in the pool. Default "
            "5 per Section VII."
        ),
    )

    @model_validator(mode="after")
    def _enforce_n_le_m(self) -> Self:
        """N must not exceed M.

        A 6-of-5 quorum is logically impossible — Section VII threshold
        ranges (2-of-3 through 5-of-7) all preserve N ≤ M.
        """
        if self.n > self.m:
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section VII, N (required "
                f"signatures, got {self.n}) must not exceed M (total "
                f"signing authorities, got {self.m})."
            )
        return self


class SigningAuthority(_QuorumModel):
    """A single signing authority in the quorum pool.

    Carries the separation-of-duties data the doctrine requires per
    AUR-CUSTODY-001 v1.0 Section VII "N-of-M Structure":

    - identity (no individual holds two positions)
    - organizational unit (operations, risk, compliance, treasury,
      audit, etc.)
    - jurisdiction (geographic independence)
    - signing system (system independence — independent credentials
      and signing devices)
    """

    authority_id: str = Field(
        min_length=1,
        description=(
            "Unique authority identifier within the ceremony pool — "
            "the value used in collected signatures to reference the "
            "signer."
        ),
    )
    identity_id: str = Field(
        min_length=1,
        description=(
            "Identifier of the natural person holding this authority. "
            "Per Section VII identity independence: no two pool "
            "members may share this identifier when "
            "IndependenceRequirement.IDENTITY is required."
        ),
    )
    organizational_unit: str = Field(
        min_length=1,
        description=(
            "Organizational unit (e.g., 'operations', 'risk', "
            "'compliance', 'treasury', 'audit'). Section VII "
            "organizational independence requires the pool to span at "
            "least three units at Sovereign deployment."
        ),
    )
    jurisdiction: str = Field(
        min_length=1,
        description=(
            "ISO 3166-1 alpha-2 (or operational-specification-defined) "
            "jurisdiction identifier. Section VII geographic "
            "independence requires at least two jurisdictions where "
            "operationally feasible."
        ),
    )
    signing_system: str = Field(
        min_length=1,
        description=(
            "Identifier of the signing infrastructure (independent HSM, "
            "MPC node, hardware wallet, ceremony platform) used by this "
            "authority. Section VII system independence requires the "
            "pool to span independent signing systems."
        ),
    )


class Signature(_QuorumModel):
    """A collected signature record.

    Per AUR-CUSTODY-001 v1.0 Section VII Step 3, every signature is
    logged to the DSOR with authority identity, timestamp, and any
    commentary the signer attaches. The contracts layer carries this
    record; the cryptographic signature payload itself is a runtime
    ceremony artifact (out of scope for the contracts layer).
    """

    authority_id: str = Field(
        min_length=1,
        description="The signing authority's pool identifier.",
    )
    signed_at: datetime = Field(
        description=(
            "Timestamp at which the signature was collected. Used by "
            "ceremony-execution code to enforce temporal independence "
            "when IndependenceRequirement.TEMPORAL is required."
        ),
    )
    commentary: str | None = Field(
        default=None,
        description=(
            "Optional free-text commentary from the signer (per "
            "Section VII Step 3 — 'any commentary the signer "
            "attaches')."
        ),
    )


class QuorumAuthority(_QuorumModel):
    """Composite quorum-authority ceremony-state record.

    Custody operations on inherent-safety surfaces carry an instance of
    this record per AUR-CUSTODY-001 v1.0 Section VII. The contracts
    layer enforces structural rules; the ceremony state machine (out of
    scope for this build) drives state transitions and enforces
    runtime concerns (temporal interval, cryptographic signature
    validity, ceremony deadline).
    """

    threshold: QuorumThreshold = Field(
        default_factory=QuorumThreshold,
        description="N-of-M threshold (defaults to 3-of-5).",
    )
    independence_requirements: frozenset[IndependenceRequirement] = Field(
        description=(
            "The independence requirements active for this ceremony. "
            "The doctrine names five (Section VII); operational "
            "specifications determine which apply per operation class "
            "and magnitude."
        ),
    )
    signing_pool: tuple[SigningAuthority, ...] = Field(
        description=(
            "The full pool of signing authorities. Length must equal "
            "threshold.m."
        ),
    )
    collected_signatures: tuple[Signature, ...] = Field(
        default=(),
        description=(
            "Signatures collected so far. Length must not exceed "
            "threshold.n; collected ceremonies in COMPLETED state must "
            "have exactly threshold.n signatures."
        ),
    )
    ceremony_step: CeremonyStep = Field(
        default=CeremonyStep.PACKAGE_ASSEMBLY,
        description="Current step within the six-step protocol.",
    )
    ceremony_state: CeremonyState = Field(
        default=CeremonyState.PENDING,
        description="High-level ceremony lifecycle state.",
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "Session identifier logged to DSOR at ceremony initiation "
            "(Section VII Step 2). None until initiation."
        ),
    )

    @model_validator(mode="after")
    def _enforce_pool_matches_m(self) -> Self:
        """Per Section VII: the signing pool is the M of N-of-M."""
        if len(self.signing_pool) != self.threshold.m:
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section VII, signing_pool "
                f"length ({len(self.signing_pool)}) must equal "
                f"threshold.m ({self.threshold.m})."
            )
        return self

    @model_validator(mode="after")
    def _enforce_unique_authority_ids_in_pool(self) -> Self:
        """Pool members are uniquely identified — duplicate
        ``authority_id`` would make signature reference ambiguous."""
        authority_ids = [a.authority_id for a in self.signing_pool]
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section VII, signing_pool "
                "members must have unique authority_id values."
            )
        return self

    @model_validator(mode="after")
    def _enforce_signature_pool_membership(self) -> Self:
        """Every collected signature must reference a pool member."""
        pool_ids = {a.authority_id for a in self.signing_pool}
        for sig in self.collected_signatures:
            if sig.authority_id not in pool_ids:
                raise ValueError(
                    f"Per AUR-CUSTODY-001 v1.0 Section VII, collected "
                    f"signature references authority_id "
                    f"{sig.authority_id!r} which is not in the signing "
                    f"pool."
                )
        return self

    @model_validator(mode="after")
    def _enforce_no_double_signing(self) -> Self:
        """A pool member may sign at most once per ceremony.

        Double-signing would violate identity independence even when
        identity_id values differ (the same authority_id in the pool
        cannot contribute two signatures toward the threshold).
        """
        authority_ids = [s.authority_id for s in self.collected_signatures]
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section VII, no signing "
                "authority may contribute more than one signature to a "
                "ceremony."
            )
        return self

    @model_validator(mode="after")
    def _enforce_signature_count_bounded_by_threshold(self) -> Self:
        """Collected signatures must not exceed threshold.n.

        A ceremony in COMPLETED state must have exactly N signatures.
        An IN_PROGRESS or PENDING ceremony may have fewer.
        """
        if len(self.collected_signatures) > self.threshold.n:
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section VII, collected "
                f"signatures ({len(self.collected_signatures)}) must "
                f"not exceed threshold.n ({self.threshold.n})."
            )
        if (
            self.ceremony_state is CeremonyState.COMPLETED
            and len(self.collected_signatures) != self.threshold.n
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section VII, COMPLETED "
                f"ceremony must have exactly threshold.n="
                f"{self.threshold.n} signatures, got "
                f"{len(self.collected_signatures)}."
            )
        return self

    @model_validator(mode="after")
    def _enforce_pool_independence(self) -> Self:
        """Enforce identity / organizational / geographic / system
        independence across the pool when those requirements are active.

        Per AUR-CUSTODY-001 v1.0 Section VII "N-of-M Structure".
        Temporal independence is signature-time, not pool-composition,
        and is enforced at ceremony-execution time (out of scope for
        the contracts layer).
        """
        reqs = self.independence_requirements
        if IndependenceRequirement.IDENTITY in reqs:
            ids = [a.identity_id for a in self.signing_pool]
            if len(set(ids)) != len(ids):
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section VII identity "
                    "independence: no two pool members may share an "
                    "identity_id."
                )
        if IndependenceRequirement.ORGANIZATIONAL in reqs:
            # The doctrine names "at least three organizational units"
            # at Sovereign deployment; the contracts layer enforces the
            # general principle (at least two distinct units in the
            # pool) and leaves the per-deployment count to operational
            # specifications.
            units = {a.organizational_unit for a in self.signing_pool}
            min_distinct_units = 2
            if len(units) < min_distinct_units:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section VII "
                    "organizational independence: signing pool must "
                    "span at least two distinct organizational units."
                )
        if IndependenceRequirement.GEOGRAPHIC in reqs:
            jurisdictions = {a.jurisdiction for a in self.signing_pool}
            min_distinct_jurisdictions = 2
            if len(jurisdictions) < min_distinct_jurisdictions:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section VII geographic "
                    "independence: signing pool must span at least "
                    "two jurisdictions."
                )
        if IndependenceRequirement.SYSTEM in reqs:
            systems = {a.signing_system for a in self.signing_pool}
            if len(systems) != len(self.signing_pool):
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section VII system "
                    "independence: every pool member must use a "
                    "distinct signing system."
                )
        return self


__all__ = [
    "DEFAULT_THRESHOLD_M",
    "DEFAULT_THRESHOLD_N",
    "CeremonyState",
    "CeremonyStep",
    "IndependenceRequirement",
    "QuorumAuthority",
    "QuorumThreshold",
    "Signature",
    "SigningAuthority",
]
