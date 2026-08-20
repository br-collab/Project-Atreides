"""Tests for the continuous net settlement rail.

The load-bearing assertion in this file is that no trade fails in a netted
system. The net position fails, and the framework refuses to say which
underlying trade caused it. Everything else supports that refusal or tests
the fail-handling it makes necessary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.rails import cns
from atreides.rails.cns import (
    CNS_FINALITY,
    CloseOutRegime,
    CNSDisposition,
    MarketProfile,
    NetSettlementResult,
    ProcessingDateRule,
    SecuritiesBreak,
    SecuritiesBreakCode,
    absent_market_profile,
    absent_processing_date,
    absent_trade_attribution,
    close_out_deadline,
    net_positions,
    processing_date_offset,
    settle_net_position,
)
from atreides.rails.finality import FinalityClass

D = Decimal

CITATION = "Market rulebook, settlement and close-out provisions, read Aug 2026"


def _profile(**kw: object) -> MarketProfile:
    base: dict[str, object] = {
        "market_id": "XCLR",
        "settlement_cycle_days": 1,
        "close_out_regime": CloseOutRegime.MANDATORY_DEADLINE,
        "close_out_deadline_days": 3,
        "allocation_rule_published": True,
        "provenance": CITATION,
    }
    base.update(kw)
    return MarketProfile(**base)  # type: ignore[arg-type]


def _position(quantity: Decimal | None = None, **kw: object):
    quantity = D("1000") if quantity is None else quantity
    positions = net_positions(
        ((str(kw.get("security_id", "SEC-A")), quantity),),
        market_id="XCLR",
        settlement_date_offset_days=int(kw.get("settlement_date_offset_days", 1)),
    )
    return positions[0]


# ---------------------------------------------------------------------------
# The refusal this module is built around
# ---------------------------------------------------------------------------


def test_there_is_no_trade_level_fail_attribution_api() -> None:
    """Novation and netting destroyed the trade-to-obligation
    correspondence before settlement ran. Any per-trade attribution would be
    an inference presented as an observation."""
    assert not any(
        "attribute_fail_to_trade" in name or name.startswith("fail_for_trade")
        for name in dir(cns)
    )


def test_the_refusal_is_stated_rather_than_implied() -> None:
    text = absent_trade_attribution("SEC-A")
    assert "No trade failed in SEC-A" in text
    assert "The net position failed" in text
    assert "inference presented as an observation" in text


def test_constituent_trade_count_is_recorded_and_never_attributed() -> None:
    """The count is on the record for the record's sake. It is not a handle
    for working backward to a culprit."""
    positions = net_positions(
        (("SEC-A", D("600")), ("SEC-A", D("-100")), ("SEC-A", D("500"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )
    assert positions[0].constituent_trade_count == 3
    assert positions[0].quantity == D("1000")


# ---------------------------------------------------------------------------
# Netting
# ---------------------------------------------------------------------------


def test_netting_is_order_independent() -> None:
    trades = (("SEC-A", D("100")), ("SEC-B", D("-50")), ("SEC-A", D("-30")))
    a = net_positions(trades, market_id="XCLR", settlement_date_offset_days=1)
    b = net_positions(
        tuple(reversed(trades)), market_id="XCLR", settlement_date_offset_days=1
    )
    assert a == b


def test_positions_are_ordered_by_security_identifier() -> None:
    result = net_positions(
        (("SEC-Z", D("1")), ("SEC-A", D("1"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )
    assert [p.security_id for p in result] == ["SEC-A", "SEC-Z"]


def test_an_un_novated_trade_produces_no_position_at_all() -> None:
    """Manufacturing a position so the shape looks familiar would assert a
    settlement mechanism that does not occur."""
    assert (
        net_positions(
            (("SEC-A", D("100")),),
            market_id="XCLR",
            settlement_date_offset_days=1,
            novated=False,
        )
        == ()
    )


def test_every_position_carries_the_deferred_net_finality_class() -> None:
    assert _position().finality_class is FinalityClass.DEFERRED_NET
    assert CNS_FINALITY is FinalityClass.DEFERRED_NET


def test_direction_is_readable_from_the_signed_quantity() -> None:
    assert _position(D("100")).is_receive is True
    assert _position(D("-100")).is_deliver is True


# ---------------------------------------------------------------------------
# Fail-safe
# ---------------------------------------------------------------------------


def test_no_reported_outcome_is_indeterminate_never_settled() -> None:
    """A position with no reported outcome is not a settled position."""
    r = settle_net_position(_position(), _profile(), allocated_quantity=None)
    assert r.disposition is CNSDisposition.INDETERMINATE
    assert r.completed is False
    assert r.is_fail is False
    assert [b.code for b in r.breaks] == [SecuritiesBreakCode.OUTCOME_NOT_REPORTED]


def test_the_fail_safe_check_runs_first() -> None:
    """Ordered ahead of the flat check deliberately: a flat position with no
    reported outcome is still an unreported outcome."""
    flat = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    r = settle_net_position(flat, _profile(), allocated_quantity=None)
    assert r.disposition is CNSDisposition.INDETERMINATE


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------


def test_full_settlement() -> None:
    r = settle_net_position(_position(), _profile(), allocated_quantity=D("1000"))
    assert r.disposition is CNSDisposition.SETTLED_IN_FULL
    assert r.completed is True
    assert r.residual is None
    assert r.breaks == ()


def test_flat_position_settles_nothing_and_fails_nothing() -> None:
    flat = net_positions(
        (("SEC-A", D("400")), ("SEC-A", D("-400"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    r = settle_net_position(flat, _profile(), allocated_quantity=D("0"))
    assert r.disposition is CNSDisposition.FLAT
    assert r.completed is True
    assert r.is_fail is False


def test_partial_allocation_is_not_completion() -> None:
    """Something moved and the residual is a live obligation. Treating the
    day as done is how a residual gets dropped."""
    r = settle_net_position(_position(), _profile(), allocated_quantity=D("400"))
    assert r.disposition is CNSDisposition.PARTIAL_ALLOCATION
    assert r.completed is False
    assert r.residual is not None
    assert r.residual.quantity == D("600")


def test_partial_allocation_is_not_a_fail() -> None:
    r = settle_net_position(_position(), _profile(), allocated_quantity=D("400"))
    assert r.is_fail is False


def test_fail_to_receive_on_a_net_long() -> None:
    r = settle_net_position(_position(D("1000")), _profile(), allocated_quantity=D("0"))
    assert r.disposition is CNSDisposition.FAILED_TO_RECEIVE
    assert SecuritiesBreakCode.FAIL_TO_RECEIVE in {b.code for b in r.breaks}


def test_fail_to_deliver_on_a_net_short() -> None:
    r = settle_net_position(_position(D("-1000")), _profile(), allocated_quantity=D("0"))
    assert r.disposition is CNSDisposition.FAILED_TO_DELIVER
    assert SecuritiesBreakCode.FAIL_TO_DELIVER in {b.code for b in r.breaks}


def test_the_two_fail_directions_are_not_one_disposition_with_a_sign() -> None:
    """Same event from opposite sides, different remedies, different
    regulatory consequences."""
    receive = settle_net_position(
        _position(D("1000")), _profile(), allocated_quantity=D("0")
    )
    deliver = settle_net_position(
        _position(D("-1000")), _profile(), allocated_quantity=D("0")
    )
    assert receive.disposition is not deliver.disposition


def test_a_fail_rationale_names_the_settlement_unit() -> None:
    r = settle_net_position(_position(), _profile(), allocated_quantity=D("0"))
    assert "no underlying trade failed" in r.rationale


# ---------------------------------------------------------------------------
# Market profile discipline
# ---------------------------------------------------------------------------


def test_absent_profile_asserts_nothing() -> None:
    p = absent_market_profile("XUNKNOWN")
    assert p.close_out_regime is CloseOutRegime.NOT_ASSESSED
    assert p.settlement_cycle_days is None
    assert p.close_out_deadline_days is None
    assert p.allocation_rule_published is False


def test_settlement_cycle_is_never_defaulted_to_a_convention() -> None:
    """The US convention is the one most likely to be assumed and therefore
    the one most dangerous to default to. Markets have moved cycles in
    different years."""
    assert absent_market_profile("XANY").settlement_cycle_days is None


def test_unassessed_profile_may_not_state_a_cycle() -> None:
    with pytest.raises(ValueError, match="may not state a settlement cycle"):
        MarketProfile(market_id="XCLR", settlement_cycle_days=2)


def test_assessed_profile_requires_provenance() -> None:
    with pytest.raises(ValueError, match="requires provenance"):
        MarketProfile(
            market_id="XCLR", close_out_regime=CloseOutRegime.NONE_PUBLISHED
        )


def test_mandatory_deadline_requires_the_deadline() -> None:
    with pytest.raises(ValueError, match="requires close_out_deadline_days"):
        MarketProfile(
            market_id="XCLR",
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            provenance=CITATION,
        )


def test_a_deadline_without_a_mandatory_regime_is_rejected() -> None:
    with pytest.raises(ValueError, match="meaningful only under"):
        MarketProfile(
            market_id="XCLR",
            close_out_regime=CloseOutRegime.NONE_PUBLISHED,
            close_out_deadline_days=3,
            provenance=CITATION,
        )


def test_not_assessed_is_distinct_from_none_published() -> None:
    """Unread rules and rules that impose nothing are different states with
    the same conservative treatment and different remedies."""
    unread = absent_market_profile("XCLR")
    read_and_clean = _profile(
        close_out_regime=CloseOutRegime.NONE_PUBLISHED,
        close_out_deadline_days=None,
    )
    assert unread.close_out_regime is not read_and_clean.close_out_regime
    assert close_out_deadline(unread, 1) is None
    assert close_out_deadline(read_and_clean, 1) is None


def test_close_out_deadline_is_computed_from_the_market_not_a_constant() -> None:
    assert close_out_deadline(_profile(close_out_deadline_days=3), 1) == 4
    assert close_out_deadline(_profile(close_out_deadline_days=7), 2) == 9


# ---------------------------------------------------------------------------
# Open-fail findings
# ---------------------------------------------------------------------------


def test_an_open_fail_on_an_unread_market_breaks() -> None:
    """Whether a deadline is running is unknown rather than absent. Closed by
    populating the registry, not by any market action."""
    r = settle_net_position(
        _position(), absent_market_profile("XCLR"), allocated_quantity=D("0")
    )
    assert SecuritiesBreakCode.CLOSE_OUT_DEADLINE_UNREADABLE in {
        b.code for b in r.breaks
    }


def test_a_passed_close_out_deadline_breaks() -> None:
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        current_offset_days=9,
    )
    assert SecuritiesBreakCode.CLOSE_OUT_DEADLINE_PASSED in {b.code for b in r.breaks}


def test_a_deadline_not_yet_reached_does_not_break() -> None:
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        current_offset_days=2,
    )
    assert SecuritiesBreakCode.CLOSE_OUT_DEADLINE_PASSED not in {
        b.code for b in r.breaks
    }


def test_an_unsupplied_current_day_never_asserts_a_passed_deadline() -> None:
    """The module has no clock and will not invent one."""
    r = settle_net_position(_position(), _profile(), allocated_quantity=D("0"))
    assert SecuritiesBreakCode.CLOSE_OUT_DEADLINE_PASSED not in {
        b.code for b in r.breaks
    }


def test_a_settled_position_carries_no_open_fail_findings() -> None:
    r = settle_net_position(
        _position(),
        absent_market_profile("XCLR"),
        allocated_quantity=D("1000"),
        current_offset_days=99,
    )
    assert r.breaks == ()


# ---------------------------------------------------------------------------
# Corporate actions over an open fail
# ---------------------------------------------------------------------------


def test_a_fail_across_a_record_date_breaks() -> None:
    """The condition published guidance names: eligible and settled balances
    diverge where position moved after record-date capture."""
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        spans_record_date=True,
    )
    (found,) = [
        b
        for b in r.breaks
        if b.code is SecuritiesBreakCode.ELIGIBLE_SETTLED_DIVERGENCE
    ]
    assert "pending receipt (fail long)" in found.detail
    assert "does not state the outcome" in found.detail


def test_a_ratio_event_without_restatement_breaks() -> None:
    """The fail is denominated in shares that no longer exist in that
    form."""
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        corporate_action_ratio_applied=True,
        quantity_restated=False,
    )
    assert SecuritiesBreakCode.QUANTITY_NOT_RESTATED in {b.code for b in r.breaks}


def test_a_ratio_event_with_restatement_does_not_break() -> None:
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        corporate_action_ratio_applied=True,
        quantity_restated=True,
    )
    assert SecuritiesBreakCode.QUANTITY_NOT_RESTATED not in {b.code for b in r.breaks}
    assert r.residual is not None
    assert r.residual.restated_by_corporate_action is True


def test_a_restated_fail_is_distinguishable_from_an_original_one() -> None:
    """The two reconcile against different source records."""
    plain = settle_net_position(_position(), _profile(), allocated_quantity=D("0"))
    restated = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        corporate_action_ratio_applied=True,
        quantity_restated=True,
    )
    assert plain.residual is not None
    assert restated.residual is not None
    assert plain.residual.restated_by_corporate_action is False
    assert restated.residual != plain.residual


def test_corporate_action_findings_attach_to_partials_too() -> None:
    """A partially allocated position still carries an open quantity, and an
    open quantity is what a record date acts on."""
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("400"),
        spans_record_date=True,
    )
    assert r.disposition is CNSDisposition.PARTIAL_ALLOCATION
    assert SecuritiesBreakCode.ELIGIBLE_SETTLED_DIVERGENCE in {
        b.code for b in r.breaks
    }


# ---------------------------------------------------------------------------
# Allocation transparency
# ---------------------------------------------------------------------------


def test_a_partial_on_an_opaque_market_breaks() -> None:
    """The member cannot explain why it received what it received, and this
    framework will not manufacture an explanation."""
    r = settle_net_position(
        _position(),
        _profile(allocation_rule_published=False),
        allocated_quantity=D("400"),
    )
    assert SecuritiesBreakCode.PARTIAL_WITH_UNEXPLAINED_ALLOCATION in {
        b.code for b in r.breaks
    }


def test_a_partial_on_a_transparent_market_does_not_break_on_that_ground() -> None:
    r = settle_net_position(
        _position(), _profile(allocation_rule_published=True), allocated_quantity=D("400")
    )
    assert SecuritiesBreakCode.PARTIAL_WITH_UNEXPLAINED_ALLOCATION not in {
        b.code for b in r.breaks
    }


def test_a_full_fail_is_not_an_allocation_transparency_question() -> None:
    """Nothing was allocated, so there is no allocation to explain."""
    r = settle_net_position(
        _position(),
        _profile(allocation_rule_published=False),
        allocated_quantity=D("0"),
    )
    assert SecuritiesBreakCode.PARTIAL_WITH_UNEXPLAINED_ALLOCATION not in {
        b.code for b in r.breaks
    }


# ---------------------------------------------------------------------------
# Determinism and hygiene
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_results() -> None:
    kw = {"allocated_quantity": D("400"), "spans_record_date": True}
    a = settle_net_position(_position(), _profile(), **kw)  # type: ignore[arg-type]
    b = settle_net_position(_position(), _profile(), **kw)  # type: ignore[arg-type]
    assert a == b


def test_a_break_with_no_detail_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a finding"):
        SecuritiesBreak(SecuritiesBreakCode.FAIL_TO_DELIVER, "")


@pytest.mark.parametrize("disposition", list(CNSDisposition))
def test_every_disposition_answers_both_derived_questions(
    disposition: CNSDisposition,
) -> None:
    """Exhaustiveness. A new disposition must be decided into or out of both
    is_fail and completed rather than falling through."""
    r = NetSettlementResult(
        disposition=disposition,
        position=_position(),
        allocated_quantity=D("0"),
        residual=None,
    )
    assert isinstance(r.is_fail, bool)
    assert isinstance(r.completed, bool)


def test_not_novated_is_representable_and_is_not_a_fail() -> None:
    """A trade that settles bilaterally is out of this model's scope, not
    failing within it."""
    r = NetSettlementResult(
        disposition=CNSDisposition.NOT_NOVATED,
        position=_position(),
        allocated_quantity=D("0"),
        residual=None,
    )
    assert r.is_fail is False
    assert r.completed is False


def test_market_id_is_required() -> None:
    with pytest.raises(ValueError, match="market_id is required"):
        MarketProfile(market_id="")


# ---------------------------------------------------------------------------
# Record-date balances: published vocabulary, no computed outcome
# ---------------------------------------------------------------------------


def test_record_date_position_records_divergence_without_asserting_an_outcome() -> None:
    """Every field name traces to published depository vocabulary. There is
    no entitlement field and there will not be one."""
    from atreides.rails.cns import RecordDatePosition

    pos = RecordDatePosition(
        security_id="SEC-A",
        eligible_balance=D("1000"),
        settlement_balance=D("400"),
        pending_receipt_balance=D("600"),
        provenance="Depository corporate-action usage guidance",
    )
    assert pos.diverges is True
    assert pos.divergence == D("600")
    assert not hasattr(pos, "entitlement")


def test_matching_balances_do_not_diverge() -> None:
    from atreides.rails.cns import RecordDatePosition

    pos = RecordDatePosition(
        security_id="SEC-A",
        eligible_balance=D("1000"),
        settlement_balance=D("1000"),
    )
    assert pos.diverges is False
    assert pos.divergence == D("0")


def test_lottery_and_voluntary_balances_are_representable() -> None:
    """Obligated balance for partial calls, uncovered protect for voluntary
    events. Both are named in the guidance and both were absent from the
    first cut of this module."""
    from atreides.rails.cns import RecordDatePosition

    pos = RecordDatePosition(
        security_id="SEC-A",
        eligible_balance=D("1000"),
        settlement_balance=D("800"),
        obligated_balance=D("200"),
        uncovered_protect_balance=D("50"),
    )
    assert pos.obligated_balance == D("200")
    assert pos.uncovered_protect_balance == D("50")


# ---------------------------------------------------------------------------
# The processing date: which business date a trade clears for
#
# A settlement cycle counts business days FROM the processing date and
# silently assumes what that date is. Extended-hours equities separated the
# two: the boundary is fixed by a message the market sends, so a trade at
# 23:58 and one at 00:02 can clear for different dates and the timestamps do
# not say which. These tests hold the framework to expressing that rather
# than computing through it.
# ---------------------------------------------------------------------------


def _message_market(**kw: object) -> MarketProfile:
    return _profile(
        market_id="XCLR-EXT",
        processing_date_rule=ProcessingDateRule.SESSION_CLOSURE_MESSAGE,
        session_closure_message="the session-closure message",
        **kw,
    )


def test_the_processing_date_rule_is_unassessed_by_default() -> None:
    """Not FIXED_CYCLE_FROM_TRADE_DATE. Defaulting to the familiar case is
    the specific error this field exists to prevent, and it is the same
    error the module's own docstring warns about for settlement cycles."""
    assert absent_market_profile("XCLR").processing_date_rule is (
        ProcessingDateRule.NOT_ASSESSED
    )
    assert _profile().processing_date_rule is ProcessingDateRule.NOT_ASSESSED


