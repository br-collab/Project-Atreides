"""ATR-I-09 regression: only flows that can land in the window drive the cap test.

Before Wave 2 the net-debit-cap trough walked every committed flow, so a certain
outflow dated after the settlement window closed breached today's cap (stress
case H3.4). Fixed in W2A-1 (``funding_state._cap_trough``).
"""

from __future__ import annotations

from decimal import Decimal

from atreides.rails.finality import FinalityClass
from atreides.rails.funding_state import (
    CashFlow,
    FundingDisposition,
    FundingInputs,
    project_funding,
)

D = Decimal


def _inputs(*flows: CashFlow, close: int | None = 7200) -> FundingInputs:
    return FundingInputs(
        opening_position=D("100"),
        obligation=D("10"),
        finality_class=FinalityClass.GROSS_FINAL,
        settlement_offset_seconds=3600,
        window_close_offset_seconds=close,
        net_debit_cap=D("50"),
        flows=flows,
    )


def test_stress_h3_4_certain_outflow_after_the_window_does_not_breach_the_cap() -> None:
    p = project_funding(_inputs(CashFlow(86400, D("-1000"), "next-day outflow")))
    assert p.disposition is FundingDisposition.FUNDED
    assert p.net_debit_cap_headroom == D("50")
    # Still shown on the ladder: excluded from the cap test, not hidden.
    assert any(point.label == "next-day outflow" for point in p.ladder)


def test_certain_outflow_inside_the_window_still_breaches() -> None:
    p = project_funding(_inputs(CashFlow(5400, D("-1000"), "in-window outflow")))
    assert p.disposition is FundingDisposition.CAP_BREACH


def test_uncertain_outflow_after_the_window_stays_in_conservatively() -> None:
    flow = CashFlow(86400, D("-1000"), "undated outflow", offset_is_certain=False)
    p = project_funding(_inputs(flow))
    assert p.disposition is FundingDisposition.CAP_BREACH
    assert p.net_debit_cap_headroom == D("50") + D("100") - D("1000")


def test_uncertain_inflow_after_the_window_is_not_counted() -> None:
    inflow = CashFlow(86400, D("5000"), "undated inflow", offset_is_certain=False)
    outflow = CashFlow(5400, D("-1000"), "in-window outflow")
    assert project_funding(_inputs(inflow, outflow)).disposition is FundingDisposition.CAP_BREACH


def test_a_rail_with_no_window_close_counts_every_committed_flow() -> None:
    p = project_funding(_inputs(CashFlow(86400, D("-1000"), "later outflow"), close=None))
    assert p.disposition is FundingDisposition.CAP_BREACH


def test_uncommitted_flows_never_count() -> None:
    flow = CashFlow(5400, D("-1000"), "hoped-for outflow", committed=False)
    assert project_funding(_inputs(flow)).disposition is FundingDisposition.FUNDED
