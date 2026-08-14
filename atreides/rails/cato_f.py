"""CATO-F — FIAT/cash settlement-rail governance gate.

Per AUR-CUSTODY-CASH-001 v0.2 Section V (gate specification) and
AUR-CUSTODY-001 v1.0 Section X as amended by AUR-CUSTODY-AMD-001
(FIAT settlement-rail governance reclassified from forward-state to
present-state build obligation).

CATO-F is the cash-leg twin of Cato. It stands in the 1:1 parity
AUR-CUSTODY-001 Section VI and Section X commit the framework to:
Cato governs the securities/tokenized rail, CATO-F governs the cash
rail, and neither decides the settlement method alone (Section VI of
CASH-001 — the joint resolver).

Architectural contract — PURE, NO I/O
-------------------------------------
This module makes no network calls, reads no files, and consults no
clock. Every input arrives as a scalar or frozen value object, exactly
as the Cato Python twin receives FRED/Blockscout/CoinGecko state via
scalar parameters from the caller's refresh loop. Per the Cato
invariant: *any endpoint that makes a network call in the request
handler is a bug.* Input refresh is the caller's responsibility.

This purity is also what makes the gate replayable: a decision is
reproducible from its recorded inputs alone, which is what
`checks_evaluated` on the decision object exists to preserve.

Parity
------
Per AUR-CUSTODY-CASH-001 Section V.F, if CATO-F is ever exposed through
a second implementation (external MCP surface, licensee-side twin), the
Cato Parity Principle applies without modification: bit-for-bit
identical decisions for identical inputs, golden vectors run in both
implementations in CI, doctrine changes landing in both in the same
commit series. GOLDEN_VECTORS below is the shared fixture for that.

Status: v0.1 — doctrine-first implementation. Creates no authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from atreides.rails.determination import (
    DeterminationOutcome,
    obligation_finality_class,
)
from atreides.rails.finality import FinalityClass

__all__ = [
    "DOCTRINE_VERSION",
    "GOLDEN_VECTORS",
    "OFR_ESCALATE_THRESHOLD",
    "OFR_HOLD_THRESHOLD",
    "OFR_STRESS_PREFERENCE_THRESHOLD",
    "RAIL_FINALITY",
    "CashRail",
    "CatoFDecision",
    "FinalityClass",
    "FundingState",
    "GateDecision",
    "OperationContext",
    "RailState",
    "RailStatus",
    "ReasonCode",
    "absent_gate_decision",
    "evaluate",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-CASH-001-v0.2"

# Stress thresholds are deliberately identical to Cato's OFR STLFSI4
# bands. The cash leg and the securities leg respond to systemic stress
# identically — that is what parity means operationally, and sharing the
# threshold constants makes the parity structural rather than a matter
# of discipline (CASH-001 Section V.B).
OFR_ESCALATE_THRESHOLD: Final[float] = 1.0
OFR_HOLD_THRESHOLD: Final[float] = 0.5

# Stress-posture preference band per AUR-CUSTODY-CASH-001 v0.2 SV.C.1.
# Stress below the HOLD band but at or above this value is "elevated":
# the ladder prefers gross-final rails so that deferred-net exposure is
# not carried into a stressed window. Ratified into doctrine at CASH-001
# v0.2 rather than left as an unattributed implementation constant --
# every threshold in this module must trace to a doctrine line.
OFR_STRESS_PREFERENCE_THRESHOLD: Final[float] = 0.25


class GateDecision(StrEnum):
    """Gate disposition. Mirrors Cato's PROCEED / HOLD / ESCALATE."""

    PROCEED = "PROCEED"
    """Cleared. The operation may be released."""
    HOLD = "HOLD"
    """Stopped pending a condition changing. Not an escalation and not a failure."""
    ESCALATE = "ESCALATE"
    """Routed to human authority. The gate declines to decide."""


