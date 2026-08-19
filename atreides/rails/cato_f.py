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

import math
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
    "Counterparty",
    "CounterpartyStanding",
    "FinalityClass",
    "FreshnessPolicy",
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
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    """A load-bearing input is older than the freshness policy allows, or its
    age was never established.

    Both conditions produce this code and the rationale distinguishes them, on
    the discipline this framework applies to every registry: "we read it an
    hour ago" and "nobody recorded when we read it" carry the same
    conservative treatment and completely different remedies.

    Fires only where a freshness policy was supplied. A caller that states no
    policy is not policed, and the decision record says so rather than
    implying a check that did not run."""
    COUNTERPARTY_UNASSESSED = "COUNTERPARTY_UNASSESSED"
    """A counterparty was named and nobody has established its standing.

    Distinct from no counterparty at all. Naming one and leaving its standing
    unread is the unread-rulebook condition: closed by an assessment, not by a
    market action."""
    COUNTERPARTY_NOT_IN_GOOD_STANDING = "COUNTERPARTY_NOT_IN_GOOD_STANDING"
    """The counterparty is suspended or in default. Whether to face them is
    the question, and it is answered before whether the leg can be funded."""
    COUNTERPARTY_UNDER_REVIEW = "COUNTERPARTY_UNDER_REVIEW"
    """The counterparty is under review. Escalates rather than holds: a review
    means a human is already looking, and this operation is evidence they need
    rather than a decision this gate should take without them."""
    STRESS_READING_UNUSABLE = "STRESS_READING_UNUSABLE"
    """The systemic-stress reading is not a usable number, so no statement
    about market stress can be made from it.

    Deliberately NOT the escalate code. SYSTEMIC_STRESS_ESCALATE asserts that
    stress was observed above a band; a NaN or an infinity asserts nothing
    except that the feed is broken. Naming the two differently is the same
    discipline the registries apply between NOT_ASSESSED and NONE_DISCLOSED:
    "we could not read it" and "we read it and it says X" carry the same
    conservative treatment and completely different remedies.

    Holds rather than escalates because HOLD is this framework's default
    everywhere evidence is absent, including the absent-gate default. The
    trade-off is stated rather than hidden: an operator who wants a broken
    feed to page somebody must route on this code, because the gate will not
    manufacture a stress finding it does not have."""
    FUNDING_INDETERMINATE = "FUNDING_INDETERMINATE"
    """The funding model declined to assert the position, so the gate has no
    funded state to check.

    Distinct from UNFUNDED_AT_SETTLEMENT_INSTANT, which asserts that the
    position is short. This code asserts nothing about the position at all -
    the projection reached a state where the model refuses to say, and a
    refusal must not be converted into a number on the way to this gate."""
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
    # How long ago this status was observed, in seconds before the evaluation
    # instant. None means the age was never recorded. A rail marked AVAILABLE
    # an hour ago is not the same evidence as one marked AVAILABLE this
    # second, and before this field existed the record could not tell them
    # apart. Policed only where a FreshnessPolicy is supplied.
    observed_age_seconds: int | None = None

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

    #: Whether the position above is an assertion the funding model was
    #: willing to make.
    #:
    #: The funding model has states in which it explicitly refuses to say
    #: whether a position is funded - a correspondent-dependent leg, an
    #: obligation awaiting determination. Before this field existed, that
    #: refusal died at this boundary: the projection carried a disposition of
    #: INDETERMINATE and handed the gate four scalars, one of which happened
    #: to be a large number, and the gate read a large number as funded.
    #:
    #: Defaults to True because constructing this object by hand IS the
    #: assertion - a caller who builds a funding state is saying "this is the
    #: position." Only ``FundingProjection.to_gate_input()`` has a refusal to
    #: carry, and only it sets this False.
    position_is_assertable: bool = True

    @property
    def is_funded(self) -> bool:
        """Whether the position covers the obligation.

        Answers only the arithmetic. A caller must read
        ``position_is_assertable`` first: where the model refused to assert
        the position, this property is comparing two numbers one of which
        means nothing. The gate does exactly that, in check 3a, before it
        reaches check 3.
        """
        return self.projected_funded_position >= self.net_obligation


