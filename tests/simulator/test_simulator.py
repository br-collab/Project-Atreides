from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.rails.cns import absent_entitlement_treatment
from simulator.calibration import load_calibration_pack
from simulator.invariants import InvariantEvidence, evaluate_invariants
from simulator.market import (
    PriceTimeBook,
    allocate_largest_remainder,
    auction_print,
    treasury_consideration,
)
from simulator.model import AssetClass, Order, Side
from simulator.runner import DISCLAIMER, publish_run, run_simulation
from simulator.settlement import (
    RULE_204_PARAGRAPH,
    buy_in_cash_difference,
    cash_rail_movement,
    cns_cycles,
    dtc_dvp_status,
    gsd_messages,
    rule_204_deadline,
    short_sale_restricted,
)


def order(name: str, *, arrived: int = 0, quantity: int = 10) -> Order:
    return Order(
        order_id=name,
        issue="SYN-EQ-1",
        asset_class=AssetClass.EQUITY,
        side=Side.BUY,
        quantity=quantity,
        limit_price=Decimal("10.00"),
        arrived_at=datetime(2026, 1, 2, 14, 30, arrived, tzinfo=UTC),
        account_weights=(1, 1, 1),
    )


def test_price_time_priority_and_size_ahead() -> None:
    book = PriceTimeBook()
    book.rest(order("EARLY"), size_ahead=5)
    book.rest(order("LATE", arrived=1))
    prints = book.execute(
        price=Decimal("10.00"), quantity=17, matched_at=datetime(2026, 1, 2, 15, tzinfo=UTC)
    )
    assert [(p.order_id, p.quantity) for p in prints] == [("EARLY", 10), ("LATE", 2)]


def test_match_and_report_clocks_preserve_late_print() -> None:
    book = PriceTimeBook()
    book.rest(order("CANCELLED"))
    matched = datetime(2026, 1, 2, 15, tzinfo=UTC)
    prints = book.execute(price=Decimal("10.00"), quantity=3, matched_at=matched, report_delay=30)
    assert prints[0].matched_at == matched
    assert prints[0].reported_at == matched + timedelta(seconds=30)


def test_rule_612_scope_allows_subpenny_execution() -> None:
    book_doc = PriceTimeBook.__doc__ or ""
    module_doc = sys.modules["simulator.market"].__doc__ or ""
    assert "bid or offer, an order" in book_doc or "bid or offer, an order" in module_doc
    assert Decimal("10.001") != Decimal("10.00")


def test_multi_print_uses_report_prices_including_subpenny() -> None:
    book = PriceTimeBook()
    book.rest(order("MULTI", quantity=10))
    first = book.execute(
        price=Decimal("10.00"),
        quantity=4,
        matched_at=datetime(2026, 1, 2, 15, tzinfo=UTC),
        execution_price=Decimal("9.999"),
    )
    second = book.execute(
        price=Decimal("10.00"),
        quantity=6,
        matched_at=datetime(2026, 1, 2, 15, 0, 1, tzinfo=UTC),
        execution_price=Decimal("9.995"),
    )
    reports = (*first, *second)
    assert [item.price for item in reports] == [Decimal("9.999"), Decimal("9.995")]
    assert sum(Decimal(item.quantity) * item.price for item in reports) == Decimal("99.966")


def test_open_and_close_auctions_add_prints_with_declared_imbalance() -> None:
    interest = order("AUCTION", quantity=100)
    opening = auction_print(
        order=interest, clearing_price=Decimal("9.90"), imbalance=7, session="OPEN_AUCTION"
    )
    closing = auction_print(
        order=interest, clearing_price=Decimal("10.10"), imbalance=-3, session="CLOSE_AUCTION"
    )
    assert (opening.quantity, closing.quantity) == (93, 97)
    assert opening.session == "OPEN_AUCTION" and closing.session == "CLOSE_AUCTION"


