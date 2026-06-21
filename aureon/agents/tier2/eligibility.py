"""Eligibility verification for the FIAT Operations Specialist.

Per AUR-CUSTODY-001 v1.0 Section VI line 634 (FIAT-leg rendering of
the J-class "eligibility before routing" guardrail) and AUR-CANONICAL-
001 v1.6 Axiom 8 (Verana Autonomous Block, OFAC enforcement).

This module implements :func:`verify_eligibility`, which produces an
:class:`~aureon.agents.tier2.outputs.EligibilityVerification` from a
typed :class:`EligibilityInputs` package. The five checks per
:class:`~aureon.agents.tier2.outputs.EligibilityCheckKind` are:

1. **KYC** — beneficial owner identity verification (current,
   non-expired evidence).
2. **KYB** — counterparty entity verification (current, non-expired
   evidence). Vacuous-pass when the operation has no counterparty
   entity.
3. **OFAC** — Treasury Office of Foreign Assets Control screening of
   subjects on the OFAC SDN, CAPTA, and analogous lists. Verana
   enforces OFAC autonomously at Layer 0 (AUR-CANONICAL-001 v1.6
   Axiom 8); this check confirms the screening was performed and did
   not match.
4. **SANCTIONS** — non-OFAC sanctions screening (UN, EU, UK HMT,
   jurisdiction-specific lists).
5. **CORRESPONDENT_BANK_COMPLIANCE** — current compliance attestation
   for each correspondent bank in the operation's routing path.
   Vacuous-pass when the operation does not route through
   correspondent banking.

Per the build prompt: "implement as type-safe checks against operation
inputs; do not integrate with external eligibility services."
External-service integration (real OFAC list lookups, real KYC/KYB
provider APIs, real correspondent-bank compliance attestation
sources) is operational-specification work for FED-001 / INST-001 and
is tracked in ``FOLLOW-UPS.md``. The verifier here checks that the
agent has the required evidence in hand and that the evidence is
current; it does not call external systems to refresh the evidence.

The verifier is pure: same inputs always produce the same
:class:`EligibilityVerification`. This is consistent with the
deterministic discipline expected of agent-layer code (per the
contracts-build pattern of pure cross-validators).
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
)

# ---------------------------------------------------------------------------
# Evidence models
# ---------------------------------------------------------------------------


class KYCEvidence(BaseModel):
    """Evidence that KYC verification was performed for a beneficial owner.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4. The agent does
    not perform KYC; it confirms upstream KYC evidence is present and
    current.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    beneficial_owner_id: str = Field(min_length=1)
    kyc_reference_id: str = Field(
        min_length=1,
        description="Identifier of the upstream KYC verification record.",
    )
    verified_at: datetime
    expires_at: datetime


class KYBEvidence(BaseModel):
    """Evidence that KYB verification was performed for a counterparty
    entity.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4. KYB applies only
    to operations involving a counterparty entity; operations with no
    counterparty (e.g., internal positioning) skip KYB via vacuous-
    pass per :attr:`EligibilityInputs.requires_kyb`.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    counterparty_entity_id: str = Field(min_length=1)
    kyb_reference_id: str = Field(
        min_length=1,
        description="Identifier of the upstream KYB verification record.",
    )
    verified_at: datetime
    expires_at: datetime


class OFACScreeningEvidence(BaseModel):
    """Evidence that an OFAC screening was performed on a subject.

    Per AUR-CANONICAL-001 v1.6 Axiom 8 (Verana Autonomous Block):
    Verana enforces OFAC autonomously at Layer 0. The agent's check
    confirms the per-operation screening was performed (typically by
    Verana or by the AML/KYC Analyst Tier 2 agent per AUR-CANONICAL-
    001 v1.6 Section IV) and did not match.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    subject_id: str = Field(
        min_length=1,
        description=(
            "Identifier of the screened subject (beneficial owner id, "
            "counterparty entity id, intermediary correspondent BIC, "
            "etc.)."
        ),
    )
    screening_id: str = Field(
        min_length=1,
        description="Identifier of the screening record (for DSOR replay).",
    )
    matched: bool = Field(
        description=(
            "True if the subject matched a list entry; False if the "
            "screening cleared."
        ),
    )
    matched_list: str | None = Field(
        default=None,
        description=(
            "Name of the OFAC list the subject matched (SDN, CAPTA, "
            "NS-PLC, etc.). Required when ``matched`` is True; must "
            "be None when ``matched`` is False."
        ),
    )
    screened_at: datetime

    @model_validator(mode="after")
    def _validate_matched_list_consistency(self) -> Self:
        """Per Guardrail 4: a matched screening must name the list it
        matched on so downstream review can verify the match against
        the source-of-truth list."""
        if self.matched and not self.matched_list:
            raise ValueError(
                "OFACScreeningEvidence with matched=True must name "
                "the matched_list (SDN, CAPTA, NS-PLC, etc.) per "
                "AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 and "
                "AUR-CANONICAL-001 v1.6 Axiom 8."
            )
        if not self.matched and self.matched_list is not None:
            raise ValueError(
                "OFACScreeningEvidence with matched=False must not "
                "carry a matched_list; the field is reserved for "
                "matches."
            )
        return self