class CounterpartyStanding(StrEnum):
    """Whether this firm should be facing this counterparty at all.

    Consumed, never derived. The framework holds no credit model and will not
    acquire one: standing is established by whatever function a firm already
    has for the purpose, and recorded here so that a settlement decision can
    be explained against it afterwards.

    NOT_ASSESSED is kept distinct from IN_GOOD_STANDING for the reason it is
    kept distinct everywhere else in this corpus: "we checked and they are
    fine" and "nobody checked" carry the same conservative treatment and
    completely different remedies, and collapsing them lets an unassessed
    counterparty pass as a cleared one.
    """

    NOT_ASSESSED = "not_assessed"
    """Nobody has established this counterparty's standing. The remedy is an
    assessment; the gate holds until there is one."""
    IN_GOOD_STANDING = "in_good_standing"
    """Assessed, and nothing prevents facing them."""
    UNDER_REVIEW = "under_review"
    """Assessed, and a review is open. Escalates: a human is already looking
    and this operation is evidence for them."""
    SUSPENDED = "suspended"
    """New business with this counterparty is stopped, by this firm's own
    decision or by a venue's."""
    DEFAULTED = "defaulted"
    """The counterparty has defaulted. Nothing routine proceeds."""


@dataclass(frozen=True, slots=True)
class Counterparty:
    """Who is on the other side, and what is known about them.

    Optional on an operation. ``None`` means this framework was not told,
    which is recorded on the decision rather than treated as an assessment: a
    gate that cannot tell "no counterparty risk" from "nobody mentioned a
    counterparty" is recording nothing useful about either.

    Supplying a counterparty makes the gate stricter, never more permissive.
    That is deliberate. The field exists so a firm can bring its own credit
    process to bear, and a field that could only relax a decision would be an
    invitation to omit it.
    """

    counterparty_id: str
    standing: CounterpartyStanding = CounterpartyStanding.NOT_ASSESSED
    #: How long ago the standing was established, in seconds before the
    #: evaluation instant. Supplied by the caller because this module reads no
    #: clock. ``None`` means the age was never recorded, which a freshness
    #: policy treats as stale.
    assessed_age_seconds: int | None = None
    provenance: str | None = None

    def __post_init__(self) -> None:
        # Coerce at the boundary, as every other registry here does. An
        # exported profile that cannot be read back in is not portable.
        if not isinstance(self.standing, CounterpartyStanding):
            object.__setattr__(self, "standing", CounterpartyStanding(self.standing))
        if not self.counterparty_id:
            raise ValueError("counterparty_id is required")
        if (
            self.standing is not CounterpartyStanding.NOT_ASSESSED
            and not self.provenance
        ):
            raise ValueError(
                "an assessed counterparty standing requires provenance; an "
                "unattributed assessment is indistinguishable from a guess"
            )
        if (
            self.standing is CounterpartyStanding.NOT_ASSESSED
            and self.assessed_age_seconds is not None
        ):
            raise ValueError(
                "an unassessed counterparty has no assessment to date; "
                "assessed_age_seconds is meaningful only once a standing has "
                "been established"
            )
        if self.assessed_age_seconds is not None and self.assessed_age_seconds < 0:
            raise ValueError("assessed_age_seconds may not be negative")


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """How old a load-bearing input may be before it stops being evidence.

    WHY THIS IS A POLICY AND NOT A CONSTANT
    ---------------------------------------
    Every bound here is a firm's operational decision, not a property of the
    market. A firm consuming a weekly stress series and a firm consuming an
    intraday one need different answers, and a default baked into this module
    would be wrong for whichever of them did not write it.

    WHY AN UNKNOWN AGE FAILS
    ------------------------
    Where a policy is supplied and an age is not, the input is treated as
    stale. That is the same rule as NOT_ASSESSED everywhere else: a firm that
    has decided freshness matters has not decided it matters only when the
    measurement is convenient. A caller unwilling to supply ages should supply
    no policy, and the record will say the check did not run.

    WHY NO POLICY IS THE DEFAULT
    ----------------------------
    So that adding this does not silently hold every operation for every
    existing caller. The cost is stated rather than hidden: with no policy, a
    stress reading from six months ago is accepted with the same standing as
    one from this second, and nothing in the record distinguishes them. That
    was the condition the stress probe found and could not attack, because
    there was no field to attack it through.
    """

    max_stress_reading_age_seconds: int | None = None
    max_rail_state_age_seconds: int | None = None
    max_counterparty_assessment_age_seconds: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_stress_reading_age_seconds",
            "max_rail_state_age_seconds",
            "max_counterparty_assessment_age_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive where it is stated")

    @property
    def polices_anything(self) -> bool:
        return any(
            v is not None
            for v in (
                self.max_stress_reading_age_seconds,
                self.max_rail_state_age_seconds,
                self.max_counterparty_assessment_age_seconds,
            )
        )