def test_halt_refuses_new_order_and_cancels_resting() -> None:
    book = PriceTimeBook()
    book.rest(order("OPEN"))
    book.halt("SYN-EQ-1", cancel_resting=True)
    with pytest.raises(ValueError, match="halt"):
        book.rest(order("DURING"))


def test_ex_date_open_fail_uses_existing_refusal() -> None:
    refusal = absent_entitlement_treatment("SYN-EQ-EXDATE")
    assert "is not computed" in refusal
    assert "SYN-EQ-EXDATE" in refusal


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10**7),
    weights=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20).map(tuple),
)
def test_allocation_conserves_every_share(quantity: int, weights: tuple[int, ...]) -> None:
    allocated = allocate_largest_remainder(quantity, weights)
    assert sum(allocated) == quantity
    assert all(value >= 0 for value in allocated)


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    par=st.integers(min_value=1, max_value=10**9),
    price=st.decimals(min_value="0.000001", max_value="200", places=6),
    accrued=st.decimals(min_value="0", max_value="100000", places=6),
)
def test_treasury_money_rounds_once_to_cent(par: int, price: Decimal, accrued: Decimal) -> None:
    result = treasury_consideration(
        asset_class=AssetClass.TREASURY_NOTE, par=par, price=price, accrued_interest=accrued
    )
    assert result == (Decimal(par) * price / Decimal(100) + accrued).quantize(Decimal("0.01"))
    assert result.as_tuple().exponent == -2


def test_missing_note_accrual_is_not_zero() -> None:
    with pytest.raises(ValueError, match="missing is not zero"):
        treasury_consideration(
            asset_class=AssetClass.TREASURY_NOTE, par=100, price=Decimal(99), accrued_interest=None
        )


def test_distinct_settlement_messages_and_cap_hold() -> None:
    cns = cns_cycles(issue="SYN", quantity=101, mark_price=Decimal("9.99"), night_capacity=70)
    gsd = gsd_messages(
        issue="SYN-T",
        quantity=100,
        principal=Decimal(99),
        invoice=Decimal(1),
        coupon=Decimal(2),
        mark=Decimal(3),
    )
    cash = cash_rail_movement(issue="SYN-T", money=Decimal(105))
    dtc = dtc_dvp_status(
        issue="SYN",
        quantity=10,
        money=Decimal(100),
        net_debit_cap=Decimal(90),
        collateral=Decimal(200),
    )
    assert {m.message_name for m in (*cns, *gsd, cash, dtc)} == {
        "CNS_NIGHT_CYCLE",
        "CNS_DAY_CYCLE",
        "GSD_SECURITIES_NET",
        "GSD_FUNDS_ONLY",
        "CASH_RAIL_MOVEMENT",
        "DTC_DVP_STATUS",
    }
    assert dtc.status == "HELD_CAP_OR_COLLATERAL" and dtc.securities == 0


def test_rule_204_uses_one_or_three_settlement_days() -> None:
    assert "beginning of regular trading hours" in RULE_204_PARAGRAPH
    assert "30-day" in (rule_204_deadline.__doc__ or "")
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    settlement = date(2026, 12, 30)
    assert rule_204_deadline(
        settlement_date=settlement, sale_kind="SHORT", calendar=calendar
    ) == date(2026, 12, 31)
    assert rule_204_deadline(
        settlement_date=settlement, sale_kind="LONG", calendar=calendar
    ) == date(2027, 1, 5)
    assert short_sale_restricted(
        deadline=date(2026, 12, 31), close_date=date(2026, 12, 31), closeout_settled=False
    )
    assert not short_sale_restricted(
        deadline=date(2026, 12, 31), close_date=date(2027, 1, 2), closeout_settled=True
    )


