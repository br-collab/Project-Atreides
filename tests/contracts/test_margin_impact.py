"""Tests for the margin-aware break model.

House convention: every validator carries a positive and a negative test,
and the negative tests are the point. Each one asserts that the model
refuses to record a claim it cannot support.

The load-bearing assertion in this file is that an unassessed break resolves
to INDETERMINATE and never to NO_MARGIN_EFFECT. Everything else supports it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from atreides.contracts.margin_impact import (
    CallWindow,
    IndeterminacyReason,
    MarginDirection,
    MarginDisposition,
    MarginImpact,
    Observability,
    absent_margin_assessment,
    margin_impact_for_clearing_fund_deficiency,
    margin_impact_outside_monitoring_window,
    margin_priority_rank,
    raises_quorum_question,
    sort_by_margin_consequence,
)
from atreides.contracts.margin_profile import (
    CollectionModel,
    DeterminabilityRegime,
    MonitoringModel,
    ProfileStatus,
    VenueMarginProfile,
    absent_margin_profile,
)
from atreides.rails.finality import FinalityClass

D = Decimal

BASIS = "AUR-CUSTODY-MARGIN-001 sec. 7"


def _impact(**kw: object) -> MarginImpact:
    base: dict[str, object] = {
        "disposition": MarginDisposition.UNDER_COLLATERALIZED,
        "direction": MarginDirection.OWED_TO_VENUE,
        "observability": Observability.OBSERVED,
        "collateral_observability": Observability.OBSERVED,
        "delta_amount": D("250000"),
        "delta_currency": "USD",
        "basis": BASIS,
    }
    base.update(kw)
    return MarginImpact(**base)  # type: ignore[arg-type]


def _open_window() -> CallWindow:
    return CallWindow(
        collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
        is_open=True,
        closes_at_offset_seconds=7200,
    )


def _shut_window() -> CallWindow:
    return CallWindow(
        collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
        is_open=False,
        reopens_at_offset_seconds=54000,
    )


# ---------------------------------------------------------------------------
# The fail-safe default
# ---------------------------------------------------------------------------


def test_absent_assessment_is_indeterminate() -> None:
    m = absent_margin_assessment()
    assert m.disposition is MarginDisposition.INDETERMINATE
    assert m.direction is MarginDirection.UNKNOWN
    assert m.observability is Observability.UNOBSERVABLE


def test_absent_assessment_is_never_no_margin_effect() -> None:
    """A break with no margin assessment is not a break with no margin
    impact. The framework does not infer neutrality from absence of
    evidence, exactly as it does not infer finality from the absence of a
    gate decision."""
    assert absent_margin_assessment().disposition is not (
        MarginDisposition.NO_MARGIN_EFFECT
    )


def test_absent_assessment_escalates() -> None:
    assert absent_margin_assessment().escalates is True


def test_absent_assessment_carries_its_reason() -> None:
    m = absent_margin_assessment("upstream reconciliation not run")
    assert "upstream reconciliation not run" in m.basis
    assert "never" in m.basis


# ---------------------------------------------------------------------------
# Amount and currency travel together
# ---------------------------------------------------------------------------


def test_amount_with_currency_is_accepted() -> None:
    assert _impact().delta_amount == D("250000")


def test_amount_without_currency_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires delta_currency"):
        _impact(delta_currency=None)


def test_currency_without_amount_is_rejected() -> None:
    with pytest.raises(ValidationError, match="denominates nothing"):
        _impact(
            disposition=MarginDisposition.METHODOLOGY_DEPENDENT,
            direction=MarginDirection.UNKNOWN,
            delta_amount=None,
        )


def test_currency_must_be_three_characters() -> None:
    with pytest.raises(ValidationError):
        _impact(delta_currency="DOLLARS")


# ---------------------------------------------------------------------------
# An unobservable basis asserts no exposure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disposition,direction",
    [
        (MarginDisposition.UNDER_COLLATERALIZED, MarginDirection.OWED_TO_VENUE),
        (MarginDisposition.OVER_COLLATERALIZED, MarginDirection.OWED_TO_FIRM),
        (MarginDisposition.CALL_WINDOW_CLOSED, MarginDirection.OWED_TO_VENUE),
    ],
)
def test_quantified_disposition_on_an_unobservable_basis_is_rejected(
    disposition: MarginDisposition, direction: MarginDirection
) -> None:
    """If nobody can observe the collateral state, the disposition that says
    what it is cannot be held. The correct answer is INDETERMINATE."""
    with pytest.raises(ValidationError, match="cannot be held on an UNOBSERVABLE"):
        _impact(
            disposition=disposition,
            direction=direction,
            observability=Observability.UNOBSERVABLE,
            call_window=_shut_window(),
        )


def test_derived_basis_may_carry_a_confident_disposition() -> None:
    """Derived is not a weaker verdict, it is a different provenance. A
    break can be confidently under-collateralised on a derived basis, and
    the basis is visible to whoever acts on it."""
    m = _impact(observability=Observability.DERIVED)
    assert m.disposition is MarginDisposition.UNDER_COLLATERALIZED
    assert m.observability is Observability.DERIVED


# ---------------------------------------------------------------------------
# Direction must agree with disposition
# ---------------------------------------------------------------------------


def test_under_collateralized_owed_to_firm_is_rejected() -> None:
    with pytest.raises(ValidationError, match="implies direction owed_to_venue"):
        _impact(direction=MarginDirection.OWED_TO_FIRM)


def test_over_collateralized_owed_to_venue_is_rejected() -> None:
    with pytest.raises(ValidationError, match="implies direction owed_to_firm"):
        _impact(
            disposition=MarginDisposition.OVER_COLLATERALIZED,
            direction=MarginDirection.OWED_TO_VENUE,
        )


def test_over_collateralized_owed_to_firm_is_accepted() -> None:
    m = _impact(
        disposition=MarginDisposition.OVER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_FIRM,
    )
    assert m.escalates is True


def test_no_margin_effect_must_be_neutral() -> None:
    with pytest.raises(ValidationError, match="implies direction neutral"):
        _impact(
            disposition=MarginDisposition.NO_MARGIN_EFFECT,
            direction=MarginDirection.OWED_TO_VENUE,
            delta_amount=None,
            delta_currency=None,
        )


def test_indeterminate_direction_is_unconstrained() -> None:
    """Deliberately not pinned. An unobservable state can still carry a
    direction somebody has reason to suspect, and forcing UNKNOWN would
    discard it."""
    m = _impact(
        disposition=MarginDisposition.INDETERMINATE,
        direction=MarginDirection.OWED_TO_VENUE,
        observability=Observability.UNOBSERVABLE,
        indeterminacy=IndeterminacyReason.UNSPECIFIED,
        delta_amount=None,
        delta_currency=None,
    )
    assert m.direction is MarginDirection.OWED_TO_VENUE


# ---------------------------------------------------------------------------
# CALL_WINDOW_CLOSED
# ---------------------------------------------------------------------------


def test_call_window_closed_with_a_shut_window_is_accepted() -> None:
    m = _impact(
        disposition=MarginDisposition.CALL_WINDOW_CLOSED,
        direction=MarginDirection.OWED_TO_VENUE,
        call_window=_shut_window(),
    )
    assert m.call_window is not None
    assert m.call_window.is_open is False


def test_call_window_closed_without_a_window_is_rejected() -> None:
    """Asserting a closed window without one is an inference, and the
    registry does not hold inferences."""
    with pytest.raises(ValidationError, match="requires a call_window"):
        _impact(disposition=MarginDisposition.CALL_WINDOW_CLOSED)


def test_call_window_closed_against_an_open_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="against an open window"):
        _impact(
            disposition=MarginDisposition.CALL_WINDOW_CLOSED,
            call_window=_open_window(),
        )


def test_unknown_collection_model_may_not_state_a_schedule() -> None:
    with pytest.raises(ValidationError, match="may not state a schedule"):
        CallWindow(
            collection_model=CollectionModel.UNKNOWN,
            is_open=True,
            closes_at_offset_seconds=3600,
        )


def test_unknown_collection_model_may_still_record_openness() -> None:
    """Whether the desk can call right now is observable operationally
    without the venue's published schedule."""
    w = CallWindow(is_open=False)
    assert w.collection_model is CollectionModel.UNKNOWN
    assert w.is_open is False


