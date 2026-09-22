#!/usr/bin/env python3
"""Enforce branch-coverage floors on settlement control surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MINIMUM_BRANCH_COVERAGE = {
    "atreides/rails/cato_cash.py": 93.0,
    "atreides/rails/funding_state.py": 100.0,
}


def check(report_path: Path) -> list[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    files = report.get("files", {})
    failures: list[str] = []

    for source, minimum in MINIMUM_BRANCH_COVERAGE.items():
        summary = files.get(source, {}).get("summary")
        if summary is None:
            failures.append(f"{source}: absent from branch-coverage report")
            continue

        total = int(summary.get("num_branches", 0))
        covered = int(summary.get("covered_branches", 0))
        if total == 0:
            failures.append(f"{source}: report contains no branch measurements")
            continue

        percent = covered / total * 100
        print(f"{source}: {covered}/{total} branches ({percent:.2f}%; minimum {minimum:.2f}%)")
        if percent < minimum:
            failures.append(
                f"{source}: branch coverage {percent:.2f}% is below {minimum:.2f}%"
            )

    return failures


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    failures = check(report_path)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