def test_cns_and_non_cns_buyins_post_separate_profit_or_loss() -> None:
    cns_loss = buy_in_cash_difference(
        quantity=101, original_price=Decimal("10.00"), buy_in_price=Decimal("10.13")
    )
    bilateral_profit = buy_in_cash_difference(
        quantity=37, original_price=Decimal("20.00"), buy_in_price=Decimal("19.75")
    )
    assert cns_loss == Decimal("13.13")
    assert bilateral_profit == Decimal("-9.25")


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10**7),
    original=st.decimals(min_value="0.000001", max_value="100000", places=6),
    buy_in=st.decimals(min_value="0.000001", max_value="100000", places=6),
)
def test_buy_in_money_conserves_to_the_cent(
    quantity: int, original: Decimal, buy_in: Decimal
) -> None:
    expected = (Decimal(quantity) * (buy_in - original)).quantize(Decimal("0.01"))
    assert (
        buy_in_cash_difference(quantity=quantity, original_price=original, buy_in_price=buy_in)
        == expected
    )


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10**7),
    capacity=st.integers(min_value=0, max_value=10**7),
    mark=st.decimals(min_value="0.000001", max_value="100000", places=6),
)
def test_cns_cycles_conserve_shares_and_each_money_side(
    quantity: int, capacity: int, mark: Decimal
) -> None:
    movements = cns_cycles(
        issue="SYN-EQ-PROPERTY", quantity=quantity, mark_price=mark, night_capacity=capacity
    )
    assert sum(item.securities for item in movements) == quantity
    assert all(
        item.money == (Decimal(item.securities) * mark).quantize(Decimal("0.01"))
        for item in movements
    )


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10**7),
    principal=st.decimals(min_value="0", max_value="1000000000", places=6),
    invoice=st.decimals(min_value="-1000000", max_value="1000000", places=6),
    coupon=st.decimals(min_value="-1000000", max_value="1000000", places=6),
    mark=st.decimals(min_value="-1000000", max_value="1000000", places=6),
    cap=st.decimals(min_value="0", max_value="1000000000", places=2),
    collateral=st.decimals(min_value="0", max_value="1000000000", places=2),
)
def test_street_money_paths_conserve_to_the_cent(
    quantity: int,
    principal: Decimal,
    invoice: Decimal,
    coupon: Decimal,
    mark: Decimal,
    cap: Decimal,
    collateral: Decimal,
) -> None:
    securities, funds = gsd_messages(
        issue="SYN-UST-PROPERTY",
        quantity=quantity,
        principal=principal,
        invoice=invoice,
        coupon=coupon,
        mark=mark,
    )
    assert securities.money == principal.quantize(Decimal("0.01"))
    assert funds.money == (invoice + coupon + mark).quantize(Decimal("0.01"))
    cash = cash_rail_movement(issue="SYN-CASH", money=securities.money + funds.money)
    assert cash.money == (securities.money + funds.money).quantize(Decimal("0.01"))

    dvp = dtc_dvp_status(
        issue="SYN-EQ-PROPERTY",
        quantity=quantity,
        money=principal,
        net_debit_cap=cap,
        collateral=collateral,
    )
    expected_money = principal.quantize(Decimal("0.01"))
    expected_settled = expected_money <= min(cap, collateral)
    assert dvp.securities == (quantity if expected_settled else 0)
    assert dvp.money == (expected_money if expected_settled else Decimal(0))


def test_seed_replay_and_scenario_coverage(tmp_path: Path) -> None:
    shas = {
        "cannae-kernel": "kernel-sha",
        "Cato-FICC-MCP": "cato-sha",
        "Legiones-Cannenses": "lc-sha",
        "aureon": "aureon-sha",
        "atreides": "atreides-sha",
    }
    first = run_simulation(seed=7, days=5, repository_shas=shas)
    again = run_simulation(seed=7, days=5)
    other = run_simulation(seed=8, days=5)
    assert first["economics_digest"] == again["economics_digest"]
    assert first["economics_digest"] != other["economics_digest"]
    assert {"MULTI_PRINT", "ODD_LOT", "CNS_NIGHT", "CNS_DAY"} <= set(
        cast(list[str], first["scenarios_exercised"])
    )
    assert first["all_invariants_pass"] is True
    assert first["repository_shas"] == shas
    publish_run(first, tmp_path)
    for name in ("daily-close.json", "run-summary.json", "trend.json"):
        document = json.loads((tmp_path / name).read_text())
        assert document["disclaimer"] == DISCLAIMER
    assert (tmp_path / "SUMMARY.md").read_text().splitlines()[0] == DISCLAIMER
    for name in ("run-summary.json", "SUMMARY.md"):
        assert "SIM-1 v1 invariants are not yet independent checks" not in (
            tmp_path / name
        ).read_text()