def _staleness(age_seconds: int | None, maximum: int | None) -> tuple[bool, str]:
    """Whether an input fails a freshness bound, and why in the record's words.

    Returns the reason string in both directions, so the decision can say
    "checked and fresh" as well as "stale" - a check that only speaks when it
    fires is indistinguishable from a check that did not run.
    """
    if maximum is None:
        return False, "not policed"
    if age_seconds is None:
        return True, "age never established"
    if age_seconds > maximum:
        return True, f"{age_seconds}s old against a {maximum}s bound"
    return False, f"{age_seconds}s old within a {maximum}s bound"


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
    #: Who is on the other side. ``None`` means this framework was not
    #: told, and the decision records that rather than treating it as an
    #: assessment.
    counterparty: Counterparty | None = None


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


def _serviceable(state: RailState, operation: OperationContext) -> bool:
    """Whether a rail can actually carry this operation right now.

    Usability and capacity are different questions and the gate needs both.
    Keeping them in one named predicate means check 6 and the rail ladder
    cannot drift apart again - the defect this function was extracted to
    close was precisely that they had.
    """
    if not state.usable:
        return False
    return state.value_cap is None or operation.notional <= state.value_cap


def _recommend_rail(
    *,
    operation: OperationContext,
    rails: dict[CashRail, RailState],
    ofr_stlfsi4: float,
) -> tuple[CashRail, str] | None:
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

    # Fall through to any rail that can actually carry this operation.
    #
    # Deterministic despite iterating a caller-supplied dict: sorted by rail
    # identifier, so two callers passing the same rails in different order
    # get the same recommendation. Insertion order was the previous
    # behaviour and it quietly made the gate's replay claim conditional on
    # how the caller happened to build a dictionary.
    for rail in sorted(usable, key=lambda r: r.value):
        if rail is CashRail.PORTS_WHOLESALE:
            continue
        if not _serviceable(usable[rail], operation):
            continue
        return rail, "Sole serviceable rail within the settlement window."

    # Reached only where check 6 was bypassed. It previously raised an
    # AssertionError here, on the reasoning that check 6 made this
    # unreachable — and check 6 did not, because it tested usability and
    # this loop tests capacity. Returning None lets the caller hold with a
    # named reason instead of dying without a decision record. An
    # "unreachable" assertion inside a governance gate is the wrong failure
    # mode even when the reasoning behind it is right.
    return None


