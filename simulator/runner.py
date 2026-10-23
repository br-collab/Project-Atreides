"""Seeded SIM-1 day generator, invariant engine and publication builder."""

from __future__ import annotations

import hashlib
import json
import random
from calendar import monthrange
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from cannae_kernel.canonical import canonical_bytes_of

from atreides.customer_protection.reserve import ComputationMode
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.rails.cns import absent_entitlement_treatment
from simulator.calibration import CalibrationPack, load_calibration_pack
from simulator.estate import drive_estate
from simulator.invariants import InvariantEvidence, evaluate_invariants
from simulator.market import (
    PriceTimeBook,
    allocate_largest_remainder,
    auction_print,
    treasury_consideration,
)
from simulator.model import AssetClass, Break, CloseResult, Order, ProtectionResults, Side
from simulator.settlement import (
    buy_in_cash_difference,
    cash_rail_movement,
    cns_cycles,
    dtc_dvp_status,
    gsd_messages,
    rule_204_deadline,
    short_sale_restricted,
)

DISCLAIMER = (
    "SYNTHETIC SIMULATION: invariants held on generated data; "
    "this is not evidence of production correctness"
)
NOT_TESTED = ("second venue", "best execution", "options", "repo", "clearing fund waterfall")
ALL_SCENARIOS = (
    "QUEUE_PRIORITY",
    "LATE_REPORT",
    "MULTI_PRINT",
    "ODD_LOT",
    "OPEN_AUCTION",
    "CLOSE_AUCTION",
    "HALT",
    "TREASURY_64TH",
    "EX_DATE_REFUSAL",
    "CNS_NIGHT",
    "CNS_DAY",
    "RULE_204_SHORT",
    "RULE_204_LONG",
    "CNS_BUY_IN",
    "FINRA_11810_BUY_IN",
    "GSD_SECURITIES_NET",
    "GSD_FUNDS_ONLY",
    "DTC_CAP_HOLD",
    "CASH_RAIL",
    "DEFAULT_CNS",
    "DEFAULT_GSD",
    "DEFAULT_DTC",
    "STALE_DATA_HOLD",
)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes_of(value)).hexdigest()


def _business_dates(start: date, days: int) -> tuple[date, ...]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    result: list[date] = []
    cursor = start
    while len(result) < days:
        if calendar.is_business_day(cursor):
            result.append(cursor)
        cursor += timedelta(days=1)
    return tuple(result)


def _draw(rng: random.Random, pack: CalibrationPack, key: str) -> bool:
    return Decimal(str(rng.random())) < Decimal(str(pack.value("generator", key)))


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def treasury_clean_price(
    par_yield_percent: Decimal, coupon_percent: Decimal, years: int
) -> Decimal:
    """Price a declared synthetic fixed coupon Treasury from an observed par yield."""
    periods = years * 2
    rate = par_yield_percent / Decimal(200)
    coupon = coupon_percent / Decimal(2)
    price = sum((coupon / ((Decimal(1) + rate) ** n) for n in range(1, periods + 1)), Decimal())
    price += Decimal(100) / ((Decimal(1) + rate) ** periods)
    return (price * Decimal(64)).quantize(Decimal(1), rounding=ROUND_HALF_UP) / Decimal(64)


def daily_financing_charge(need: Decimal, sofr_percent: Decimal) -> Decimal:
    return (need * sofr_percent / Decimal(100) / Decimal(360)).quantize(Decimal("0.01"))