class SanctionsScreeningEvidence(BaseModel):
    """Evidence that a non-OFAC sanctions screening was performed.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4. Covers UN, EU,
    UK HMT, and jurisdiction-specific sanctions lists. OFAC is a
    distinct check (handled by :class:`OFACScreeningEvidence`).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    subject_id: str = Field(min_length=1)
    screening_id: str = Field(min_length=1)
    matched: bool
    matched_list: str | None = Field(
        default=None,
        description=(
            "Name of the sanctions list the subject matched (UN, EU, "
            "UK HMT, jurisdiction-specific). Required when ``matched`` "
            "is True; must be None when False."
        ),
    )
    screened_at: datetime

    @model_validator(mode="after")
    def _validate_matched_list_consistency(self) -> Self:
        if self.matched and not self.matched_list:
            raise ValueError(
                "SanctionsScreeningEvidence with matched=True must "
                "name the matched_list (UN, EU, UK HMT, jurisdiction-"
                "specific) per AUR-CUSTODY-001 v1.0 Section VI "
                "Guardrail 4."
            )
        if not self.matched and self.matched_list is not None:
            raise ValueError(
                "SanctionsScreeningEvidence with matched=False must "
                "not carry a matched_list."
            )
        return self


class CorrespondentBankComplianceEvidence(BaseModel):
    """Evidence that a correspondent bank holds a current compliance
    attestation.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 line 634:
    "correspondent-bank compliance verification before any large-value
    transfer." The attestation typically covers Basel correspondent
    banking expectations, sanctions program adequacy, and AML controls
    appropriate to the correspondent's regulatory regime.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    correspondent_bic: str = Field(
        min_length=8,
        max_length=11,
        description=(
            "BIC of the correspondent (8 or 11 characters per ISO "
            "9362)."
        ),
    )
    attestation_id: str = Field(min_length=1)
    attested_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------------------
# EligibilityInputs
# ---------------------------------------------------------------------------