def test_open_window_may_not_state_a_reopen() -> None:
    with pytest.raises(ValidationError, match="does not reopen"):
        CallWindow(
            collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
            is_open=True,
            reopens_at_offset_seconds=3600,
        )


# ---------------------------------------------------------------------------
# WITHIN_TOLERANCE records its threshold
# ---------------------------------------------------------------------------


def test_within_tolerance_without_a_threshold_is_rejected() -> None:
    """"Below tolerance" with no stated tolerance is not a finding."""
    with pytest.raises(ValidationError, match="must record the threshold"):
        _impact(
            disposition=MarginDisposition.WITHIN_TOLERANCE,
            direction=MarginDirection.OWED_TO_VENUE,
            delta_amount=D("12"),
        )


def test_within_tolerance_with_a_threshold_is_accepted() -> None:
    m = _impact(
        disposition=MarginDisposition.WITHIN_TOLERANCE,
        direction=MarginDirection.OWED_TO_VENUE,
        delta_amount=D("12"),
        materiality_threshold=D("50000"),
    )
    assert m.escalates is False
    assert m.materiality_threshold == D("50000")


def test_no_default_materiality_threshold_exists() -> None:
    """A fixed default would be wrong for every firm. The model records
    which threshold was applied and supplies none of its own."""
    assert _impact().materiality_threshold is None