class CashRail(StrEnum):
    """The cash-rail universe per AUR-CUSTODY-CASH-001 Section III."""

    FEDWIRE = "fedwire"
    """US real-time gross settlement for large-value payments. Gross-final."""
    CHIPS = "chips"
    """US privately operated netting system for large-value payments. Deferred-net."""
    FEDNOW = "fednow"
    """US instant payment rail, 24/7/365, gross-final, subject to a value cap."""
    NSS_DTC_NSCC = "nss_dtc_nscc"
    """Net settlement service carrying depository and clearing-corporation net obligations."""
    FICC_GSD_FUNDS_ONLY = "ficc_gsd_funds_only"
    """The funds-only leg of government securities clearing."""
    CORRESPONDENT = "correspondent"
    """Settlement on the books of an intermediary bank. The only rail whose finality the originator
    cannot observe."""
    TOKENIZED_DEPOSIT = "tokenized_deposit"
    """Commercial bank money on a distributed ledger. Ledger-final."""
    REGULATED_STABLECOIN = "regulated_stablecoin"
    """Regulated payment stablecoin. Ledger-final."""
    # Reserved placeholder. ALWAYS present in rail state, NEVER removed.
    # Mirrors the Cato `fed_l1` invariant exactly: when wholesale
    # tokenized settlement infrastructure ships, the rail-state shape
    # does not change — only the status field flips. Rail addition is a
    # doctrine non-event by design (CASH-001 Section III).
    PORTS_WHOLESALE = "ports_wholesale"
    """Reserved placeholder for wholesale tokenized settlement infrastructure. Always present in
    rail state and never removed, so that its arrival flips a status field rather than changing
    the shape of the record."""


# DETERMINATION_DEPENDENT is deliberately absent from this table and its
# absence is asserted by a test. It is an obligation-level class: the money
# leg of a contingent-payout settlement runs on an ordinary rail with that
# rail's ordinary finality. Adding a pseudo-rail to carry it would put a
# property of the instrument into the table that answers "how does money
# move", which is the category error this comment exists to prevent.
RAIL_FINALITY: Final[dict[CashRail, FinalityClass]] = {
    CashRail.FEDWIRE: FinalityClass.GROSS_FINAL,
    CashRail.FEDNOW: FinalityClass.GROSS_FINAL,
    CashRail.CHIPS: FinalityClass.DEFERRED_NET,
    CashRail.NSS_DTC_NSCC: FinalityClass.DEFERRED_NET,
    CashRail.FICC_GSD_FUNDS_ONLY: FinalityClass.DEFERRED_NET,
    CashRail.TOKENIZED_DEPOSIT: FinalityClass.LEDGER_FINAL,
    CashRail.REGULATED_STABLECOIN: FinalityClass.LEDGER_FINAL,
    CashRail.CORRESPONDENT: FinalityClass.CORRESPONDENT_DEPENDENT,
    CashRail.PORTS_WHOLESALE: FinalityClass.LEDGER_FINAL,
}


class ReasonCode(StrEnum):
    """Reason codes. One per check in Section V.B plus the PROCEED case."""

    SYSTEMIC_STRESS_ESCALATE = "SYSTEMIC_STRESS_ESCALATE"
    """Systemic stress above the escalation band. Routed to human authority."""
    MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE = "MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE"
    """Material by magnitude, so quorum authority is required, and quorum is architecturally
    unavailable. Holds by doctrine; pretending otherwise would be theatre."""
    UNFUNDED_AT_SETTLEMENT_INSTANT = "UNFUNDED_AT_SETTLEMENT_INSTANT"
    """The projected position is below the obligation. No rail selection remedies an unfunded
    position."""
    RISK_CONTROL_BREACH = "RISK_CONTROL_BREACH"
    """Net-debit-cap headroom exhausted or clearing fund deficient. A hard control, independent of
    position."""
    BROAD_STRESS_HOLD = "BROAD_STRESS_HOLD"
    """Systemic stress above the hold band but below escalation."""
    NO_RAIL_IN_WINDOW = "NO_RAIL_IN_WINDOW"
    """No rail is open and reachable in the settlement window. Hold to the next window rather than
    routing to a closed rail."""
    UNRESOLVABLE_FINALITY = "UNRESOLVABLE_FINALITY"
    """A correspondent chain whose finality state cannot be established. Unknown finality is not
    acceptable finality."""
    DETERMINATION_PENDING = "DETERMINATION_PENDING"
    """A contingent obligation whose outcome has not been determined. The instruction is premature,
    not unsafe."""
    UNASSESSED_REVOCATION_AUTHORITY = "UNASSESSED_REVOCATION_AUTHORITY"
    """Determined, and nobody has read whether the venue may cancel and return funds. Closed by
    populating the registry, not by a market action."""
    CLEARED = "CLEARED"
    """No check fired. A rail is recommended."""
    GATE_UNAVAILABLE = "GATE_UNAVAILABLE"
    """The gate could not be consulted. The absent-gate default is HOLD."""


