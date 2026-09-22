"""The synthetic flow the activated agents run against (W3 § WP-A1).

WP-A1 asks for the existing agents to run *continuously against the synthetic
flow rather than on demand*. This module is that flow: a small, deterministic,
repeating cycle of work for each activated agent, built from the same contract
types the agents already take in production.

Everything here is synthetic and says so
----------------------------------------
Every value is invented. Nothing reaches a venue, a rail or a counterparty, and
no credential is used — the containment claim that
:data:`~atreides.activation.outputs.ADVISORY_EFFECTS` makes is true because of
what this module is, not in spite of it. Where a work unit carries provenance,
it carries ``FACT_SYNTHETIC``: reported by a synthetic emulator standing in for
an external authority, never ``FACT_EXTERNAL``.

The cycle is deliberately mixed
-------------------------------
Each agent's flow alternates between a unit that passes its gates and one that
holds. An activation that only ever ran clean work would leave the escalation
path unexercised, and the escalation path is the one that carries the operator's
attention. The cycle is a fixed tuple, indexed by tick, so two runs of the same
supervisor over the same ticks produce the same work — the flow is a fixture,
not a generator, and a surface built on it can be compared between runs.

Clocks are injected, never read
-------------------------------
Every builder takes the time it should stamp. Nothing here calls
``datetime.now``: a fixture that reads the wall clock cannot be replayed, and
the whole point of a continuously running advisory loop is that yesterday's
output can be re-derived.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from atreides.agents.tier1.investigation_outputs import (
    EvidenceGap,
    EvidenceItem,
    EvidenceSource,
    GapReason,
)
from atreides.agents.tier1.outputs import (
    SettlementKind,
    SettlementRail,
    SettlementTaskingRecord,
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
)
from atreides.agents.tier2.fiat_operations_specialist import PathSelectionRequest
from atreides.agents.tier2.outputs import JurisdictionalAttribution
from atreides.contracts import (
    AssetClass,
    CAOMTier,
    CustodyOperationUnion,
    DSORLineageStub,
    DvP1Settlement,
    EquityOperation,
    EquityTransactionType,
    FailureModeClass,
    MajorAssetCategory,
    OrdinarySafekeepingObject,
    Representation,
)
from atreides.rails.cato_cash import (
    CashRail,
    CatoCashDecision,
    FinalityClass,
    GateDecision,
    ReasonCode,
)

__all__ = [
    "SYNTHETIC_OPERATOR",
    "cato_cash_proceed",
    "investigation_lineage",
    "investigation_unit",
    "path_selection_unit",
    "settlement_tasking_unit",
    "synthetic_operation_id",
]

#: The operator on whose direct tasking the synthetic flow runs. CAOM-001: a
#: named human authority, not an agent, stands behind every unit of work.
SYNTHETIC_OPERATOR: Final = "operator-synthetic-activation"

_CYCLE = 2
"""Units in each agent's repeating cycle: one that passes, one that holds."""


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def synthetic_operation_id(agent_id: str, tick: int) -> UUID:
    """A stable operation identifier for ``(agent, tick)``.

    Derived rather than random so that a replayed tick produces the same
    identifier and the DSOR's one-original-record-per-operation rule means the
    same thing across runs.
    """
    return UUID(bytes=hashlib.sha256(f"{agent_id}:{tick}".encode()).digest()[:16], version=4)


def _lineage(operation_id: UUID, at: datetime, label: str) -> DSORLineageStub:
    """A lineage stub bound to its operation.

    ``c2_handoff_id`` is left unset, which is the correct state for an
    operator-direct operation and is what
    :func:`~atreides.activation.handoff.basis_from_lineage` converts into a
    recorded absence before any agent output carries it (AMD1 § 3b).
    """
    return DSORLineageStub(
        operation_id=operation_id,
        authority_tier=CAOMTier.T1,
        authority_id=SYNTHETIC_OPERATOR,
        initiated_at=at,
        pre_operation_state_hash=_hash(f"synthetic-pre-{label}"),
    )


# Tier 1 — Settlement Operations Analyst -----------------------------------------------


def settlement_tasking_unit(tick: int, at: datetime) -> SettlementTaskingRecord:
    """One unit of settlement tasking. Even ticks pass the gates; odd ticks hold.

    The odd unit drives intraday credit usage to the facility limit, which is
    the first gate in the analyst's evaluation order, so the escalation path is
    exercised on every second tick.
    """
    operation_id = synthetic_operation_id("settlement-operations-analyst", tick)
    holds = tick % _CYCLE == 1
    limit = Decimal("500000000.00")
    usage = limit if holds else Decimal("120000000.00")
    return SettlementTaskingRecord(
        task_id=synthetic_operation_id("settlement-operations-task", tick),
        operation_id=operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="synthetic-counterparty-01",
        deadline=at + timedelta(hours=4),
        lineage_stub=_lineage(operation_id, at, f"settlement-{tick}"),
        net_cusip="912828XG8",
        net_delivery_quantity=Decimal("25000000"),
        net_payment_amount=Decimal("24875000.00"),
        ficc_published_net_delivery=Decimal("25000000"),
        ficc_published_net_payment=Decimal("24875000.00"),
        intraday_credit_limit=limit,
        intraday_credit_current_usage=usage,
        ficc_clearing_fund_compliant=True,
    )


# Tier 1 — Settlement Investigation Analyst --------------------------------------------

