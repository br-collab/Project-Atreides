"""Tests for the Settlement Investigation Analyst — Tier 1 · Thifur-R.

Per AUR-CUSTODY-AMD-002 §II.A. The load-bearing assertions are the ones
about what the agent CANNOT do: infer a cause, emit a complete-looking
timeline over an incomplete assembly, or lose evidence when it escalates.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atreides.agents.tier1.investigation_outputs import (
    EXPECTED_SOURCES,
    EvidenceGap,
    EvidenceItem,
    EvidenceSource,
    EvidenceTimeline,
    GapReason,
    InvestigationDiscrepancyCode,
    InvestigationEscalation,
)
from atreides.agents.tier1.settlement_investigation_analyst import (
    SettlementInvestigationAnalyst,
)
from atreides.contracts.dsor_stub import CAOMTier, DSORLineageStub

T0 = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)


@pytest.fixture
def analyst() -> SettlementInvestigationAnalyst:
    return SettlementInvestigationAnalyst()


@pytest.fixture
def lineage() -> DSORLineageStub:
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="operator-1",
        initiated_at=T0,
        pre_operation_state_hash=hashlib.sha256(b"pre").hexdigest(),
    )


def _item(source: EvidenceSource, offset: int = 0, label: str = "obs") -> EvidenceItem:
    return EvidenceItem(
        source=source,
        observed_at=T0 + timedelta(seconds=offset),
        label=label,
        value="v",
        provenance=f"{source.value}-ref-1",
    )


def _all_sources_observed() -> tuple[EvidenceItem, ...]:
    return tuple(
        _item(s, offset=i) for i, s in enumerate(sorted(EXPECTED_SOURCES))
    )


def _run(analyst, lineage, store, observations, gaps=()):
    return analyst.run(
        operation_id=uuid4(),
        task_id=uuid4(),
        lineage_stub=lineage,
        observations=observations,
        gaps=gaps,
        store=store,
        now=T0,
    )


# --- the happy path --------------------------------------------------------


class TestCompleteAssembly:
    def test_all_sources_observed_yields_a_timeline(
        self, analyst, lineage, mem_store
    ) -> None:
        out, record = _run(analyst, lineage, mem_store, _all_sources_observed())
        assert isinstance(out, EvidenceTimeline)
        assert out.sources_present == EXPECTED_SOURCES
        assert out.gaps == ()
        assert record.record_id is not None

    def test_not_applicable_gap_does_not_escalate(
        self, analyst, lineage, mem_store
    ) -> None:
        """An operation with no FX leg is not missing FX evidence."""
        observed = tuple(
            _item(s, offset=i)
            for i, s in enumerate(sorted(EXPECTED_SOURCES))
            if s is not EvidenceSource.COUNTERPARTY_AFFIRMATION
        )
        gaps = (
            EvidenceGap(
                source=EvidenceSource.COUNTERPARTY_AFFIRMATION,
                reason=GapReason.NOT_APPLICABLE,
                detail="No counterparty leg on this operation.",
            ),
        )
        out, _ = _run(analyst, lineage, mem_store, observed, gaps)
        assert isinstance(out, EvidenceTimeline)

    def test_persisted_output_replays_from_the_dsor(
        self, analyst, lineage, mem_store
    ) -> None:
        out, record = _run(analyst, lineage, mem_store, _all_sources_observed())
        assert mem_store.replay(record.record_id) == out


# --- determinism -----------------------------------------------------------


class TestDeterminism:
    def test_input_order_does_not_affect_the_timeline(
        self, analyst, lineage, mem_store
    ) -> None:
        items = _all_sources_observed()
        a, _ = _run(analyst, lineage, mem_store, items)
        b, _ = _run(analyst, lineage, mem_store, tuple(reversed(items)))
        assert a.items == b.items

    def test_same_timestamp_ties_break_stably(
        self, analyst, lineage, mem_store
    ) -> None:
        tied = tuple(_item(s, offset=0) for s in sorted(EXPECTED_SOURCES))
        a, _ = _run(analyst, lineage, mem_store, tied)
        b, _ = _run(analyst, lineage, mem_store, tuple(reversed(tied)))
        assert [i.source for i in a.items] == [i.source for i in b.items]

    def test_timeline_is_chronological(self, analyst, lineage, mem_store) -> None:
        out, _ = _run(analyst, lineage, mem_store, _all_sources_observed())
        stamps = [i.observed_at for i in out.items]
        assert stamps == sorted(stamps)


# --- completeness is explicit ----------------------------------------------


class TestCompletenessIsExplicit:
    def test_forgotten_source_becomes_an_escalating_gap(
        self, analyst, lineage, mem_store
    ) -> None:
        """A source the caller simply omitted must not pass as complete."""
        observed = tuple(
            _item(s, offset=i)
            for i, s in enumerate(sorted(EXPECTED_SOURCES))
            if s is not EvidenceSource.FUNDING_STATE
        )
        out, _ = _run(analyst, lineage, mem_store, observed)
        assert isinstance(out, InvestigationEscalation)
        assert out.discrepancy_code is (
            InvestigationDiscrepancyCode.EVIDENCE_SOURCE_UNAVAILABLE
        )
        assert any(g.source is EvidenceSource.FUNDING_STATE for g in out.gaps)

    def test_escalation_retains_the_partial_timeline(
        self, analyst, lineage, mem_store
    ) -> None:
        """A gap never costs the operator the evidence that WAS assembled."""
        observed = tuple(
            _item(s, offset=i)
            for i, s in enumerate(sorted(EXPECTED_SOURCES))
            if s is not EvidenceSource.RAIL_STATE
        )
        out, _ = _run(analyst, lineage, mem_store, observed)
        assert isinstance(out, InvestigationEscalation)
        assert len(out.partial_timeline) == len(observed)

    def test_inconsistency_outranks_unavailability(
        self, analyst, lineage, mem_store
    ) -> None:
        gaps = (
            EvidenceGap(
                source=EvidenceSource.MESSAGE_STATUS,
                reason=GapReason.UNAVAILABLE,
                detail="No ACK retrieved.",
            ),
            EvidenceGap(
                source=EvidenceSource.PORTAL_READBACK,
                reason=GapReason.INCONSISTENT,
                detail="Readback contradicts the instruction package.",
            ),
        )
        observed = tuple(
            _item(s, offset=i)
            for i, s in enumerate(sorted(EXPECTED_SOURCES))
            if s
            not in {EvidenceSource.MESSAGE_STATUS, EvidenceSource.PORTAL_READBACK}
        )
        out, _ = _run(analyst, lineage, mem_store, observed, gaps)
        assert out.discrepancy_code is (
            InvestigationDiscrepancyCode.EVIDENCE_INTERNALLY_INCONSISTENT
        )

    def test_no_observations_escalates_without_a_partial_timeline(
        self, analyst, lineage, mem_store
    ) -> None:
        out, _ = _run(analyst, lineage, mem_store, ())
        assert isinstance(out, InvestigationEscalation)
        assert out.discrepancy_code is (
            InvestigationDiscrepancyCode.NO_EVIDENCE_ASSEMBLED
        )
        assert out.partial_timeline == ()


# --- the R-class boundary, enforced structurally ---------------------------


class TestNoInferenceBoundary:
    def test_timeline_cannot_carry_inference(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceTimeline(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=DSORLineageStub(
                    authority_tier=CAOMTier.T1,
                    authority_id="op",
                    initiated_at=T0,
                    pre_operation_state_hash=hashlib.sha256(b"p").hexdigest(),
                ),
                emitted_at=T0,
                items=(_item(EvidenceSource.DSOR_LINEAGE),),
                contains_inference=True,  # type: ignore[arg-type]
            )

    def test_no_cause_or_hypothesis_field_exists_anywhere(self) -> None:
        """The Tier 1/Tier 2 split is the reason Thifur-H stays unactivated."""
        banned = {"cause", "hypothesis", "likely_cause", "ranking", "probability"}
        for model in (EvidenceTimeline, InvestigationEscalation, EvidenceItem):
            assert not (banned & set(model.model_fields))

    def test_incomplete_assembly_cannot_be_emitted_as_a_timeline(
        self, lineage
    ) -> None:
        """Constructing a complete-looking timeline over a gap must fail."""
        with pytest.raises(ValidationError, match="escalating gaps"):
            EvidenceTimeline(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=lineage,
                emitted_at=T0,
                items=_all_sources_observed(),
                gaps=(
                    EvidenceGap(
                        source=EvidenceSource.RAIL_STATE,
                        reason=GapReason.UNAVAILABLE,
                        detail="down",
                    ),
                ),
            )

    def test_timeline_must_account_for_every_expected_source(
        self, lineage
    ) -> None:
        with pytest.raises(ValidationError, match="does not account for"):
            EvidenceTimeline(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=lineage,
                emitted_at=T0,
                items=(_item(EvidenceSource.DSOR_LINEAGE),),
            )

    def test_evidence_requires_provenance(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceItem(
                source=EvidenceSource.MESSAGE_STATUS,
                observed_at=T0,
                label="ACK",
                value="accepted",
                provenance="",
            )

    def test_unordered_items_are_rejected(self, lineage) -> None:
        with pytest.raises(ValidationError, match="ordered by observed_at"):
            EvidenceTimeline(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=lineage,
                emitted_at=T0,
                items=(
                    _item(EvidenceSource.RECONCILIATION, offset=10),
                    _item(EvidenceSource.DSOR_LINEAGE, offset=0),
                ),
            )

    def test_no_evidence_code_cannot_carry_a_partial_timeline(
        self, lineage
    ) -> None:
        """The code and the payload must not contradict each other."""
        with pytest.raises(ValidationError, match="contradicts the payload"):
            InvestigationEscalation(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=lineage,
                emitted_at=T0,
                discrepancy_code=(
                    InvestigationDiscrepancyCode.NO_EVIDENCE_ASSEMBLED
                ),
                failure_detail="nothing supplied",
                gaps=(
                    EvidenceGap(
                        source=EvidenceSource.DSOR_LINEAGE,
                        reason=GapReason.UNAVAILABLE,
                        detail="absent",
                    ),
                ),
                partial_timeline=(_item(EvidenceSource.DSOR_LINEAGE),),
            )

    def test_escalation_requires_a_genuinely_escalating_gap(
        self, lineage
    ) -> None:
        """A not-applicable gap is not a failure and must not escalate."""
        with pytest.raises(ValidationError, match="at least one gap whose"):
            InvestigationEscalation(
                operation_id=uuid4(),
                task_id=uuid4(),
                lineage_stub=lineage,
                emitted_at=T0,
                discrepancy_code=(
                    InvestigationDiscrepancyCode.EVIDENCE_SOURCE_UNAVAILABLE
                ),
                failure_detail="spurious",
                gaps=(
                    EvidenceGap(
                        source=EvidenceSource.RAIL_STATE,
                        reason=GapReason.NOT_APPLICABLE,
                        detail="no rail leg",
                    ),
                ),
            )