# ---------------------------------------------------------------------------
# INDETERMINATE and NO_MARGIN_EFFECT assert no figure
# ---------------------------------------------------------------------------


def test_indeterminate_with_a_delta_is_rejected() -> None:
    with pytest.raises(ValidationError, match="delta figure contradicts it"):
        _impact(
            disposition=MarginDisposition.INDETERMINATE,
            direction=MarginDirection.UNKNOWN,
            observability=Observability.UNOBSERVABLE,
            indeterminacy=IndeterminacyReason.UNSPECIFIED,
        )


def test_no_margin_effect_with_a_non_zero_delta_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot carry a non-zero delta"):
        _impact(
            disposition=MarginDisposition.NO_MARGIN_EFFECT,
            direction=MarginDirection.NEUTRAL,
        )


def test_no_margin_effect_with_an_explicit_zero_is_accepted() -> None:
    """Recording a measured zero is different from recording nothing."""
    m = _impact(
        disposition=MarginDisposition.NO_MARGIN_EFFECT,
        direction=MarginDirection.NEUTRAL,
        delta_amount=D("0"),
    )
    assert m.escalates is False


# ---------------------------------------------------------------------------
# Collateral finality mismatch
# ---------------------------------------------------------------------------


def test_mismatch_is_representable() -> None:
    """Collateral final on a ledger against an obligation settling on a
    cycle. A record that cannot state this cannot govern the exposure
    between them."""
    m = _impact(
        collateral_finality_class=FinalityClass.LEDGER_FINAL,
        obligation_finality_class=FinalityClass.DEFERRED_NET,
    )
    assert m.collateral_mismatch is True


def test_matching_classes_are_not_a_mismatch() -> None:
    m = _impact(
        collateral_finality_class=FinalityClass.DEFERRED_NET,
        obligation_finality_class=FinalityClass.DEFERRED_NET,
    )
    assert m.collateral_mismatch is False


def test_unrecorded_side_is_not_reported_as_a_match() -> None:
    """Absence of a record is not evidence of a match."""
    m = _impact(collateral_finality_class=FinalityClass.LEDGER_FINAL)
    assert m.collateral_mismatch is False
    assert m.obligation_finality_class is None


def test_determination_dependent_obligation_is_representable_here() -> None:
    m = _impact(
        collateral_finality_class=FinalityClass.GROSS_FINAL,
        obligation_finality_class=FinalityClass.DETERMINATION_DEPENDENT,
    )
    assert m.collateral_mismatch is True


