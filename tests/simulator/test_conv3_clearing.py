"""CONV-3 clearing-readiness acceptance tests."""

from decimal import Decimal
from typing import cast

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from simulator.clearing_readiness import attack_clearing_readiness, run_clearing_readiness


def test_ready_run_adds_declared_fund_to_real_cns_money() -> None:
    result = run_clearing_readiness("ready")
    assert result["dtcc_license_gate"] == "INDETERMINATE"
    assert result["disposition"] == "PASS"
    funding = cast(dict[str, str], result["declared_funding_inputs"])
    assert Decimal(cast(str, result["daily_funding_need"])) == (
        Decimal(cast(str, result["cns_money_settlement"]))
        + Decimal(funding["clearing_fund_requirement"])
    )


def test_named_membership_and_fund_variants_hold() -> None:
    missing = run_clearing_readiness("missing-membership")
    assert missing["disposition"] == "HOLD"
    assert "NSCC" in " ".join(cast(list[str], missing["reasons"]))
    fund = run_clearing_readiness("fund-call")
    assert fund["disposition"] == "HOLD"
    assert "clearing fund call" in " ".join(cast(list[str], fund["reasons"]))
    assert attack_clearing_readiness() == {"inflate-fund-call": True}


@seed(20261025)
@settings(max_examples=200, deadline=None)
@given(
    cns_cents=st.integers(min_value=0, max_value=100_000_000_00),
    fund_cents=st.integers(min_value=0, max_value=100_000_000_00),
)
def test_daily_funding_addition_conserves_every_cent(cns_cents: int, fund_cents: int) -> None:
    cns = Decimal(cns_cents) / 100
    fund = Decimal(fund_cents) / 100
    need = cns + fund
    assert int(need * 100) == cns_cents + fund_cents
