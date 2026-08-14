"""Tests for the intraday funding-state model — AUR-CUSTODY-CASH-001 §VII.

The load-bearing assertion in this file is that a queue is not a failure.
Everything else supports it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.rails.cato_f import FinalityClass, FundingState
from atreides.rails.funding_state import (
    CashFlow,
    FundingDisposition,
    FundingInputs,
    project_funding,
)

D = Decimal


def _inputs(**kw) -> FundingInputs:
    base = {
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


# --- the distinction the module exists to make -----------------------------


class TestQueueIsNotFailure:
    def test_gross_final_shortfall_with_later_inflow_queues(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                flows=(CashFlow(7200, D("2000000"), "incoming wire"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_QUEUE
        assert p.funded_at_offset_seconds == 7200
        assert "NOT a failure" in p.rationale

    def test_queue_is_explicitly_not_a_failure(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                flows=(CashFlow(7200, D("2000000"), "incoming"),),
            )
        )
        assert not p.is_failure
        assert not p.settles  # it has not settled either — callers must branch

    def test_gross_final_shortfall_past_window_close_fails(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                flows=(CashFlow(20000, D("2000000"), "too late"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_FAIL
        assert p.funded_at_offset_seconds is None
        assert p.is_failure

    def test_gross_final_with_no_inflow_at_all_fails(self) -> None:
        p = project_funding(_inputs(opening_position=D("0")))
        assert p.disposition is FundingDisposition.WILL_FAIL


# --- finality drives treatment ---------------------------------------------


class TestFinalityDrivesTreatment:
    def test_deferred_net_funded_by_finality_is_funded(self) -> None:
        """Instruction-instant shortfall is not a failure on a netted rail."""
        p = project_funding(
            _inputs(
                finality_class=FinalityClass.DEFERRED_NET,
                opening_position=D("0"),
                flows=(CashFlow(10000, D("2000000"), "eod inflow"),),
            )
        )
        assert p.disposition is FundingDisposition.FUNDED
        assert "runs to end-of-day" in p.rationale

    def test_deferred_net_short_at_finality_fails(self) -> None:
        p = project_funding(
            _inputs(
                finality_class=FinalityClass.DEFERRED_NET,
                opening_position=D("0"),
                flows=(CashFlow(10000, D("100"), "not enough"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_FAIL

    def test_ledger_final_has_no_queue(self) -> None:
        p = project_funding(
            _inputs(
                finality_class=FinalityClass.LEDGER_FINAL,
                opening_position=D("0"),
                flows=(CashFlow(7200, D("2000000"), "later"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_FAIL
        assert "no queue on a ledger" in p.rationale

    def test_correspondent_dependent_is_indeterminate_not_guessed(self) -> None:
        p = project_funding(
            _inputs(finality_class=FinalityClass.CORRESPONDENT_DEPENDENT)
        )
        assert p.disposition is FundingDisposition.INDETERMINATE
        assert "declines to assert" in p.rationale

    def test_24_7_rail_has_no_window_close_and_still_queues(self) -> None:
        """§VII: the model must not assume a nightly reset."""
        p = project_funding(
            _inputs(
                window_close_offset_seconds=None,
                opening_position=D("0"),
                flows=(CashFlow(999999, D("2000000"), "much later"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_QUEUE


# --- committed vs expected flows -------------------------------------------


class TestCommittedVersusExpected:
    def test_uncommitted_inflow_does_not_fund(self) -> None:
        """You do not fund a settlement on hoped-for inflows."""
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                window_close_offset_seconds=None,
                flows=(
                    CashFlow(600, D("5000000"), "expected receivable", committed=False),
                ),
            )
        )
        assert p.disposition is FundingDisposition.WILL_FAIL
        assert p.projected_position_at_settlement == D("0")

    def test_uncommitted_inflow_is_still_surfaced(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                flows=(
                    CashFlow(600, D("5000000"), "expected", committed=False),
                ),
            )
        )
        assert p.optimistic_position_at_settlement == D("5000000")
        assert p.projected_position_at_settlement == D("0")


# --- hard risk controls -----------------------------------------------------


class TestHardControls:
    def test_clearing_fund_deficiency_gates_regardless_of_position(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("999999999"),
                clearing_fund_posted=D("0"),
            )
        )
        assert p.disposition is FundingDisposition.CLEARING_FUND_DEFICIENT
        assert p.is_failure

    def test_cap_breach_measured_at_the_intraday_trough(self) -> None:
        """A cap is breached by the deepest point, not the closing one."""
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                obligation=D("0"),
                net_debit_cap=D("1000"),
                flows=(
                    CashFlow(60, D("-5000"), "morning outflow"),
                    CashFlow(120, D("5000"), "afternoon recovery"),
                ),
            )
        )
        assert p.disposition is FundingDisposition.CAP_BREACH
        assert "trough" in p.rationale

    def test_recovering_position_alone_does_not_excuse_the_trough(self) -> None:
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                obligation=D("0"),
                net_debit_cap=D("1000"),
                flows=(
                    CashFlow(60, D("-5000"), "dip"),
                    CashFlow(120, D("5000"), "recover"),
                ),
            )
        )
        assert p.projected_position_at_settlement == D("0")  # closes flat
        assert p.disposition is FundingDisposition.CAP_BREACH  # still breached

    def test_clearing_fund_outranks_cap_breach(self) -> None:
        p = project_funding(
            _inputs(
                clearing_fund_posted=D("0"),
                net_debit_cap=D("0"),
                opening_position=D("-999"),
            )
        )
        assert p.disposition is FundingDisposition.CLEARING_FUND_DEFICIENT


# --- the happy path and the CATO-F handoff ---------------------------------


class TestFundedAndHandoff:
    def test_covered_position_is_funded(self) -> None:
        p = project_funding(_inputs())
        assert p.disposition is FundingDisposition.FUNDED
        assert p.settles
        assert p.shortfall == D("0")

    def test_to_gate_input_produces_a_cato_f_funding_state(self) -> None:
        p = project_funding(_inputs())
        gate_input = p.to_gate_input()
        assert isinstance(gate_input, FundingState)
        assert gate_input.is_funded
        assert gate_input.net_obligation == p.obligation

    def test_queued_operation_reports_unfunded_to_the_gate(self) -> None:
        """The gate should hold a queued operation — it cannot settle NOW —
        even though the operation is not a failure."""
        p = project_funding(
            _inputs(
                opening_position=D("0"),
                flows=(CashFlow(7200, D("2000000"), "later"),),
            )
        )
        assert p.disposition is FundingDisposition.WILL_QUEUE
        assert not p.to_gate_input().is_funded

    def test_ladder_is_ordered_and_includes_post_settlement(self) -> None:
        p = project_funding(
            _inputs(flows=(CashFlow(600, D("500000"), "inflow"),))
        )
        offsets = [pt.offset_seconds for pt in p.ladder]
        assert offsets == sorted(offsets)
        assert any(pt.label == "post-settlement" for pt in p.ladder)


# --- determinism ------------------------------------------------------------


def test_projection_is_deterministic() -> None:
    flows = (
        CashFlow(600, D("100"), "b"),
        CashFlow(60, D("200"), "a"),
        CashFlow(600, D("50"), "a"),
    )
    a = project_funding(_inputs(flows=flows))
    b = project_funding(_inputs(flows=tuple(reversed(flows))))
    assert a.ladder == b.ladder
    assert a.disposition is b.disposition


@pytest.mark.parametrize("finality", list(FinalityClass))
def test_every_finality_class_yields_a_disposition(finality: FinalityClass) -> None:
    """Derived from the enum, not from a hand-copied list.

    The hand-copied form of this test would have passed silently when
    DETERMINATION_DEPENDENT was added, which is precisely the failure an
    exhaustiveness test exists to prevent. Parametrising over
    ``list(FinalityClass)`` makes the next enum addition break the build
    until somebody decides what it means here.
    """
    p = project_funding(_inputs(finality_class=finality))
    assert isinstance(p.disposition, FundingDisposition)


def test_inflows_before_the_settlement_instant_are_not_queue_candidates() -> None:
    """A flow that lands before settlement is already counted in the
    projected position; it can never be the moment a shortfall *clears*."""
    p = project_funding(
        _inputs(
            opening_position=D("0"),
            flows=(
                CashFlow(60, D("1"), "early dribble"),
                CashFlow(9000, D("2000000"), "the real inflow"),
            ),
        )
    )
    assert p.disposition is FundingDisposition.WILL_QUEUE
    assert p.funded_at_offset_seconds == 9000


def test_absent_net_debit_cap_yields_zero_headroom_and_no_breach() -> None:
    """No cap configured is not an unlimited cap — headroom reports zero
    and the cap check is skipped rather than passed."""
    p = project_funding(_inputs(net_debit_cap=None, opening_position=D("-999999")))
    assert p.net_debit_cap_headroom == D("0")
    assert p.disposition is not FundingDisposition.CAP_BREACH