def test_an_unread_market_may_not_state_a_processing_date_rule() -> None:
    with pytest.raises(ValueError, match="may not state a settlement cycle"):
        MarketProfile(
            market_id="XCLR",
            processing_date_rule=ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE,
        )


def test_a_message_determined_market_must_name_its_message() -> None:
    """An operator reconciling a rolled processing date searches for the
    market's own term. A flag does not give them one."""
    with pytest.raises(ValueError, match="requires the message to be named"):
        _profile(processing_date_rule=ProcessingDateRule.SESSION_CLOSURE_MESSAGE)


def test_a_message_name_without_a_message_rule_is_rejected() -> None:
    with pytest.raises(ValueError, match="meaningful only under"):
        _profile(session_closure_message="the session-closure message")


def test_an_unread_rule_does_not_read_as_a_fixed_cycle() -> None:
    """The collapse this whole field exists to prevent, asserted directly."""
    unread = _profile()
    assert unread.settlement_cycle_days == 1
    assert unread.settlement_date_follows_from_trade_date is False


def test_a_fixed_cycle_market_dates_settlement_from_the_trade_date() -> None:
    fixed = _profile(
        processing_date_rule=ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE
    )
    assert fixed.settlement_date_follows_from_trade_date is True
    assert processing_date_offset(fixed, _position()) == 0