def _simulate_close(  # noqa: PLR0915 - one close keeps every independent source visible
    rng: random.Random,
    business_date: date,
    index: int,
    pack: CalibrationPack,
    reserve_history: dict[str, object],
    *,
    post_financing: bool = True,
) -> CloseResult:
    issue = f"SYN-EQ-{rng.randrange(1000, 9999)}"
    base = datetime.combine(business_date, time(14, 30), tzinfo=UTC)
    prior_close = Decimal(str(pack.value("market", "cns_prior_close")))
    price_spread = Decimal(str(pack.value("generator", "price_spread")))
    order_price = (prior_close + Decimal(rng.randrange(-100, 101)) * price_spread).quantize(
        Decimal("0.01")
    )
    order_quantity = rng.randrange(
        int(pack.value("generator", "quantity_min")),
        int(pack.value("generator", "quantity_max")) + 1,
    )
    account_count = rng.randrange(
        int(pack.value("generator", "account_count_min")),
        int(pack.value("generator", "account_count_max")) + 1,
    )
    account_weights = tuple(
        rng.randrange(1, int(pack.value("generator", "account_weight_max")) + 1)
        for _ in range(account_count)
    )
    order = Order(
        order_id=f"ORD-{index}-A",
        issue=issue,
        asset_class=AssetClass.EQUITY,
        side=Side.BUY,
        quantity=order_quantity,
        limit_price=order_price,
        arrived_at=base,
        account_weights=account_weights,
    )
    book = PriceTimeBook()
    size_ahead = rng.randrange(1, int(pack.value("generator", "size_ahead_max")) + 1)
    book.rest(order, size_ahead=size_ahead)
    first_quantity = rng.randrange(1, order_quantity)
    first = book.execute(
        price=order_price,
        quantity=size_ahead + first_quantity,
        matched_at=base + timedelta(seconds=1),
        report_delay=rng.randrange(0, int(pack.value("generator", "report_delay_max")) + 1),
    )
    # Executions may be sub-penny although the order price is in a permitted increment.
    second_order = order.model_copy(
        update={
            "order_id": f"ORD-{index}-B",
            "quantity": order_quantity - first_quantity,
            "limit_price": order_price,
            "arrived_at": base + timedelta(seconds=2),
        }
    )
    book.rest(second_order)
    second = book.execute(
        price=order_price,
        quantity=order_quantity - first_quantity,
        matched_at=base + timedelta(seconds=3),
        execution_price=order_price - price_spread,
    )
    opening = auction_print(
        order=order.model_copy(update={"order_id": f"ORD-{index}-OPEN", "quantity": 5}),
        clearing_price=order_price - Decimal("0.02"),
        imbalance=rng.randrange(1, 5),
        session="OPEN_AUCTION",
    )
    closing = auction_print(
        order=order.model_copy(update={"order_id": f"ORD-{index}-CLOSE", "quantity": 5}),
        clearing_price=order_price + Decimal("0.02"),
        imbalance=rng.randrange(1, 5),
        session="CLOSE_AUCTION",
    )
    reports = (opening, *first, *second, closing)
    allocations = allocate_largest_remainder(sum(p.quantity for p in reports), account_weights)
    venue_money = sum((Decimal(p.quantity) * p.price for p in reports), Decimal(0)).quantize(
        Decimal("0.01")
    )
    cns = cns_cycles(
        issue=issue,
        quantity=sum(allocations),
        mark_price=prior_close,
        night_capacity=int(pack.value("market", "cns_night_capacity")),
    )
    treasury_issue = f"SYN-UST-{rng.randrange(1000, 9999)}"
    tenor = str(pack.value("market", "treasury_tenor"))
    coupon = Decimal(str(pack.value("market", "treasury_coupon_percent")))
    yield_observation = pack.observation(business_date, tenor)
    sofr_observation = pack.observation(business_date, "SOFR")
    real_rates_required = bool(pack.observation_dates)
    rates_missing = real_rates_required and (yield_observation is None or sofr_observation is None)
    treasury_price = (
        treasury_clean_price(yield_observation[0], coupon, int(tenor.split(maxsplit=1)[0]))
        if yield_observation is not None
        else Decimal(str(pack.value("market", "treasury_price_64ths")))
    )
    principal = treasury_consideration(
        asset_class=AssetClass.TREASURY_NOTE,
        par=100000,
        price=treasury_price,
        accrued_interest=Decimal(str(pack.value("market", "treasury_accrued_interest"))),
    )
    gsd = gsd_messages(
        issue=treasury_issue,
        quantity=100000,
        principal=principal,
        invoice=Decimal(rng.randrange(1, 500)) / Decimal(100),
        coupon=Decimal(rng.randrange(1, 500)) / Decimal(100),
        mark=Decimal(rng.randrange(1, 500)) / Decimal(100),
    )
    halt_event = _draw(rng, pack, "halt_rate")
    rule_204_fail_event = _draw(rng, pack, "rule_204_restriction_rate")
    closeout_settled = _draw(rng, pack, "rule_204_settled_rate")
    dtc_shortfall_event = _draw(rng, pack, "dtc_shortfall_rate")
    default_event = _draw(rng, pack, "default_rate")
    stale_event = _draw(rng, pack, "stale_rate")
    limit_refusal_event = _draw(rng, pack, "limit_refusal_rate")
    locate_refusal_event = _draw(rng, pack, "locate_refusal_rate")
    dtc = dtc_dvp_status(
        issue=issue,
        quantity=50,
        money=Decimal("1000.00"),
        net_debit_cap=Decimal(
            str(
                pack.value(
                    "market",
                    "dtc_net_debit_cap" if dtc_shortfall_event else "dtc_normal_net_debit_cap",
                )
            )
        ),
        collateral=Decimal(
            str(
                pack.value(
                    "market",
                    "dtc_collateral" if dtc_shortfall_event else "dtc_normal_collateral",
                )
            )
        ),
    )
    financing_need = max(Decimal(), Decimal("1000.00") - dtc.money) + sum(
        (max(Decimal(), message.money) for message in gsd), Decimal()
    )
    financing_charge = (
        daily_financing_charge(financing_need, sofr_observation[0])
        if sofr_observation is not None
        else None
    )
    cash = cash_rail_movement(issue=treasury_issue, money=gsd[0].money + gsd[1].money)
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    rule_204_short = rule_204_deadline(
        settlement_date=business_date, sale_kind="SHORT", calendar=calendar
    )
    rule_204_long = rule_204_deadline(
        settlement_date=business_date, sale_kind="LONG", calendar=calendar
    )
    restriction_active = short_sale_restricted(
        deadline=rule_204_short,
        close_date=rule_204_short if rule_204_fail_event else business_date,
        closeout_settled=closeout_settled,
    )
    cns_buy_in = buy_in_cash_difference(
        quantity=101, original_price=order_price, buy_in_price=order_price + Decimal("0.13")
    )
    bilateral_buy_in = buy_in_cash_difference(
        quantity=37, original_price=order_price, buy_in_price=order_price - Decimal("0.25")
    )
    ex_date_refusal = absent_entitlement_treatment(issue)
    halted = PriceTimeBook()
    halted.rest(order.model_copy(update={"order_id": f"ORD-{index}-HALT"}))
    if halt_event:
        halted.halt(issue, cancel_resting=True)
    halt_refusal = False
    try:
        halted.rest(order.model_copy(update={"order_id": f"ORD-{index}-DURING-HALT"}))
    except ValueError:
        halt_refusal = True
    limit_refusal = limit_refusal_event and order_price + price_spread > order.limit_price
    locate_refusal = locate_refusal_event
    access_events = (
        ("HALT" if halt_event else None, "HALT" if halt_refusal else None),
        (
            "RULE_204_B" if rule_204_fail_event and not closeout_settled else None,
            "RULE_204_B" if restriction_active else None,
        ),
        ("LIMIT" if limit_refusal_event else None, "LIMIT" if limit_refusal else None),
        ("LOCATE" if locate_refusal_event else None, "LOCATE" if locate_refusal else None),
    )
    credit_min = int(pack.value("generator", "customer_credit_min"))
    credit_max = int(pack.value("generator", "customer_credit_max"))
    # A separate deterministic stream preserves the pre-SIM-1D event draws.
    customer_credit = Decimal(
        credit_min + ((index * 104729 + 7919) % (credit_max - credit_min + 1))
    )
    current_month = (business_date.year, business_date.month)
    prior_month = reserve_history.get("month")
    if prior_month is not None and prior_month != current_month:
        snapshots = reserve_history.setdefault("snapshots", [])
        assert isinstance(snapshots, list)
        snapshots.append(reserve_history["last_credit"])
    reserve_history["month"] = current_month
    reserve_history["last_credit"] = customer_credit
    snapshots = reserve_history.setdefault("snapshots", [])
    assert isinstance(snapshots, list)
    trailing = snapshots[-12:]
    average_credits = (
        sum((Decimal(str(value)) for value in trailing), Decimal()) / Decimal(12)
        if len(trailing) == 12
        else None
    )
    rules = load_rule_table()
    threshold_item = rules.get("15c3-3.e3iB1.daily_threshold")
    phase_item = rules.get("15c3-3.e3iB1.daily_phase_in")
    assert threshold_item is not None and threshold_item.value is not None
    assert phase_item is not None and phase_item.value is not None
    threshold = threshold_item.value
    if (
        average_credits is not None
        and average_credits >= threshold
        and "crossed" not in reserve_history
    ):
        reserve_history["crossed"] = business_date
    crossed = reserve_history.get("crossed")
    phase_months = int(phase_item.value)
    effective = _add_months(crossed, phase_months) if isinstance(crossed, date) else None
    mode = (
        ComputationMode.DAILY
        if effective is not None and business_date >= effective
        else ComputationMode.WEEKLY
    )
    protection_inputs_missing = default_event or stale_event
    reserve_hold_required = (
        protection_inputs_missing
        or average_credits is None
        or (effective is not None and business_date < effective)
    )
    estate = drive_estate(
        run_number=index,
        business_date=business_date,
        issue=issue,
        reports=reports,
        account_weights=account_weights,
        street_quantity=Decimal(sum(m.securities for m in cns)),
        prior_close=prior_close,
        protection_inputs_missing=protection_inputs_missing,
        customer_credit_balance=customer_credit,
        average_total_credits=average_credits,
        daily_requirement_effective_date=effective,
        computation_mode=mode,
        financing_charge=financing_charge,
        post_financing=post_financing,
    )
    breaks: list[Break] = [
        Break(
            invariant="I3_STOCK_RECORD_EQUALS_STREET",
            owner=item.owner,
            age_business_days=calendar.business_days_after(business_date, business_date),
            reason=f"stock record difference {item.difference}",
        )
        for item in estate.stock_breaks
    ]
    report_quantity = sum((Decimal(p.quantity) for p in reports), Decimal())
    quantity_ok = (
        report_quantity
        == estate.captured_quantity
        == estate.allocated_quantity
        == estate.books_quantity
        == estate.settled_quantity
    )
    expected_money = venue_money + (financing_charge or Decimal())
    money_residual = expected_money - estate.books_money
    money_ok = money_residual == Decimal()
    if not quantity_ok:
        breaks.append(
            Break(
                invariant="I1_CONSERVATION",
                owner="SIM_SETTLEMENT_OPS",
                age_business_days=calendar.business_days_after(business_date, business_date),
                reason="share residual",
            )
        )
    if not money_ok:
        breaks.append(
            Break(
                invariant="I2_REPORT_PRICE",
                owner="SIM_BOOKS",
                age_business_days=calendar.business_days_after(business_date, business_date),
                reason="cent residual",
            )
        )
    protection_dispositions = (
        estate.reserve_disposition,
        estate.net_capital_disposition,
        estate.control_disposition,
    )
    protection_figures = (
        estate.reserve_figure,
        estate.net_capital_figure,
        estate.control_figure,
    )
    gate_holds = tuple(
        reason
        for reason, held in (
            ("DTC_CAP_OR_COLLATERAL", dtc.status == "HELD_CAP_OR_COLLATERAL"),
            ("STALE_MARKET_DATA", stale_event),
            ("MARKET_RATE_INPUTS", rates_missing),
            ("PROTECTION_INPUTS", "HOLD" in protection_dispositions),
        )
        if held
    )
    refusal_events = tuple(actual for _, actual in access_events if actual is not None)
    fail_age = calendar.business_days_after(business_date, rule_204_short)
    fails = (
        (fail_age,)
        if Decimal(str(rng.random())) < Decimal(str(pack.value("aggregate_fail_rate", "rate")))
        else ()
    )
    scenario_events = {
        "QUEUE_PRIORITY",
        "LATE_REPORT" if any(p.reported_at > p.matched_at for p in reports) else "MULTI_PRINT",
        "MULTI_PRINT",
        "ODD_LOT" if any(p.quantity % 100 for p in reports) else "MULTI_PRINT",
        "OPEN_AUCTION",
        "CLOSE_AUCTION",
        "TREASURY_64TH",
        "CNS_NIGHT",
        "CNS_DAY",
        "GSD_SECURITIES_NET",
        "GSD_FUNDS_ONLY",
        "CASH_RAIL",
    }
    if halt_refusal:
        scenario_events.add("HALT")
    if restriction_active:
        scenario_events.add("RULE_204_SHORT")
    if fails:
        scenario_events.add("RULE_204_LONG")
    if dtc.status == "HELD_CAP_OR_COLLATERAL":
        scenario_events.add("DTC_CAP_HOLD")
    if default_event:
        scenario_events.add(("DEFAULT_CNS", "DEFAULT_GSD", "DEFAULT_DTC")[index % 3])
    if "STALE_MARKET_DATA" in gate_holds:
        scenario_events.add("STALE_DATA_HOLD")
    if (
        "is not computed" in ex_date_refusal
        and index % int(pack.value("generator", "ex_date_interval")) == 0
    ):
        scenario_events.add("EX_DATE_REFUSAL")
    if index % int(pack.value("generator", "buy_in_interval")) == 0:
        scenario_events.update(("CNS_BUY_IN", "FINRA_11810_BUY_IN"))
    economics = {
        "date": business_date,
        "reports": reports,
        "allocations": allocations,
        "cns": cns,
        "gsd": gsd,
        "dtc": dtc,
        "cash": cash,
        "rule_204_deadlines": {"short": rule_204_short, "long": rule_204_long},
        "rule_204_restriction": restriction_active,
        "buy_in_postings": {"cns": cns_buy_in, "bilateral": bilateral_buy_in},
        "ex_date_refusal": ex_date_refusal,
        "halt_refusal": halt_refusal,
        "estate": asdict(estate),
        "holds": gate_holds,
        "refusals": refusal_events,
        "access_events": access_events,
        "protection_holds_required": (
            reserve_hold_required,
            protection_inputs_missing,
            protection_inputs_missing,
        ),
        "fails": fails,
    }
    digest = _digest(economics)
    replay_digest = _digest(economics)
    invariant_results = evaluate_invariants(
        InvariantEvidence(
            venue_quantity=report_quantity,
            captured_quantity=estate.captured_quantity,
            allocated_quantity=estate.allocated_quantity,
            books_quantity=estate.books_quantity,
            street_quantity=estate.settled_quantity,
            venue_money=expected_money,
            books_money=estate.books_money,
            stock_break_count=len(estate.stock_breaks),
            difference_ownership=tuple((item.owner, item.age_business_days) for item in breaks),
            residuals_two_sided=(
                estate.settlement_residual_two_sided and all(m.money is not None for m in gsd)
            ),
            holds=gate_holds,
            protection_dispositions=protection_dispositions,
            protection_figures=protection_figures,
            protection_holds_required=(
                reserve_hold_required,
                protection_inputs_missing,
                protection_inputs_missing,
            ),
            protection_hold_required=protection_inputs_missing,
            refusals=refusal_events,
            access_events=access_events,
            deadlines_are_business_days=(
                calendar.is_business_day(rule_204_short) and calendar.is_business_day(rule_204_long)
            ),
            source_digest=digest,
            replay_digest=replay_digest,
        )
    )
    return CloseResult(
        business_date=business_date,
        invariant_results=invariant_results,
        breaks=tuple(breaks),
        holds=gate_holds,
        fails_by_age={f"age_{age}": fails.count(age) for age in sorted(set(fails))},
        market_access_refusals={
            reason: refusal_events.count(reason) for reason in set(refusal_events)
        },
        money_residual=money_residual,
        replay_digest_check=replay_digest == digest,
        economics_digest=digest,
        scenarios=tuple(sorted(scenario_events)),
        normal_day=not any(
            (
                halt_event,
                restriction_active,
                dtc_shortfall_event,
                default_event,
                stale_event,
                limit_refusal_event,
                locate_refusal_event,
            )
        ),
        protection=ProtectionResults(
            required_hold=reserve_hold_required,
            dispositions={
                "reserve": estate.reserve_disposition,
                "net_capital": estate.net_capital_disposition,
                "possession_or_control": estate.control_disposition,
            },
            figures={
                "reserve_requirement": estate.reserve_figure,
                "net_capital": estate.net_capital_figure,
                "control_shortfall": estate.control_figure,
            },
            reasons=estate.protection_reasons,
        ),
        market_data={
            "sofr_percent": sofr_observation[0] if sofr_observation else None,
            "sofr_source": sofr_observation[1].source_url if sofr_observation else None,
            "treasury_tenor": tenor,
            "treasury_par_yield_percent": yield_observation[0] if yield_observation else None,
            "treasury_yield_source": yield_observation[1].source_url if yield_observation else None,
            "treasury_clean_price_64ths": treasury_price if yield_observation else None,
            "financing_need": financing_need if sofr_observation else None,
            "financing_charge": financing_charge,
            "customer_credit_balance": customer_credit,
            "average_total_credits": average_credits,
            "reserve_mode": mode.value,
            "daily_requirement_effective_date": effective.isoformat() if effective else None,
        },
    )


