"""Volume probe - what the gates look like at scale.

WHY THIS EXISTS
---------------
Every human-in-the-loop gate degrades into a rubber stamp under volume. It is
the same pathology as alert fatigue in a security operations centre and as
control sign-off in Sarbanes-Oxley testing: by the third week of clicking
approve on the fortieth item, the gate has become theatre with an audit
trail.

The question that catches it is **what does this gate look like at 500 events
a week**, and it is not answerable by reading the code. Each gate is correct
in isolation; the failure is in the distribution, and a distribution has to
be measured.

WHAT IT ALREADY FOUND
---------------------
Two things, neither of which any existing test catches, because each module
is right on its own and they only collide in aggregate.

**The gate holds on most operations.** In the shipped configuration a large
share of the sample stops at MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE, which
holds *by doctrine* because quorum authority is architecturally unavailable.
That check can never clear. It is not a control, it is a permanent stop, and
the first operational response at volume will be to raise the materiality
threshold until the holds go away - which disables the control silently while
leaving the doctrine text intact.

**The break queue had no ordering.** Every venue profile ships flagged, so an
unassessed break resolves to INDETERMINATE by the fail-safe, and INDETERMINATE
carried a single priority rank. Five hundred unassessed breaks, one rank. The
fail-safe default and the prioritisation rule were each correct and
degenerate together. That is what produced ``IndeterminacyReason``.

HOW TO READ THE OUTPUT
----------------------
The number to watch is the **flatness** of each distribution. A gate whose
decisions are 95% one value is not discriminating, whatever its reasons say,
and a queue whose ranks collapse to one value is not a queue. Both are
reported as a share of the modal outcome.

This is a probe, not a test. It asserts nothing about what the right
distribution is - that is an operator judgment and it differs by firm. It
makes the distribution visible so somebody can have the argument.

Deterministic: the sample is drawn from a seeded generator, so two runs of
the same configuration produce the same distribution and a change in the
output means a change in the code.

Usage::

    python3 tools/volume_probe.py
    python3 tools/volume_probe.py --events 5000
    python3 tools/volume_probe.py --json
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import sys
from decimal import Decimal

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atreides.contracts.margin_impact import (  # noqa: E402
    IndeterminacyReason,
    absent_margin_assessment,
    margin_priority_rank,
)
from atreides.rails.cato_f import (  # noqa: E402
    CashRail,
    OperationContext,
    RailState,
    RailStatus,
    evaluate,
)
from atreides.rails.finality import FinalityClass  # noqa: E402
from atreides.rails.funding_state import (  # noqa: E402
    CashFlow,
    FundingInputs,
    project_funding,
)

D = Decimal

#: Fixed so the distribution is reproducible. A probe whose output moves on
#: its own teaches nobody anything.
SEED = 20260817

#: A plausible week, weighted toward the ordinary. These are assumptions and
#: they are the first thing to change for a specific firm - the shape of the
#: book drives every number below.
NOTIONALS = [D(50_000), D(250_000), D(1_000_000), D(5_000_000), D(25_000_000)]
OPENING_POSITIONS = [D(0), D(500_000), D(5_000_000), D(50_000_000)]
STRESS_READINGS = [0.0, 0.0, 0.0, 0.1, 0.6, 1.2]

MATERIAL_AT = D(5_000_000)
LVPS_MATERIAL_AT = D(1_000_000)


def _rails() -> dict[CashRail, RailState]:
    return {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
    }


def _flatness(counter: collections.Counter[str], total: int) -> float:
    """Share taken by the single most common outcome."""
    return (counter.most_common(1)[0][1] / total) if total else 0.0


def run(events: int) -> dict[str, object]:
    rng = random.Random(SEED)
    gate: collections.Counter[str] = collections.Counter()
    reason: collections.Counter[str] = collections.Counter()
    funding: collections.Counter[str] = collections.Counter()

    for _ in range(events):
        notional = rng.choice(NOTIONALS)
        inputs = FundingInputs(
            opening_position=rng.choice(OPENING_POSITIONS),
            obligation=notional,
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=14400,
            flows=(CashFlow(7200, notional, "inflow"),) if rng.random() < 0.5 else (),
            net_debit_cap=D(50_000_000),
            clearing_fund_requirement=D(500_000),
            clearing_fund_posted=rng.choice(
                [D(500_000), D(500_000), D(500_000), D(250_000)]
            ),
        )
        projection = project_funding(inputs)
        funding[projection.disposition.value] += 1

        decision = evaluate(
            operation=OperationContext(
                notional=notional,
                currency="USD",
                is_material=notional >= MATERIAL_AT,
                is_lvps_material=notional >= LVPS_MATERIAL_AT,
            ),
            funding=projection.to_gate_input(),
            rails=_rails(),
            ofr_stlfsi4=rng.choice(STRESS_READINGS),
        )
        gate[decision.decision.value] += 1
        reason[decision.reason_code.value] += 1

    # The break queue in the state the framework ships in: nothing assessed.
    unassessed = tuple(absent_margin_assessment(f"break {i}") for i in range(events))
    unassessed_ranks = collections.Counter(
        str(margin_priority_rank(m)) for m in unassessed
    )
    # And the same queue after triage has said why each one is indeterminate.
    reasons = [r for r in IndeterminacyReason if r is not IndeterminacyReason.NOT_APPLICABLE]
    triaged = tuple(
        absent_margin_assessment(f"break {i}", reasons[i % len(reasons)])
        for i in range(events)
    )
    triaged_ranks = collections.Counter(str(margin_priority_rank(m)) for m in triaged)

    return {
        "events": events,
        "gate_decision": dict(gate),
        "gate_reason": dict(reason),
        "funding_disposition": dict(funding),
        "queue_ranks_unassessed": dict(unassessed_ranks),
        "queue_ranks_triaged": dict(triaged_ranks),
        "flatness": {
            "gate_decision": round(_flatness(gate, events), 4),
            "gate_reason": round(_flatness(reason, events), 4),
            "funding_disposition": round(_flatness(funding, events), 4),
            "queue_unassessed": round(_flatness(unassessed_ranks, events), 4),
            "queue_triaged": round(_flatness(triaged_ranks, events), 4),
        },
        "human_touch_rate": round(
            (gate.get("HOLD", 0) + gate.get("ESCALATE", 0)) / events, 4
        ),
    }


def _table(title: str, counts: dict[str, int], total: int) -> None:
    print(f"\n{title}")
    for key, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        bar = "#" * int(40 * count / total)
        print(f"  {key:<42} {count:>6} {count / total:>7.1%}  {bar}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run(args.events)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    n = result["events"]
    print(f"\n=== {n} operations, seeded sample ===")
    _table("GATE DECISION", result["gate_decision"], n)  # type: ignore[arg-type]
    _table("GATE REASON", result["gate_reason"], n)  # type: ignore[arg-type]
    _table("FUNDING DISPOSITION", result["funding_disposition"], n)  # type: ignore[arg-type]
    _table("BREAK QUEUE - nothing assessed (shipped state)", result["queue_ranks_unassessed"], n)  # type: ignore[arg-type]
    _table("BREAK QUEUE - after triage names a reason", result["queue_ranks_triaged"], n)  # type: ignore[arg-type]

    flat = result["flatness"]  # type: ignore[index]
    print("\nFLATNESS (share taken by the single most common outcome)")
    for key, value in flat.items():  # type: ignore[union-attr]
        note = "  <-- not discriminating" if value >= 0.9 else ""
        print(f"  {key:<24} {value:>7.1%}{note}")

    print(f"\nHUMAN TOUCH RATE: {result['human_touch_rate']:.1%} of operations hold or escalate")
    print(
        "\nA gate that only works at five events a week is not a gate. This\n"
        "probe asserts nothing about the right distribution - it makes the\n"
        "distribution visible so somebody can have the argument."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