#: The sources a complete synthetic investigation accounts for. Every member of
#: ``EvidenceSource`` appears either as an observation or as a declared gap; a
#: source that is neither is reported as unaccounted-for and escalates, which is
#: the behaviour the odd tick below exercises on purpose.
_OBSERVED_SOURCES: Final = (
    EvidenceSource.DSOR_LINEAGE,
    EvidenceSource.GATE_DECISION,
    EvidenceSource.INSTRUCTION_PACKAGE,
    EvidenceSource.MESSAGE_STATUS,
    EvidenceSource.FUNDING_STATE,
    EvidenceSource.RAIL_STATE,
    EvidenceSource.PORTAL_READBACK,
    EvidenceSource.RECONCILIATION,
)


def investigation_lineage(tick: int, at: datetime) -> DSORLineageStub:
    """The lineage stub an investigation binds its output to."""
    return _lineage(
        synthetic_operation_id("settlement-investigation-analyst", tick),
        at,
        f"investigation-{tick}",
    )


def investigation_unit(
    tick: int, at: datetime
) -> tuple[tuple[EvidenceItem, ...], tuple[EvidenceGap, ...]]:
    """Evidence and declared gaps for one investigation.

    Even ticks account for every source, so a complete timeline is assembled.
    Odd ticks leave the rail state unavailable, which escalates — a gap never
    costs the operator the evidence that *was* assembled, and the advisory
    surface should show that difference.
    """
    holds = tick % _CYCLE == 1
    observed = _OBSERVED_SOURCES[:-1] if holds else _OBSERVED_SOURCES
    items = tuple(
        EvidenceItem(
            source=source,
            observed_at=at + timedelta(seconds=index * 30),
            label=f"synthetic {source.value}",
            value=f"tick-{tick}-{source.value}",
            provenance=f"synthetic-emulator://{source.value}/tick-{tick}",
        )
        for index, source in enumerate(observed)
    )
    gaps = [
        EvidenceGap(
            source=EvidenceSource.CUTOFF_CLOCK,
            reason=GapReason.NOT_APPLICABLE,
            detail="The synthetic operation is intraday; no cut-off applies.",
        ),
        EvidenceGap(
            source=EvidenceSource.COUNTERPARTY_AFFIRMATION,
            reason=GapReason.NOT_APPLICABLE,
            detail="Delivery versus payment: no separate affirmation is expected.",
        ),
    ]
    if holds:
        gaps.append(
            EvidenceGap(
                source=EvidenceSource.RAIL_STATE,
                reason=GapReason.UNAVAILABLE,
                detail="The synthetic rail emulator reported no state for this operation.",
            )
        )
    return items, tuple(gaps)


# Tier 2 — FIAT Operations Specialist --------------------------------------------------


def cato_cash_proceed() -> CatoCashDecision:
    """A cleared Cato Cash cash-leg gate decision, bound to a synthetic obligation.

    Bound rather than unbound because Tier 2 refuses an unbound PROCEED
    (ATR-I-04), and an activation that only ever fed the agent input it refuses
    would tell us nothing about the routing path.
    """
    return CatoCashDecision(
        decision=GateDecision.PROCEED,
        reason_code=ReasonCode.CLEARED,
        recommended_rail=CashRail.FEDWIRE,
        finality_class=FinalityClass.GROSS_FINAL,
        rationale="Synthetic activation flow: gate cleared against emulated funding state.",
        checks_evaluated=(("synthetic_activation", "True"),),
        funding_state_snapshot=(),
        obligation_id="obl_01M2P20SY00000000000000001",
        obligation_digest="sha256:" + "0" * 64,
    )


def _equity_operation(at: datetime, tick: int) -> CustodyOperationUnion:
    return EquityOperation(
        lineage=_lineage(
            synthetic_operation_id("fiat-operations-specialist", tick),
            at,
            f"path-selection-{tick}",
        ),
        custody_object=OrdinarySafekeepingObject(
            beneficial_owner_id="bo-synthetic-1",
            asset_class=AssetClass(
                major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
                representation=Representation.FIAT,
                sub_category="Common Stock",
                asset_identifier="SYN",
            ),
        ),
        failure_mode_class=FailureModeClass.RA,
        settlement_method=DvP1Settlement(),
        transaction_type=EquityTransactionType.LONG_BUY,
    )


def _eligibility(at: datetime, *, ofac_matched: bool) -> EligibilityInputs:
    return EligibilityInputs(
        check_time=at,
        kyc=KYCEvidence(
            beneficial_owner_id="bo-synthetic-1",
            kyc_reference_id="kyc-synthetic-1",
            verified_at=at - timedelta(days=30),
            expires_at=at + timedelta(days=335),
        ),
        requires_kyb=False,
        ofac_screenings=(
            OFACScreeningEvidence(
                subject_id="bo-synthetic-1",
                screening_id="ofac-synthetic-1",
                matched=ofac_matched,
                matched_list="SDN" if ofac_matched else None,
                screened_at=at,
            ),
        ),
        sanctions_screenings=(
            SanctionsScreeningEvidence(
                subject_id="bo-synthetic-1",
                screening_id="sanctions-synthetic-1",
                matched=False,
                screened_at=at,
            ),
        ),
    )


def path_selection_unit(tick: int, at: datetime) -> PathSelectionRequest:
    """One path-selection request. Even ticks route; odd ticks fail Guardrail 4.

    The odd unit carries a positive OFAC (Office of Foreign Assets Control)
    screening match, so eligibility fails before any routing decision is made —
    the agent produces an escalation rather than routing past it.
    """
    holds = tick % _CYCLE == 1
    return PathSelectionRequest(
        operation=_equity_operation(at, tick),
        eligibility_inputs=_eligibility(at, ofac_matched=holds),
        attribution=JurisdictionalAttribution(
            originating_jurisdiction="US",
            receiving_jurisdiction="US",
            verana_session_id=f"verana-synthetic-{tick}",
            attributed_at=at,
        ),
        emitted_at=at,
        cato_cash_decision=cato_cash_proceed(),
        amount=Decimal("1500000.00"),
    )