def test_a_message_determined_market_does_not_date_settlement_from_a_clock() -> None:
    assert _message_market().settlement_date_follows_from_trade_date is False


def test_an_assigned_processing_date_is_reported_not_derived() -> None:
    position = net_positions(
        (("SEC-A", D("1000")),),
        market_id="XCLR-EXT",
        settlement_date_offset_days=1,
        assigned_processing_date_offset_days=1,
    )[0]
    assert processing_date_offset(_message_market(), position) == 1


def test_an_unestablished_processing_date_returns_nothing() -> None:
    assert processing_date_offset(_message_market(), _position()) is None
    assert processing_date_offset(absent_market_profile("XCLR"), _position()) is None


def test_an_unestablished_processing_date_is_a_break_on_a_settled_position() -> None:
    """The case most likely to be missed. The shares moved, so every
    settlement field reads clean, and the position may still have cleared
    for a business date nobody has established. "It settled" and "it settled
    on the date we assumed" are different assertions."""
    result = settle_net_position(
        _position(), _message_market(), allocated_quantity=D("1000")
    )
    assert result.disposition is CNSDisposition.SETTLED_IN_FULL
    assert result.completed is True
    codes = {b.code for b in result.breaks}
    assert SecuritiesBreakCode.PROCESSING_DATE_NOT_ESTABLISHED in codes


