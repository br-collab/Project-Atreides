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
    SecuritiesBreak,
    SecuritiesBreakCode,
    absent_market_profile,
    absent_trade_attribution,
    close_out_deadline,
    net_positions,
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
    """Entitlement does not disappear because delivery did. It becomes a
    claim, and a claim nobody raised is a loss nobody recorded."""
    r = settle_net_position(
        _position(),
        _profile(),
        allocated_quantity=D("0"),
        spans_record_date=True,
    )
    (found,) = [
        b
        for b in r.breaks
        if b.code is SecuritiesBreakCode.UNSETTLED_ACROSS_RECORD_DATE
    ]
    assert "becomes a claim" in found.detail


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
    assert SecuritiesBreakCode.UNSETTLED_ACROSS_RECORD_DATE in {
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
