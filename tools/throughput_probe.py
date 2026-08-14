"""Throughput probe - what the governance layer costs per decision.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
----------------------------------------
This does **not** measure settlement throughput. Nothing here moves money,
and a benchmark of this framework says nothing about how fast any venue
settles anything.

It measures one thing: **the cost of interposing governance.** Every gate
and model in this framework is a pure function with no I/O and no clock, so
the cost of a governed decision is a real, stable, measurable number rather
than a number dominated by network variance. That purity was adopted for
replayability and it has a second consequence, which is that this benchmark
is honest in a way most systems' benchmarks are not: there is nothing to
warm up, nothing to cache, and no external service whose bad afternoon
changes the result.

WHY THAT IS THE NUMBER THAT MATTERS
-----------------------------------
A firm that already runs post-trade at scale does not ask whether a
governance layer solves its throughput problem. It asks whether the layer
*becomes* one. The objection is "your thing will slow us down", and it is a
fair objection that no amount of doctrine answers.

So the claim this tool exists to support is narrow and testable: **governance
costs a bounded, measured amount per decision, and the amount is small
relative to anything that touches a network.** That is a claim a sceptical
engineer can check in one command, on their own hardware, against their own
threshold.

WHAT A NUMBER FROM THIS DOES NOT LICENSE
----------------------------------------
- It is single-threaded and in-process. Concurrency, contention and
  scheduling are not modelled.
- It excludes serialisation to the decision-of-record, which involves a
  disk and is therefore the part most likely to dominate in production.
- It excludes XML emission except where a stage explicitly includes it.
- Synthetic inputs are shaped by the author's assumptions. They exercise the
  machinery; they do not prove the taxonomy covers reality.

Usage::

    python3 tools/throughput_probe.py
    python3 tools/throughput_probe.py --iterations 50000
    python3 tools/throughput_probe.py --json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from decimal import Decimal

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atreides.contracts.margin_impact import (  # noqa: E402
    CallWindow,
    MarginDirection,
    MarginDisposition,
    MarginImpact,
    Observability,
    margin_priority_rank,
    sort_by_margin_consequence,
)
from atreides.contracts.margin_profile import CollectionModel  # noqa: E402
from atreides.messaging.emit import emit_instruction_artifact  # noqa: E402
from atreides.messaging.readback import ingest_readback  # noqa: E402
from atreides.rails.cato_f import (  # noqa: E402
    OperationContext,
    evaluate,
)
from atreides.rails.cns import (  # noqa: E402
    CloseOutRegime,
    MarketProfile,
    net_positions,
    settle_net_position,
)
from atreides.rails.determination import (  # noqa: E402
    DeterminationProfile,
    RevocationForm,
    classify_determination,
)
from atreides.rails.finality import FinalityClass  # noqa: E402
from atreides.rails.funding_state import (  # noqa: E402
    CashFlow,
    FundingInputs,
    project_funding,
)

sys.path.insert(0, str(REPO / "tools"))
from pipeline_probe import _instruction, _pacs002, _rails, _tx  # noqa: E402

D = Decimal


def _funding_inputs() -> FundingInputs:
    return FundingInputs(
        opening_position=D("10000000"),
        obligation=D("1000000"),
        finality_class=FinalityClass.GROSS_FINAL,
        settlement_offset_seconds=3600,
        window_close_offset_seconds=14400,
        flows=tuple(
            CashFlow(i * 600, D("50000"), f"flow-{i}") for i in range(10)
        ),
        net_debit_cap=D("50000000"),
        clearing_fund_requirement=D("500000"),
        clearing_fund_posted=D("500000"),
    )


def _operation() -> OperationContext:
    return OperationContext(
        notional=D("1000000"),
        currency="USD",
        is_material=False,
        is_lvps_material=False,
    )


def _margin_impact(seq: int) -> MarginImpact:
    return MarginImpact(
        disposition=MarginDisposition.UNDER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_VENUE,
        observability=Observability.OBSERVED,
        collateral_observability=Observability.OBSERVED,
        delta_amount=D(seq % 1000 + 1),
        delta_currency="USD",
        call_window=CallWindow(
            collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
            is_open=seq % 2 == 0,
            closes_at_offset_seconds=7200 if seq % 2 == 0 else None,
        ),
        basis="throughput probe",
    )


def _determination_profile() -> DeterminationProfile:
    return DeterminationProfile(
        venue_id="VENUE-BENCH",
        revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
        qualification_window_seconds=86400,
        provenance="throughput probe",
    )


def _market_profile() -> MarketProfile:
    return MarketProfile(
        market_id="XBENCH",
        settlement_cycle_days=1,
        close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
        close_out_deadline_days=3,
        allocation_rule_published=True,
        provenance="throughput probe",
    )


# name -> (setup, per-iteration callable, what one iteration represents)
def _stages() -> dict[str, tuple[object, str]]:
    funding = _funding_inputs()
    operation = _operation()
    rails = _rails()
    projection = project_funding(funding)
    gate_funding = projection.to_gate_input()
    instruction = _instruction()
    prepared = (instruction,)
    readback_bytes = _pacs002(_tx("E2E-0001", "ACSC"))
    det_profile = _determination_profile()
    market = _market_profile()
    position = net_positions(
        (("SEC-A", D("5000")),), market_id="XBENCH", settlement_date_offset_days=1
    )[0]
    impacts = tuple(_margin_impact(i) for i in range(1000))

    return {
        "funding_projection": (
            lambda: project_funding(funding),
            "one intraday funding projection over a 10-point flow ladder",
        ),
        "cato_f_gate": (
            lambda: evaluate(
                operation=operation,
                funding=gate_funding,
                rails=rails,
                ofr_stlfsi4=0.0,
            ),
            "one full gate evaluation, all checks plus the rail ladder",
        ),
        "determination_classify": (
            lambda: classify_determination(
                profile=det_profile,
                instrument_is_contingent=True,
                determined=True,
                seconds_since_determination=3600,
            ),
            "one contingent-obligation classification",
        ),
        "cns_settle": (
            lambda: settle_net_position(
                position, market, allocated_quantity=D("2000"), current_offset_days=2
            ),
            "one netted-position settlement classification",
        ),
        "margin_rank": (
            lambda: margin_priority_rank(impacts[0]),
            "one break prioritisation",
        ),
        "margin_sort_1k": (
            lambda: sort_by_margin_consequence(impacts),
            "sorting a 1,000-break queue by margin consequence",
        ),
        "readback_ingest": (
            lambda: ingest_readback(readback_bytes, prepared),
            "parsing and reconciling one pacs.002 status report",
        ),
        "emit_artifact": (
            lambda: emit_instruction_artifact(instruction),
            "emitting a schema-shaped pacs.009 package plus header",
        ),
    }


def _bench(fn, iterations: int, repeats: int = 5) -> dict[str, float]:
    # Warm the interpreter, then take the best of several passes. Best-of
    # rather than mean: the interesting number is the cost of the work, and
    # the slower passes are measuring the machine's other tenants.
    for _ in range(min(100, iterations)):
        fn()
    timings: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(iterations):
            fn()
        timings.append(time.perf_counter() - start)
    best = min(timings)
    return {
        "iterations": iterations,
        "best_seconds": best,
        "per_call_microseconds": (best / iterations) * 1_000_000,
        "calls_per_second": iterations / best,
        "spread_pct": (
            (max(timings) - best) / best * 100 if best > 0 else 0.0
        ),
        "median_seconds": statistics.median(timings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    stages = _stages()
    results: dict[str, dict[str, float]] = {}
    for name, (fn, _desc) in stages.items():
        iterations = args.iterations
        if name == "margin_sort_1k":
            iterations = max(1, iterations // 100)
        results[name] = _bench(fn, iterations)

    if args.json:
        print(json.dumps({"python": sys.version.split()[0], "stages": results}, indent=2))
        return 0

    print(f"\nGovernance cost per decision  (python {sys.version.split()[0]})")
    print("Pure functions, single-threaded, no I/O, no network.\n")
    print(f"{'stage':<24} {'us/call':>10} {'calls/sec':>14}   what one call is")
    print("-" * 110)
    for name, (_fn, desc) in stages.items():
        r = results[name]
        print(
            f"{name:<24} {r['per_call_microseconds']:>10.2f} "
            f"{r['calls_per_second']:>14,.0f}   {desc}"
        )
    print(
        "\nMeasures the cost of interposing governance, not settlement "
        "throughput.\nExcludes decision-of-record persistence, which touches a "
        "disk and will dominate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