# ---------------------------------------------------------------------------
# Prioritisation
# ---------------------------------------------------------------------------


def test_in_cycle_call_leads() -> None:
    in_cycle = _impact(call_window=_open_window())
    assert margin_priority_rank(in_cycle) == 10


def test_call_window_closed_outranks_indeterminate() -> None:
    shut = _impact(
        disposition=MarginDisposition.CALL_WINDOW_CLOSED,
        call_window=_shut_window(),
    )
    indet = absent_margin_assessment()
    assert margin_priority_rank(shut) < margin_priority_rank(indet)


def test_unknown_exposure_outranks_known_cost() -> None:
    """An operator can plan around a quantified over-collateralisation and
    cannot plan around a position whose collateral state nobody can
    observe."""
    indet = absent_margin_assessment()
    over = _impact(
        disposition=MarginDisposition.OVER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_FIRM,
    )
    assert margin_priority_rank(indet) < margin_priority_rank(over)


def test_under_collateralized_with_no_window_is_treated_as_out_of_cycle() -> None:
    """Fail-safe cuts the other way here. Claiming an in-cycle deadline the
    framework cannot evidence would put a break at the top of an operator's
    queue on an assumption."""
    no_window = _impact()
    in_cycle = _impact(call_window=_open_window())
    out_of_cycle = _impact(call_window=_shut_window())
    assert margin_priority_rank(no_window) > margin_priority_rank(in_cycle)
    assert margin_priority_rank(no_window) == margin_priority_rank(out_of_cycle)


@pytest.mark.parametrize("disposition", list(MarginDisposition))
def test_every_disposition_has_a_rank(disposition: MarginDisposition) -> None:
    """Exhaustiveness. A new disposition added without a ranking decision
    raises KeyError here rather than sorting silently to a default."""
    direction = {
        MarginDisposition.UNDER_COLLATERALIZED: MarginDirection.OWED_TO_VENUE,
        MarginDisposition.OVER_COLLATERALIZED: MarginDirection.OWED_TO_FIRM,
        MarginDisposition.NO_MARGIN_EFFECT: MarginDirection.NEUTRAL,
    }.get(disposition, MarginDirection.UNKNOWN)
    m = _impact(
        disposition=disposition,
        direction=direction,
        delta_amount=None,
        delta_currency=None,
        materiality_threshold=D("1"),
        observability=(
            Observability.UNOBSERVABLE
            if disposition is MarginDisposition.INDETERMINATE
            else Observability.OBSERVED
        ),
        call_window=(
            _shut_window()
            if disposition is MarginDisposition.CALL_WINDOW_CLOSED
            else None
        ),
        indeterminacy=(
            IndeterminacyReason.UNSPECIFIED
            if disposition is MarginDisposition.INDETERMINATE
            else IndeterminacyReason.NOT_APPLICABLE
        ),
    )
    assert isinstance(margin_priority_rank(m), int)


def test_ordering_is_a_total_order_and_stable() -> None:
    routine_a = _impact(
        disposition=MarginDisposition.NO_MARGIN_EFFECT,
        direction=MarginDirection.NEUTRAL,
        delta_amount=None,
        delta_currency=None,
        venue="A",
    )
    routine_b = _impact(
        disposition=MarginDisposition.NO_MARGIN_EFFECT,
        direction=MarginDirection.NEUTRAL,
        delta_amount=None,
        delta_currency=None,
        venue="B",
    )
    urgent = _impact(call_window=_open_window())
    ordered = sort_by_margin_consequence((routine_a, routine_b, urgent))
    assert ordered[0] is urgent
    # Equal ranks keep input order, so the caller's own secondary ordering
    # survives and the result is reproducible.
    assert ordered[1].venue == "A"
    assert ordered[2].venue == "B"


def test_sorting_is_deterministic() -> None:
    items = (
        absent_margin_assessment(),
        _impact(call_window=_open_window()),
        _impact(
            disposition=MarginDisposition.OVER_COLLATERALIZED,
            direction=MarginDirection.OWED_TO_FIRM,
        ),
    )
    assert sort_by_margin_consequence(items) == sort_by_margin_consequence(items)


