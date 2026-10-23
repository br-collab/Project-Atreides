#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from simulator.runner import publish_run, run_simulation

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--days", type=int, choices=range(1, 251), required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repository-sha", action="append", default=[])
args = parser.parse_args()
repository_shas = dict(value.split("=", 1) for value in args.repository_sha)
publish_run(
    run_simulation(seed=args.seed, days=args.days, repository_shas=repository_shas), args.output
)