def test_the_break_names_the_markets_own_message() -> None:
    result = settle_net_position(
        _position(), _message_market(), allocated_quantity=D("1000")
    )
    detail = next(
        b.detail
        for b in result.breaks
        if b.code is SecuritiesBreakCode.PROCESSING_DATE_NOT_ESTABLISHED
    )
    assert "the session-closure message" in detail


def test_a_reported_processing_date_closes_the_break() -> None:
    position = net_positions(
        (("SEC-A", D("1000")),),
        market_id="XCLR-EXT",
        settlement_date_offset_days=1,
        assigned_processing_date_offset_days=0,
    )[0]
    result = settle_net_position(
        position, _message_market(), allocated_quantity=D("1000")
    )
    assert SecuritiesBreakCode.PROCESSING_DATE_NOT_ESTABLISHED not in {
        b.code for b in result.breaks
    }


def test_a_fixed_cycle_market_never_raises_the_break() -> None:
    """The break is a property of how the market fixes its dates, not a tax
    on every position everywhere."""
    fixed = _profile(
        processing_date_rule=ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE
    )
    result = settle_net_position(_position(), fixed, allocated_quantity=D("1000"))
    assert result.breaks == ()


def test_the_processing_date_refusal_is_stated_rather_than_implied() -> None:
    text = absent_processing_date("XCLR-EXT", "the session-closure message")
    assert "No processing date for market XCLR-EXT" in text
    assert "the session-closure message" in text
    assert "cannot establish it" in text