# ---------------------------------------------------------------------------
# Gate interactions
# ---------------------------------------------------------------------------


def test_clearing_fund_deficiency_becomes_an_under_collateralisation() -> None:
    m = margin_impact_for_clearing_fund_deficiency(
        requirement=D("1000000"),
        posted=D("750000"),
        currency="USD",
        venue="CCP_A",
        call_window=_open_window(),
    )
    assert m.disposition is MarginDisposition.UNDER_COLLATERALIZED
    assert m.delta_amount == D("250000")
    assert m.direction is MarginDirection.OWED_TO_VENUE
    assert m.observability is Observability.OBSERVED
    assert "no methodology was applied here" in m.basis


def test_clearing_fund_deficiency_with_a_shut_window_is_uncollectable() -> None:
    """Quantified and simultaneously uncollectable. Different state, different
    remedy: a position or hedging decision, not a call."""
    m = margin_impact_for_clearing_fund_deficiency(
        requirement=D("1000000"),
        posted=D("750000"),
        currency="USD",
        venue="CCP_A",
        call_window=_shut_window(),
    )
    assert m.disposition is MarginDisposition.CALL_WINDOW_CLOSED


def test_clearing_fund_bridge_computes_no_margin_of_its_own() -> None:
    """Both figures come from the venue. The bridge subtracts; it does not
    model."""
    m = margin_impact_for_clearing_fund_deficiency(
        requirement=D("3"), posted=D("1"), currency="USD", venue="CCP_A"
    )
    assert m.delta_amount == D("2")
    assert m.methodology is None


def test_large_delta_raises_the_quorum_question() -> None:
    assert raises_quorum_question(_impact(), magnitude_threshold=D("100000")) is True


def test_small_delta_does_not() -> None:
    assert raises_quorum_question(_impact(), magnitude_threshold=D("500000")) is False


def test_direction_does_not_change_the_quorum_trigger() -> None:
    """Magnitude is magnitude. An over-collateralisation of the same size
    raises the same routing question."""
    over = _impact(
        disposition=MarginDisposition.OVER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_FIRM,
    )
    assert raises_quorum_question(over, magnitude_threshold=D("100000")) is True


def test_an_unfigured_assessment_never_triggers_quorum() -> None:
    """An unobservable exposure is a reason to investigate, not a reason to
    convene a ceremony against a number nobody has. It escalates on its own
    disposition instead."""
    m = absent_margin_assessment()
    assert raises_quorum_question(m, magnitude_threshold=D("1")) is False
    assert m.escalates is True


# ---------------------------------------------------------------------------
# Immutability and determinism
# ---------------------------------------------------------------------------


def test_impact_is_frozen() -> None:
    """A reassessment appends a new record with its own offset; the earlier
    assessment stays visible, because how the picture changed through the day
    is itself evidence."""
    m = _impact()
    with pytest.raises(ValidationError):
        m.disposition = MarginDisposition.NO_MARGIN_EFFECT  # type: ignore[misc]


def test_identical_inputs_produce_identical_records() -> None:
    a = _impact(assessed_at_offset_seconds=3600)
    b = _impact(assessed_at_offset_seconds=3600)
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _impact(predicted_margin=D("1000"))


def test_basis_is_required() -> None:
    with pytest.raises(ValidationError):
        _impact(basis="")


# ---------------------------------------------------------------------------
# Deliberate absence
# ---------------------------------------------------------------------------


def test_no_test_asserts_a_predicted_margin_figure() -> None:
    """Placeholder marking a deliberate absence.

    There is no forecast in this module and no test of one. A reader looking
    for predictive coverage should find this note instead of a gap.
    Doctrine: AUR-CUSTODY-MARGIN-001 sec. 2.
    """
    assert not hasattr(MarginImpact, "predict_margin")
    assert not any("predict" in name for name in MarginImpact.model_fields)


