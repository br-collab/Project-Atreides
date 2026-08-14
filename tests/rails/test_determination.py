"""Tests for determination dependence — the fifth finality class.

Two things this file is built to hold.

The first is the answer to the question that blocked implementation: how
long a determined outcome stays qualified. The answer is that the venue
decides, the framework records, and an unbounded window is recorded as
unbounded rather than converted into a finality timestamp. The tests that
carry that answer are grouped under "the duration question".

The second is exhaustiveness. Adding a member to ``FinalityClass`` or to
``DeterminationOutcome`` must break this file until somebody decides what
the new member means, rather than falling through to a default.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from atreides.rails.cato_f import (
    RAIL_FINALITY,
    CashRail,
    FinalityClass,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)
from atreides.rails.determination import (
    DeterminationOutcome,
    DeterminationProfile,
    RevocationForm,
    absent_determination_profile,
    classify_determination,
    obligation_finality_class,
)
from atreides.rails.funding_state import (
    CashFlow,
    FundingDisposition,
    FundingInputs,
    project_funding,
)

D = Decimal

CITATION = "Venue rulebook, emergency authority provision, read 14 Aug 2026"


def _profile(**kw: object) -> DeterminationProfile:
    base: dict[str, object] = {
        "venue_id": "VENUE_A",
        "revocation_form": RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
        "provenance": CITATION,
    }
    base.update(kw)
    return DeterminationProfile(**base)  # type: ignore[arg-type]


def _classify(**kw: object) -> DeterminationOutcome:
    base: dict[str, object] = {
        "profile": _profile(),
        "instrument_is_contingent": True,
        "determined": True,
    }
    base.update(kw)
    return classify_determination(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Registry discipline — the profile refuses what it cannot attribute
# ---------------------------------------------------------------------------


def test_absent_profile_is_not_assessed_and_asserts_nothing() -> None:
    p = absent_determination_profile("VENUE_UNKNOWN")
    assert p.revocation_form is RevocationForm.NOT_ASSESSED
    assert p.qualification_window_seconds is None
    assert p.provenance is None
    assert p.reverses_settlement is False


def test_assessed_profile_without_provenance_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires provenance"):
        DeterminationProfile(
            venue_id="VENUE_A",
            revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
        )


def test_unassessed_profile_may_not_state_a_window() -> None:
    """You cannot record a bound you have not read."""
    with pytest.raises(ValueError, match="may not state a qualification window"):
        DeterminationProfile(venue_id="VENUE_A", qualification_window_seconds=3600)


def test_non_positive_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _profile(qualification_window_seconds=0)


def test_profile_is_frozen() -> None:
    p = absent_determination_profile("VENUE_A")
    with pytest.raises(FrozenInstanceError):
        p.venue_id = "VENUE_B"  # type: ignore[misc]


def test_not_assessed_is_distinct_from_none_disclosed() -> None:
    """The distinction is the point.

    "We have not read this venue's rulebook" and "we read it and it grants
    no cancellation power" get the same conservative posture and completely
    different remedies. Collapsing them would let an unread venue pass as a
    clean one.
    """
    unread = absent_determination_profile("VENUE_A")
    read_and_clean = _profile(revocation_form=RevocationForm.NONE_DISCLOSED)

    assert unread.revocation_form is not read_and_clean.revocation_form
    assert _classify(profile=unread) is DeterminationOutcome.QUALIFICATION_UNKNOWN
    assert _classify(profile=read_and_clean) is DeterminationOutcome.UNQUALIFIED


# ---------------------------------------------------------------------------
# The form of the authority decides, not its existence
# ---------------------------------------------------------------------------


def test_administered_price_liquidation_does_not_produce_dependence() -> None:
    """The narrow claim the verification pass earned.

    Cross-venue reading found broad emergency authority at every designated
    contract market examined, including the power to establish the price at
    which contracts are liquidated. That preserves settlement: the payment
    happened and stays happened, and the exposure is a valuation exposure
    that belongs to margin. Only cancellation-and-return reverses the
    settlement itself.
    """
    administered = _profile(
        revocation_form=RevocationForm.LIQUIDATION_AT_ADMINISTERED_PRICE
    )
    assert administered.reverses_settlement is False
    assert _classify(profile=administered) is DeterminationOutcome.UNQUALIFIED
    assert obligation_finality_class(_classify(profile=administered)) is None


def test_cancellation_and_return_does_produce_dependence() -> None:
    outcome = _classify(profile=_profile())
    assert outcome is DeterminationOutcome.QUALIFIED_UNBOUNDED
    assert (
        obligation_finality_class(outcome) is FinalityClass.DETERMINATION_DEPENDENT
    )


def test_revocability_alone_is_not_the_discriminator() -> None:
    """Both forms are emergency authority. They classify differently."""
    administered = _classify(
        profile=_profile(
            revocation_form=RevocationForm.LIQUIDATION_AT_ADMINISTERED_PRICE
        )
    )
    cancelling = _classify(profile=_profile())
    assert administered is not cancelling


# ---------------------------------------------------------------------------
# The duration question
# ---------------------------------------------------------------------------


def test_no_stated_bound_stays_qualified_and_says_so() -> None:
    """The load-bearing answer.

    Emergency and force-majeure authority in the rulebooks examined is
    written as a standing power with no expiry. The framework records that
    as QUALIFIED_UNBOUNDED. It does not invent an expiry, and it does not
    give up and call the position final.
    """
    outcome = _classify(profile=_profile(qualification_window_seconds=None))
    assert outcome is DeterminationOutcome.QUALIFIED_UNBOUNDED
    assert outcome is not DeterminationOutcome.UNQUALIFIED


def test_stated_bound_not_yet_elapsed_is_qualified() -> None:
    outcome = _classify(
        profile=_profile(qualification_window_seconds=86400),
        seconds_since_determination=3600,
    )
    assert outcome is DeterminationOutcome.QUALIFIED_BOUNDED


def test_stated_bound_elapsed_is_the_only_path_to_finality() -> None:
    outcome = _classify(
        profile=_profile(qualification_window_seconds=86400),
        seconds_since_determination=86400,
    )
    assert outcome is DeterminationOutcome.UNQUALIFIED


def test_elapsed_time_not_supplied_stays_qualified() -> None:
    """The module has no clock and will not invent one.

    A caller who does not supply elapsed time gets the conservative answer,
    never the assumption that the window has run.
    """
    outcome = _classify(
        profile=_profile(qualification_window_seconds=1),
        seconds_since_determination=None,
    )
    assert outcome is DeterminationOutcome.QUALIFIED_BOUNDED


def test_bounded_and_unbounded_are_not_collapsed() -> None:
    """A venue that publishes a contest window and one that publishes none
    are materially different counterparties. Making that visible is the
    whole value of the class."""
    bounded = _classify(profile=_profile(qualification_window_seconds=86400))
    unbounded = _classify(profile=_profile())
    assert bounded is not unbounded
    assert obligation_finality_class(bounded) is obligation_finality_class(unbounded)


# ---------------------------------------------------------------------------
# Ordering and scope of the classifier
# ---------------------------------------------------------------------------


def test_non_contingent_instrument_is_out_of_scope_entirely() -> None:
    outcome = _classify(instrument_is_contingent=False, profile=_profile())
    assert outcome is DeterminationOutcome.NOT_APPLICABLE
    assert obligation_finality_class(outcome) is None


def test_undetermined_outranks_the_profile() -> None:
    """An outcome that has not been determined is undetermined regardless of
    what the rulebook says about revoking determinations not yet made."""
    assert (
        _classify(determined=False, profile=absent_determination_profile("V"))
        is DeterminationOutcome.AWAITING_DETERMINATION
    )
    assert (
        _classify(determined=False, profile=_profile())
        is DeterminationOutcome.AWAITING_DETERMINATION
    )


def test_classification_is_deterministic() -> None:
    kw = {"profile": _profile(qualification_window_seconds=600)}
    assert _classify(**kw, seconds_since_determination=59) == _classify(
        **kw, seconds_since_determination=59
    )


# ---------------------------------------------------------------------------
# Exhaustiveness — the sweep this class exists to force
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", list(DeterminationOutcome))
def test_every_outcome_maps_to_a_decided_finality_class(
    outcome: DeterminationOutcome,
) -> None:
    result = obligation_finality_class(outcome)
    assert result is None or result is FinalityClass.DETERMINATION_DEPENDENT


def test_no_rail_maps_to_determination_dependent() -> None:
    """A deliberate absence, asserted rather than assumed.

    DETERMINATION_DEPENDENT is a class of the obligation. The money leg of
    a contingent-payout settlement runs on an ordinary rail with that
    rail's ordinary finality. Adding a pseudo-rail to carry it would put a
    property of the instrument into the table that answers how money moves.
    """
    assert FinalityClass.DETERMINATION_DEPENDENT not in set(RAIL_FINALITY.values())


def test_every_rail_still_maps_to_a_finality_class() -> None:
    """The original invariant, unweakened by the addition."""
    for rail in CashRail:
        assert rail in RAIL_FINALITY


# ---------------------------------------------------------------------------
# Funding model
# ---------------------------------------------------------------------------


def _funding(**kw: object) -> FundingInputs:
    base: dict[str, object] = {
        "opening_position": D("10000000"),
        "obligation": D("1000000"),
        "finality_class": FinalityClass.GROSS_FINAL,
        "settlement_offset_seconds": 3600,
        "window_close_offset_seconds": 14400,
        "net_debit_cap": D("50000000"),
        "clearing_fund_requirement": D("500000"),
        "clearing_fund_posted": D("500000"),
    }
    base.update(kw)
    return FundingInputs(**base)  # type: ignore[arg-type]


def test_determination_dependent_as_a_rail_class_is_refused() -> None:
    """A category error, caught rather than defaulted.

    Without this branch the if-ladder falls through to gross-final
    treatment and a contingent obligation silently acquires queue
    semantics.
    """
    p = project_funding(
        _funding(finality_class=FinalityClass.DETERMINATION_DEPENDENT)
    )
    assert p.disposition is FundingDisposition.INDETERMINATE
    assert "obligation-level" in p.rationale


def test_awaiting_determination_refuses_to_project() -> None:
    p = project_funding(
        _funding(determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION)
    )
    assert p.disposition is FundingDisposition.INDETERMINATE
    assert p.settles is False
    assert p.is_failure is False


def test_awaiting_determination_outranks_correspondent_indeterminacy() -> None:
    """Both refuse. The nearer cause is reported, and the rationale must
    name which refusal applied so the remedy is not guessed at."""
    p = project_funding(
        _funding(
            finality_class=FinalityClass.CORRESPONDENT_DEPENDENT,
            determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION,
        )
    )
    assert p.disposition is FundingDisposition.INDETERMINATE
    assert "awaiting outcome determination" in p.rationale
    assert "Correspondent-dependent" not in p.rationale


@pytest.mark.parametrize(
    "outcome",
    [
        DeterminationOutcome.QUALIFIED_BOUNDED,
        DeterminationOutcome.QUALIFIED_UNBOUNDED,
        DeterminationOutcome.QUALIFICATION_UNKNOWN,
    ],
)
def test_funded_against_a_revocable_entitlement_is_qualified(
    outcome: DeterminationOutcome,
) -> None:
    p = project_funding(_funding(determination_outcome=outcome))
    assert p.disposition is FundingDisposition.FUNDED_QUALIFIED
    assert p.qualified is True
    assert p.settles is True
    assert p.is_failure is False
    assert p.determination_outcome is outcome


def test_qualified_funding_on_a_deferred_net_rail_is_also_qualified() -> None:
    """The downgrade is written once, so it cannot be applied on the
    gross-final path and forgotten on the deferred-net one."""
    p = project_funding(
        _funding(
            finality_class=FinalityClass.DEFERRED_NET,
            opening_position=D("0"),
            flows=(CashFlow(10800, D("1000000"), "late inflow"),),
            determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED,
        )
    )
    assert p.disposition is FundingDisposition.FUNDED_QUALIFIED


def test_a_qualification_never_improves_a_failure() -> None:
    """A shortfall is a shortfall whether or not the venue can later cancel
    the contract. Marking a failure "qualified" would dilute a disposition
    that is already correct."""
    p = project_funding(
        _funding(
            opening_position=D("0"),
            finality_class=FinalityClass.LEDGER_FINAL,
            determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED,
        )
    )
    assert p.disposition is FundingDisposition.WILL_FAIL


def test_unqualified_determination_funds_normally() -> None:
    p = project_funding(
        _funding(determination_outcome=DeterminationOutcome.UNQUALIFIED)
    )
    assert p.disposition is FundingDisposition.FUNDED


def test_default_is_not_applicable_so_nothing_pre_existing_changes() -> None:
    plain = project_funding(_funding())
    assert plain.determination_outcome is DeterminationOutcome.NOT_APPLICABLE
    assert plain.disposition is FundingDisposition.FUNDED


def test_qualified_receipt_is_not_a_failure_and_not_free_cash() -> None:
    """The sentence this disposition exists to make true.

    The direct analogue of "a queued payment is not a failed payment": a
    qualified receipt is not a failed settlement, and it is also not money
    the firm may spend.
    """
    p = project_funding(
        _funding(determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED)
    )
    assert p.is_failure is False
    assert p.settles is True
    assert p.disposition is not FundingDisposition.FUNDED
    assert "NOT netted here" in p.rationale


# ---------------------------------------------------------------------------
# CATO-F gate
# ---------------------------------------------------------------------------


def _rails() -> dict[CashRail, RailState]:
    return {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }


def _op(**kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": D("100000"),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _gate(operation: OperationContext):
    return evaluate(
        operation=operation,
        funding=FundingState(D("10000000"), D("100000"), D("50000000"), True),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )


def test_gate_holds_on_pending_determination() -> None:
    d = _gate(_op(determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION))
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.DETERMINATION_PENDING
    assert "premature, not unsafe" in d.rationale


def test_gate_holds_on_unassessed_revocation_authority() -> None:
    d = _gate(_op(determination_outcome=DeterminationOutcome.QUALIFICATION_UNKNOWN))
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.UNASSESSED_REVOCATION_AUTHORITY
    assert "Unknown finality is not acceptable finality" in d.rationale


@pytest.mark.parametrize(
    "outcome",
    [
        DeterminationOutcome.QUALIFIED_BOUNDED,
        DeterminationOutcome.QUALIFIED_UNBOUNDED,
    ],
)
def test_gate_proceeds_on_a_qualified_determination(
    outcome: DeterminationOutcome,
) -> None:
    """Contingent markets settle every day. A gate that refused them would
    be describing a market that does not exist. The qualification is a
    disclosure, not a hold."""
    d = _gate(_op(determination_outcome=outcome))
    assert d.decision is GateDecision.PROCEED
    assert d.reason_code is ReasonCode.CLEARED
    assert "DETERMINATION_DEPENDENT" in d.rationale


def test_decision_carries_both_finality_classes() -> None:
    """The structural point: the money is final on its rail and the
    entitlement to it is not. One field cannot say both."""
    d = _gate(_op(determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED))
    assert d.finality_class is FinalityClass.GROSS_FINAL
    assert d.obligation_finality_class is FinalityClass.DETERMINATION_DEPENDENT


def test_rail_finality_field_meaning_is_unchanged_for_ordinary_operations() -> None:
    """Replay comparability. Records written before this class existed must
    still mean what they meant."""
    d = _gate(_op())
    assert d.finality_class is FinalityClass.GROSS_FINAL
    assert d.obligation_finality_class is None


def test_determination_outcome_is_recorded_in_checks_evaluated() -> None:
    """A decision that cannot be replayed from its recorded inputs is not a
    governed decision, so the new input joins the recorded set."""
    d = _gate(_op(determination_outcome=DeterminationOutcome.QUALIFIED_BOUNDED))
    assert ("determination_outcome", "qualified_bounded") in d.checks_evaluated


def test_hard_checks_still_outrank_determination() -> None:
    """Check ordering is doctrine. Systemic stress escalates whether or not
    the obligation is contingent."""
    d = evaluate(
        operation=_op(
            determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION
        ),
        funding=FundingState(D("10000000"), D("100000"), D("50000000"), True),
        rails=_rails(),
        ofr_stlfsi4=1.5,
    )
    assert d.reason_code is ReasonCode.SYSTEMIC_STRESS_ESCALATE


# ---------------------------------------------------------------------------
# Deliberate absence
# ---------------------------------------------------------------------------


def test_no_test_asserts_a_venue_will_or_will_not_exercise_its_authority() -> None:
    """Placeholder marking a deliberate absence.

    The framework records that authority exists and in what form. It makes
    no prediction about whether a venue will use it, and there is no test
    of one. A reader looking for that coverage should find this note rather
    than a gap. Doctrine: CASH-001 SIV, determination dependence.
    """
    assert not hasattr(DeterminationProfile, "probability_of_revocation")


def test_venue_id_is_required() -> None:
    with pytest.raises(ValueError, match="venue_id is required"):
        DeterminationProfile(venue_id="")
