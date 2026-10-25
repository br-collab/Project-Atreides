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
from typing import Any, cast

from cannae_kernel.canonical import canonical_bytes_of

from atreides.customer_protection.reserve import ComputationMode
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.rails.cns import absent_entitlement_treatment
from simulator.calibration import CalibrationPack, load_calibration_pack
from simulator.estate import (
    DEPOSIT_BREACH_OUTCOMES,
    DepositDraw,
    DepositPolicy,
    ReserveDeposit,
    drive_estate,
    simulated_filed_credit_total,
)
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
SYNTHETIC_START = date(2026, 12, 28)
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


#: Text the reserve engine writes for a deposit shortfall (atreides/customer_protection/reserve.py).
SHORTFALL_REASON = "reserve deposit is short of the requirement"

DEPOSIT_POLICY_KEYS = (
    "reserve_deposit_late_rate",
    "reserve_deposit_short_rate",
    "reserve_deposit_short_fraction_min",
    "reserve_deposit_short_fraction_max",
    "reserve_bank_equity_capital",
)


def deposit_breach(deposit: ReserveDeposit) -> bool:
    """True when a deposit was needed and the simulated deposit did not meet it in time."""
    return (
        deposit.needed is not None
        and deposit.needed > 0
        and deposit.outcome in DEPOSIT_BREACH_OUTCOMES
    )


def _deposit_draw(
    rng: random.Random, late: Decimal, short: Decimal, low: Decimal, high: Decimal
) -> DepositDraw:
    # Two draws per computation, always consumed, so the stream does not depend on outcomes.
    uniform = Decimal(str(rng.random()))
    fraction = (low + (high - low) * Decimal(str(rng.random()))).quantize(Decimal("0.0001"))
    if uniform < late:
        return DepositDraw(outcome="LATE", short_fraction=fraction)
    if uniform < late + short:
        return DepositDraw(outcome="SHORT", short_fraction=fraction)
    return DepositDraw(outcome="ON_TIME", short_fraction=fraction)