class EligibilityInputs(BaseModel):
    """The complete evidence package the agent passes to
    :func:`verify_eligibility`.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 and the build
    prompt: "implement as type-safe checks against operation inputs;
    do not integrate with external eligibility services." This input
    type is the agent's structured view of the eligibility evidence
    it has gathered for the operation; the verifier is a pure
    function over this input.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    check_time: datetime = Field(
        description=(
            "Time at which the verification is being performed. "
            "Typically the operation's ``initiated_at``. The verifier "
            "uses this to determine whether time-bound evidence "
            "(KYC/KYB/correspondent compliance) has expired."
        ),
    )
    kyc: KYCEvidence | None = Field(
        default=None,
        description="Beneficial-owner KYC evidence; None if missing.",
    )
    kyb: KYBEvidence | None = Field(
        default=None,
        description=(
            "Counterparty KYB evidence; None when no counterparty "
            "entity is involved or when the evidence is missing."
        ),
    )
    ofac_screenings: tuple[OFACScreeningEvidence, ...] = Field(
        default=(),
        description=(
            "OFAC screening records — one per subject (beneficial "
            "owner, counterparty, intermediary correspondents). At "
            "least one record must be present for the OFAC check to "
            "pass; any matched record fails the check."
        ),
    )
    sanctions_screenings: tuple[SanctionsScreeningEvidence, ...] = Field(
        default=(),
        description=(
            "Non-OFAC sanctions screening records — same per-subject "
            "structure as ``ofac_screenings``."
        ),
    )
    correspondent_compliance: tuple[CorrespondentBankComplianceEvidence, ...] = Field(
        default=(),
        description=(
            "Correspondent-bank compliance attestations — one per "
            "correspondent in the operation's routing path."
        ),
    )
    requires_kyb: bool = Field(
        default=True,
        description=(
            "True (default) when the operation involves a "
            "counterparty entity that requires KYB verification. "
            "False for operations with no counterparty (e.g., "
            "internal cash sweep within the same beneficial owner's "
            "accounts); the KYB check vacuous-passes."
        ),
    )
    requires_correspondent_compliance: bool = Field(
        default=False,
        description=(
            "True when the operation routes through correspondent "
            "banking. The set of expected correspondents is named "
            "in :attr:`expected_correspondent_bics`."
        ),
    )
    expected_correspondent_bics: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "BICs of the correspondents the operation routes "
            "through. Each BIC in this set must have a current, "
            "non-expired entry in :attr:`correspondent_compliance` "
            "for the correspondent-bank-compliance check to pass."
        ),
    )

    @model_validator(mode="after")
    def _validate_correspondent_expectations_set_when_required(self) -> Self:
        """Per Guardrail 4: when correspondent compliance is required,
        the agent must name the correspondents to verify against;
        otherwise the check would vacuously pass on no expected BICs,
        defeating the guardrail."""
        if self.requires_correspondent_compliance and not self.expected_correspondent_bics:
            raise ValueError(
                "EligibilityInputs with requires_correspondent_"
                "compliance=True must name at least one expected "
                "correspondent BIC in expected_correspondent_bics; "
                "otherwise the check would vacuously pass per "
                "AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."
            )
        return self


# ---------------------------------------------------------------------------
# Per-check verifiers (private)
# ---------------------------------------------------------------------------


def _verify_kyc(inputs: EligibilityInputs) -> EligibilityCheck:
    """KYC check per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."""
    if inputs.kyc is None:
        return EligibilityCheck(
            kind=EligibilityCheckKind.KYC,
            passed=False,
            failure_reason=(
                "KYC evidence missing for beneficial owner; per "
                "AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 "
                "(eligibility before routing), KYC verification "
                "must be performed and current before any routing "
                "decision."
            ),
            verified_at=inputs.check_time,
        )
    if inputs.kyc.expires_at < inputs.check_time:
        return EligibilityCheck(
            kind=EligibilityCheckKind.KYC,
            passed=False,
            failure_reason=(
                f"KYC evidence for beneficial owner "
                f"{inputs.kyc.beneficial_owner_id!r} expired at "
                f"{inputs.kyc.expires_at.isoformat()} (check time "
                f"{inputs.check_time.isoformat()}); per "
                f"AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."
            ),
            verified_at=inputs.check_time,
        )
    return EligibilityCheck(
        kind=EligibilityCheckKind.KYC,
        passed=True,
        verified_at=inputs.check_time,
    )


def _verify_kyb(inputs: EligibilityInputs) -> EligibilityCheck:
    """KYB check per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."""
    if not inputs.requires_kyb:
        # Vacuous pass — operation has no counterparty entity.
        return EligibilityCheck(
            kind=EligibilityCheckKind.KYB,
            passed=True,
            verified_at=inputs.check_time,
        )
    if inputs.kyb is None:
        return EligibilityCheck(
            kind=EligibilityCheckKind.KYB,
            passed=False,
            failure_reason=(
                "KYB evidence missing for counterparty entity; per "
                "AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 "
                "(eligibility before routing), KYB verification "
                "must be performed for operations involving "
                "counterparty entities."
            ),
            verified_at=inputs.check_time,
        )
    if inputs.kyb.expires_at < inputs.check_time:
        return EligibilityCheck(
            kind=EligibilityCheckKind.KYB,
            passed=False,
            failure_reason=(
                f"KYB evidence for counterparty entity "
                f"{inputs.kyb.counterparty_entity_id!r} expired at "
                f"{inputs.kyb.expires_at.isoformat()} (check time "
                f"{inputs.check_time.isoformat()}); per "
                f"AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."
            ),
            verified_at=inputs.check_time,
        )
    return EligibilityCheck(
        kind=EligibilityCheckKind.KYB,
        passed=True,
        verified_at=inputs.check_time,
    )


def _verify_ofac(inputs: EligibilityInputs) -> EligibilityCheck:
    """OFAC check per AUR-CANONICAL-001 v1.6 Axiom 8 and
    AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."""
    if not inputs.ofac_screenings:
        return EligibilityCheck(
            kind=EligibilityCheckKind.OFAC,
            passed=False,
            failure_reason=(
                "OFAC screening not performed for any subject; per "
                "AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 and "
                "AUR-CANONICAL-001 v1.6 Axiom 8 (Verana Autonomous "
                "Block), OFAC screening is required before routing."
            ),
            verified_at=inputs.check_time,
        )
    matched = [s for s in inputs.ofac_screenings if s.matched]
    if matched:
        first = matched[0]
        return EligibilityCheck(
            kind=EligibilityCheckKind.OFAC,
            passed=False,
            failure_reason=(
                f"OFAC screening matched: subject "
                f"{first.subject_id!r} on list "
                f"{first.matched_list!r}; per AUR-CANONICAL-001 v1.6 "
                f"Axiom 8 (Verana Autonomous Block), Verana enforces "
                f"OFAC autonomously and the agent does not route "
                f"past a match."
            ),
            verified_at=inputs.check_time,
        )
    return EligibilityCheck(
        kind=EligibilityCheckKind.OFAC,
        passed=True,
        verified_at=inputs.check_time,
    )


def _verify_sanctions(inputs: EligibilityInputs) -> EligibilityCheck:
    """Non-OFAC sanctions check per AUR-CUSTODY-001 v1.0 Section VI
    Guardrail 4."""
    if not inputs.sanctions_screenings:
        return EligibilityCheck(
            kind=EligibilityCheckKind.SANCTIONS,
            passed=False,
            failure_reason=(
                "Non-OFAC sanctions screening not performed for any "
                "subject; per AUR-CUSTODY-001 v1.0 Section VI "
                "Guardrail 4, sanctions screening (UN, EU, UK HMT, "
                "jurisdiction-specific lists) is required before "
                "routing."
            ),
            verified_at=inputs.check_time,
        )
    matched = [s for s in inputs.sanctions_screenings if s.matched]
    if matched:
        first = matched[0]
        return EligibilityCheck(
            kind=EligibilityCheckKind.SANCTIONS,
            passed=False,
            failure_reason=(
                f"Sanctions screening matched: subject "
                f"{first.subject_id!r} on list "
                f"{first.matched_list!r}; per AUR-CUSTODY-001 v1.0 "
                f"Section VI Guardrail 4, the agent does not route "
                f"past a sanctions match."
            ),
            verified_at=inputs.check_time,
        )
    return EligibilityCheck(
        kind=EligibilityCheckKind.SANCTIONS,
        passed=True,
        verified_at=inputs.check_time,
    )


def _verify_correspondent_bank_compliance(
    inputs: EligibilityInputs,
) -> EligibilityCheck:
    """Correspondent-bank compliance check per AUR-CUSTODY-001 v1.0
    Section VI Guardrail 4 line 634."""
    if not inputs.requires_correspondent_compliance:
        # Vacuous pass — operation does not route through correspondent banking.
        return EligibilityCheck(
            kind=EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
            passed=True,
            verified_at=inputs.check_time,
        )
    by_bic: dict[str, CorrespondentBankComplianceEvidence] = {
        evidence.correspondent_bic: evidence
        for evidence in inputs.correspondent_compliance
    }
    missing: list[str] = []
    expired: list[str] = []
    for bic in inputs.expected_correspondent_bics:
        evidence = by_bic.get(bic)
        if evidence is None:
            missing.append(bic)
        elif evidence.expires_at < inputs.check_time:
            expired.append(bic)
    if missing:
        return EligibilityCheck(
            kind=EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
            passed=False,
            failure_reason=(
                f"Correspondent-bank compliance attestation missing "
                f"for required BICs: {sorted(missing)}; per "
                f"AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 line "
                f"634, correspondent-bank compliance must be verified "
                f"before any correspondent-banking-routed settlement."
            ),
            verified_at=inputs.check_time,
        )
    if expired:
        return EligibilityCheck(
            kind=EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
            passed=False,
            failure_reason=(
                f"Correspondent-bank compliance attestation expired "
                f"for BICs: {sorted(expired)} (check time "
                f"{inputs.check_time.isoformat()}); per "
                f"AUR-CUSTODY-001 v1.0 Section VI Guardrail 4."
            ),
            verified_at=inputs.check_time,
        )
    return EligibilityCheck(
        kind=EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
        passed=True,
        verified_at=inputs.check_time,
    )


# ---------------------------------------------------------------------------
# Public verifier
# ---------------------------------------------------------------------------


def verify_eligibility(inputs: EligibilityInputs) -> EligibilityVerification:
    """Run the five J-class Guardrail 4 checks and produce an
    :class:`~aureon.agents.tier2.outputs.EligibilityVerification`.

    Per AUR-CUSTODY-001 v1.0 Section VI Guardrail 4 (FIAT-leg
    rendering of the J-class "eligibility before routing" guardrail).
    The function is pure: same inputs produce the same verification.

    The agent calls this once before any path-selection decision; if
    :attr:`EligibilityVerification.all_passed` is False, the agent
    emits an
    :class:`~aureon.agents.tier2.outputs.EscalationRequired` with
    ``failed_guardrail = ELIGIBILITY_BEFORE_ROUTING`` carrying the
    verification record.
    """
    return EligibilityVerification(
        checks=(
            _verify_kyc(inputs),
            _verify_kyb(inputs),
            _verify_ofac(inputs),
            _verify_sanctions(inputs),
            _verify_correspondent_bank_compliance(inputs),
        )
    )


__all__ = [
    "CorrespondentBankComplianceEvidence",
    "EligibilityInputs",
    "KYBEvidence",
    "KYCEvidence",
    "OFACScreeningEvidence",
    "SanctionsScreeningEvidence",
    "verify_eligibility",
]