class RailStatus(StrEnum):
    AVAILABLE = "available"
    """Open and reachable."""
    CLOSED = "closed"
    """Not operating in this window."""
    DEGRADED = "degraded"
    """Operating with reduced capability. Not usable, because partial availability is not
    availability for a settlement decision."""
    NOT_YET_ISSUED = "not_yet_issued"
    """The infrastructure does not exist yet. Distinct from CLOSED, which describes something that
    exists and is shut."""


@dataclass(frozen=True, slots=True)
class RailState:
    """Per-rail operational state. Supplied by the caller's refresh loop."""

    rail: CashRail
    status: RailStatus
    # Seconds of processing headroom remaining before this rail's cutoff
    # for the requested settlement date. Negative means the cutoff has
    # passed. None means "not cutoff-bound" (24/7 rails).
    seconds_to_cutoff: int | None = None
    # Value cap where the rail imposes one (FedNow). None means uncapped.
    value_cap: Decimal | None = None

    @property
    def usable(self) -> bool:
        """A rail is usable when open and not past its cutoff."""
        if self.status is not RailStatus.AVAILABLE:
            return False
        if self.seconds_to_cutoff is None:
            return True
        return self.seconds_to_cutoff > 0


@dataclass(frozen=True, slots=True)
class FundingState:
    """Intraday funding state per AUR-CUSTODY-CASH-001 Section VII.

    Rail selection answers *how* the money moves. This answers *whether
    it can* — and it is the check that most often determines whether a
    cash leg completes.
    """

    projected_funded_position: Decimal
    net_obligation: Decimal
    net_debit_cap_headroom: Decimal
    clearing_fund_sufficient: bool

    @property
    def is_funded(self) -> bool:
        return self.projected_funded_position >= self.net_obligation


@dataclass(frozen=True, slots=True)
class OperationContext:
    """The operation under evaluation.

    `is_material` and `is_lvps_material` are supplied by the caller from
    MagnitudeThresholdPolicy (AUR-CUSTODY-FED-AMD-001). This gate does
    not re-derive materiality — it consumes the determination, exactly
    as it consumes the eligibility result rather than re-screening.
    """

    notional: Decimal
    currency: str
    is_material: bool
    is_lvps_material: bool
    is_fx_leg: bool = False
    pvp_available: bool = True
    # Where the cash leg is the money side of a depository or CCP
    # settlement, the rail is DETERMINED, not selected. The gate
    # validates rather than chooses (CASH-001 Section V.C item 4).
    depository_linked_rail: CashRail | None = None
    # Set when the operation must route through a correspondent chain
    # whose finality state cannot be established.
    correspondent_finality_resolvable: bool = True
    tokenized_deposit_supported: bool = False
    within_business_hours: bool = True
    # Contingent-payout instruments only. Supplied by the caller from
    # `determination.classify_determination()`; this gate consumes the
    # classification exactly as it consumes materiality and eligibility,
    # and does not re-derive it. NOT_APPLICABLE is the default and means
    # the obligation is not contingent, which is true of every instrument
    # the framework handled before this class existed.
    determination_outcome: DeterminationOutcome = DeterminationOutcome.NOT_APPLICABLE


