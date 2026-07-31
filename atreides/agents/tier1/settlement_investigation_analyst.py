"""Settlement Investigation Analyst — Tier 1 · Thifur-R.

Per AUR-CUSTODY-AMD-002 §II.A and AUR-CANONICAL-001 v1.6 Section II
(Thifur-R — deterministic, zero variance, no path selection).

WHAT THIS AGENT IS FOR
----------------------
Settlement failures and stalled cash legs are routine. The cockpit raises
them through ``raise_break`` and routes them to a workbench where, until
now, a human performed all evidence gathering *and* all causal reasoning
unaided. In settlement operations the dominant cost of an exception is the
gathering — chasing state across the DSOR, the instruction, the message
status, the funding position, the rail calendar and the counterparty. This
agent collapses that cost and hands the operator a complete, ordered,
provenance-cited timeline.

WHAT IT DOES NOT DO
-------------------
It infers nothing. It proposes no cause, ranks no candidates, and
volunteers no hypothesis — those belong to the Cash-Leg Diagnostic
Specialist at Tier 2, bounded by the closed inventory in
``AUR-J-PATHSET-RCA-001``. The separation is why the diagnostic capability
requires no Thifur-H activation (``AUR-ROADMAP-001 §III`` non-goal 1).

The R-class guarantee is what makes the Tier 2 layer above it auditable: if
evidence assembly were itself inferential, every downstream diagnosis would
inherit the error invisibly.

DETERMINISM
-----------
Given the same observations the agent emits the same timeline, byte for
byte. It sorts by observed_at with a stable tiebreak on source order, makes
no network call, and consults no clock except the caller-supplied one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from atreides.agents.tier1.investigation_outputs import (
    EXPECTED_SOURCES,
    EvidenceGap,
    EvidenceItem,
    EvidenceSource,
    EvidenceTimeline,
    InvestigationDiscrepancyCode,
    InvestigationEscalation,
    InvestigationOutput,
)
from atreides.contracts.dsor_stub import DSORLineageStub
from atreides.dsor import DSORRecord, DSORStore

#: Stable ordering for observations sharing a timestamp. Follows the
#: operation's own flow — what we decided, what we sent, what the network
#: said, what came back — so a same-instant tie never reorders between runs.
_SOURCE_ORDER: dict[EvidenceSource, int] = {
    source: index for index, source in enumerate(EvidenceSource)
}


class SettlementInvestigationAnalyst:
    """Tier 1 · Thifur-R — deterministic evidence assembly for cash-leg breaks.

    Usage::

        analyst = SettlementInvestigationAnalyst()
        output, record = analyst.run(
            operation_id=op_id,
            task_id=task_id,
            lineage_stub=lineage,
            observations=items,
            gaps=declared_gaps,
            store=store,
        )
    """

    def run(
        self,
        *,
        operation_id,
        task_id,
        lineage_stub: DSORLineageStub,
        observations: tuple[EvidenceItem, ...] | list[EvidenceItem],
        gaps: tuple[EvidenceGap, ...] | list[EvidenceGap] = (),
        store: DSORStore,
        now: datetime | None = None,
    ) -> tuple[InvestigationOutput, DSORRecord]:
        """Assemble observations into a timeline and persist it to the DSOR.

        Emits an :class:`EvidenceTimeline` when every expected source is
        represented or accounted for by a non-escalating gap. Otherwise
        emits an :class:`InvestigationEscalation` carrying the partial
        timeline — a gap never costs the operator the evidence that was
        assembled.

        Args:
            operation_id: The operation under investigation.
            task_id: C2 task identifier for this investigation.
            lineage_stub: DSOR lineage the output binds to.
            observations: Evidence gathered from the sources. Order is
                irrelevant; the agent sorts deterministically.
            gaps: Sources that contributed nothing, each with a reason.
                Sources neither observed nor declared here are reported as
                unaccounted-for and escalate.
            store: DSOR store for output persistence.
            now: Override emission timestamp (testing only).

        Returns:
            ``(output, record)`` — the emitted output and its persisted
            :class:`DSORRecord`, whose ``record_id`` replays the assembly.
        """
        emitted_at = now if now is not None else datetime.now(tz=UTC)

        ordered = self._order(observations)
        declared = tuple(gaps)
        all_gaps = declared + self._unaccounted_gaps(ordered, declared)

        output: InvestigationOutput
        if not ordered:
            output = InvestigationEscalation(
                operation_id=operation_id,
                task_id=task_id,
                lineage_stub=lineage_stub,
                emitted_at=emitted_at,
                discrepancy_code=(
                    InvestigationDiscrepancyCode.NO_EVIDENCE_ASSEMBLED
                ),
                failure_detail=(
                    "No observations were supplied for this operation; there "
                    "is nothing to reconstruct. Investigation cannot proceed "
                    "without at least one cited observation."
                ),
                gaps=all_gaps or self._unaccounted_gaps((), ()),
            )
        elif escalating := [g for g in all_gaps if g.escalates]:
            output = InvestigationEscalation(
                operation_id=operation_id,
                task_id=task_id,
                lineage_stub=lineage_stub,
                emitted_at=emitted_at,
                discrepancy_code=self._classify(escalating),
                failure_detail=self._describe(escalating),
                gaps=all_gaps,
                partial_timeline=ordered,
            )
        else:
            output = EvidenceTimeline(
                operation_id=operation_id,
                task_id=task_id,
                lineage_stub=lineage_stub,
                emitted_at=emitted_at,
                items=ordered,
                gaps=all_gaps,
            )

        return output, store.append(output, dtg=emitted_at)

    # ------------------------------------------------------------------
    # Deterministic assembly — no inference happens anywhere below.
    # ------------------------------------------------------------------

    @staticmethod
    def _order(
        observations: tuple[EvidenceItem, ...] | list[EvidenceItem],
    ) -> tuple[EvidenceItem, ...]:
        """Sort chronologically, tie-broken by source order then label.

        Total and stable: two runs over the same observations produce
        byte-identical timelines regardless of input order.
        """
        return tuple(
            sorted(
                observations,
                key=lambda i: (i.observed_at, _SOURCE_ORDER[i.source], i.label),
            )
        )

    @staticmethod
    def _unaccounted_gaps(
        items: tuple[EvidenceItem, ...],
        declared: tuple[EvidenceGap, ...],
    ) -> tuple[EvidenceGap, ...]:
        """Name every expected source that is neither observed nor declared.

        This is the completeness guarantee: a source the caller simply
        forgot becomes an explicit UNAVAILABLE gap and escalates, rather
        than passing as a timeline that reads complete.
        """
        covered = {i.source for i in items} | {g.source for g in declared}
        return tuple(
            EvidenceGap(
                source=source,
                reason="unavailable",  # type: ignore[arg-type]
                detail=(
                    f"Source {source.value!r} was neither observed nor "
                    f"declared as a gap; treated as unavailable rather than "
                    f"assumed irrelevant."
                ),
            )
            for source in sorted(
                EXPECTED_SOURCES - covered, key=lambda s: _SOURCE_ORDER[s]
            )
        )

    @staticmethod
    def _classify(
        escalating: list[EvidenceGap],
    ) -> InvestigationDiscrepancyCode:
        """Inconsistency outranks unavailability.

        A source that contradicts itself is a harder failure than one that
        is merely absent: absence is a gap in the picture, contradiction
        means part of the picture is wrong.
        """
        if any(g.reason == "inconsistent" for g in escalating):
            return InvestigationDiscrepancyCode.EVIDENCE_INTERNALLY_INCONSISTENT
        return InvestigationDiscrepancyCode.EVIDENCE_SOURCE_UNAVAILABLE

    @staticmethod
    def _describe(escalating: list[EvidenceGap]) -> str:
        listed = ", ".join(
            f"{g.source.value}({g.reason.value})"
            for g in sorted(escalating, key=lambda g: _SOURCE_ORDER[g.source])
        )
        return (
            f"Evidence assembly incomplete — {len(escalating)} source(s) "
            f"escalating: {listed}. The partial timeline is attached; the "
            f"cause is not determined here (AUR-CUSTODY-AMD-002 §II.A)."
        )


__all__ = ["SettlementInvestigationAnalyst"]
