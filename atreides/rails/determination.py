"""Determination dependence - the fifth finality class and its registry.

Per AUR-CUSTODY-CASH-001 Section IV as extended, and the research memo
RESEARCH-PREDICTION-MARKETS-FINALITY (14 August 2026).

WHAT THIS MODULE EXISTS TO SAY
------------------------------
The four original finality classes all answer one question: *when does the
cash movement become irrevocable*. Gross-final answers "at the instant".
Deferred-net answers "at end of cycle". Ledger-final answers "at commit".
Correspondent-dependent answers "we cannot see".

A contingent-payout instrument - a binary event contract is the clearest
example - produces a case none of those describe. The cash leg settles on
an ordinary rail and is irrevocable on that rail's own terms. What is
revocable is the *entitlement*: the venue determined an outcome, and the
venue retains authority to revisit that determination and, in one of the
two forms below, to cancel the contract and return the funds.

So the movement is final and the value is not. ``DETERMINATION_DEPENDENT``
names that state, and it is a class of the **obligation**, never of the
rail. No entry in ``RAIL_FINALITY`` maps to it and none ever will. A
decision record therefore carries two finality classes where this applies:
the rail's, and the obligation's.

WHAT THE VERIFICATION PASS CHANGED
----------------------------------
The first draft of this finding held that the power to revoke a determined
outcome was distinctive to prediction-market venues. Cross-venue reading on
14 August 2026 disconfirmed that. Broad emergency authority exists at every
designated contract market examined - the power to suspend trading, to
order liquidation, to *establish the settlement price at which contracts
are to be liquidated*, and force-majeure authority vested in senior
officers. Revocability as such is not distinctive.

What differs is the **form**, and the difference is dispositive here:

- Liquidation at an administered price leaves settlement intact. The
  exchange set the value; the payment still happened and stays happened.
  The residual exposure is a valuation exposure, and it belongs to margin
  and to risk, not to finality.
- Cancellation of the contract and return of funds reverses the settlement
  itself.

Only the second produces ``DETERMINATION_DEPENDENT``. That is a narrow
claim and a falsifiable one: it can be checked against any venue's
rulebook, and it is wrong if a venue's cancellation power turns out to be
something else on inspection.

HOW LONG A DETERMINED OUTCOME STAYS QUALIFIED
---------------------------------------------
This was the open question that blocked implementation, and the answer is
the same answer the framework gives everywhere else: **the venue decides
the duration, the framework records it, and where the venue states no
bound the position never leaves the qualified state and the record says
so.**

The three answers that were available and are all wrong:

- *Qualified forever, always.* Then nothing settles, every position on
  every venue sits in a permanent contingent state, and the class carries
  no information because it never discriminates.
- *Unqualified on determination.* Then the class collapses into whatever
  the rail says and the finding is discarded.
- *A fixed period chosen here.* An invented number tracing to no
  disclosure. The framework does not hold guesses.

What the framework does instead: read the venue's own stated review or
contest period into ``qualification_window_seconds``, and classify.
Emergency and force-majeure authority in the rulebooks examined is written
as a standing power with no expiry, so ``QUALIFIED_UNBOUNDED`` is expected
to be the common case rather than an edge one. That is not a defect in the
model. A venue that publishes a bounded contest window and a venue that
publishes none are materially different counterparties, and making that
difference visible is the entire value of the class. Laundering an
unbounded window into a finality timestamp would hide exactly the fact an
operator needs.

Note the deliberate separation of ``NOT_ASSESSED`` from ``NONE_DISCLOSED``.
"We have not read this venue's rulebook" and "we read it and it grants no
cancellation power" are different states with the same conservative
treatment and completely different remedies: one is a research task, the
other is a risk acceptance. Collapsing them would let an unread venue pass
as a clean one.

Architectural contract: PURE, NO I/O, NO CLOCK. Same as CATO-F. Elapsed
time since determination arrives as a scalar from the caller; this module
never asks what time it is, which is what keeps a classification
replayable from its recorded inputs.

Status: v0.1 - doctrine-first implementation. Creates no authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from atreides.rails.finality import FinalityClass

__all__ = [
    "DOCTRINE_VERSION",
    "RevocationForm",
    "DeterminationOutcome",
    "DeterminationProfile",
    "absent_determination_profile",
    "classify_determination",
    "obligation_finality_class",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-CASH-001-v0.2-SIV-DET"


class RevocationForm(StrEnum):
    """How, if at all, a venue may unwind an outcome it has determined.

    Recorded from the venue's rulebook. Never inferred, and never ranked -
    the registry states which form applies and the classification rules
    below decide what follows.
    """

    NOT_ASSESSED = "not_assessed"
    """No profile has been populated for this venue. This is the default
    and it is NOT the same as "the venue has no such power"; it means
    nobody has read the rulebook. The remedy is research, not risk
    acceptance."""

    NONE_DISCLOSED = "none_disclosed"
    """The rulebook was read and discloses no power to cancel a determined
    contract and return funds."""

    LIQUIDATION_AT_ADMINISTERED_PRICE = "liquidation_at_administered_price"
    """The venue may liquidate positions and establish the price at which
    they are liquidated. Settlement occurs and stays occurred; the value
    was administered. This does NOT produce determination dependence - the
    residual is a valuation exposure and belongs to margin."""

    CANCELLATION_AND_RETURN_OF_FUNDS = "cancellation_and_return_of_funds"
    """The venue may cancel the contract and return funds. The settlement
    itself reverses. This is the only form that produces determination
    dependence."""


class DeterminationOutcome(StrEnum):
    """State of a contingent obligation with respect to its determination.

    A closed set, following the funding model's discipline: the answer is
    not a boolean, because collapsing these removes the information an
    operator needs first.
    """

    NOT_APPLICABLE = "not_applicable"
    """The obligation is not contingent on an outcome determination, or the
    venue's revocation form does not reverse settlement. The rail's finality
    class governs alone and nothing here applies."""

    AWAITING_DETERMINATION = "awaiting_determination"
    """The outcome has not been determined. The obligation is not yet a
    fixed number and no shortfall can be projected against it."""

    QUALIFIED_BOUNDED = "qualified_bounded"
    """Determined, and the venue publishes a period during which the
    determination may be revisited. That period has not elapsed. The
    position is qualified and will stop being qualified at a knowable
    moment."""

    QUALIFIED_UNBOUNDED = "qualified_unbounded"
    """Determined, and the venue's cancellation authority is written with
    no expiry. The position does not leave the qualified state. Expected to
    be the common case; recorded honestly rather than converted into a
    finality timestamp."""

    QUALIFICATION_UNKNOWN = "qualification_unknown"
    """Determined, but no profile has been populated for the venue, so
    whether the settlement can be reversed is unread rather than absent.
    Treated as conservatively as QUALIFIED_UNBOUNDED and kept distinct from
    it because the remedy differs."""

    UNQUALIFIED = "unqualified"
    """Determined, and either the venue holds no power to reverse the
    settlement or its stated window has elapsed. The only path to real
    finality on a contingent instrument."""


@dataclass(frozen=True, slots=True)
class DeterminationProfile:
    """One venue's determination and revocation characteristics.

    Parallel in construction and discipline to the depository profile: the
    registry ships with the shape defined and the entries flagged, never
    populated by inference.
    """

    venue_id: str

    revocation_form: RevocationForm = RevocationForm.NOT_ASSESSED

    #: Seconds after determination during which the venue may revisit it,
    #: as the venue states it. ``None`` on an assessed profile means the
    #: venue states no bound. On a NOT_ASSESSED profile it means nothing,
    #: and setting it is rejected.
    qualification_window_seconds: int | None = None

    #: Citation for the rulebook provision this profile was read from.
    provenance: str | None = None

    def __post_init__(self) -> None:
        if not self.venue_id:
            raise ValueError("venue_id is required")

        assessed = self.revocation_form is not RevocationForm.NOT_ASSESSED

        if assessed and not self.provenance:
            raise ValueError(
                "an assessed determination profile requires provenance; an "
                "unattributed profile is indistinguishable from a guess "
                "(CASH-001 SIV, registry discipline)"
            )
        if not assessed and self.qualification_window_seconds is not None:
            raise ValueError(
                "a NOT_ASSESSED profile may not state a qualification window; "
                "you cannot record a bound you have not read"
            )
        if (
            self.qualification_window_seconds is not None
            and self.qualification_window_seconds <= 0
        ):
            raise ValueError("qualification_window_seconds must be positive")

    @property
    def reverses_settlement(self) -> bool:
        """True only where the venue may cancel and return funds.

        Deliberately narrow. Administered-price liquidation returns False
        because settlement is preserved under it, which is the distinction
        the cross-venue reading established.
        """
        return self.revocation_form is RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS


def absent_determination_profile(venue_id: str) -> DeterminationProfile:
    """Return the profile for a venue with no registry entry.

    Named and exported so that "what happens when no profile exists" is
    answered in one auditable place rather than implicitly at each call
    site. The answer is always a NOT_ASSESSED profile asserting nothing.
    Mirrors ``absent_gate_decision()`` and the margin registry's default.
    """
    return DeterminationProfile(venue_id=venue_id)


def classify_determination(
    *,
    profile: DeterminationProfile,
    instrument_is_contingent: bool,
    determined: bool,
    seconds_since_determination: int | None = None,
) -> DeterminationOutcome:
    """Classify a contingent obligation. Deterministic, pure, replayable.

    Check order is doctrine, not optimisation, and the first condition met
    decides:

    1. A non-contingent instrument is out of scope entirely.
    2. An undetermined outcome is undetermined regardless of what the
       venue's rulebook says about revoking determinations it has not made.
    3. An unread rulebook cannot be treated as a clean one.
    4. Forms that preserve settlement do not produce a finality question.
    5. Only then does the window arithmetic apply.

    ``seconds_since_determination`` left as ``None`` means the caller did
    not supply elapsed time. The classification stays qualified rather than
    assuming the window has run - the module has no clock and will not
    invent one.
    """
    if not instrument_is_contingent:
        return DeterminationOutcome.NOT_APPLICABLE

    if not determined:
        return DeterminationOutcome.AWAITING_DETERMINATION

    if profile.revocation_form is RevocationForm.NOT_ASSESSED:
        return DeterminationOutcome.QUALIFICATION_UNKNOWN

    if not profile.reverses_settlement:
        return DeterminationOutcome.UNQUALIFIED

    window = profile.qualification_window_seconds
    if window is None:
        return DeterminationOutcome.QUALIFIED_UNBOUNDED

    if seconds_since_determination is None:
        return DeterminationOutcome.QUALIFIED_BOUNDED

    if seconds_since_determination >= window:
        return DeterminationOutcome.UNQUALIFIED

    return DeterminationOutcome.QUALIFIED_BOUNDED


def obligation_finality_class(
    outcome: DeterminationOutcome,
) -> FinalityClass | None:
    """The obligation-level finality class implied by an outcome.

    Returns ``None`` where the obligation carries no finality class of its
    own and the rail's class governs alone. Returns
    ``DETERMINATION_DEPENDENT`` for every state in which the value can
    still move against the holder for reasons the rail knows nothing about.

    Exhaustive over ``DeterminationOutcome`` by construction: a new member
    added without a decision here fails the exhaustiveness test rather than
    falling through to a default.
    """
    match outcome:
        case DeterminationOutcome.NOT_APPLICABLE | DeterminationOutcome.UNQUALIFIED:
            return None
        case (
            DeterminationOutcome.AWAITING_DETERMINATION
            | DeterminationOutcome.QUALIFIED_BOUNDED
            | DeterminationOutcome.QUALIFIED_UNBOUNDED
            | DeterminationOutcome.QUALIFICATION_UNKNOWN
        ):
            return FinalityClass.DETERMINATION_DEPENDENT
    raise AssertionError(f"unhandled DeterminationOutcome: {outcome!r}")
