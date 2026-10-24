#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from simulator.conversion import VARIANTS, publish_conversion, run_conversion_variant
from simulator.runner import publish_run, run_simulation

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int)
parser.add_argument("--conversion-variant", choices=VARIANTS)
parser.add_argument("--days", type=int, choices=range(1, 251))
parser.add_argument("--start", type=date.fromisoformat)
parser.add_argument("--end", type=date.fromisoformat)
parser.add_argument("--calibration-uri")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repository-sha", action="append", default=[])
args = parser.parse_args()
repository_shas = dict(value.split("=", 1) for value in args.repository_sha)
if args.conversion_variant:
    publish_conversion(run_conversion_variant(args.conversion_variant), args.output)
else:
    if args.seed is None:
        parser.error("--seed is required unless --conversion-variant is used")
    publish_run(
        run_simulation(
            seed=args.seed,
            days=args.days,
            start=args.start,
            end=args.end,
            calibration_uri=args.calibration_uri,
            repository_shas=repository_shas,
            require_explicit_dated_window=True,
        ),
        args.output,
    )
