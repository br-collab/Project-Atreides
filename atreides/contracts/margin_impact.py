"""Margin impact - margin as an attribute of a break.

Implements SPEC-MARGIN-AWARE-BREAKS v0.2. Doctrine: AUR-CUSTODY-MARGIN-001
(draft), with the determinism boundary at section 2 governing every claim in
this module.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not calculate margin, and the refusal is the load-bearing part.
Margin quantum is not deterministic: it is a deterministic function of
stochastic and partly discretionary inputs, so the model reproduces while
its arguments do not. Volatility and correlations are stochastic,
calibration parameters are revised by the venue, add-ons for concentration
and liquidity and wrong-way risk are frequently judgment rather than
output, and the venue retains discretion to make intraday calls.

**No component here returns a predicted margin figure and no interface is
shaped so a consumer could infer one is on offer.** What is deterministic,
and all that is claimed, is the *classification of a supplied figure*: given
a delta, an observability and a call window, the disposition and the
resulting priority are reproducible byte for byte. That is the same
architecture as the intraday funding model, which does not predict whether
funding arrives and does deterministically classify whether an instruction
queues or fails.

Stated once, in the form meant to survive into doctrine: **deterministic
governance over non-deterministic inputs.**

THE PROBLEM IT SOLVES
---------------------
The Breaks Workbench traces a break from symptom to proximate cause to
originating event against an append-only trail, and carries no economic
dimension. Two breaks that look identical operationally can be worlds apart
economically: one touches an unmargined position and costs an hour of
somebody's morning, the other moves a collateral requirement at a CCP and
carries a call inside the day. Sorting by age, size or counterparty sorts by
everything except the variable that determines urgency.

STANDARDS POSTURE
-----------------
This framework occupies the participant seat. The international standards
governing margin practice address financial market infrastructures and the
authorities that supervise them; the chain runs standard-setter to national
regulator to infrastructure, and a participant is not an addressee. So this
is a **consumer of mandated disclosure and not a compliance artifact**, it
makes no claim of observance, and it does not import infrastructure-internal
vocabulary - resource adequacy, default resources, waterfall - which is
unobservable from where it sits.

Architectural contract: PURE, NO I/O, NO CLOCK. Offsets arrive as scalars.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.contracts.margin_profile import (
    CollectionModel,
    MonitoringModel,
    VenueMarginProfile,
)
from atreides.rails.finality import FinalityClass

__all__ = [
    "DOCTRINE_VERSION",
    "CallWindow",
    "IndeterminacyReason",
    "MarginDirection",
    "MarginDisposition",
    "MarginImpact",
    "Observability",
    "absent_margin_assessment",
    "margin_impact_for_clearing_fund_deficiency",
    "margin_impact_outside_monitoring_window",
    "margin_priority_rank",
    "margin_sort_key",
    "raises_quorum_question",
    "sort_by_margin_consequence",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-MARGIN-001-draft-v0.1"


class MarginDisposition(StrEnum):
    """What a break means for margin.

    Following the funding model's discipline: the answer is not a boolean,
    because "does this break affect margin" has more than two materially
    different answers and collapsing them removes the information an
    operator needs first.
    """

    NO_MARGIN_EFFECT = "no_margin_effect"
    """The break does not touch a margined position. Routine queue."""

    WITHIN_TOLERANCE = "within_tolerance"
    """Delta is below the applied materiality threshold. Routine queue, and
    the threshold that was applied is recorded on the assessment."""

    UNDER_COLLATERALIZED = "under_collateralized"
    """Firm owes more than it has posted. Escalate; call risk."""

    OVER_COLLATERALIZED = "over_collateralized"
    """Firm has posted more than it owes. Escalate; funding cost,
    recoverable."""

    CALL_WINDOW_CLOSED = "call_window_closed"
    """Exposure is quantified and no collection mechanism is open until the
    venue's window reopens. Materially different from an
    under-collateralisation with an open window: the remedy is a position or
    hedging decision, because no call can be made or met. Continuous trading
    against periodic collection is the condition that produces it."""

    METHODOLOGY_DEPENDENT = "methodology_dependent"
    """The answer differs by which model the venue applies and that is not
    determinable from the inputs. Escalate with both outcomes stated."""

    INDETERMINATE = "indeterminate"
    """Margin state is not observable. Escalate; treat as unbounded until
    resolved. This is also the fail-safe default - see
    :func:`absent_margin_assessment`."""


class MarginDirection(StrEnum):
    """Which way the money goes.

    Recorded separately from disposition because an under-collateralised and
    an over-collateralised position are the same discovery with opposite
    cash consequences, and collapsing them loses what an operator needs
    first.
    """

    OWED_TO_VENUE = "owed_to_venue"
    """The firm owes. A call is coming, or should be."""
    OWED_TO_FIRM = "owed_to_firm"
    """The venue owes. A funding cost that is recoverable."""
    NEUTRAL = "neutral"
    """Measured, and no cash consequence in either direction."""
    UNKNOWN = "unknown"
    """Direction not established. The default where nobody assessed it."""


class IndeterminacyReason(StrEnum):
    """Why a margin state is not observable.

    Exists because of a collision found by measurement rather than by
    reading: every venue profile ships flagged, so an unassessed break
    resolves to INDETERMINATE by the fail-safe, INDETERMINATE carried a
    single priority rank, and a queue of five hundred unassessed breaks
    therefore had no ordering at all. The fail-safe default and the
    prioritisation rule were each correct in isolation and degenerate
    together.

    Sub-ranking does NOT repair the shipped state, and claiming otherwise
    would be the second mistake. Where nobody has assessed anything there is
    no information to order by, and inventing one would be worse than a flat
    queue. What this does is give triage somewhere to put its answer, so the
    queue orders itself as soon as a human looks - and makes the flatness
    diagnosable rather than invisible.

    The substantive reasons carry different remedies, which is the whole
    justification for separating them: an operations task, a research task,
    a risk acceptance already taken, and - since a market forced the case
    into the open - a wait with a stated end time.
    """

    NOT_APPLICABLE = "not_applicable"
    """The disposition is not INDETERMINATE. Nothing here applies."""

    UNSPECIFIED = "unspecified"
    """Indeterminate, and nobody has said why. Ranks first within the group:
    the break cannot even be routed, and triage is both the fastest action
    available and the one that unblocks every other."""

    UNRECONCILED_POSITION = "unreconciled_position"
    """The position itself is not reconciled. An operations task, closeable
    today, and the most likely of the three to be masking real exposure."""

    UNREAD_VENUE_PROFILE = "unread_venue_profile"
    """No profile has been populated for the venue. A research task: closed
    by reading an entitled document, not by any market action, and not
    closeable inside the day."""

    VENUE_PUBLISHES_NOTHING = "venue_publishes_nothing"
    """The venue was assessed and discloses no margin methodology on any
    standard basis. There is no work item - it is a standing condition and a
    risk acceptance already taken. Distinct from UNREAD_VENUE_PROFILE for
    exactly the reason NOT_ASSESSED is distinct from NONE_DISCLOSED
    everywhere else in this framework."""

    OUTSIDE_MONITORING_WINDOW = "outside_monitoring_window"
    """The venue publishes a methodology and monitors on a stated cycle, and
    this exposure accrued outside the hours that cycle covers.

    Added for a condition that is now real rather than hypothetical: US
    equity clearing extended to a night session while the clearing
    corporation's intraday monitoring stayed inside narrower hours, so a
    position can be novated, guaranteed and growing while the venue's own
    observation is silent. See ``MonitoringModel.BOUNDED_WINDOW``.

    **This is not an uncollectable exposure.** The position rolls into the
    next start-of-day call, which will be made. What is absent is
    observation, and conflating that with a closed collection window would
    have the framework report an exposure nobody can collect where in fact
    somebody will.

    Ranks last within the group, which is the debatable part and is stated
    rather than hidden. The case for last: every other reason names work
    somebody could start now, and this one names a wait that ends at an hour
    the venue has published. The case against, which loses: the exposure is
    live and accruing, and burying it under a standing condition risks it
    being read as inert. It loses because rank orders *attention*, nothing
    at 3am changes the outcome, and the break does not disappear - it
    reprices itself the moment the window opens."""


class Observability(StrEnum):
    """On what basis the assessment is held.

    Not the same axis as disposition. A break can be confidently
    UNDER_COLLATERALIZED on a DERIVED basis, and that combination must be
    visible to the person acting on it.
    """

    OBSERVED = "observed"
    """The venue published it."""

    DERIVED = "derived"
    """Computed by an upstream system from observed inputs."""

    UNOBSERVABLE = "unobservable"
    """The venue does not publish at this frequency, or the position is not
    reconciled."""


class CallWindow(BaseModel):
    """When the venue can actually call and collect.

    Sourced from the venue margin profile registry, never inferred. The
    window is what separates a quantified exposure that can be met from one
    that cannot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_model: CollectionModel = CollectionModel.UNKNOWN
    is_open: bool
    #: Offset at which an open window closes. ``None`` on a known collection
    #: model means the window does not close; on an UNKNOWN collection model
    #: it means nobody has read the venue's schedule. The two are
    #: disambiguated by ``collection_model``, deliberately, because a
    #: continuous window and an unread one are different facts.
    closes_at_offset_seconds: int | None = None
    #: Offset at which a closed window reopens. ``None`` where the venue
    #: publishes no reopening time.
    reopens_at_offset_seconds: int | None = None

    @model_validator(mode="after")
    def _unknown_model_states_no_schedule(self) -> CallWindow:
        if self.collection_model is CollectionModel.UNKNOWN and (
            self.closes_at_offset_seconds is not None
            or self.reopens_at_offset_seconds is not None
        ):
            raise ValueError(
                "a window with an UNKNOWN collection model may not state a "
                "schedule; you cannot record a cutoff you have not read "
                "(AUR-CUSTODY-MARGIN-001 sec. 4)"
            )
        return self

    @model_validator(mode="after")
    def _open_window_has_no_reopen(self) -> CallWindow:
        if self.is_open and self.reopens_at_offset_seconds is not None:
            raise ValueError("an open window does not reopen")
        return self