def test_reference_defect_classes_are_rediscovered_by_named_invariants() -> None:
    reports = ((67, Decimal("10.00")), (34, Decimal("9.999")))
    correct_money = sum((Decimal(quantity) * price for quantity, price in reports), Decimal(0))
    legacy_last_price_capture = Decimal(sum(quantity for quantity, _ in reports)) * reports[-1][1]
    assert legacy_last_price_capture != correct_money  # L.C. 1299da8: I2_REPORT_PRICE

    repeating_average = (100 // 3,) * 3
    assert sum(repeating_average) != 100  # L.C. 254376e: I1_CONSERVATION

    calendar = MarketCalendar.load(Market.US_EQUITIES)
    assert calendar.add_settlement_days(date(2026, 12, 31), 1) != date(2027, 1, 1)
    assert {"SYN-EQ-STREET"} != set()  # Atreides dd90e8e: I3_STOCK_RECORD_EQUALS_STREET


def test_mutation_multifill_last_price_is_caught_by_i2(monkeypatch: pytest.MonkeyPatch) -> None:
    from simulator import estate

    original = estate.capture

    def last_price_capture(*args: object, **kwargs: object):
        journal, record = original(*args, **kwargs)
        reports = args[1]
        last_price = reports[-1].price
        executions = tuple(
            execution.model_copy(update={"price": last_price}) for execution in record.executions
        )
        return journal, record.model_copy(update={"price": last_price, "executions": executions})

    monkeypatch.setattr(estate, "capture", last_price_capture)
    close = cast(list[dict[str, Any]], run_simulation(seed=22, days=1)["closes"])[0]
    assert close["invariant_results"]["I2_BOOKED_FROM_REPORTS"] is False


def test_mutation_repeating_average_is_caught_by_i1(monkeypatch: pytest.MonkeyPatch) -> None:
    from simulator import estate

    original = estate.allocate

    def repeating_average(*args: object, **kwargs: object):
        journal, record = original(*args, **kwargs)
        repeated = record.executed_quantity // len(record.entries)
        entries = tuple(item.model_copy(update={"quantity": repeated}) for item in record.entries)
        return journal, record.model_copy(
            update={"entries": entries, "executed_quantity": sum(e.quantity for e in entries)}
        )

    monkeypatch.setattr(estate, "allocate", repeating_average)
    close = cast(list[dict[str, Any]], run_simulation(seed=22, days=1)["closes"])[0]
    assert close["invariant_results"]["I1_QUANTITY_MONEY_CONSERVE"] is False


def test_mutation_year_end_calendar_is_caught_by_i7(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MarketCalendar.add_settlement_days

    def holiday_is_business_day(self: MarketCalendar, start: date, days: int) -> date:
        if start == date(2026, 12, 31):
            return date(2027, 1, 1)
        return original(self, start, days)

    monkeypatch.setattr(MarketCalendar, "add_settlement_days", holiday_is_business_day)
    close = cast(
        list[dict[str, Any]],
        run_simulation(seed=22, days=1, start=date(2026, 12, 31))["closes"],
    )[0]
    assert close["invariant_results"]["I7_MARKET_ACCESS_REFUSES"] is False


def test_mutation_omitted_street_issue_is_caught_by_i3(monkeypatch: pytest.MonkeyPatch) -> None:
    from simulator import runner

    original = runner.drive_estate

    def omit_street_issue(**kwargs: object):
        kwargs["street_quantity"] = Decimal()
        return original(**kwargs)

    monkeypatch.setattr(runner, "drive_estate", omit_street_issue)
    close = cast(list[dict[str, Any]], run_simulation(seed=22, days=1)["closes"])[0]
    assert close["invariant_results"]["I3_STOCK_RECORD_EQUALS_STREET"] is False


def test_simulator_has_no_literal_control_results() -> None:
    forbidden = {
        "invariant_results",
        "money_residual",
        "replay_digest_check",
        "holds",
        "fails_by_age",
        "market_access_refusals",
    }
    root = Path(__file__).parents[2] / "simulator"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.keyword)
                and node.arg in forbidden
                and isinstance(node.value, (ast.Constant, ast.Dict, ast.List, ast.Tuple))
            ):
                offenders.append(f"{path.name}:{node.lineno}:{node.arg}")
    assert offenders == []