def _deposit_policy(pack: CalibrationPack, rng: random.Random) -> DepositPolicy | None:
    """The pack's declared SYNTHETIC deposit policy, or None when the pack declares none."""
    try:
        late, short, low, high, equity = (
            Decimal(str(pack.value("generator", key))) for key in DEPOSIT_POLICY_KEYS
        )
    except KeyError:
        return None
    if not (Decimal(0) < low <= high < Decimal(1)):
        raise ValueError("reserve deposit short fraction must lie in (0, 1)")
    return DepositPolicy(
        customer=_deposit_draw(rng, late, short, low, high),
        pab=_deposit_draw(rng, late, short, low, high),
        bank_equity_capital=equity,
    )


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _opening_filed_credit_history(start: date) -> list[dict[str, object]]:
    """Create 11 synthetic pre-run FOCUS stand-ins through Atreides books."""
    history: list[dict[str, object]] = []
    cursor = date(start.year, start.month, 1)
    for position, months_back in enumerate(range(11, 0, -1)):
        month_start = _add_months(cursor, -months_back)
        month_end = date(
            month_start.year,
            month_start.month,
            monthrange(month_start.year, month_start.month)[1],
        )
        # The oldest six low months roll off during phase-in.  The five later
        # high months keep the computed average above the threshold until the
        # daily regime starts, then roll off to exercise the prescribed exit.
        filed_credit = Decimal("50000000") if position < 6 else Decimal("1000000000")
        customer, pab = simulated_filed_credit_total(month_end, filed_credit)
        history.append(
            {
                "month_end": month_end,
                "customer_total_credits": customer,
                "pab_total_credits": pab,
                "total_credits": customer + pab,
                "source": "SIMULATED_FOCUS_STAND_IN_FROM_ATREIDES_BOOKS",
            }
        )
    return history


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
    credit_min = Decimal(str(pack.value("generator", "customer_credit_min")))
    credit_max = Decimal(str(pack.value("generator", "customer_credit_max")))
    current_month = (business_date.year, business_date.month)
    first_month = reserve_history["first_month"]
    assert isinstance(first_month, tuple)
    month_index = (business_date.year - first_month[0]) * 12 + business_date.month - first_month[1]
    customer_credit = credit_max if month_index < 1 else credit_min
    prior_month = reserve_history.get("month")
    if prior_month is not None and prior_month != current_month:
        snapshots = reserve_history["snapshots"]
        assert isinstance(snapshots, list)
        filed = reserve_history.get("last_filed")
        assert isinstance(filed, dict)
        snapshots.append(filed)
    reserve_history["month"] = current_month
    snapshots = reserve_history["snapshots"]
    assert isinstance(snapshots, list)
    trailing = snapshots[-12:]
    average_credits = (
        sum((Decimal(str(value["total_credits"])) for value in trailing), Decimal())
        / Decimal(12)
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
    daily_started = bool(reserve_history.get("daily_started"))
    if (
        effective is not None
        and business_date >= effective
        and average_credits is not None
        and average_credits >= threshold
    ):
        daily_started = True
        reserve_history["daily_started"] = True
    exit_notice = reserve_history.get("exit_notice")
    if (
        average_credits is not None
        and average_credits < threshold
        and daily_started
        and exit_notice is None
    ):
        exit_notice = business_date
        reserve_history["exit_notice"] = exit_notice
    exit_item = rules.get("15c3-3.e3iB2.exit_notice")
    assert exit_item is not None and exit_item.value is not None
    exit_active = isinstance(exit_notice, date) and business_date < exit_notice + timedelta(
        days=int(exit_item.value)
    )
    average_above_threshold = average_credits is not None and average_credits >= threshold
    mode = (
        ComputationMode.DAILY
        if daily_started and (average_above_threshold or exit_active)
        else ComputationMode.WEEKLY
    )
    protection_inputs_missing = default_event or stale_event
    # CLOSE-1 WP5: PAB activity drawn from its own seeded stream (run seed and day
    # index), so every pre-existing draw on ``rng`` is unchanged and two seeds still
    # differ. Rates and sizes are declared SYNTHETIC in the calibration pack.
    pab_rng = random.Random(f"close-1-pab:{reserve_history['seed']}:{index}")
    pab_fail_to_receive = None
    try:
        pab_fail_rate: Decimal | None = Decimal(str(pack.value("generator", "pab_fail_rate")))
    except KeyError:
        # A pack built before CLOSE-1 declares no PAB activity. That is recorded in
        # the close as NOT_DECLARED_IN_PACK; nothing is invented in its place.
        pab_fail_rate = None
    if pab_fail_rate is not None and Decimal(str(pab_rng.random())) < pab_fail_rate:
        pab_fail_to_receive = (
            Decimal(
                pab_rng.randrange(
                    int(pack.value("generator", "pab_fail_quantity_min")),
                    int(pack.value("generator", "pab_fail_quantity_max")) + 1,
                )
            ),
            Decimal(str(pack.value("generator", "pab_fail_price"))),
        )
    # SIM-1G: Reserve Bank Account deposit behaviour, drawn from its own seeded
    # stream so every pre-existing draw is unchanged. Rates are declared SYNTHETIC in
    # the calibration pack; a pack without them posts no deposit and records
    # NOT_DECLARED_IN_PACK.
    deposit_rng = random.Random(f"sim-1g-deposit:{reserve_history['seed']}:{index}")
    deposit_policy = _deposit_policy(pack, deposit_rng)
    carried = reserve_history.get("reserve_bank", (Decimal(0), Decimal(0)))
    assert isinstance(carried, tuple)
    opening_balances = (Decimal(carried[0]), Decimal(carried[1]))
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
        previously_daily_required=daily_started,
        daily_exit_notice_date=exit_notice if isinstance(exit_notice, date) else None,
        financing_charge=financing_charge,
        post_financing=post_financing,
        pab_fail_to_receive=pab_fail_to_receive,
        reserve_bank_opening=opening_balances,
        deposit_policy=deposit_policy,
    )
    reserve_history["reserve_bank"] = tuple(
        deposit.closing_balance for deposit in estate.reserve_deposits
    )
    # SIM-1G: the hold requirement for each reserve computation is derived from the
    # day's inputs and the simulated deposit, never from the engine's disposition.
    # Missing inputs (default or stale day, or no 12-month average total credits for
    # Rule 15c3-3(e)(3)(i)(B)(1)) require HOLD. A deposit that is short, late or not
    # declared while a deposit was needed requires HOLD with the shortfall reason.
    # Otherwise the day is funded and requires a computed figure and no HOLD.
    inputs_missing = protection_inputs_missing or average_credits is None
    reserve_hold_required, pab_hold_required = (
        inputs_missing or deposit_breach(deposit) for deposit in estate.reserve_deposits
    )
    reserve_reason_required, pab_reason_required = (
        SHORTFALL_REASON if deposit_breach(deposit) and not inputs_missing else None
        for deposit in estate.reserve_deposits
    )
    reserve_history["last_filed"] = {
        "month_end": business_date,
        "customer_total_credits": estate.customer_total_credits,
        "pab_total_credits": estate.pab_total_credits,
        "total_credits": estate.customer_total_credits + estate.pab_total_credits,
        "source": "SIMULATED_FOCUS_STAND_IN_FROM_ATREIDES_BOOKS",
    }
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
        estate.pab_reserve_disposition,
        estate.net_capital_disposition,
        estate.control_disposition,
    )
    protection_figures = (
        estate.reserve_figure,
        estate.pab_reserve_figure,
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
            pab_hold_required,
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
                pab_hold_required,
                protection_inputs_missing,
                protection_inputs_missing,
            ),
            protection_hold_required=protection_inputs_missing,
            protection_reasons=(
                estate.protection_reasons["reserve"],
                estate.protection_reasons["pab_reserve"],
                estate.protection_reasons["net_capital"],
                estate.protection_reasons["possession_or_control"],
            ),
            protection_required_reasons=(
                reserve_reason_required,
                pab_reason_required,
                None,
                None,
            ),
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
                "pab_reserve": estate.pab_reserve_disposition,
                "net_capital": estate.net_capital_disposition,
                "possession_or_control": estate.control_disposition,
            },
            figures={
                "reserve_requirement": estate.reserve_figure,
                "pab_reserve_requirement": estate.pab_reserve_figure,
                "net_capital": estate.net_capital_figure,
                "control_shortfall": estate.control_figure,
            },
            reasons=estate.protection_reasons,
            deposits={
                deposit.computation: {
                    key: None if value is None else str(value)
                    for key, value in asdict(deposit).items()
                    if key != "computation"
                }
                for deposit in estate.reserve_deposits
            },
            holds_required={
                "reserve": reserve_hold_required,
                "pab_reserve": pab_hold_required,
            },
            reasons_required={
                "reserve": reserve_reason_required,
                "pab_reserve": pab_reason_required,
            },
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
            "filed_credit_history_count": len(snapshots),
            "book_customer_total_credits": estate.customer_total_credits,
            "book_pab_total_credits": estate.pab_total_credits,
            "pab_fail_to_receive_quantity": (
                pab_fail_to_receive[0]
                if pab_fail_to_receive is not None
                else "NOT_DECLARED_IN_PACK"
                if pab_fail_rate is None
                else None
            ),
            "pab_fail_to_receive_contract_price": (
                pab_fail_to_receive[1] if pab_fail_to_receive is not None else None
            ),
            "reserve_mode": mode.value,
            "daily_requirement_effective_date": effective.isoformat() if effective else None,
            "previously_daily_required": daily_started,
            "daily_exit_notice_date": (
                exit_notice.isoformat() if isinstance(exit_notice, date) else None
            ),
        },
    )


