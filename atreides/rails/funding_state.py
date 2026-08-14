"""Intraday funding-state model — the cash leg's "can it settle" answer.

Per AUR-CUSTODY-CASH-001 v0.2 Section VII. Rail selection (CATO-F, §V)
answers *how* the money moves. This module answers *whether it can*, and
it is the check that most often determines whether a cash leg completes.

It produces the :class:`~atreides.rails.cato_f.FundingState` that CATO-F's
checks 3 and 4 consume, closing the loop the gate left open: before this
module, funding state was whatever the caller asserted.

THE DISTINCTION THIS MODULE EXISTS TO MAKE
------------------------------------------
**A queued operation is not a failed operation.** CASH-001 §VII states this
as doctrine, not implementation detail, because it is what the
anti-duplicate-payment interlock in ``AUR-J-PATHSET-RCA-001`` depends on.
On a gross-final rail an unfunded instruction *queues* and settles when
funding arrives; classifying that as a failure and re-issuing creates a
duplicate payment, which per ``AUR-CUSTODY-001 §IX`` cannot be reversed by
the settlement system and resolves at best to UR-R.

So the model never returns a bare "unfunded". It distinguishes
:attr:`FundingDisposition.WILL_QUEUE` from
:attr:`FundingDisposition.WILL_FAIL`, and that distinction is the product.

FINALITY DRIVES THE TREATMENT
-----------------------------
Per §VII, the same shortfall means different things by finality class:

- **Gross-final** (Fedwire, FedNow) — the position must be funded
  moment-to-moment. A shortfall at the settlement instant queues; it fails
  only if funding does not arrive before the window closes.
- **Deferred-net** (CHIPS, NSS, FICC/GSD) — exposure is modelled across the
  window to end-of-day finality. What matters is the position at finality,
  not at instruction.
- **Ledger-final** (tokenized deposit, stablecoin) — funded or not, at the
  instant. There is no queue on a ledger.
- **Correspondent-dependent** — the finality state is not observable, so
  the model refuses to assert fundedness rather than guessing.

CERTAIN VERSUS EXPECTED FLOWS
-----------------------------
Projections use **committed** flows only. An expected-but-uncommitted
receivable is tracked and reported, never counted toward fundedness — you
do not fund a settlement on hoped-for inflows. The optimistic projection is
surfaced separately so an operator can see the gap between what is
committed and what is anticipated.

Architectural contract: PURE, NO I/O, NO CLOCK. Same as CATO-F. Every
input arrives as a value; the caller's refresh loop owns data fetching.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from atreides.rails.cato_f import FinalityClass, FundingState
from atreides.rails.determination import DeterminationOutcome

__all__ = [
    "DOCTRINE_VERSION",
    "CashFlow",
    "FundingDisposition",
    "FundingInputs",
    "FundingProjection",
    "LadderPoint",
    "project_funding",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-CASH-001-v0.2-SVII"


class FundingDisposition(StrEnum):
    """What will happen to this cash leg on funding grounds."""

    FUNDED = "funded"
    """The committed position covers the obligation."""
    #: Funded, and the obligation is DETERMINATION_DEPENDENT: the venue may
    #: still cancel the contract and return the funds. The settlement
    #: completes and the money is not yet the firm's to spend. Kept
    #: distinct from FUNDED for the same reason WILL_QUEUE is kept distinct
    #: from WILL_FAIL - an operator who treats a qualified receipt as free
    #: cash has taken an unpriced exposure to a venue's emergency authority.
    FUNDED_QUALIFIED = "funded_qualified"
    #: Gross-final rail, short at the settlement instant, but funding
    #: arrives before the window closes. NOT a failure — see module docstring.
    WILL_QUEUE = "will_queue"
    #: Short, and funding does not arrive in the window.
    WILL_FAIL = "will_fail"
    #: Projected intraday debit exceeds the net-debit cap (Fed PSR policy).
    CAP_BREACH = "cap_breach"
    #: Clearing-fund or margin requirement not met at the CCP.
    CLEARING_FUND_DEFICIENT = "clearing_fund_deficient"
    #: Correspondent chain whose finality is not observable. The model
    #: declines to assert fundedness rather than guessing.
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class CashFlow:
    """An expected movement on the funding account.

    ``committed`` is the load-bearing field. Only committed flows count
    toward fundedness; uncommitted ones are reported but never relied on.
    """

    offset_seconds: int
    amount: Decimal
    label: str
    committed: bool = True


@dataclass(frozen=True, slots=True)
class LadderPoint:
    """Projected position at one point on the intraday ladder."""

    offset_seconds: int
    position: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class FundingInputs:
    """Everything the projection needs. All offsets are seconds from now."""

    opening_position: Decimal
    obligation: Decimal
    finality_class: FinalityClass
    settlement_offset_seconds: int
    #: When the rail's window closes. Funding arriving after this cannot
    #: rescue a queued instruction. None means a 24/7 rail with no close —
    #: per §VII the model must not assume a nightly reset.
    window_close_offset_seconds: int | None = None
    flows: tuple[CashFlow, ...] = ()
    net_debit_cap: Decimal | None = None
    clearing_fund_requirement: Decimal = Decimal(0)
    clearing_fund_posted: Decimal = Decimal(0)
    #: Obligation-level classification for contingent payouts, supplied by
    #: the caller from ``determination.classify_determination()``. Note that
    #: this is ORTHOGONAL to ``finality_class`` above and does not replace
    #: it: the rail is still gross-final or deferred-net or ledger-final,
    #: and the obligation is separately qualified or not. One field cannot
    #: carry two independent facts, and overloading ``finality_class`` to
    #: try was the first design and was wrong.
    determination_outcome: DeterminationOutcome = DeterminationOutcome.NOT_APPLICABLE

    @property
    def clearing_fund_sufficient(self) -> bool:
        return self.clearing_fund_posted >= self.clearing_fund_requirement


@dataclass(frozen=True, slots=True)
class FundingProjection:
    """The funding answer, with the evidence behind it."""

    disposition: FundingDisposition
    projected_position_at_settlement: Decimal
    optimistic_position_at_settlement: Decimal
    obligation: Decimal
    shortfall: Decimal
    net_debit_cap_headroom: Decimal
    clearing_fund_sufficient: bool
    #: When a shortfall clears, for a queued instruction. None if it never does.
    funded_at_offset_seconds: int | None
    ladder: tuple[LadderPoint, ...]
    rationale: str
    doctrine_version: str = DOCTRINE_VERSION
    determination_outcome: DeterminationOutcome = DeterminationOutcome.NOT_APPLICABLE

    @property
    def settles(self) -> bool:
        """True where the settlement completes.

        FUNDED_QUALIFIED is included, and that inclusion is a decision
        rather than a convenience: the payment happens, the rail's finality
        holds, and the operation is not blocked. What is unresolved is
        whether the value stays. Callers who need that distinction read
        :attr:`qualified` or the disposition itself — which is the same
        instruction the WILL_QUEUE case already carries.
        """
        return self.disposition in {
            FundingDisposition.FUNDED,
            FundingDisposition.FUNDED_QUALIFIED,
        }

    @property
    def qualified(self) -> bool:
        """True where settlement completed against a revocable entitlement."""
        return self.disposition is FundingDisposition.FUNDED_QUALIFIED

    @property
    def is_failure(self) -> bool:
        """True only where the operation genuinely cannot settle.

        WILL_QUEUE is deliberately excluded. Treating a queue as a failure
        is the mechanism that produces duplicate payments. FUNDED_QUALIFIED
        is excluded for a different reason: nothing failed, and a
        contingent claw-back that has not happened is not a settlement
        failure. Calling it one would re-import the same error in a new
        place.
        """
        return self.disposition in {
            FundingDisposition.WILL_FAIL,
            FundingDisposition.CAP_BREACH,
            FundingDisposition.CLEARING_FUND_DEFICIENT,
        }

    def to_gate_input(self) -> FundingState:
        """Render as the :class:`FundingState` CATO-F consumes.

        A queued instruction reports its committed position honestly — the
        gate holds on it, which is correct: an operation that cannot settle
        *at the instant* should not be released, even though it will
        eventually settle if left alone.
        """
        return FundingState(
            projected_funded_position=self.projected_position_at_settlement,
            net_obligation=self.obligation,
            net_debit_cap_headroom=self.net_debit_cap_headroom,
            clearing_fund_sufficient=self.clearing_fund_sufficient,
        )


def _position_at(
    opening: Decimal, flows: tuple[CashFlow, ...], offset: int, *, committed_only: bool
) -> Decimal:
    total = opening
    for f in flows:
        if f.offset_seconds <= offset and (f.committed or not committed_only):
            total += f.amount
    return total


def _build_ladder(
    inputs: FundingInputs,
) -> tuple[tuple[LadderPoint, ...], Decimal]:
    """Position over time on committed flows, plus the worst (lowest) point.

    The trough matters independently of the settlement instant: a net-debit
    cap is breached by the deepest intraday position, not the closing one.
    """
    points: list[LadderPoint] = [
        LadderPoint(0, inputs.opening_position, "opening position")
    ]
    running = inputs.opening_position
    for f in sorted(inputs.flows, key=lambda x: (x.offset_seconds, x.label)):
        if not f.committed:
            continue
        running += f.amount
        points.append(LadderPoint(f.offset_seconds, running, f.label))

    settle_pos = _position_at(
        inputs.opening_position,
        inputs.flows,
        inputs.settlement_offset_seconds,
        committed_only=True,
    )
    points.append(
        LadderPoint(
            inputs.settlement_offset_seconds,
            settle_pos - inputs.obligation,
            "post-settlement",
        )
    )
    trough = min(p.position for p in points)
    return tuple(sorted(points, key=lambda p: (p.offset_seconds, p.label))), trough


def _first_funded_offset(inputs: FundingInputs) -> int | None:
    """Earliest offset at which committed inflows cover the obligation.

    Returns None if the obligation is never covered within the window.
    """
    candidates = sorted(
        {f.offset_seconds for f in inputs.flows if f.committed}
        | {inputs.settlement_offset_seconds}
    )
    for offset in candidates:
        if offset < inputs.settlement_offset_seconds:
            continue
        if inputs.window_close_offset_seconds is not None and (
            offset > inputs.window_close_offset_seconds
        ):
            return None
        pos = _position_at(
            inputs.opening_position, inputs.flows, offset, committed_only=True
        )
        if pos >= inputs.obligation:
            return offset
    return None


def project_funding(inputs: FundingInputs) -> FundingProjection:
    """Project funding state. Deterministic, pure, replayable.

    Check order is doctrine, not optimisation: clearing-fund sufficiency and
    the net-debit cap are hard risk controls that gate regardless of whether
    the position covers the obligation — a funded operation that breaches
    the cap is still a breach (AUR-COCKPIT-001 §VII).
    """
    ladder, trough = _build_ladder(inputs)

    committed = _position_at(
        inputs.opening_position,
        inputs.flows,
        inputs.settlement_offset_seconds,
        committed_only=True,
    )
    optimistic = _position_at(
        inputs.opening_position,
        inputs.flows,
        inputs.settlement_offset_seconds,
        committed_only=False,
    )
    shortfall = max(Decimal(0), inputs.obligation - committed)

    if inputs.net_debit_cap is None:
        headroom = Decimal(0)
    else:
        # Headroom against the deepest intraday point, not the closing one.
        headroom = inputs.net_debit_cap + min(trough, Decimal(0))

    def build(
        disposition: FundingDisposition,
        rationale: str,
        funded_at: int | None = None,
    ) -> FundingProjection:
        return FundingProjection(
            disposition=disposition,
            projected_position_at_settlement=committed,
            optimistic_position_at_settlement=optimistic,
            obligation=inputs.obligation,
            shortfall=shortfall,
            net_debit_cap_headroom=headroom,
            clearing_fund_sufficient=inputs.clearing_fund_sufficient,
            funded_at_offset_seconds=funded_at,
            ladder=ladder,
            rationale=rationale,
            determination_outcome=inputs.determination_outcome,
        )

    # 0. Contract violation, caught rather than guessed at.
    #    DETERMINATION_DEPENDENT is an obligation-level class and no rail
    #    carries it. A caller who supplies it as the rail's class has made
    #    a category error, and the fail-safe posture says refuse rather
    #    than fall through to the gross-final branch, which is what the
    #    if-ladder below would otherwise do silently.
    if inputs.finality_class is FinalityClass.DETERMINATION_DEPENDENT:
        return build(
            FundingDisposition.INDETERMINATE,
            "DETERMINATION_DEPENDENT is an obligation-level finality class "
            "and is not carried by any rail. Supply the rail's own class in "
            "finality_class and the contingency in determination_outcome. "
            "The model refuses rather than defaulting to gross-final "
            "treatment (CASH-001 SIV).",
        )

    # 1. Clearing fund / margin — a hard control, independent of position.
    if not inputs.clearing_fund_sufficient:
        return build(
            FundingDisposition.CLEARING_FUND_DEFICIENT,
            f"Clearing-fund posted {inputs.clearing_fund_posted} is below "
            f"requirement {inputs.clearing_fund_requirement}. Hard control; "
            f"position is irrelevant (CASH-001 §VII, COCKPIT §VII).",
        )

    # 2. Net-debit cap — breached by the deepest intraday point.
    if inputs.net_debit_cap is not None and headroom < 0:
        return build(
            FundingDisposition.CAP_BREACH,
            f"Projected intraday trough {trough} breaches the net-debit cap "
            f"{inputs.net_debit_cap} (headroom {headroom}). Federal Reserve "
            f"Payment System Risk policy; hold and escalate.",
        )

    # 3. Awaiting determination — there is no fixed obligation yet.
    #    Ordered ahead of the correspondent check because the existence of
    #    an obligation is logically prior to the observability of the rail
    #    that would carry it: if the amount owed is not yet a number,
    #    whether the rail's finality can be seen is moot.
    if inputs.determination_outcome is DeterminationOutcome.AWAITING_DETERMINATION:
        return build(
            FundingDisposition.INDETERMINATE,
            "Contingent obligation awaiting outcome determination. The "
            "amount owed is not yet fixed, so no shortfall can be projected "
            "against it. The model declines to project rather than "
            "projecting against a placeholder (CASH-001 SIV, SVII).",
        )

    # 4. Correspondent-dependent finality is not observable — do not guess.
    if inputs.finality_class is FinalityClass.CORRESPONDENT_DEPENDENT:
        return build(
            FundingDisposition.INDETERMINATE,
            "Correspondent-dependent finality: the funding position at "
            "finality is not observable to the originator. The model "
            "declines to assert fundedness (CASH-001 §IV).",
        )

    # 5. Funded outright — subject to whether the entitlement is qualified.
    #    A qualification never improves a worse disposition and is applied
    #    only on a funded path: a shortfall is a shortfall whether or not
    #    the venue can later cancel the contract, and marking a failure
    #    "qualified" would dilute a disposition that is already correct.
    def build_funded(rationale: str) -> FundingProjection:
        """FUNDED, downgraded where the entitlement is revocable.

        Written once so that the qualification cannot be applied on the
        gross-final funded path and forgotten on the deferred-net one.
        """
        if inputs.determination_outcome not in {
            DeterminationOutcome.QUALIFIED_BOUNDED,
            DeterminationOutcome.QUALIFIED_UNBOUNDED,
            DeterminationOutcome.QUALIFICATION_UNKNOWN,
        }:
            return build(FundingDisposition.FUNDED, rationale)
        return build(
            FundingDisposition.FUNDED_QUALIFIED,
            rationale
            + f" Obligation is DETERMINATION_DEPENDENT "
            f"({inputs.determination_outcome.value}): the settlement "
            f"completes and the venue retains authority to cancel the "
            f"contract and return the funds. The contingent return "
            f"obligation is NOT netted here and is NOT a committed flow "
            f"(CASH-001 SIV, SVII).",
        )

    if shortfall == 0:
        return build_funded(
            f"Committed position {committed} covers obligation "
            f"{inputs.obligation} at the settlement instant.",
        )

    # 6. Short. What that means depends on finality.
    if inputs.finality_class is FinalityClass.DEFERRED_NET:
        # Exposure runs to end-of-day finality; the position at finality is
        # what settles, not the position at instruction.
        close = inputs.window_close_offset_seconds
        at_finality = (
            committed
            if close is None
            else _position_at(
                inputs.opening_position, inputs.flows, close, committed_only=True
            )
        )
        if at_finality >= inputs.obligation:
            return build_funded(
                f"Deferred-net rail: position at finality {at_finality} covers "
                f"obligation {inputs.obligation}. Exposure runs to end-of-day; "
                f"the instruction-instant shortfall of {shortfall} is not a "
                f"settlement failure (CASH-001 §IV, §VII).",
            )
        return build(
            FundingDisposition.WILL_FAIL,
            f"Deferred-net rail: position at finality {at_finality} is below "
            f"obligation {inputs.obligation}; shortfall persists to end-of-day.",
        )

    if inputs.finality_class is FinalityClass.LEDGER_FINAL:
        return build(
            FundingDisposition.WILL_FAIL,
            f"Ledger-final rail: short {shortfall} at the settlement instant "
            f"and there is no queue on a ledger — the transaction simply does "
            f"not execute.",
        )

    # Gross-final: short at the instant queues rather than fails.
    funded_at = _first_funded_offset(inputs)
    if funded_at is not None:
        return build(
            FundingDisposition.WILL_QUEUE,
            f"Gross-final rail: short {shortfall} at the settlement instant. "
            f"Committed inflows cover the obligation at +{funded_at}s, within "
            f"the window. The instruction QUEUES and settles then — this is "
            f"NOT a failure, and re-issuing it produces a duplicate payment "
            f"(CASH-001 §VII).",
            funded_at,
        )
    return build(
        FundingDisposition.WILL_FAIL,
        f"Gross-final rail: short {shortfall} at the settlement instant and no "
        f"committed inflow covers the obligation before the window closes.",
    )
