"""FINRA Rules 3110, 3120 and 3130 supervisory records.

The system records and tests supervision. It never signs a certification and
never substitutes an agent for the named synthetic registered principal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    decision_id: str
    decider: str
    reviewer: str
    outcome: str
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class TestResult:
    gate: str
    test_name: str
    status: str
    remediation_owner: str | None


@dataclass(frozen=True, slots=True)
class TestingReport:
    report_id: str
    addressed_to: str
    run_id: str
    tests: tuple[TestResult, ...]

    @property
    def exception_count(self) -> int:
        return sum(item.status == "EXCEPTION" for item in self.tests)


@dataclass(frozen=True, slots=True)
class CertificationDraft:
    certification_id: str
    ceo: str
    testing_report_id: str
    status: str = "UNSIGNED_DRAFT"
    signed_by: None = None


def load_wsp_register() -> tuple[dict[str, Any], ...]:
    path = Path(__file__).with_name("wsp_register.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(dict(item) for item in raw["rows"])


def record_review(
    *,
    decision_id: str,
    decider: str,
    reviewer: str,
    outcome: str,
    reviewed_at: datetime,
) -> ReviewRecord:
    if reviewer == decider:
        raise ValueError("SELF_REVIEW_REFUSED")
    return ReviewRecord(decision_id, decider, reviewer, outcome, reviewed_at)


def run_3120_testing(
    *,
    run_id: str,
    executed_tests: frozenset[str],
    addressed_to: str = "SYNTHETIC_SENIOR_MANAGEMENT",
) -> TestingReport:
    results = []
    for row in load_wsp_register():
        name = str(row["test"])
        ran = name in executed_tests
        results.append(
            TestResult(
                gate=str(row["gate"]),
                test_name=name,
                status="PASS" if ran else "EXCEPTION",
                remediation_owner=None if ran else str(row["supervisor_role"]),
            )
        )
    return TestingReport(f"3120-{run_id}", addressed_to, run_id, tuple(results))


def build_3130_draft(*, report: TestingReport, ceo: str) -> CertificationDraft:
    return CertificationDraft(f"3130-{report.run_id}", ceo, report.report_id)


def build_public_summary(
    *,
    wsp_rows: tuple[dict[str, Any], ...],
    testing_report: TestingReport,
    cat_summary: dict[str, int],
    aml_alert_count: int,
    surveillance_dispositions: tuple[str, ...],
) -> dict[str, Any]:
    """Build public counts only from engine outputs and omit confidential case data."""
    return {
        "wsp_count": len(wsp_rows),
        "3120_exception_count": testing_report.exception_count,
        "cat_record_count": cat_summary["record_count"],
        "cat_exception_count": cat_summary["exception_count"],
        "aml_alert_count": aml_alert_count,
        "surveillance_dispositions": surveillance_dispositions,
    }