def test_the_sort_key_is_the_priority_rank() -> None:
    """Two names for one function, so a call site can read as what it is
    doing rather than as what the function is called."""
    from atreides.contracts.margin_impact import margin_sort_key

    m = _impact()
    assert margin_sort_key(m) == margin_priority_rank(m)


# ---------------------------------------------------------------------------
# Why it is indeterminate, and what that does to the queue
# ---------------------------------------------------------------------------


def _indeterminate(reason: IndeterminacyReason) -> MarginImpact:
    return absent_margin_assessment("volume test", reason)


def test_an_indeterminate_assessment_must_say_why() -> None:
    """UNSPECIFIED is a valid answer. NOT_APPLICABLE is not, because the
    reasons carry three different remedies and a break that names none of
    them cannot be routed to anybody."""
    with pytest.raises(ValidationError, match="must say why it is"):
        _impact(
            disposition=MarginDisposition.INDETERMINATE,
            direction=MarginDirection.UNKNOWN,
            observability=Observability.UNOBSERVABLE,
            delta_amount=None,
            delta_currency=None,
            indeterminacy=IndeterminacyReason.NOT_APPLICABLE,
        )


def test_a_reason_on_a_determinate_disposition_is_rejected() -> None:
    with pytest.raises(ValidationError, match="meaningful only where"):
        _impact(indeterminacy=IndeterminacyReason.UNREAD_VENUE_PROFILE)


def test_the_indeterminate_band_now_has_an_internal_order() -> None:
    """The defect this exists to fix: five hundred unassessed breaks used to
    share one rank, so the queue had no ordering in the state the framework
    actually ships in."""
    ranks = [
        margin_priority_rank(_indeterminate(r))
        for r in (
            IndeterminacyReason.UNSPECIFIED,
            IndeterminacyReason.UNRECONCILED_POSITION,
            IndeterminacyReason.UNREAD_VENUE_PROFILE,
            IndeterminacyReason.VENUE_PUBLISHES_NOTHING,
        )
    ]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


def test_triage_leads_the_indeterminate_band() -> None:
    """A break nobody has classified cannot be routed to anybody, and triage
    is both the fastest action available and the one that unblocks the
    rest."""
    unspecified = margin_priority_rank(_indeterminate(IndeterminacyReason.UNSPECIFIED))
    for other in (
        IndeterminacyReason.UNRECONCILED_POSITION,
        IndeterminacyReason.UNREAD_VENUE_PROFILE,
        IndeterminacyReason.VENUE_PUBLISHES_NOTHING,
    ):
        assert unspecified < margin_priority_rank(_indeterminate(other))


def test_a_standing_condition_trails_every_work_item() -> None:
    """A venue that publishes nothing is a risk acceptance already taken.
    There is no work item, so it must not sit above breaks that have one."""
    standing = margin_priority_rank(
        _indeterminate(IndeterminacyReason.VENUE_PUBLISHES_NOTHING)
    )
    for actionable in (
        IndeterminacyReason.UNSPECIFIED,
        IndeterminacyReason.UNRECONCILED_POSITION,
        IndeterminacyReason.UNREAD_VENUE_PROFILE,
    ):
        assert standing > margin_priority_rank(_indeterminate(actionable))


# ---------------------------------------------------------------------------
# Seen versus collected: the extended-hours condition
#
# A venue can clear through a session it does not observe on its intraday
# cycle. The exposure is real, accruing, and fully collectable at the next
# start of day. The framework's job is to hold all three of those at once
# without turning any of them into the others.
# ---------------------------------------------------------------------------


def _bounded_venue(**kw: object) -> VenueMarginProfile:
    base: dict[str, object] = {
        "venue_id": "CCP-EQ",
        "status": ProfileStatus.POPULATED,
        "model_type": "Portfolio VaR with discretionary add-ons",
        "determinability": DeterminabilityRegime.DISCRETIONARY,
        "collection_model": CollectionModel.TRADITIONAL_HOURS_ONLY,
        "monitoring_model": MonitoringModel.BOUNDED_WINDOW,
        "monitoring_window": "15-minute cycle, 06:00-23:00 venue local time",
        "provenance": "Venue clearing rulebook, intraday risk monitoring",
    }
    base.update(kw)
    return VenueMarginProfile(**base)  # type: ignore[arg-type]


