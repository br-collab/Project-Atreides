#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from simulator.runner import publish_run, run_simulation

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--days", type=int, choices=range(1, 251))
parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 12, 28))
parser.add_argument("--end", type=date.fromisoformat)
parser.add_argument("--calibration-uri")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repository-sha", action="append", default=[])
args = parser.parse_args()
repository_shas = dict(value.split("=", 1) for value in args.repository_sha)
publish_run(
    run_simulation(
        seed=args.seed,
        days=args.days,
        start=args.start,
        end=args.end,
        calibration_uri=args.calibration_uri,
        repository_shas=repository_shas,
    ),
    args.output,
)