@dataclass(frozen=True, slots=True)
class CatoFDecision:
    """Gate output per AUR-CUSTODY-CASH-001 Section V.D.

    Every field is recorded in the DSOR lineage. A decision that cannot
    be replayed from its recorded inputs is not a governed decision.
    """

    decision: GateDecision
    reason_code: ReasonCode
    recommended_rail: CashRail | None
    #: The RAIL's finality class. Meaning unchanged since v0.1, deliberately:
    #: historical records stay comparable and replay is not disturbed.
    finality_class: FinalityClass | None
    rationale: str
    checks_evaluated: tuple[tuple[str, str], ...]
    funding_state_snapshot: tuple[tuple[str, str], ...]
    doctrine_version: str = DOCTRINE_VERSION
    dsor_lineage_uri: str | None = None
    #: The OBLIGATION's finality class, where it has one of its own. None
    #: for every non-contingent instrument, which is why this is additive
    #: rather than a change to the field above. Where this is populated it
    #: is always DETERMINATION_DEPENDENT and the record carries two classes
    #: at once: the money is final on its rail, the entitlement is not.
    obligation_finality_class: FinalityClass | None = None

    @property
    def proceeds(self) -> bool:
        return self.decision is GateDecision.PROCEED


def _snapshot_funding(funding: FundingState) -> tuple[tuple[str, str], ...]:
    return (
        ("projected_funded_position", str(funding.projected_funded_position)),
        ("net_obligation", str(funding.net_obligation)),
        ("net_debit_cap_headroom", str(funding.net_debit_cap_headroom)),
        ("clearing_fund_sufficient", str(funding.clearing_fund_sufficient)),
        ("is_funded", str(funding.is_funded)),
    )


def _recommend_rail(
    *,
    operation: OperationContext,
    rails: dict[CashRail, RailState],
    ofr_stlfsi4: float,
) -> tuple[CashRail, str]:
    """Deterministic rail ladder per AUR-CUSTODY-CASH-001 Section V.C.

    Evaluated in order; first applicable rule wins. Applied only on the
    PROCEED path.
    """
    usable = {r: s for r, s in rails.items() if s.usable}

    # 4. Depository linkage — determined, not selected. Evaluated before
    #    the preference rules because there is nothing to prefer: the
    #    money side of a depository settlement has one rail.
    if operation.depository_linked_rail is not None:
        linked = operation.depository_linked_rail
        return linked, (
            f"Depository-linked settlement: rail is determined by the "
            f"linkage ({linked.value}), not selected. Gate validates "
            f"availability rather than choosing (CASH-001 SV.C.4)."
        )

    def _prefer(candidates: list[CashRail]) -> CashRail | None:
        for rail in candidates:
            state = usable.get(rail)
            if state is None:
                continue
            if state.value_cap is not None and operation.notional > state.value_cap:
                continue
            return rail
        return None

    gross_final = [CashRail.FEDWIRE, CashRail.FEDNOW]

    # 1. Stress posture — elevated but below the HOLD band. Deferred-net
    #    exposure is the wrong risk to carry into a stressed window.
    if ofr_stlfsi4 >= OFR_STRESS_PREFERENCE_THRESHOLD and (
        chosen := _prefer(gross_final)
    ) is not None:
        return chosen, (
            f"Elevated systemic stress (OFR {ofr_stlfsi4} >= "
            f"{OFR_STRESS_PREFERENCE_THRESHOLD}); prefer gross-final "
            f"settlement over deferred-net exposure (CASH-001 SV.C.1)."
        )

    # 2. Materiality proximity — approaching but not crossing the
    #    threshold still warrants gross-final treatment.
    if operation.is_lvps_material and (chosen := _prefer(gross_final)) is not None:
        return chosen, (
            "Operation is LVPS-material; gross-final rail preferred over "
            "deferred-net (CASH-001 SV.C.2, SIV finality doctrine)."
        )

    # 3. Window — outside business hours, FedNow within caps.
    if not operation.within_business_hours:
        fednow = usable.get(CashRail.FEDNOW)
        if fednow is not None and (
            fednow.value_cap is None or operation.notional <= fednow.value_cap
        ):
            return CashRail.FEDNOW, (
                "Outside business hours; FedNow is instant-final and "
                "operates 24/7/365, notional within value cap "
                "(CASH-001 SV.C.3)."
            )

    # 5. Tokenized preference — cost and 24/7 grounds, subject to 1 and 2.
    if operation.tokenized_deposit_supported:
        tokenized = _prefer([CashRail.TOKENIZED_DEPOSIT])
        if tokenized is not None:
            return tokenized, (
                "Both counterparties support a tokenized-deposit rail and "
                "the instrument is eligible; preferred on cost and 24/7 "
                "grounds (CASH-001 SV.C.5)."
            )

    # 6. Default.
    if (chosen := _prefer([CashRail.FEDWIRE])) is not None:
        return chosen, "Default rail (CASH-001 SV.C.6)."

    # Fall through to any usable rail; check 6 in evaluate() guarantees
    # at least one exists by this point.
    for rail, state in usable.items():
        if rail is CashRail.PORTS_WHOLESALE:
            continue
        if state.value_cap is not None and operation.notional > state.value_cap:
            continue
        return rail, "Sole usable rail within the settlement window."

    raise AssertionError(
        "unreachable: check 6 guarantees a usable rail before the ladder runs"
    )