#: Dispositions that assert a known direction of exposure. Each carries a
#: number the framework was given, so none may be held on an unobservable
#: basis.
_QUANTIFIED: Final[frozenset[MarginDisposition]] = frozenset(
    {
        MarginDisposition.UNDER_COLLATERALIZED,
        MarginDisposition.OVER_COLLATERALIZED,
        MarginDisposition.CALL_WINDOW_CLOSED,
    }
)


class MarginImpact(BaseModel):
    """The margin consequence of one break, with the evidence behind it.

    Attaches to a break and is appended to the decision-of-record, never
    overwritten. A reassessment appends a new record with its own offset and
    the earlier assessment stays visible, because how the picture changed
    through the day is itself evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    disposition: MarginDisposition
    direction: MarginDirection
    observability: Observability
    collateral_observability: Observability

    #: The figure as supplied. ``None`` where not determinable. This module
    #: never populates it from a calculation of its own.
    delta_amount: Decimal | None = None
    delta_currency: str | None = Field(default=None, min_length=3, max_length=3)

    #: The threshold that was applied, recorded rather than assumed. The
    #: threshold itself is firm-configured; a fixed default would be wrong
    #: for every firm, so the assessment records which one it used.
    materiality_threshold: Decimal | None = Field(default=None, ge=Decimal("0"))

    #: Why the margin state is not observable. Meaningful only where the
    #: disposition is INDETERMINATE; validated below.
    indeterminacy: IndeterminacyReason = IndeterminacyReason.NOT_APPLICABLE

    venue: str | None = None
    #: The methodology as the venue discloses it, never as this framework
    #: computes it.
    methodology: str | None = None

    #: Finality class of the posted collateral, and of the obligation it is
    #: posted against. Both are recorded because the interesting case is
    #: when they differ - see :attr:`collateral_mismatch`.
    collateral_finality_class: FinalityClass | None = None
    obligation_finality_class: FinalityClass | None = None

    call_window: CallWindow | None = None

    assessed_at_offset_seconds: int | None = None

    #: The doctrine subsection this assessment rests on. An assessment that
    #: traces to nothing is an opinion.
    basis: str = Field(min_length=1)
    doctrine_version: str = DOCTRINE_VERSION

    # -- validators: the refusals are the product ---------------------------

    @model_validator(mode="after")
    def _amount_and_currency_travel_together(self) -> MarginImpact:
        if self.delta_amount is not None and not self.delta_currency:
            raise ValueError(
                "delta_amount requires delta_currency; an unlabelled amount "
                "is not a figure anybody can act on"
            )
        if self.delta_currency and self.delta_amount is None:
            raise ValueError(
                "delta_currency without delta_amount denominates nothing"
            )
        return self

    @model_validator(mode="after")
    def _unobservable_asserts_no_direction(self) -> MarginImpact:
        if self.observability is Observability.UNOBSERVABLE and (
            self.disposition in _QUANTIFIED
        ):
            raise ValueError(
                f"{self.disposition.value} asserts a known exposure and cannot "
                f"be held on an UNOBSERVABLE basis; the correct disposition is "
                f"INDETERMINATE (AUR-CUSTODY-MARGIN-001 sec. 6)"
            )
        return self

    @model_validator(mode="after")
    def _direction_matches_disposition(self) -> MarginImpact:
        expected = {
            MarginDisposition.UNDER_COLLATERALIZED: MarginDirection.OWED_TO_VENUE,
            MarginDisposition.OVER_COLLATERALIZED: MarginDirection.OWED_TO_FIRM,
            MarginDisposition.NO_MARGIN_EFFECT: MarginDirection.NEUTRAL,
        }.get(self.disposition)
        if expected is not None and self.direction is not expected:
            raise ValueError(
                f"{self.disposition.value} implies direction {expected.value}, "
                f"got {self.direction.value}"
            )
        return self

    @model_validator(mode="after")
    def _call_window_closed_requires_a_closed_window(self) -> MarginImpact:
        if self.disposition is MarginDisposition.CALL_WINDOW_CLOSED:
            if self.call_window is None:
                raise ValueError(
                    "CALL_WINDOW_CLOSED requires a call_window from the venue "
                    "margin profile registry; asserting a closed window "
                    "without one is an inference"
                )
            if self.call_window.is_open:
                raise ValueError(
                    "CALL_WINDOW_CLOSED asserted against an open window"
                )
        return self

    @model_validator(mode="after")
    def _within_tolerance_records_its_threshold(self) -> MarginImpact:
        if (
            self.disposition is MarginDisposition.WITHIN_TOLERANCE
            and self.materiality_threshold is None
        ):
            raise ValueError(
                "WITHIN_TOLERANCE must record the threshold it was measured "
                "against; 'below tolerance' with no stated tolerance is not a "
                "finding (SPEC-MARGIN-AWARE-BREAKS sec. 12)"
            )
        return self

    @model_validator(mode="after")
    def _indeterminacy_reason_matches_disposition(self) -> MarginImpact:
        indeterminate = self.disposition is MarginDisposition.INDETERMINATE
        applicable = self.indeterminacy is not IndeterminacyReason.NOT_APPLICABLE
        if applicable and not indeterminate:
            raise ValueError(
                f"indeterminacy={self.indeterminacy.value} is meaningful only "
                f"where the disposition is INDETERMINATE, got "
                f"{self.disposition.value}"
            )
        if indeterminate and not applicable:
            raise ValueError(
                "an INDETERMINATE assessment must say why it is "
                "indeterminate; UNSPECIFIED is a valid answer and NOT_APPLICABLE "
                "is not, because the three reasons carry three different remedies"
            )
        return self

    @model_validator(mode="after")
    def _indeterminate_asserts_no_figure(self) -> MarginImpact:
        if (
            self.disposition is MarginDisposition.INDETERMINATE
            and self.delta_amount is not None
        ):
            raise ValueError(
                "INDETERMINATE means the margin state is not observable; a "
                "delta figure contradicts it"
            )
        if (
            self.disposition is MarginDisposition.NO_MARGIN_EFFECT
            and self.delta_amount not in (None, Decimal(0))
        ):
            raise ValueError(
                "NO_MARGIN_EFFECT cannot carry a non-zero delta"
            )
        return self

    # -- derived ------------------------------------------------------------

    @property
    def escalates(self) -> bool:
        """True where the break leaves the routine queue."""
        return self.disposition not in {
            MarginDisposition.NO_MARGIN_EFFECT,
            MarginDisposition.WITHIN_TOLERANCE,
        }

    @property
    def collateral_mismatch(self) -> bool:
        """True where posted collateral and the obligation it secures settle
        on different finality terms.

        Collateral moving on a continuous rail against an obligation
        settling on a cycle produces an exposure in the gap between them,
        and that gap is precisely what regulators are now telling clearing
        organisations to price. A record that cannot state that collateral
        is final while the obligation is not cannot govern the exposure that
        arises between them.

        Returns False where either side is unrecorded. Absence of a record
        is not evidence of a match, and callers who need that distinction
        read the two fields.
        """
        if (
            self.collateral_finality_class is None
            or self.obligation_finality_class is None
        ):
            return False
        return self.collateral_finality_class is not self.obligation_finality_class


def absent_margin_assessment(
    reason: str = "no margin assessment was made",
    indeterminacy: IndeterminacyReason = IndeterminacyReason.UNSPECIFIED,
) -> MarginImpact:
    """The fail-safe default: INDETERMINATE, never NO_MARGIN_EFFECT.

    **A break with no margin assessment is not a break with no margin
    impact.** The framework does not infer margin neutrality from the
    absence of evidence, exactly as it does not infer finality from the
    absence of a gate decision.

    Named and exported so that "what happens when nobody assessed this" is
    answered in one auditable place rather than implicitly at every call
    site. Mirrors ``absent_gate_decision()`` and
    ``absent_determination_profile()``.
    """
    return MarginImpact(
        disposition=MarginDisposition.INDETERMINATE,
        direction=MarginDirection.UNKNOWN,
        observability=Observability.UNOBSERVABLE,
        collateral_observability=Observability.UNOBSERVABLE,
        indeterminacy=indeterminacy,
        basis=(
            f"{reason}. Absent-assessment default is INDETERMINATE, never "
            f"NO_MARGIN_EFFECT (AUR-CUSTODY-MARGIN-001 sec. 6)."
        ),
    )


# ---------------------------------------------------------------------------
# Prioritisation
# ---------------------------------------------------------------------------

#: Base ranks. Lower sorts first. The two UNDER_COLLATERALIZED cases are not
#: in this table because their rank depends on the call window, which is a
#: property of the assessment rather than of the disposition - see
#: :func:`margin_priority_rank`.
# Ranks are spaced by ten so a group can be sub-ranked without renumbering
# its neighbours. Relative order is unchanged from the first version; only
# the scale moved, and no test that compares two ranks is affected.
_BASE_RANK: Final[dict[MarginDisposition, int]] = {
    MarginDisposition.CALL_WINDOW_CLOSED: 20,
    MarginDisposition.INDETERMINATE: 30,
    MarginDisposition.METHODOLOGY_DEPENDENT: 40,
    MarginDisposition.OVER_COLLATERALIZED: 60,
    MarginDisposition.WITHIN_TOLERANCE: 70,
    MarginDisposition.NO_MARGIN_EFFECT: 80,
}

_UNDER_IN_CYCLE: Final[int] = 10
_UNDER_OUT_OF_CYCLE: Final[int] = 50

#: Offsets within the INDETERMINATE band. Same principle as the outer
#: ordering: priority tracks what can be acted upon and how fast. A break
#: nobody has classified leads, because triage is the fastest action
#: available and it unblocks everything behind it. A venue that publishes
#: nothing trails, because there is no work item at all - it is a standing
#: condition somebody already accepted.
_INDETERMINACY_OFFSET: Final[dict[IndeterminacyReason, int]] = {
    IndeterminacyReason.UNSPECIFIED: 0,
    IndeterminacyReason.UNRECONCILED_POSITION: 1,
    IndeterminacyReason.UNREAD_VENUE_PROFILE: 2,
    IndeterminacyReason.VENUE_PUBLISHES_NOTHING: 3,
    IndeterminacyReason.OUTSIDE_MONITORING_WINDOW: 4,
    IndeterminacyReason.NOT_APPLICABLE: 0,
}


def margin_priority_rank(impact: MarginImpact) -> int:
    """Rank a break by margin consequence. Lower sorts first.

    **These orderings are operator judgments, not derivations.** The
    reasoning is stated here so it can be argued with rather than merely
    obeyed.

    Priority tracks what can be acted upon and how fast the window closes.
    An in-cycle call carries a hard deadline today, so it leads.
    CALL_WINDOW_CLOSED ranks next because the exposure is quantified and the
    firm can still act on it - reduce, hedge, pre-fund - even though no call
    can be made or met. INDETERMINATE ranks below both because the first
    action there is investigation rather than remediation, and above every
    known cost because **unknown exposure outranks known cost**: an operator
    can plan around a quantified over-collateralisation and cannot plan
    around a position whose collateral state nobody can observe.

    An UNDER_COLLATERALIZED assessment with no call window at all is treated
    as out-of-cycle. Fail-safe cuts the other way here than it usually does:
    claiming an in-cycle deadline the framework cannot evidence would put a
    break at the top of an operator's queue on the strength of an
    assumption.
    """
    if impact.disposition is MarginDisposition.UNDER_COLLATERALIZED:
        window = impact.call_window
        in_cycle = window is not None and window.is_open
        return _UNDER_IN_CYCLE if in_cycle else _UNDER_OUT_OF_CYCLE
    if impact.disposition is MarginDisposition.INDETERMINATE:
        return _BASE_RANK[impact.disposition] + _INDETERMINACY_OFFSET[
            impact.indeterminacy
        ]
    return _BASE_RANK[impact.disposition]


def margin_sort_key(impact: MarginImpact) -> int:
    """Sort key for a break queue. Alias of :func:`margin_priority_rank`,
    named for its call site."""
    return margin_priority_rank(impact)


def sort_by_margin_consequence(
    impacts: tuple[MarginImpact, ...],
) -> tuple[MarginImpact, ...]:
    """Order breaks by margin consequence rather than by age or notional.

    Stable: equal ranks keep their input order, so the caller's own
    secondary ordering survives and the result is reproducible.
    """
    return tuple(sorted(impacts, key=margin_priority_rank))


# ---------------------------------------------------------------------------
# Gate interactions - SPEC-MARGIN-AWARE-BREAKS section 9
# ---------------------------------------------------------------------------


def margin_impact_for_clearing_fund_deficiency(
    *,
    requirement: Decimal,
    posted: Decimal,
    currency: str,
    venue: str,
    call_window: CallWindow | None = None,
) -> MarginImpact:
    """Render a clearing-fund deficiency as a margin assessment.

    Settlement Execution already produces a hold on this condition, and that
    hold has a margin consequence it does not currently state. The figures
    here come from the funding inputs the caller already holds; nothing is
    computed that was not supplied.

    Where the venue's collection window is closed, the exposure is
    quantified and simultaneously uncollectable, which is a different state
    from an ordinary under-collateralisation and gets its own disposition:
    the remedy is a position or hedging decision, not a call.
    """
    shortfall = requirement - posted
    window_shut = call_window is not None and not call_window.is_open
    disposition = (
        MarginDisposition.CALL_WINDOW_CLOSED
        if window_shut
        else MarginDisposition.UNDER_COLLATERALIZED
    )
    return MarginImpact(
        disposition=disposition,
        direction=MarginDirection.OWED_TO_VENUE,
        observability=Observability.OBSERVED,
        collateral_observability=Observability.OBSERVED,
        delta_amount=shortfall,
        delta_currency=currency,
        venue=venue,
        call_window=call_window,
        basis=(
            f"Clearing-fund posted {posted} is below requirement "
            f"{requirement} at {venue}. Both figures supplied by the venue; "
            f"no methodology was applied here "
            f"(AUR-CUSTODY-MARGIN-001 sec. 3, SPEC sec. 9)."
        ),
    )


def margin_impact_outside_monitoring_window(
    *,
    profile: VenueMarginProfile,
    exposure_note: str = "",
) -> MarginImpact:
    """Render an exposure accrued outside a venue's monitoring hours.

    The condition: the venue clears through a session it does not observe on
    its intraday cycle. The position is novated and guaranteed, the exposure
    is accruing, and the venue's own monitoring is silent until the window
    reopens.

    **What this deliberately does not return.** Not ``CALL_WINDOW_CLOSED``,
    because the collection mechanism is not shut - the position rolls into
    the next start-of-day call and that call will be made. Not
    ``UNDER_COLLATERALIZED``, because asserting a known exposure on an
    unobservable basis is exactly the combination the model refuses. What is
    absent here is observation, and the assessment says so and nothing more.

    The window is taken from the profile rather than from an argument, so
    the hours cannot be asserted at a call site. A venue whose monitoring
    arrangement has not been read raises instead of returning: that state is
    ``UNREAD_VENUE_PROFILE``, it is a research task rather than a market
    condition, and returning a monitoring-gap assessment for it would let an
    unread venue present as an assessed one.
    """
    if profile.monitoring_model is not MonitoringModel.BOUNDED_WINDOW:
        raise ValueError(
            f"a monitoring-window assessment requires a venue whose "
            f"monitoring is known to be bounded; {profile.venue_id} is "
            f"{profile.monitoring_model.value}. An unread arrangement is "
            f"UNREAD_VENUE_PROFILE, not a market condition "
            f"(AUR-CUSTODY-MARGIN-001 sec. 4)"
        )
    window = profile.monitoring_window  # required under BOUNDED_WINDOW
    note = f" {exposure_note.strip()}" if exposure_note.strip() else ""
    return MarginImpact(
        disposition=MarginDisposition.INDETERMINATE,
        direction=MarginDirection.UNKNOWN,
        observability=Observability.UNOBSERVABLE,
        # The firm's own posted collateral is a fact about the firm and is
        # observable throughout. Only the requirement moving against it is
        # not, and recording both as unobservable would overstate the gap.
        collateral_observability=Observability.OBSERVED,
        indeterminacy=IndeterminacyReason.OUTSIDE_MONITORING_WINDOW,
        venue=profile.venue_id,
        methodology=profile.model_type,
        basis=(
            f"Exposure accrued outside {profile.venue_id}'s stated monitoring "
            f"hours ({window}). The venue clears through this session and "
            f"does not observe it on its intraday cycle, so no figure is "
            f"available at this hour. Collection is unaffected: the position "
            f"rolls into the next start-of-day requirement.{note} "
            f"(AUR-CUSTODY-MARGIN-001 sec. 6; window from the venue margin "
            f"profile registry, not from this call site.)"
        ),
    )


def raises_quorum_question(
    impact: MarginImpact, *, magnitude_threshold: Decimal
) -> bool:
    """Whether a margin delta independently triggers the quorum question.

    Quorum Authority already routes on notional. A large margin delta is a
    second and independent trigger for the same routing question: an
    operation can be immaterial by notional and move a collateral
    requirement that is not.

    An assessment with no figure never triggers on this path. It escalates
    on its own disposition instead, which is the correct route - an
    unobservable exposure is a reason to investigate, not a reason to
    convene a ceremony against a number nobody has.
    """
    if impact.delta_amount is None:
        return False
    return abs(impact.delta_amount) >= magnitude_threshold