def test_a_monitoring_gap_is_not_a_closed_call_window() -> None:
    """The distinction the whole addition rests on. CALL_WINDOW_CLOSED says
    the exposure is quantified and nobody can collect it. Here the exposure
    is not quantified and collection is unaffected - the position rolls into
    a start-of-day call that will be made. Returning CALL_WINDOW_CLOSED
    would report an uncollectable exposure where none exists."""
    impact = margin_impact_outside_monitoring_window(profile=_bounded_venue())
    assert impact.disposition is not MarginDisposition.CALL_WINDOW_CLOSED
    assert impact.disposition is MarginDisposition.INDETERMINATE
    assert impact.call_window is None


def test_a_monitoring_gap_asserts_no_exposure_figure() -> None:
    """Asserting a known exposure on an unobservable basis is the exact
    combination the model refuses elsewhere. This constructor must not be
    the back door into it."""
    impact = margin_impact_outside_monitoring_window(profile=_bounded_venue())
    assert impact.observability is Observability.UNOBSERVABLE
    assert impact.delta_amount is None
    assert impact.direction is MarginDirection.UNKNOWN


def test_the_firms_own_collateral_stays_observable() -> None:
    """What the firm posted is a fact about the firm. Only the requirement
    moving against it is unobservable, and recording both as unobservable
    would overstate the gap."""
    impact = margin_impact_outside_monitoring_window(profile=_bounded_venue())
    assert impact.collateral_observability is Observability.OBSERVED


def test_the_window_comes_from_the_profile_and_not_the_call_site() -> None:
    impact = margin_impact_outside_monitoring_window(profile=_bounded_venue())
    assert "06:00-23:00 venue local time" in impact.basis
    assert impact.venue == "CCP-EQ"


def test_an_unread_venue_cannot_claim_a_monitoring_gap() -> None:
    """The refusal that keeps this honest. An unread monitoring arrangement
    is a research task - UNREAD_VENUE_PROFILE - and letting it return a
    monitoring-gap assessment would have an unread venue present as an
    assessed one."""
    with pytest.raises(ValueError, match="UNREAD_VENUE_PROFILE"):
        margin_impact_outside_monitoring_window(
            profile=absent_margin_profile("CCP-EQ")
        )


def test_a_continuously_monitored_venue_cannot_claim_a_monitoring_gap() -> None:
    with pytest.raises(ValueError, match="monitoring is known to be bounded"):
        margin_impact_outside_monitoring_window(
            profile=_bounded_venue(
                monitoring_model=MonitoringModel.CONTINUOUS,
                monitoring_window=None,
            )
        )


def test_a_monitoring_gap_still_outranks_every_known_cost() -> None:
    """Sub-ranking must not leak across the band boundary. The least urgent
    unknown still beats the most urgent known one."""
    impact = margin_impact_outside_monitoring_window(profile=_bounded_venue())
    known = _impact(
        disposition=MarginDisposition.UNDER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_VENUE,
    )
    assert margin_priority_rank(impact) < margin_priority_rank(known)


def test_a_scheduled_wait_ranks_below_every_reason_that_names_work() -> None:
    """The debatable ordering, asserted so the debate is visible. Every
    other reason in the band names something somebody could start now; this
    one names a wait that ends at an hour the venue has published."""
    scheduled = margin_priority_rank(
        _indeterminate(IndeterminacyReason.OUTSIDE_MONITORING_WINDOW)
    )
    for other in (
        IndeterminacyReason.UNSPECIFIED,
        IndeterminacyReason.UNRECONCILED_POSITION,
        IndeterminacyReason.UNREAD_VENUE_PROFILE,
        IndeterminacyReason.VENUE_PUBLISHES_NOTHING,
    ):
        assert scheduled > margin_priority_rank(_indeterminate(other))