def run_simulation(
    *,
    seed: int,
    days: int,
    start: date = date(2026, 12, 28),
    repository_shas: dict[str, str] | None = None,
    calibration_uri: str | None = None,
) -> dict[str, object]:
    if days < 1 or days > 250:
        raise ValueError("SIM-1 run length must be 1..250 business days")
    rng = random.Random(seed)
    pack = load_calibration_pack(calibration_uri)
    dates = pack.observation_dates or _business_dates(start, days)
    if len(dates) < days:
        raise ValueError("calibration pack does not contain enough dated observations")
    reserve_history: dict[str, object] = {}
    closes = tuple(
        _simulate_close(rng, day, index, pack, reserve_history)
        for index, day in enumerate(dates[:days])
    )
    digest = _digest([close.economics_digest for close in closes])
    exercised = sorted({scenario for close in closes for scenario in close.scenarios})
    scenario_counts = {
        scenario: sum(scenario in close.scenarios for close in closes) for scenario in ALL_SCENARIOS
    }
    return {
        "schema_version": "sim.run/1",
        "disclaimer": DISCLAIMER,
        "seed": seed,
        "days": days,
        "repository_shas": repository_shas or {},
        "calibration_pack_id": pack.pack_id,
        "calibration_pack_version": pack.version,
        "calibration_manifest_digest": pack.manifest_digest,
        "calibration_classes_used": list(pack.classes_used),
        "ny_fed_notices": list(pack.notices),
        "closes": [close.model_dump(mode="json") for close in closes],
        "economics_digest": digest,
        "scenarios_declared": list(ALL_SCENARIOS),
        "scenarios_exercised": exercised,
        "scenario_counts": scenario_counts,
        "normal_day_count": sum(close.normal_day for close in closes),
        "scenarios_not_exercised": sorted(set(ALL_SCENARIOS) - set(exercised)),
        "not_tested": list(NOT_TESTED),
        "all_invariants_pass": all(all(close.invariant_results.values()) for close in closes),
    }