def evaluate(
    *,
    operation: OperationContext,
    funding: FundingState,
    rails: dict[CashRail, RailState],
    ofr_stlfsi4: float,
    dsor_lineage_uri: str | None = None,
) -> CatoFDecision:
    """Evaluate the cash leg. Deterministic, pure, replayable.

    Checks run in the order fixed by AUR-CUSTODY-CASH-001 Section V.B.
    The first condition met determines the decision — the ordering is
    doctrine, not an optimization, and must not be reordered without a
    doctrine change landing in both implementations.
    """
    checks: list[tuple[str, str]] = [
        ("ofr_stlfsi4", str(ofr_stlfsi4)),
        ("is_material", str(operation.is_material)),
        ("is_lvps_material", str(operation.is_lvps_material)),
        ("is_funded", str(funding.is_funded)),
        ("net_debit_cap_headroom", str(funding.net_debit_cap_headroom)),
        ("clearing_fund_sufficient", str(funding.clearing_fund_sufficient)),
        ("usable_rails", ",".join(sorted(r.value for r, s in rails.items() if s.usable))),
        ("correspondent_finality_resolvable", str(operation.correspondent_finality_resolvable)),
        ("is_fx_leg", str(operation.is_fx_leg)),
        ("pvp_available", str(operation.pvp_available)),
        ("determination_outcome", operation.determination_outcome.value),
    ]
    snapshot = _snapshot_funding(funding)
    obligation_class = obligation_finality_class(operation.determination_outcome)

    def _decide(
        decision: GateDecision,
        reason: ReasonCode,
        rationale: str,
        rail: CashRail | None = None,
    ) -> CatoFDecision:
        return CatoFDecision(
            decision=decision,
            reason_code=reason,
            recommended_rail=rail,
            finality_class=RAIL_FINALITY.get(rail) if rail is not None else None,
            rationale=rationale,
            checks_evaluated=tuple(checks),
            funding_state_snapshot=snapshot,
            dsor_lineage_uri=dsor_lineage_uri,
            obligation_finality_class=obligation_class,
        )

    # 1. Systemic stress — escalate to human authority.
    if ofr_stlfsi4 > OFR_ESCALATE_THRESHOLD:
        return _decide(
            GateDecision.ESCALATE,
            ReasonCode.SYSTEMIC_STRESS_ESCALATE,
            f"OFR STLFSI4 {ofr_stlfsi4} exceeds {OFR_ESCALATE_THRESHOLD}; "
            f"systemic stress routes to human authority (CASH-001 SV.B.1, "
            f"Cato parity band).",
        )

    # 2. Material magnitude — quorum-required, quorum architecturally
    #    unavailable under CAOM-001. Holds by doctrine; pretending
    #    otherwise is theater (canonical SV).
    if operation.is_material:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE,
            "Operation is material per MagnitudeThresholdPolicy; quorum "
            "authority is required and is architecturally unavailable "
            "under CAOM-001. HOLD and surface a CAOM-transition trigger "
            "(FED-001 SVII, CASH-001 SV.B.2).",
        )

    # 3. Unfunded — no rail choice remedies an unfunded position.
    if not funding.is_funded:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.UNFUNDED_AT_SETTLEMENT_INSTANT,
            f"Projected funded position {funding.projected_funded_position} "
            f"is below net obligation {funding.net_obligation} at the "
            f"settlement instant. No rail selection remedies this "
            f"(CASH-001 SV.B.3, SVII).",
        )

    # 4. Risk-control breach — net debit cap or clearing fund.
    if funding.net_debit_cap_headroom < 0 or not funding.clearing_fund_sufficient:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.RISK_CONTROL_BREACH,
            "Risk-control breach: net-debit-cap headroom exhausted or "
            "clearing-fund/margin deficient. Hold and escalate "
            "(AUR-COCKPIT-001 SVII, CASH-001 SV.B.4).",
        )

    # 5. Broad stress — hold, route to the most conservative rail.
    if ofr_stlfsi4 > OFR_HOLD_THRESHOLD:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.BROAD_STRESS_HOLD,
            f"OFR STLFSI4 {ofr_stlfsi4} exceeds {OFR_HOLD_THRESHOLD}; broad "
            f"settlement-system stress (CASH-001 SV.B.5, Cato parity band).",
        )

    # 6. Timing infeasible — no rail open and reachable in the window.
    #    PORTS_WHOLESALE is excluded: it is a reserved placeholder and is
    #    never a usable rail until the infrastructure ships.
    if not any(
        state.usable for rail, state in rails.items() if rail is not CashRail.PORTS_WHOLESALE
    ):
        return _decide(
            GateDecision.HOLD,
            ReasonCode.NO_RAIL_IN_WINDOW,
            "No cash rail is open and reachable within the required "
            "settlement window. Hold to the next window rather than "
            "routing to a closed rail (CASH-001 SV.B.6).",
        )

    # 7. Unresolvable finality on a correspondent chain. Unknown finality
    #    is not acceptable finality — the most dangerous class in SIV
    #    precisely because the state is unknown rather than deferred.
    if not operation.correspondent_finality_resolvable:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.UNRESOLVABLE_FINALITY,
            "Correspondent-dependent finality state cannot be established "
            "for this cross-border leg. Unknown finality is not acceptable "
            "finality (CASH-001 SV.B.7, SIV).",
        )

    # 8. Determination pending. A contingent payout whose outcome has not
    #    been determined has no fixed obligation to settle, so there is
    #    nothing for a rail to carry. Holding here is not a risk judgment,
    #    it is a sequencing one: the instruction is premature.
    if operation.determination_outcome is DeterminationOutcome.AWAITING_DETERMINATION:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.DETERMINATION_PENDING,
            "Contingent obligation awaiting outcome determination; the "
            "amount owed is not yet fixed. Instruction is premature, not "
            "unsafe. Hold to determination (CASH-001 SIV, determination "
            "dependence).",
        )

    # 9. Revocation authority unassessed. The outcome is determined and the
    #    venue's power to cancel it and return funds has not been read.
    #    Same doctrine as check 7 and the same sentence: unknown finality is
    #    not acceptable finality. The remedy differs - this one is closed by
    #    populating a registry entry, not by a market action.
    if operation.determination_outcome is DeterminationOutcome.QUALIFICATION_UNKNOWN:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.UNASSESSED_REVOCATION_AUTHORITY,
            "Outcome determined, but no determination profile has been "
            "populated for the venue, so whether the settlement can be "
            "cancelled and the funds returned is unread rather than absent. "
            "Unknown finality is not acceptable finality (CASH-001 SIV). "
            "Populate the registry entry from the venue rulebook.",
        )

    # 10. Cleared — recommend a rail.
    rail, ladder_rationale = _recommend_rail(
        operation=operation, rails=rails, ofr_stlfsi4=ofr_stlfsi4
    )

    rationale = ladder_rationale
    if operation.determination_outcome in {
        DeterminationOutcome.QUALIFIED_BOUNDED,
        DeterminationOutcome.QUALIFIED_UNBOUNDED,
    }:
        # Not a hold. Contingent markets settle every day and a gate that
        # refused them would be describing a market that does not exist.
        # The qualification is a disclosure, and it is recorded on the
        # decision in `obligation_finality_class` as well as here.
        bounded = (
            operation.determination_outcome is DeterminationOutcome.QUALIFIED_BOUNDED
        )
        rationale += (
            " NOTE: obligation is DETERMINATION_DEPENDENT — the cash leg is "
            "final on its rail and the venue retains authority to cancel the "
            "contract and return the funds. "
            + (
                "The venue publishes a bounded window; the position stops "
                "being qualified at a knowable moment."
                if bounded
                else "The venue states no bound, so the position does not "
                "leave the qualified state. Recorded, not resolved "
                "(CASH-001 SIV)."
            )
        )

    if operation.is_fx_leg and not operation.pvp_available:
        # Not a hold — the materiality threshold already halved upstream
        # per FED-AMD-001 SII.C. But the resolver must record that the FX
        # leg proceeded without PvP and why (CASH-001 SVI).
        rationale += (
            " NOTE: FX leg proceeding WITHOUT PvP — Herstatt risk is not "
            "eliminated. FED-AMD-001 SII.C halved the applicable "
            "materiality threshold for this condition; recorded for the "
            "joint resolver (CASH-001 SVI)."
        )

    return _decide(GateDecision.PROCEED, ReasonCode.CLEARED, rationale, rail)