def test_the_refusal_names_a_message_even_when_none_was_supplied() -> None:
    assert "a session-closure message" in absent_processing_date("XCLR-EXT")


def test_a_market_profile_with_a_processing_rule_round_trips() -> None:
    """Portability: an exported profile that cannot be read back in is not
    portable, and enum members arrive from JSON as plain strings."""
    import json

    original = _message_market()
    payload = json.loads(
        json.dumps(
            {
                "market_id": original.market_id,
                "settlement_cycle_days": original.settlement_cycle_days,
                "close_out_regime": original.close_out_regime.value,
                "close_out_deadline_days": original.close_out_deadline_days,
                "allocation_rule_published": original.allocation_rule_published,
                "processing_date_rule": original.processing_date_rule.value,
                "session_closure_message": original.session_closure_message,
                "provenance": original.provenance,
            }
        )
    )
    assert MarketProfile(**payload) == original


def test_the_entitlement_refusal_is_stated_rather_than_implied() -> None:
    """Published guidance carries the condition and not the treatment.
    Computing an outcome here would present market practice as governance.
    """
    from atreides.rails.cns import absent_entitlement_treatment

    text = absent_entitlement_treatment("SEC-A")
    assert "is not computed" in text
    assert "not published" in text
    assert "presenting market practice as governance" in text or (
        "present market practice as governance" in text
    )