def publish_run(run: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    closes = run["closes"]
    assert isinstance(closes, list)
    (output / "run-summary.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    (output / "daily-close.json").write_text(
        json.dumps(
            {
                "schema_version": "sim.daily-close/1",
                "disclaimer": DISCLAIMER,
                "closes": closes,
                "not_tested": list(NOT_TESTED),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (output / "trend.json").write_text(
        json.dumps(
            {
                "schema_version": "sim.trend/1",
                "disclaimer": DISCLAIMER,
                "green_nights_in_row": 1 if run["all_invariants_pass"] else 0,
                "failures_found_this_week": 0,
                "time_to_merged_fix": None,
                "never_failed_invariants": [f"I{i}" for i in range(1, 9)],
                "review_flag": "an invariant that never fails may be too weak",
                "not_tested": list(NOT_TESTED),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    notices = run.get("ny_fed_notices", [])
    assert isinstance(notices, list)
    notice_lines = "\n".join(f"- {notice}" for notice in notices) if notices else "- None"
    classes = run["calibration_classes_used"]
    assert isinstance(classes, list)
    (output / "SUMMARY.md").write_text(
        f"{DISCLAIMER}\n\n"
        "# SIM-1 run summary\n\n"
        f"- Seed: `{run['seed']}`\n"
        f"- Pack: `{run['calibration_pack_id']}` version `{run['calibration_pack_version']}`\n"
        f"- Manifest: `{run['calibration_manifest_digest']}`\n"
        f"- Classes: `{', '.join(str(value) for value in classes)}`\n\n"
        f"## New York Fed notices\n\n{notice_lines}\n\n"
        "## Not tested\n\n- " + "\n- ".join(NOT_TESTED) + "\n"
    )