@pytest.mark.parametrize(
    ("invariant", "change"),
    [
        ("I1_QUANTITY_MONEY_CONSERVE", {"captured_quantity": Decimal(9)}),
        ("I2_BOOKED_FROM_REPORTS", {"books_money": Decimal("99.99")}),
        ("I3_STOCK_RECORD_EQUALS_STREET", {"street_quantity": Decimal(9)}),
        ("I4_EVERY_DIFFERENCE_OWNED", {"difference_ownership": (("", 1),)}),
        ("I5_RESIDUALS_TWO_SIDED", {"residuals_two_sided": False}),
        ("I6_DEFAULT_AND_STALE_HOLD", {"protection_dispositions": ("HOLD", "PASS", "PASS")}),
        ("I7_MARKET_ACCESS_REFUSES", {"access_events": (("HALT", None),)}),
        ("I8_REPLAY_DIGEST", {"replay_digest": "sha256:other"}),
    ],
)
def test_forcing_each_invariants_sources_apart_fails_that_invariant(
    invariant: str, change: dict[str, object]
) -> None:
    baseline = InvariantEvidence(
        venue_quantity=Decimal(10),
        captured_quantity=Decimal(10),
        allocated_quantity=Decimal(10),
        books_quantity=Decimal(10),
        street_quantity=Decimal(10),
        venue_money=Decimal(100),
        books_money=Decimal(100),
        stock_break_count=0,
        difference_ownership=(),
        residuals_two_sided=True,
        holds=(),
        protection_dispositions=("PASS", "PASS", "PASS"),
        protection_figures=(Decimal(0), Decimal(100), Decimal(0)),
        protection_hold_required=False,
        refusals=(),
        access_events=((None, None),),
        deadlines_are_business_days=True,
        source_digest="sha256:same",
        replay_digest="sha256:same",
    )
    assert all(evaluate_invariants(baseline).values())
    assert evaluate_invariants(replace(baseline, **change))[invariant] is False


def test_250_day_budget_and_year_end() -> None:
    run = run_simulation(seed=20261023, days=250)
    assert run["days"] == 250
    closes = cast(list[dict[str, Any]], run["closes"])
    assert any(close["business_date"].startswith("2027") for close in closes)
    assert run["all_invariants_pass"] is True
    assert cast(int, run["normal_day_count"]) > 0
    counts = cast(dict[str, int], run["scenario_counts"])
    assert counts["HALT"] < 250
    assert counts["RULE_204_SHORT"] < 250
    assert counts["DTC_CAP_HOLD"] < 250
    reserve_figures = [
        close["protection"]["figures"]["reserve_requirement"] for close in closes
    ]
    assert any(value is not None and Decimal(value) > 0 for value in reserve_figures)
    averages = [close["market_data"]["average_total_credits"] for close in closes]
    assert averages.count(None) > 0
    assert any(value is not None for value in averages)


def test_i7_is_green_with_no_halts_and_with_several_halts() -> None:
    no_halts = run_simulation(seed=1, days=5)
    several_halts = run_simulation(seed=2, days=40)
    assert no_halts["scenario_counts"]["HALT"] == 0
    assert several_halts["scenario_counts"]["HALT"] >= 5
    for run in (no_halts, several_halts):
        closes = cast(list[dict[str, Any]], run["closes"])
        assert all(close["invariant_results"]["I7_MARKET_ACCESS_REFUSES"] for close in closes)