def test_every_indeterminacy_reason_has_a_distinct_rank() -> None:
    """The defect the sub-rank exists to fix does not come back one member
    at a time."""
    ranks = [
        margin_priority_rank(_indeterminate(r))
        for r in IndeterminacyReason
        if r is not IndeterminacyReason.NOT_APPLICABLE
    ]
    assert len(set(ranks)) == len(ranks)


def test_the_whole_indeterminate_band_still_outranks_every_known_cost() -> None:
    """Sub-ranking must not leak across the band boundary. Unknown exposure
    outranks known cost, and the least urgent unknown still beats the most
    urgent known one."""
    worst_unknown = margin_priority_rank(
        _indeterminate(IndeterminacyReason.VENUE_PUBLISHES_NOTHING)
    )
    over = _impact(
        disposition=MarginDisposition.OVER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_FIRM,
    )
    assert worst_unknown < margin_priority_rank(over)


def test_sub_ranking_does_not_repair_a_wholly_unassessed_queue() -> None:
    """Stated as a test because the honest limit matters more than the fix.

    Where nobody has assessed anything, every break is UNSPECIFIED and the
    queue is still flat. That is correct: there is no information to order
    by, and manufacturing one would be worse than a flat queue. What changed
    is that triage now has somewhere to put its answer.
    """
    queue = tuple(absent_margin_assessment(f"break {i}") for i in range(50))
    assert len({margin_priority_rank(m) for m in queue}) == 1
    triaged = queue[:1] + tuple(
        absent_margin_assessment(f"break {i}", IndeterminacyReason.UNREAD_VENUE_PROFILE)
        for i in range(1, 50)
    )
    assert len({margin_priority_rank(m) for m in triaged}) == 2


# ---------------------------------------------------------------------------
# WITHIN_TOLERANCE must actually be within it
# ---------------------------------------------------------------------------


def test_a_delta_above_its_own_threshold_is_refused() -> None:
    """The one contradiction this model's own disposition name asserts, and
    the only cross-field check it was missing. A billion against a threshold
    of one used to construct, report escalates=False, and sort to the bottom
    of the queue."""
    with pytest.raises(ValidationError, match="asserts a delta below"):
        _impact(
            disposition=MarginDisposition.WITHIN_TOLERANCE,
            direction=MarginDirection.NEUTRAL,
            delta_amount=D("1000000000"),
            delta_currency="USD",
            materiality_threshold=D("1"),
        )


def test_a_delta_below_its_threshold_is_accepted() -> None:
    impact = _impact(
        disposition=MarginDisposition.WITHIN_TOLERANCE,
        direction=MarginDirection.NEUTRAL,
        delta_amount=D("12"),
        delta_currency="USD",
        materiality_threshold=D("50000"),
    )
    assert impact.escalates is False


def test_a_delta_exactly_at_the_threshold_is_within_it() -> None:
    """Stated rather than left to a reader: the boundary is inclusive, on the
    same reasoning as every other threshold in this framework."""
    impact = _impact(
        disposition=MarginDisposition.WITHIN_TOLERANCE,
        direction=MarginDirection.NEUTRAL,
        delta_amount=D("500"),
        delta_currency="USD",
        materiality_threshold=D("500"),
    )
    assert impact.disposition is MarginDisposition.WITHIN_TOLERANCE


def test_the_magnitude_is_compared_not_the_sign() -> None:
    """A large negative delta is as material as a large positive one."""
    with pytest.raises(ValidationError, match="asserts a delta below"):
        _impact(
            disposition=MarginDisposition.WITHIN_TOLERANCE,
            direction=MarginDirection.NEUTRAL,
            delta_amount=D("-1000000"),
            delta_currency="USD",
            materiality_threshold=D("100"),
        )


def test_an_unfigured_tolerance_assessment_is_left_alone() -> None:
    """The guarded half of the comparison. Where no delta was supplied there
    is nothing to compare, and inventing one would be worse than not
    checking."""
    impact = _impact(
        disposition=MarginDisposition.WITHIN_TOLERANCE,
        direction=MarginDirection.NEUTRAL,
        delta_amount=None,
        delta_currency=None,
        materiality_threshold=D("50000"),
    )
    assert impact.delta_amount is None