def test_there_is_no_entitlement_computation_api() -> None:
    assert not any(
        name.startswith(("compute_entitlement", "allocate_entitlement", "cash_in_lieu"))
        for name in dir(cns)
    )


# ---------------------------------------------------------------------------
# A movement reported against a flat position
#
# The stress probe's best finding: this branch discarded the venue's figure
# and returned a clean day. It is the same error OUTCOME_NOT_REPORTED exists
# to prevent, running the other way - there the framework refuses to infer
# settlement from silence, here it was inferring silence from a settlement it
# had been told about.
# ---------------------------------------------------------------------------


def test_a_reported_allocation_against_a_flat_position_is_a_break() -> None:
    position = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(position, _profile(), allocated_quantity=D("50"))
    assert result.disposition is CNSDisposition.FLAT
    codes = {b.code for b in result.breaks}
    assert SecuritiesBreakCode.ALLOCATION_AGAINST_FLAT_POSITION in codes


def test_the_venues_figure_is_not_discarded() -> None:
    """It was overwritten with zero in the result object, so the number the
    venue reported did not survive anywhere in the record."""
    position = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(position, _profile(), allocated_quantity=D("50"))
    assert result.allocated_quantity == D("50")


def test_a_disputed_flat_day_is_not_a_completed_day() -> None:
    position = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(position, _profile(), allocated_quantity=D("50"))
    assert result.completed is False


def test_an_undisputed_flat_position_still_completes_cleanly() -> None:
    """The fix must not turn every netted-out security into a break."""
    position = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(position, _profile(), allocated_quantity=D("0"))
    assert result.disposition is CNSDisposition.FLAT
    assert result.completed is True
    assert result.breaks == ()


def test_the_break_names_both_sides_of_the_disagreement() -> None:
    position = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(position, _profile(), allocated_quantity=D("50"))
    detail = next(
        b.detail
        for b in result.breaks
        if b.code is SecuritiesBreakCode.ALLOCATION_AGAINST_FLAT_POSITION
    )
    assert "50" in detail
    assert "zero" in detail
    assert "cannot say which" in detail