def evaluate(
    *,
    operation: OperationContext,
    funding: FundingState,
    rails: dict[CashRail, RailState],
    ofr_stlfsi4: float,
    dsor_lineage_uri: str | None = None,
    stress_reading_age_seconds: int | None = None,
    freshness_policy: FreshnessPolicy | None = None,
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
        ("position_is_assertable", str(funding.position_is_assertable)),
        # Recorded whether or not it was supplied. An omission that leaves no
        # trace in the record is indistinguishable from a check that passed,
        # and this framework's whole claim is that a reader who was not there
        # can tell the difference.
        (
            "counterparty_standing",
            operation.counterparty.standing.value
            if operation.counterparty is not None
            else "not_supplied",
        ),
        (
            "freshness_policy",
            "stated"
            if freshness_policy is not None and freshness_policy.polices_anything
            else "not_stated",
        ),
        ("stress_reading_age_seconds", str(stress_reading_age_seconds)),
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

    # 0. Is the stress reading a number at all?
    #
    #    Every stress comparison below is a `>` or a `>=`, and every
    #    comparison against NaN is False. So a broken feed does not fail one
    #    check - it silently satisfies all of them, skips the escalate band,
    #    skips the hold band, skips the stress rail preference, and clears.
    #    The most permissive outcome in the gate was reachable by the single
    #    most likely upstream defect, which is the definition of fail-open.
    #
    #    Asked first because every check that follows depends on it.
    if not math.isfinite(ofr_stlfsi4):
        return _decide(
            GateDecision.HOLD,
            ReasonCode.STRESS_READING_UNUSABLE,
            f"Systemic-stress reading {ofr_stlfsi4!r} is not a finite number, "
            f"so no statement about market stress can be made from it. Every "
            f"stress band below is a comparison, and a non-finite value "
            f"satisfies none of them - which would clear the gate rather than "
            f"hold it. The absence of a reading is a state with a name, not a "
            f"calm market (CASH-001 SV.E).",
        )

    # 0b. Is the evidence recent enough to be evidence?
    #
    #     This module reads no clock, so ages arrive as values the caller
    #     supplies. Policed only where a policy was stated: a caller that
    #     states no policy is not policed, and the checks tuple records that
    #     rather than implying a check that did not run.
    #
    #     An unknown age fails a stated policy. That is the NOT_ASSESSED rule
    #     applied to time: a firm that has decided freshness matters has not
    #     decided it matters only where the measurement is convenient.
    if freshness_policy is not None and freshness_policy.polices_anything:
        stress_stale, stress_why = _staleness(
            stress_reading_age_seconds,
            freshness_policy.max_stress_reading_age_seconds,
        )
        if stress_stale:
            return _decide(
                GateDecision.HOLD,
                ReasonCode.MARKET_DATA_STALE,
                f"The systemic-stress reading is not current enough to be "
                f"evidence: {stress_why}. A reading whose age is unknown is "
                f"treated as stale where a freshness policy exists, on the "
                f"same discipline as an unread rulebook (CASH-001 SV.E).",
            )

        for rail_id, state in sorted(rails.items(), key=lambda kv: kv[0].value):
            rail_stale, rail_why = _staleness(
                state.observed_age_seconds,
                freshness_policy.max_rail_state_age_seconds,
            )
            if rail_stale:
                return _decide(
                    GateDecision.HOLD,
                    ReasonCode.MARKET_DATA_STALE,
                    f"Rail state for {rail_id.value} is not current enough to "
                    f"be evidence: {rail_why}. A rail recorded as open an "
                    f"hour ago is not a rail known to be open now "
                    f"(CASH-001 SV.B.6).",
                )

        if operation.counterparty is not None:
            cp_stale, cp_why = _staleness(
                operation.counterparty.assessed_age_seconds,
                freshness_policy.max_counterparty_assessment_age_seconds,
            )
            if cp_stale:
                return _decide(
                    GateDecision.HOLD,
                    ReasonCode.MARKET_DATA_STALE,
                    f"The standing assessment for counterparty "
                    f"{operation.counterparty.counterparty_id} is not current "
                    f"enough to be evidence: {cp_why}.",
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

    # 2b. Should this firm be facing this counterparty at all?
    #
    #     Asked before the funding checks because it is the prior question.
    #     Whether the money is there does not arise if the answer to "should
    #     we be trading with them" is no, and a gate that asked in the other
    #     order would produce a funded, cleared decision against a defaulted
    #     name and then hold it for a reason that was never the point.
    #
    #     Skipped entirely where no counterparty was supplied. That is the
    #     honest maximum: the framework cannot police a field it was never
    #     given, and the checks tuple records `counterparty=not_supplied` so
    #     the omission is visible in the replay rather than absent from it.
    if operation.counterparty is not None:
        standing = operation.counterparty.standing
        cp_id = operation.counterparty.counterparty_id
        if standing is CounterpartyStanding.NOT_ASSESSED:
            return _decide(
                GateDecision.HOLD,
                ReasonCode.COUNTERPARTY_UNASSESSED,
                f"Counterparty {cp_id} was named and no standing has been "
                f"established for it. Naming a counterparty and leaving its "
                f"standing unread is not the same as having no counterparty; "
                f"closed by an assessment, not by a market action.",
            )
        if standing is CounterpartyStanding.UNDER_REVIEW:
            return _decide(
                GateDecision.ESCALATE,
                ReasonCode.COUNTERPARTY_UNDER_REVIEW,
                f"Counterparty {cp_id} is under review. Routed to human "
                f"authority rather than held: a review means somebody is "
                f"already looking, and this operation is evidence for them "
                f"rather than a decision this gate should take without them.",
            )
        if standing in {
            CounterpartyStanding.SUSPENDED,
            CounterpartyStanding.DEFAULTED,
        }:
            return _decide(
                GateDecision.HOLD,
                ReasonCode.COUNTERPARTY_NOT_IN_GOOD_STANDING,
                f"Counterparty {cp_id} is {standing.value}. Nothing routine "
                f"proceeds against a name in that state, and no rail choice "
                f"or funding position changes that.",
            )

    # 3a. The funding model refused to assert this position.
    #
    #     Placed before the funded check rather than inside it, because the
    #     two say different things and collapsing them would lose the one
    #     that matters. "Short" is a finding about the position. "The model
    #     would not say" is a finding about the evidence, and it has a
    #     different remedy: resolve the correspondent chain or the pending
    #     determination, not fund the account.
    if not funding.position_is_assertable:
        return _decide(
            GateDecision.HOLD,
            ReasonCode.FUNDING_INDETERMINATE,
            "The funding model declined to assert the settlement-instant "
            "position, so there is no funded state to check. A refusal that "
            "arrives here as a number is a refusal that was thrown away in "
            "transit; this gate will not read one as evidence of funding "
            "(CASH-001 SVII).",
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

    # 6. Timing infeasible — no rail open, reachable, AND able to carry
    #    this operation within the window.
    #
    #    Capacity is part of this check rather than a ladder detail. It was
    #    not, and the consequence was a gate that raised an AssertionError
    #    reading "unreachable: check 6 guarantees a usable rail": check 6
    #    proved usability, the ladder additionally required capacity, and
    #    usability does not imply capacity. A single available rail with a
    #    value cap below the notional — the ordinary off-hours large-value
    #    case, since FedNow ships with a cap — reached an assertion instead
    #    of a decision, and an assertion is not a governance outcome.
    #
    #    Skipped where the rail is determined by depository linkage rather
    #    than selected, because there is nothing to choose among; that path
    #    is validated in the ladder.
    #
    #    PORTS_WHOLESALE is excluded: it is a reserved placeholder and is
    #    never a usable rail until the infrastructure ships.
    if operation.depository_linked_rail is None and not any(
        _serviceable(state, operation)
        for rail, state in rails.items()
        if rail is not CashRail.PORTS_WHOLESALE
    ):
        return _decide(
            GateDecision.HOLD,
            ReasonCode.NO_RAIL_IN_WINDOW,
            f"No cash rail is open, reachable, and able to carry "
            f"{operation.notional} within the required settlement window. "
            f"Hold to the next window rather than routing to a closed rail "
            f"or to one that cannot carry the operation (CASH-001 SV.B.6).",
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
    selection = _recommend_rail(
        operation=operation, rails=rails, ofr_stlfsi4=ofr_stlfsi4
    )
    if selection is None:
        # The ladder found nothing serviceable. Reachable only where check 6
        # was skipped for a depository-linked operation whose linked rail
        # cannot carry it. Hold with the check-6 reason, because that is
        # what the condition is.
        return _decide(
            GateDecision.HOLD,
            ReasonCode.NO_RAIL_IN_WINDOW,
            f"The rail ladder found no rail able to carry "
            f"{operation.notional} within the settlement window. Hold rather "
            f"than recommend a rail that cannot carry the operation "
            f"(CASH-001 SV.B.6).",
        )
    rail, ladder_rationale = selection

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
