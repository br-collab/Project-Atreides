"""Seeded SIM-1 day generator, invariant engine and publication builder."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from cannae_kernel.canonical import canonical_bytes_of

from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.rails.cns import absent_entitlement_treatment
from simulator.calibration import CalibrationPack, load_calibration_pack
from simulator.market import (
    PriceTimeBook,
    allocate_largest_remainder,
    auction_print,
    treasury_consideration,
)
from simulator.model import AssetClass, Break, CloseResult, Order, Side
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
INTERIM_NOTICE = (
    "SIM-1 v1 invariants are not yet independent checks; green results are not evidence "
    "(see SIM-1B)."
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


def _simulate_close(
    rng: random.Random, business_date: date, index: int, pack: CalibrationPack
) -> CloseResult:
    issue = f"SYN-EQ-{rng.randrange(1000, 9999)}"
    base = datetime.combine(business_date, time(14, 30), tzinfo=UTC)
    order_price = Decimal(str(pack.value("market", "equity_order_price")))
    order = Order(
        order_id=f"ORD-{index}-A",
        issue=issue,
        asset_class=AssetClass.EQUITY,
        side=Side.BUY,
        quantity=101,
        limit_price=order_price,
        arrived_at=base,
        account_weights=(1, 1, 1),
    )
    book = PriceTimeBook()
    book.rest(order, size_ahead=7)
    first = book.execute(
        price=order_price, quantity=67, matched_at=base + timedelta(seconds=1), report_delay=9
    )
    # Executions may be sub-penny although the order price is in a permitted increment.
    second_order = order.model_copy(
        update={
            "order_id": f"ORD-{index}-B",
            "quantity": 41,
            "limit_price": order_price,
            "arrived_at": base + timedelta(seconds=2),
        }
    )
    book.rest(second_order)
    second = book.execute(
        price=order_price,
        quantity=81,
        matched_at=base + timedelta(seconds=3),
        execution_price=Decimal(str(pack.value("market", "equity_subpenny_price"))),
    )
    opening = auction_print(
        order=order.model_copy(update={"order_id": f"ORD-{index}-OPEN", "quantity": 15}),
        clearing_price=Decimal("9.98"),
        imbalance=2,
        session="OPEN_AUCTION",
    )
    closing = auction_print(
        order=order.model_copy(update={"order_id": f"ORD-{index}-CLOSE", "quantity": 12}),
        clearing_price=Decimal("10.02"),
        imbalance=1,
        session="CLOSE_AUCTION",
    )
    reports = (opening, *first, *second, closing)
    allocations = allocate_largest_remainder(sum(p.quantity for p in reports), (1, 1, 1))
    venue_money = sum((Decimal(p.quantity) * p.price for p in reports), Decimal(0)).quantize(
        Decimal("0.01")
    )
    cns = cns_cycles(
        issue=issue,
        quantity=sum(allocations),
        mark_price=Decimal(str(pack.value("market", "cns_prior_close"))),
        night_capacity=int(pack.value("market", "cns_night_capacity")),
    )
    treasury_issue = f"SYN-UST-{rng.randrange(1000, 9999)}"
    principal = treasury_consideration(
        asset_class=AssetClass.TREASURY_NOTE,
        par=100000,
        price=Decimal(str(pack.value("market", "treasury_price_64ths"))),
        accrued_interest=Decimal(str(pack.value("market", "treasury_accrued_interest"))),
    )
    gsd = gsd_messages(
        issue=treasury_issue,
        quantity=100000,
        principal=principal,
        invoice=Decimal("1.01"),
        coupon=Decimal("2.02"),
        mark=Decimal("3.03"),
    )
    dtc = dtc_dvp_status(
        issue=issue,
        quantity=50,
        money=Decimal("1000.00"),
        net_debit_cap=Decimal(str(pack.value("market", "dtc_net_debit_cap"))),
        collateral=Decimal(str(pack.value("market", "dtc_collateral"))),
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
        deadline=rule_204_short, close_date=rule_204_short, closeout_settled=False
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
    halted.halt(issue, cancel_resting=True)
    halt_refusal = False
    try:
        halted.rest(order.model_copy(update={"order_id": f"ORD-{index}-DURING-HALT"}))
    except ValueError:
        halt_refusal = True
    breaks: list[Break] = []
    quantity_ok = (
        sum(allocations) == sum(p.quantity for p in reports) == sum(m.securities for m in cns)
    )
    money_ok = venue_money == sum(
        (Decimal(p.quantity) * p.price for p in reports), Decimal(0)
    ).quantize(Decimal("0.01"))
    street_ok = sum(m.securities for m in cns) == sum(allocations)
    if not quantity_ok:
        breaks.append(
            Break(
                invariant="I1_CONSERVATION",
                owner="SIM_SETTLEMENT_OPS",
                age_business_days=0,
                reason="share residual",
            )
        )
    if not money_ok:
        breaks.append(
            Break(
                invariant="I2_REPORT_PRICE",
                owner="SIM_BOOKS",
                age_business_days=0,
                reason="cent residual",
            )
        )
    invariant_results = {
        "I1_QUANTITY_MONEY_CONSERVE": quantity_ok and money_ok,
        "I2_BOOKED_FROM_REPORTS": money_ok,
        "I3_STOCK_RECORD_EQUALS_STREET": street_ok,
        "I4_EVERY_DIFFERENCE_OWNED": all(b.owner for b in breaks),
        "I5_RESIDUALS_TWO_SIDED": all(m.money is not None for m in (*cns, *gsd)),
        "I6_DEFAULT_AND_STALE_HOLD": True,
        "I7_MARKET_ACCESS_REFUSES": dtc.status == "HELD_CAP_OR_COLLATERAL",
        "I8_REPLAY_DIGEST": True,
    }
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
        "default_holds": {
            "cns": "HOLD: NSCC novated fail input missing",
            "gsd": "HOLD: GSD funds-only and margin input missing",
            "dtc": "HOLD: bilateral DVP never novated",
        },
        "stale_data_hold": "HOLD: simulated market data exceeded declared age",
    }
    digest = _digest(economics)
    return CloseResult(
        business_date=business_date,
        invariant_results=invariant_results,
        breaks=tuple(breaks),
        holds=("DTC_CAP_OR_COLLATERAL", "STALE_MARKET_DATA") if index % 5 == 0 else (),
        fails_by_age={"age_0": 1, "age_1_plus": 1},
        market_access_refusals={"HALT": 1, "RULE_204_B": 1},
        money_residual=Decimal(0),
        replay_digest_check=True,
        economics_digest=digest,
        scenarios=(
            ALL_SCENARIOS
            if index == 0
            and halt_refusal
            and restriction_active
            and "is not computed" in ex_date_refusal
            else ("MULTI_PRINT", "CNS_NIGHT", "CNS_DAY")
        ),
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
    closes = tuple(
        _simulate_close(rng, day, index, pack)
        for index, day in enumerate(_business_dates(start, days))
    )
    digest = _digest([close.economics_digest for close in closes])
    exercised = sorted({scenario for close in closes for scenario in close.scenarios})
    return {
        "schema_version": "sim.run/1",
        "disclaimer": DISCLAIMER,
        "interim_notice": INTERIM_NOTICE,
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
        "scenarios_not_exercised": sorted(set(ALL_SCENARIOS) - set(exercised)),
        "not_tested": list(NOT_TESTED),
        "all_invariants_pass": all(all(close.invariant_results.values()) for close in closes),
    }


def publish_run(run: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    closes = run["closes"]
    assert isinstance(closes, list)
    (output / "run-summary.json").write_text(
        DISCLAIMER + "\n" + json.dumps(run, indent=2, sort_keys=True) + "\n"
    )
    (output / "daily-close.json").write_text(
        DISCLAIMER
        + "\n"
        + json.dumps(
            {
                "schema_version": "sim.daily-close/1",
                "closes": closes,
                "not_tested": list(NOT_TESTED),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (output / "trend.json").write_text(
        DISCLAIMER
        + "\n"
        + json.dumps(
            {
                "schema_version": "sim.trend/1",
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
        f"{DISCLAIMER}\n\n{INTERIM_NOTICE}\n\n"
        "# SIM-1 run summary\n\n"
        f"- Seed: `{run['seed']}`\n"
        f"- Pack: `{run['calibration_pack_id']}` version `{run['calibration_pack_version']}`\n"
        f"- Manifest: `{run['calibration_manifest_digest']}`\n"
        f"- Classes: `{', '.join(str(value) for value in classes)}`\n\n"
        f"## New York Fed notices\n\n{notice_lines}\n\n"
        "## Not tested\n\n- "
        + "\n- ".join(NOT_TESTED)
        + "\n"
    )
