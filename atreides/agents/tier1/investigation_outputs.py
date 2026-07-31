"""Output contracts for the Settlement Investigation Analyst — Tier 1 · Thifur-R.

Per AUR-CUSTODY-AMD-002 §II.A (role definition) and AUR-CANONICAL-001 v1.6
Section II (Thifur-R — R-class, deterministic, zero variance).

THE BOUNDARY THIS MODULE ENFORCES
---------------------------------
The Settlement Investigation Analyst **assembles evidence and infers
nothing**. It reconstructs what happened; it never proposes why. Cause
ranking is the Cash-Leg Diagnostic Specialist's work at Tier 2, bounded by
the closed inventory in ``AUR-J-PATHSET-RCA-001``.

That split is doctrinally load-bearing, not stylistic: unbounded causal
inference over novel failures is Thifur-H behaviour, and
``AUR-ROADMAP-001 §III`` non-goal 1 keeps Thifur-H unactivated pending
SR 11-7 Tier 1 validation. So the boundary is enforced structurally rather
than by convention — exactly as the Clearing Operator Cockpit makes a
submission object unconstructible:

- There is no ``cause``, ``hypothesis``, ``likely``, ``probable`` or
  ``ranking`` field anywhere in this module.
- :class:`EvidenceTimeline` pins ``contains_inference`` to
  ``Literal[False]``, so an inferring timeline cannot be constructed.
- Every :class:`EvidenceItem` must cite its ``provenance``. An observation
  with no stated source is not evidence.

COMPLETENESS IS EXPLICIT
------------------------
Per AMD-002 §II.A an incomplete timeline is *surfaced* as incomplete rather
than silently gapped, and an unavailable or internally inconsistent source
escalates. The escalation carries the partial timeline, so assembling
nothing is never the outcome of a gap.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.contracts.dsor_stub import DSORLineageStub

CURRENT_DOCTRINE_VERSION = "AUR-CUSTODY-AMD-002-v0.1"


class EvidenceSource(StrEnum):
    """The evidence sources a cash-leg settlement investigation draws on.

    Ordered as the operation itself flows: what we decided, what we sent,
    what the network said, what came back.
    """

    DSOR_LINEAGE = "dsor_lineage"
    GATE_DECISION = "gate_decision"
    INSTRUCTION_PACKAGE = "instruction_package"
    MESSAGE_STATUS = "message_status"
    FUNDING_STATE = "funding_state"
    RAIL_STATE = "rail_state"
    CUTOFF_CLOCK = "cutoff_clock"
    COUNTERPARTY_AFFIRMATION = "counterparty_affirmation"
    PORTAL_READBACK = "portal_readback"
    RECONCILIATION = "reconciliation"


#: Every source an investigation expects to consult. Completeness is
#: measured against this set — a source absent from the assembled evidence
#: and unaccounted for in ``gaps`` is a defect, not a silent omission.
EXPECTED_SOURCES: frozenset[EvidenceSource] = frozenset(EvidenceSource)


class GapReason(StrEnum):
    """Why an expected source contributed no evidence.

    ``NOT_APPLICABLE`` is the only reason that does not escalate: an
    operation with no FX leg is not missing FX evidence.
    """

    UNAVAILABLE = "unavailable"
    INCONSISTENT = "inconsistent"
    NOT_APPLICABLE = "not_applicable"


#: Gap reasons that make a timeline incomplete and force escalation.
ESCALATING_GAP_REASONS: frozenset[GapReason] = frozenset(
    {GapReason.UNAVAILABLE, GapReason.INCONSISTENT}
)


class InvestigationDiscrepancyCode(StrEnum):
    """Why the assembly escalated. Deliberately about EVIDENCE, never cause."""

    EVIDENCE_SOURCE_UNAVAILABLE = "evidence_source_unavailable"
    EVIDENCE_INTERNALLY_INCONSISTENT = "evidence_internally_inconsistent"
    NO_EVIDENCE_ASSEMBLED = "no_evidence_assembled"


class EvidenceItem(BaseModel):
    """One observation, with its provenance.

    ``provenance`` is mandatory and non-empty: the Tier 2 diagnostic layer
    above cites evidence for every candidate cause it ranks, and it can only
    do that if every observation states where it came from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    source: EvidenceSource
    observed_at: datetime = Field(
        description="When the observation was made — the timeline's sort key.",
    )
    label: str = Field(min_length=1, description="What was observed.")
    value: str = Field(description="The observed value, rendered as text.")
    provenance: str = Field(
        min_length=1,
        description=(
            "Where this observation came from — record id, message "
            "reference, endpoint, or operator entry. An observation with "
            "no stated source is not evidence."
        ),
    )