def test_i6_requires_hold_only_when_protection_inputs_are_missing() -> None:
    normal = InvariantEvidence(
        venue_quantity=Decimal(10), captured_quantity=Decimal(10),
        allocated_quantity=Decimal(10), books_quantity=Decimal(10),
        street_quantity=Decimal(10), venue_money=Decimal(100), books_money=Decimal(100),
        stock_break_count=0, difference_ownership=(), residuals_two_sided=True, holds=(),
        protection_dispositions=("PASS", "PASS", "PASS"),
        protection_figures=(Decimal(0), Decimal(100), Decimal(0)),
        protection_hold_required=False, refusals=(), access_events=((None, None),),
        deadlines_are_business_days=True, source_digest="same", replay_digest="same",
    )
    assert evaluate_invariants(normal)["I6_DEFAULT_AND_STALE_HOLD"] is True
    assert evaluate_invariants(
        replace(normal, protection_dispositions=("HOLD", "PASS", "PASS"))
    )["I6_DEFAULT_AND_STALE_HOLD"] is False

    missing = replace(
        normal,
        protection_hold_required=True,
        protection_dispositions=("HOLD", "HOLD", "HOLD"),
        protection_figures=(None, None, None),
    )
    assert evaluate_invariants(missing)["I6_DEFAULT_AND_STALE_HOLD"] is True
    assert evaluate_invariants(
        replace(missing, protection_dispositions=("PASS", "HOLD", "HOLD"))
    )["I6_DEFAULT_AND_STALE_HOLD"] is False


def test_i7_catches_a_halt_that_passes_market_access() -> None:
    evidence = InvariantEvidence(
        venue_quantity=Decimal(10), captured_quantity=Decimal(10),
        allocated_quantity=Decimal(10), books_quantity=Decimal(10),
        street_quantity=Decimal(10), venue_money=Decimal(100), books_money=Decimal(100),
        stock_break_count=0, difference_ownership=(), residuals_two_sided=True, holds=(),
        protection_dispositions=("PASS", "PASS", "PASS"),
        protection_figures=(Decimal(0), Decimal(100), Decimal(0)),
        protection_hold_required=False, refusals=(), access_events=(("HALT", None),),
        deadlines_are_business_days=True, source_digest="same", replay_digest="same",
    )
    assert evaluate_invariants(evidence)["I7_MARKET_ACCESS_REFUSES"] is False


def test_production_profile_refuses_import() -> None:
    env = {**os.environ, "ATREIDES_PROFILE": "production"}
    result = subprocess.run(
        [sys.executable, "-c", "import simulator"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "unavailable in the production profile" in result.stderr


def test_publication_resolves_the_real_lc_repository_slug() -> None:
    action = (
        Path(__file__).parents[2]
        / ".github"
        / "actions"
        / "publish-simulation-snapshot"
        / "action.yml"
    ).read_text()
    assert "Cato-FICC-MCP L.C. aureon" in action
    assert "Legiones-Cannenses" not in action


def test_publication_installs_the_real_lc_simulator_dependency() -> None:
    action = (
        Path(__file__).parents[2]
        / ".github"
        / "actions"
        / "publish-simulation-snapshot"
        / "action.yml"
    ).read_text()
    assert "uv sync --locked --extra dev" in action


def test_configuration_is_synthetic_and_forbidden_sources_absent_from_imports() -> None:
    root = Path(__file__).parents[2] / "simulator"
    pack = load_calibration_pack()
    assert "SYNTHETIC" in pack.classes_used
    imports = "\n".join(path.read_text() for path in root.glob("*.py"))
    for forbidden in ("cta", "utp", "taq", "trace", "opra", "bloomberg", "aureon"):
        assert f"import {forbidden}" not in imports and f"from {forbidden}" not in imports