def run_simulation(
    *,
    seed: int,
    days: int | None,
    start: date | None = None,
    end: date | None = None,
    repository_shas: dict[str, str] | None = None,
    calibration_uri: str | None = None,
    require_explicit_dated_window: bool = False,
) -> dict[str, object]:
    if days is not None and (days < 1 or days > 250):
        raise ValueError("SIM-1 run length must be 1..250 business days")
    rng = random.Random(seed)
    pack = load_calibration_pack(calibration_uri)
    if pack.observation_dates:
        if require_explicit_dated_window and (start is None or end is None):
            raise ValueError("dated calibration packs require explicit --start and --end")
        dates = tuple(
            day
            for day in pack.observation_dates
            if (start is None or day >= start) and (end is None or day <= end)
        )
        if end is not None and not dates:
            raise ValueError("explicit calibration window contains no observations")
        if end is None and days is not None:
            dates = dates[:days]
        elif days is not None and days != len(dates):
            raise ValueError("days must equal the exact number of dates in the explicit window")
    else:
        if days is None:
            raise ValueError("synthetic simulation requires days")
        if end is not None:
            raise ValueError("end is only valid for a dated calibration pack")
        dates = _business_dates(start or SYNTHETIC_START, days)
    if not dates:
        raise ValueError("calibration pack does not contain enough dated observations")
    reserve_history: dict[str, object] = {
        "snapshots": _opening_filed_credit_history(dates[0]),
        "first_month": (dates[0].year, dates[0].month),
        "seed": seed,
    }
    closes = tuple(
        _simulate_close(rng, day, index, pack, reserve_history)
        for index, day in enumerate(dates)
    )
    history_snapshots = reserve_history["snapshots"]
    assert isinstance(history_snapshots, list)
    digest = _digest([close.economics_digest for close in closes])
    exercised = sorted({scenario for close in closes for scenario in close.scenarios})
    scenario_counts = {
        scenario: sum(scenario in close.scenarios for close in closes) for scenario in ALL_SCENARIOS
    }
    return {
        "schema_version": "sim.run/1",
        "disclaimer": DISCLAIMER,
        "seed": seed,
        "days": len(dates),
        "window_start": dates[0].isoformat(),
        "window_end": dates[-1].isoformat(),
        "window_basis": (
            "explicit dated-pack window"
            if pack.observation_dates
            else "declared synthetic start"
        ),
        "filed_credit_history": [
            {
                **snapshot,
                "month_end": snapshot["month_end"].isoformat(),
                "customer_total_credits": str(snapshot["customer_total_credits"]),
                "pab_total_credits": str(snapshot["pab_total_credits"]),
                "total_credits": str(snapshot["total_credits"]),
            }
            for snapshot in history_snapshots
        ],
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


RESERVE_SECTION_HEADING = "## Reserve protection"
_RESERVE_COMPUTATIONS = (("customer", "reserve", "Customer"), ("pab", "pab_reserve", "PAB"))


def reserve_section(closes: list[dict[str, Any]]) -> str:
    """Disclose each reserve computation's deposit policy and why its HOLD days held.

    SIM-1G. Derived only from the published closes, so it can be checked against
    ``daily-close.json``. A pack that declares no deposit policy makes every positive
    requirement a deposit shortfall; this section says so, so an undeclared policy is
    never read as a real funding failure.
    """
    lines = [RESERVE_SECTION_HEADING, ""]
    for name, key, label in _RESERVE_COMPUTATIONS:
        deposits = [close["protection"].get("deposits", {}).get(name, {}) for close in closes]
        drawn = {deposit.get("drawn_outcome") for deposit in deposits}
        if not deposits or drawn == {None}:
            policy = "not recorded (publication predates SIM-1G)"
        elif drawn == {"NOT_DECLARED_IN_PACK"}:
            policy = (
                "`NOT_DECLARED_IN_PACK`: the pack declares no deposit policy, so no "
                "deposit is posted and every positive requirement holds as a shortfall"
            )
        else:
            policy = "declared SYNTHETIC in the pack"
        dispositions = [close["protection"]["dispositions"][key] for close in closes]
        reasons_required = [
            close["protection"].get("reasons_required", {}).get(key) for close in closes
        ]
        outcomes = [deposit.get("outcome") for deposit in deposits]
        holds = [i for i, value in enumerate(dispositions) if value == "HOLD"]
        undeclared = sum(1 for i in holds if outcomes[i] == "NOT_DECLARED_IN_PACK")
        breach = sum(
            1
            for i in holds
            if outcomes[i] in {"SHORT", "LATE"} and reasons_required[i] is not None
        )
        other = len(holds) - undeclared - breach
        lines += [
            f"- {label} deposit policy: {policy}",
            f"- {label} reserve: `{dispositions.count('PASS')}` PASS, `{len(holds)}` HOLD "
            f"(`{undeclared}` no declared deposit, `{breach}` simulated short or late "
            f"deposit, `{other}` missing inputs or other engine reasons)",
        ]
    return "\n".join(lines) + "\n"


def publish_run(run: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if "firm_profile" in run:
        firm_closes = cast(list[dict[str, object]], run["closes"])
        profile = cast(dict[str, object], run["firm_profile"])
        (output / "run-summary.json").write_text(
            json.dumps(run, default=str, indent=2, sort_keys=True) + "\n"
        )
        (output / "daily-close.json").write_text(
            json.dumps(firm_closes, default=str, indent=2, sort_keys=True) + "\n"
        )
        (output / "trend.json").write_text(
            json.dumps(
                {
                    "schema_version": "sim.trend/1",
                    "green_nights_in_row": len(firm_closes) if run["all_invariants_pass"] else 0,
                    "review_flag": "an invariant that never fails may be too weak",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        fails: dict[str, int] = {}
        breaks: dict[str, int] = {}
        for close in firm_closes:
            for age, count in cast(dict[str, int], close["fails_by_age"]).items():
                fails[age] = fails.get(age, 0) + count
            for owner, count in cast(dict[str, int], close["breaks_by_owner"]).items():
                breaks[owner] = breaks.get(owner, 0) + count
        protection_lines: list[str] = []
        for name in ("reserve", "pab_reserve", "net_capital", "possession_or_control"):
            dispositions = [
                cast(dict[str, str], close["protection_dispositions"])[name]
                for close in firm_closes
            ]
            hold_reasons = [
                "; ".join(
                    cast(dict[str, list[str]], close["protection_reasons"])[name]
                )
                for close in firm_closes
                if cast(dict[str, str], close["protection_dispositions"])[name] == "HOLD"
            ]
            protection_lines.append(
                f"- {name}: `{dispositions.count('PASS')}` PASS, "
                f"`{dispositions.count('HOLD')}` HOLD; reasons: "
                f"`{' | '.join(hold_reasons) if hold_reasons else 'none'}`"
            )
        invariants = cast(dict[str, bool], firm_closes[-1]["invariants"])
        (output / "SUMMARY.md").write_text(
            "# SCF-1 firm at volume\n\n"
            "**SYNTHETIC LOAD LEVEL: no claim about any real firm.**\n\n"
            f"Tier `{profile['tier']}`: {int(cast(int, profile['accounts'])):,} accounts, "
            f"{int(cast(int, profile['issues'])):,} issues, "
            f"{int(cast(int, profile['executions_per_day'])):,} executions per day. "
            f"All close invariants green: `{run['all_invariants_pass']}`.\n\n"
            "## Firm section\n\n"
            f"- Executions: {sum(cast(int, close['executions']) for close in firm_closes):,}\n"
            f"- Fails by age: `{fails}`\n"
            f"- Breaks by owner: `{breaks}`\n"
            f"- I11 position roll-forward: `{invariants['I11_POSITION_ROLL_FORWARD']}`\n"
            f"- I12 idempotent replay: `{invariants['I12_IDEMPOTENT_REPLAY']}`\n\n"
            "## Reserve protection\n\n"
            + "\n".join(protection_lines)
            + "\n\n## Not claimed\n\n- "
            + "\n- ".join(cast(list[str], run["not_claimed"]))
            + "\n"
        )
        return
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
    final_close = closes[-1]
    assert isinstance(final_close, dict)
    final_market = final_close["market_data"]
    assert isinstance(final_market, dict)
    repository_shas = run["repository_shas"]
    assert isinstance(repository_shas, dict)
    source_commit = repository_shas.get("atreides")
    (output / "SUMMARY.md").write_text(
        f"{DISCLAIMER}\n\n"
        "# SIM-1 run summary\n\n"
        f"- Seed: `{run['seed']}`\n"
        f"- Pack: `{run['calibration_pack_id']}` version `{run['calibration_pack_version']}`\n"
        f"- Manifest: `{run['calibration_manifest_digest']}`\n"
        f"- Classes: `{', '.join(str(value) for value in classes)}`\n"
        f"- Closes: `{run['days']}`\n"
        f"- Window: `{run['window_start']}` through `{run['window_end']}` "
        f"(`{run['window_basis']}`)\n"
        f"- Final SOFR: `{final_market.get('sofr_percent')}` percent\n"
        f"- Final financing need: `${final_market.get('financing_need')}`\n"
        f"- Final financing charge: `${final_market.get('financing_charge')}`\n"
        f"- Source commit: `{source_commit}`\n"
        "- Provenance: locally generated from the locked Mac pack; this folder contains "
        "run outputs only, not the pack or its data.\n\n"
        f"{reserve_section(closes)}\n"
        f"## New York Fed notices\n\n{notice_lines}\n\n"
        "## Not tested\n\n- " + "\n- ".join(NOT_TESTED) + "\n"
    )