class EvidenceGap(BaseModel):
    """An expected source that contributed nothing, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    source: EvidenceSource
    reason: GapReason
    detail: str = Field(min_length=1)

    @property
    def escalates(self) -> bool:
        return self.reason in ESCALATING_GAP_REASONS


class _InvestigationOutputBase(BaseModel):
    """Common fields for all Settlement Investigation Analyst outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    task_id: UUID
    doctrine_version: str = CURRENT_DOCTRINE_VERSION
    lineage_stub: DSORLineageStub
    emitted_at: datetime


def _validate_chronological(items: tuple[EvidenceItem, ...]) -> None:
    for earlier, later in zip(items, items[1:], strict=False):
        if later.observed_at < earlier.observed_at:
            raise ValueError(
                "evidence items must be ordered by observed_at; the timeline "
                "is a reconstruction of sequence and an unordered one asserts "
                "a sequence that did not occur"
            )


class EvidenceTimeline(_InvestigationOutputBase):
    """A complete, ordered, provenance-cited reconstruction of an operation.

    Emitted only when every expected source is either represented in
    ``items`` or accounted for by a non-escalating gap. Anything less is an
    :class:`InvestigationEscalation`.
    """

    kind: Literal["evidence_timeline"] = "evidence_timeline"
    items: tuple[EvidenceItem, ...] = Field(min_length=1)
    gaps: tuple[EvidenceGap, ...] = ()
    #: Structural guarantee. This model cannot carry a cause, a hypothesis,
    #: or a ranking, and pinning the flag to False makes an inferring
    #: timeline unconstructible rather than merely discouraged.
    contains_inference: Literal[False] = False

    @model_validator(mode="after")
    def _validate_timeline(self) -> Self:
        _validate_chronological(self.items)
        escalating = [g for g in self.gaps if g.escalates]
        if escalating:
            raise ValueError(
                f"EvidenceTimeline carries escalating gaps "
                f"{[g.source.value for g in escalating]!r}; an incomplete "
                f"assembly must be emitted as an InvestigationEscalation so "
                f"the incompleteness is surfaced, never as a timeline that "
                f"reads complete (AUR-CUSTODY-AMD-002 §II.A)"
            )
        covered = {i.source for i in self.items} | {g.source for g in self.gaps}
        missing = EXPECTED_SOURCES - covered
        if missing:
            raise ValueError(
                f"EvidenceTimeline does not account for expected sources "
                f"{sorted(s.value for s in missing)!r}; every expected source "
                f"must appear as evidence or as a declared gap — silence is "
                f"not an accounting"
            )
        return self

    @property
    def sources_present(self) -> frozenset[EvidenceSource]:
        return frozenset(i.source for i in self.items)


class InvestigationEscalation(_InvestigationOutputBase):
    """Emitted when evidence is unavailable, inconsistent, or absent.

    Carries ``partial_timeline`` so that a gap never costs the operator the
    evidence that *was* assembled — the escalation is about what is missing,
    not a refusal to report what is present.
    """

    kind: Literal["investigation_escalation"] = "investigation_escalation"
    discrepancy_code: InvestigationDiscrepancyCode
    failure_detail: str = Field(min_length=1)
    gaps: tuple[EvidenceGap, ...] = Field(min_length=1)
    partial_timeline: tuple[EvidenceItem, ...] = ()
    contains_inference: Literal[False] = False

    @model_validator(mode="after")
    def _validate_escalation(self) -> Self:
        _validate_chronological(self.partial_timeline)
        if self.discrepancy_code is InvestigationDiscrepancyCode.NO_EVIDENCE_ASSEMBLED:
            if self.partial_timeline:
                raise ValueError(
                    "NO_EVIDENCE_ASSEMBLED escalation carries a non-empty "
                    "partial_timeline — the code contradicts the payload"
                )
        elif not any(g.escalates for g in self.gaps):
            raise ValueError(
                "InvestigationEscalation must carry at least one gap whose "
                "reason escalates (unavailable or inconsistent); a "
                "not-applicable gap is not a failure"
            )
        return self


InvestigationOutput = EvidenceTimeline | InvestigationEscalation

__all__ = [
    "CURRENT_DOCTRINE_VERSION",
    "ESCALATING_GAP_REASONS",
    "EXPECTED_SOURCES",
    "EvidenceGap",
    "EvidenceItem",
    "EvidenceSource",
    "EvidenceTimeline",
    "GapReason",
    "InvestigationDiscrepancyCode",
    "InvestigationEscalation",
    "InvestigationOutput",
]
