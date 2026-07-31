"""CATO-F — FIAT/cash settlement-rail governance gate.

Per AUR-CUSTODY-CASH-001 v0.1 Section V (gate specification) and
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

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final

__all__ = [
    "DOCTRINE_VERSION",
    "CashRail",
    "FinalityClass",
    "GateDecision",
    "ReasonCode",
    "RailStatus",
    "RailState",
    "FundingState",
    "OperationContext",
    "CatoFDecision",
    "RAIL_FINALITY",
    "OFR_ESCALATE_THRESHOLD",
    "OFR_HOLD_THRESHOLD",
    "evaluate",
    "absent_gate_decision",
    "GOLDEN_VECTORS",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-CASH-001-v0.1"

# Stress thresholds are deliberately identical to Cato's OFR STLFSI4
# bands. The cash leg and the securities leg respond to systemic stress
# identically — that is what parity means operationally, and sharing the
# threshold constants makes the parity structural rather than a matter
# of discipline (CASH-001 Section V.B).
OFR_ESCALATE_THRESHOLD: Final[float] = 1.0
OFR_HOLD_THRESHOLD: Final[float] = 0.5


class GateDecision(StrEnum):
    """Gate disposition. Mirrors Cato's PROCEED / HOLD / ESCALATE."""

    PROCEED = "PROCEED"
    HOLD = "HOLD"
    ESCALATE = "ESCALATE"


class FinalityClass(StrEnum):
    """Finality classes per AUR-CUSTODY-CASH-001 Section IV.

    The doctrinal core of this gate: materiality tightens as
    reversibility falls. An irreversible operation warrants a lower
    trigger than a reversible one of the same size.
    """

    GROSS_FINAL = "GROSS_FINAL"
    DEFERRED_NET = "DEFERRED_NET"
    LEDGER_FINAL = "LEDGER_FINAL"
    CORRESPONDENT_DEPENDENT = "CORRESPONDENT_DEPENDENT"


class CashRail(StrEnum):
    """The cash-rail universe per AUR-CUSTODY-CASH-001 Section III."""

    FEDWIRE = "fedwire"
    CHIPS = "chips"
    FEDNOW = "fednow"
    NSS_DTC_NSCC = "nss_dtc_nscc"
    FICC_GSD_FUNDS_ONLY = "ficc_gsd_funds_only"
    CORRESPONDENT = "correspondent"
    TOKENIZED_DEPOSIT = "tokenized_deposit"
    REGULATED_STABLECOIN = "regulated_stablecoin"
    # Reserved placeholder. ALWAYS present in rail state, NEVER removed.
    # Mirrors the Cato `fed_l1` invariant exactly: when wholesale
    # tokenized settlement infrastructure ships, the rail-state shape
    # does not change — only the status field flips. Rail addition is a
    # doctrine non-event by design (CASH-001 Section III).
    PORTS_WHOLESALE = "ports_wholesale"


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
    MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE = "MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE"
    UNFUNDED_AT_SETTLEMENT_INSTANT = "UNFUNDED_AT_SETTLEMENT_INSTANT"
    RISK_CONTROL_BREACH = "RISK_CONTROL_BREACH"
    BROAD_STRESS_HOLD = "BROAD_STRESS_HOLD"
    NO_RAIL_IN_WINDOW = "NO_RAIL_IN_WINDOW"
    UNRESOLVABLE_FINALITY = "UNRESOLVABLE_FINALITY"
    CLEARED = "CLEARED"
    GATE_UNAVAILABLE = "GATE_UNAVAILABLE"


class RailStatus(StrEnum):
    AVAILABLE = "available"
    CLOSED = "closed"
    DEGRADED = "degraded"
    NOT_YET_ISSUED = "not_yet_issued"


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


@dataclass(frozen=True, slots=True)
class CatoFDecision:
    """Gate output per AUR-CUSTODY-CASH-001 Section V.D.

    Every field is recorded in the DSOR lineage. A decision that cannot
    be replayed from its recorded inputs is not a governed decision.
    """

    decision: GateDecision
    reason_code: ReasonCode
    recommended_rail: CashRail | None
    finality_class: FinalityClass | None
    rationale: str
    checks_evaluated: tuple[tuple[str, str], ...]
    funding_state_snapshot: tuple[tuple[str, str], ...]
    doctrine_version: str = DOCTRINE_VERSION
    dsor_lineage_uri: str | None = None

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
    if ofr_stlfsi4 > 0.0 and (chosen := _prefer(gross_final)) is not None:
        if ofr_stlfsi4 >= OFR_HOLD_THRESHOLD * 0.5:
            return chosen, (
                f"Elevated systemic stress (OFR {ofr_stlfsi4}); prefer "
                f"gross-final settlement over deferred-net exposure "
                f"(CASH-001 SV.C.1)."
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
    ]
    snapshot = _snapshot_funding(funding)

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

    # 8. Cleared — recommend a rail.
    rail, ladder_rationale = _recommend_rail(
        operation=operation, rails=rails, ofr_stlfsi4=ofr_stlfsi4
    )

    rationale = ladder_rationale
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
