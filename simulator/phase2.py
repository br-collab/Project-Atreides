"""One-shot Phase 2 publication assembled only from executed leg results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from simulator.account_transfers import TRANSFER_VARIANTS, run_account_transfers
from simulator.clearing_readiness import run_clearing_readiness
from simulator.focus import run_focus

NOT_CLAIMED = (
    "production correctness",
    "regulatory approval or filing",
    "clearing-agency membership",
    "real customer assets",
    "real firm, account or security identifiers",
)


def build_phase2_summary() -> dict[str, object]:
    transfers = {variant: run_account_transfers(variant) for variant in TRANSFER_VARIANTS}
    clearing = {
        variant: run_clearing_readiness(variant)
        for variant in ("ready", "missing-membership", "fund-call")
    }
    focus = run_focus()
    transfer_counts: dict[str, dict[str, object]] = {}
    for variant, result in transfers.items():
        rows = cast(list[dict[str, object]], result["transfers"])
        transfer_counts[variant] = {
            "PASS": sum(row["disposition"] == "PASS" for row in rows),
            "HOLD": sum(row["disposition"] == "HOLD" for row in rows),
            "reasons": sorted(
                {
                    reason
                    for row in rows
                    for reason in cast(tuple[str, ...], row["reasons"])
                }
            ),
        }
    clearing_counts = {
        variant: {
            "PASS": int(result["disposition"] == "PASS"),
            "HOLD": int(result["disposition"] == "HOLD"),
            "reasons": result["reasons"],
        }
        for variant, result in clearing.items()
    }
    focus_closes = cast(list[dict[str, object]], focus["closes"])
    focus_counts = {
        "PASS": sum(
            cast(dict[str, bool], close["invariants"])["I13_FOCUS_TIE_OUT"]
            for close in focus_closes
        ),
        "HOLD": sum(
            not cast(dict[str, bool], close["invariants"])["I13_FOCUS_TIE_OUT"]
            for close in focus_closes
        ),
        "reasons": [],
    }
    return {
        "schema_version": "sim.phase-2/1",
        "synthetic": True,
        "legs": {
            "CONV-2": transfer_counts,
            "CONV-3": clearing_counts,
            "CONV-4": focus_counts,
        },
        "license_gates": {
            "FINRA": "INDETERMINATE",
            "DTCC": "INDETERMINATE",
            "eCFR_SEC_local_pins": "INDETERMINATE",
        },
        "not_claimed": list(NOT_CLAIMED),
    }


def publish_phase2(output: Path) -> None:
    summary = build_phase2_summary()
    output.mkdir(parents=True, exist_ok=True)
    (output / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    legs = cast(dict[str, object], summary["legs"])
    (output / "SUMMARY.md").write_text(
        "# Phase 2 synthetic rehearsal\n\n"
        "**Synthetic evidence only; not evidence of production correctness.**\n\n"
        + "\n".join(f"- {name}: `{value}`" for name, value in legs.items())
        + "\n\n## Licence and source gates\n\n"
        + "\n".join(
            f"- {name}: `{value}`"
            for name, value in cast(dict[str, str], summary["license_gates"]).items()
        )
        + "\n\n## Not claimed\n\n- "
        + "\n- ".join(cast(list[str], summary["not_claimed"]))
        + "\n"
    )
    for variant in TRANSFER_VARIANTS:
        target = output / "account-transfers" / variant
        target.mkdir(parents=True, exist_ok=True)
        (target / "run-summary.json").write_text(
            json.dumps(run_account_transfers(variant), indent=2, sort_keys=True) + "\n"
        )
    for clearing_variant in ("ready", "missing-membership", "fund-call"):
        target = output / "clearing-readiness" / clearing_variant
        target.mkdir(parents=True, exist_ok=True)
        (target / "run-summary.json").write_text(
            json.dumps(run_clearing_readiness(clearing_variant), indent=2, sort_keys=True) + "\n"
        )
    focus_target = output / "focus"
    focus_target.mkdir(parents=True, exist_ok=True)
    (focus_target / "run-summary.json").write_text(
        json.dumps(run_focus(), indent=2, sort_keys=True) + "\n"
    )
