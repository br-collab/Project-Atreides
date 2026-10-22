"""The per-module branch-coverage gate fails closed."""

import json
from pathlib import Path

from scripts.check_branch_coverage import MINIMUM_BRANCH_COVERAGE, check


def _write_report(path: Path, files: dict[str, dict[str, object]]) -> Path:
    path.write_text(json.dumps({"files": files}), encoding="utf-8")
    return path


def _summary(covered: int, total: int) -> dict[str, object]:
    return {"summary": {"covered_branches": covered, "num_branches": total}}


def test_branch_coverage_policy_accepts_measured_floors(tmp_path: Path) -> None:
    files = {
        "atreides/clearing/access.py": _summary(32, 32),
        "atreides/clearing/ficc.py": _summary(42, 42),
        "atreides/clearing/repo.py": _summary(42, 42),
        "atreides/books/ledger.py": _summary(36, 36),
        "atreides/books/projections.py": _summary(10, 10),
        "atreides/margin/engine.py": _summary(20, 20),
        "atreides/rails/cato_cash.py": _summary(121, 130),
        "atreides/rails/funding_state.py": _summary(52, 52),
    }
    assert check(_write_report(tmp_path / "coverage.json", files)) == []


def test_branch_coverage_policy_rejects_regression_missing_file_and_no_measurement(
    tmp_path: Path,
) -> None:
    files = {
        "atreides/rails/cato_cash.py": _summary(120, 130),
        "atreides/rails/funding_state.py": _summary(0, 0),
    }
    failures = check(_write_report(tmp_path / "coverage.json", files))
    assert any("below" in failure for failure in failures)
    assert any("no branch measurements" in failure for failure in failures)

    missing = check(_write_report(tmp_path / "missing.json", {}))
    assert len(missing) == len(MINIMUM_BRANCH_COVERAGE)
    assert all("absent" in failure for failure in missing)