def absent_gate_decision(reason: str = "CATO-F unavailable") -> CatoFDecision:
    """The absent-gate default per AUR-CUSTODY-CASH-001 Section V.E: HOLD.

    Callers MUST use this when the gate is unavailable, unreachable, or
    returns no decision. Proceeding without a gate decision inverts
    Axiom 1 (doctrine before execution) and leaves ungoverned routing as
    the fallback path.

    This exists as a named, exported function rather than as a caller-side
    convention so that "what happens when the gate is missing" is answered
    in one auditable place instead of at every call site.
    """
    return CatoFDecision(
        decision=GateDecision.HOLD,
        reason_code=ReasonCode.GATE_UNAVAILABLE,
        recommended_rail=None,
        finality_class=None,
        rationale=(
            f"{reason}. Absent-gate default is HOLD, never PROCEED "
            f"(CASH-001 SV.E). Governance before execution."
        ),
        checks_evaluated=(("gate_available", "False"),),
        funding_state_snapshot=(),
    )


# ---------------------------------------------------------------------------
# Golden vectors — the shared parity fixture (CASH-001 Section V.F).
# Any second implementation of CATO-F must reproduce these exactly.
# ---------------------------------------------------------------------------

def _std_rails() -> dict[CashRail, RailState]:
    return {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, None, Decimal("1000000")
        ),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }


GOLDEN_VECTORS: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "clear_proceed_default_fedwire",
        "ofr_stlfsi4": 0.0,
        "expect_decision": GateDecision.PROCEED,
        "expect_reason": ReasonCode.CLEARED,
        "expect_rail": CashRail.FEDWIRE,
    },
    {
        "name": "systemic_stress_escalates",
        "ofr_stlfsi4": 1.5,
        "expect_decision": GateDecision.ESCALATE,
        "expect_reason": ReasonCode.SYSTEMIC_STRESS_ESCALATE,
        "expect_rail": None,
    },
    {
        "name": "broad_stress_holds",
        "ofr_stlfsi4": 0.75,
        "expect_decision": GateDecision.HOLD,
        "expect_reason": ReasonCode.BROAD_STRESS_HOLD,
        "expect_rail": None,
    },
)
