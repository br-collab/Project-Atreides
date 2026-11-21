"""FINRA Rules 3110, 3120 and 3130 supervisory records.

The system records and tests supervision. It never signs a certification and
never substitutes an agent for the named synthetic registered principal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from atreides.supervision.aml import AMLCase


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    decision_id: str
    decider: str
    reviewer: str
    outcome: str
    reviewed_at: datetime


class TestOutcome(StrEnum):
    """Why a written supervisory procedure row is, or is not, an exception."""

    __test__ = False

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
    NO_RUN_LEVEL_TEST = "NO_RUN_LEVEL_TEST"


@dataclass(frozen=True, slots=True)
class TestResult:
    __test__ = False
    gate: str
    test_name: str
    status: str
    remediation_owner: str | None
    outcome: TestOutcome


@dataclass(frozen=True, slots=True)
class TestingReport:
    __test__ = False
    report_id: str
    addressed_to: str
    run_id: str
    tests: tuple[TestResult, ...]
    register_version: str = ""

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


def _register_document() -> dict[str, Any]:
    path = Path(__file__).with_name("wsp_register.json")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def load_wsp_register() -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in _register_document()["rows"])


def wsp_register_version() -> str:
    """The version of the register a 3120 report graded, so the report can be tied to it."""

    return str(_register_document()["version"])


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


def junit_key(node_id: str) -> tuple[str, str]:
    """Return the JUnit (classname, name) pair pytest writes for one node identifier.

    ``tests/simulator/test_x.py::test_y[case]`` becomes
    ``("tests.simulator.test_x", "test_y[case]")``. A test inside a class keeps the class in the
    classname, as pytest does.
    """

    path, _, rest = node_id.partition("::")
    if not path.endswith(".py") or not rest:
        raise ValueError(f"WSP_NODE_ID_INVALID: {node_id}")
    parts = rest.split("::")
    module = path[: -len(".py")].replace("/", ".")
    return ".".join((module, *parts[:-1])), parts[-1]


def junit_outcomes(junit_xml: Path) -> dict[tuple[str, str], str]:
    """Read every test case the runner wrote and its outcome.

    The outcome is ``PASSED``, ``FAILED`` (a failure or error element) or ``SKIPPED``.
    """

    if not junit_xml.is_file():
        raise ValueError("JUNIT_FILE_MISSING")
    try:
        root = ElementTree.parse(junit_xml).getroot()
    except ElementTree.ParseError as exc:
        raise ValueError("JUNIT_MALFORMED") from exc
    outcomes: dict[tuple[str, str], str] = {}
    for case in root.iter("testcase"):
        key = (case.attrib.get("classname", ""), case.attrib.get("name", ""))
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "FAILED"
        elif case.find("skipped") is not None:
            outcome = "SKIPPED"
        else:
            outcome = "PASSED"
        if outcomes.get(key) != "FAILED":
            outcomes[key] = outcome
    return outcomes


def _row_outcome(node_id: str | None, outcomes: dict[tuple[str, str], str]) -> TestOutcome:
    if not node_id:
        return TestOutcome.NO_RUN_LEVEL_TEST
    classname, name = junit_key(node_id)
    if "[" in name:
        found = [outcomes[(classname, name)]] if (classname, name) in outcomes else []
    else:
        found = [
            outcome
            for (case_class, case_name), outcome in outcomes.items()
            if case_class == classname and (case_name == name or case_name.startswith(f"{name}["))
        ]
    if any(outcome == "FAILED" for outcome in found):
        return TestOutcome.FAILED
    if not any(outcome == "PASSED" for outcome in found):
        return TestOutcome.NOT_RUN
    return TestOutcome.PASSED


def evaluate_3120(
    register: tuple[dict[str, Any], ...],
    junit_xml: Path,
    *,
    addressed_to: str = "SYNTHETIC_SENIOR_MANAGEMENT",
) -> TestingReport:
    """Grade each register row from the outcome the runner recorded for its node identifier."""

    outcomes = junit_outcomes(junit_xml)
    run_id = junit_xml.stem
    results = []
    for row in register:
        node_id = row.get("test")
        outcome = _row_outcome(str(node_id) if node_id else None, outcomes)
        passed = outcome is TestOutcome.PASSED
        results.append(
            TestResult(
                gate=str(row["gate"]),
                test_name=str(node_id) if node_id else "",
                status="PASS" if passed else "EXCEPTION",
                remediation_owner=None if passed else str(row["supervisor_role"]),
                outcome=outcome,
            )
        )
    return TestingReport(f"3120-{run_id}", addressed_to, run_id, tuple(results))


def run_3120_testing(
    *,
    junit_xml: Path,
    addressed_to: str = "SYNTHETIC_SENIOR_MANAGEMENT",
) -> TestingReport:
    """Compare the pinned WSP register with what the runner's JUnit file says happened.

    A row passes only when its named run-level test ran and passed. A failure or error is an
    exception (``FAILED``), an absent or skipped test is an exception (``NOT_RUN``), and a row
    with no run-level test yet is an exception (``NO_RUN_LEVEL_TEST``).
    """

    report = evaluate_3120(load_wsp_register(), junit_xml, addressed_to=addressed_to)
    return replace(report, register_version=wsp_register_version())


def register_node_ids() -> tuple[str, ...]:
    """Every distinct run-level test node identifier the register names, in register order."""

    seen: dict[str, None] = {}
    for row in load_wsp_register():
        if row.get("test"):
            seen.setdefault(str(row["test"]), None)
    return tuple(seen)


def build_3130_draft(*, report: TestingReport, ceo: str) -> CertificationDraft:
    return CertificationDraft(f"3130-{report.run_id}", ceo, report.report_id)


_SURVEILLANCE_DISPOSITIONS = frozenset(
    {
        "SURVEIL_CLEAR",
        "SURVEIL_DATA_INCOMPLETE",
        "SURVEIL_PATTERN_FLAGGED",
        "SURVEIL_PATTERN_ESCALATE",
    }
)


def build_public_summary(
    *,
    junit_xml: Path,
    cat_feedback_file: Path,
    aml_cases: tuple[AMLCase, ...],
    surveillance_dispositions: tuple[str, ...],
    publication: Path,
) -> dict[str, Any]:
    """Write Phase A public counts from engine outputs and omit confidential case data.

    Rule 3120 counts come from ``run_3120_testing``. CAT (Consolidated Audit Trail) record
    and feedback counts come from the feedback file that engine wrote. Anti-money laundering
    alert counts are the length of the monitoring result. No suspicious activity report field
    and no case identifier is written. No run calls this yet.
    """

    if any(case.decision is not None or case.draft_sar is not None for case in aml_cases):
        raise ValueError("PUBLIC_SUMMARY_SAR_REFUSED")
    unknown = set(surveillance_dispositions) - _SURVEILLANCE_DISPOSITIONS
    if unknown:
        raise ValueError("PUBLIC_SUMMARY_DISPOSITION_UNKNOWN")
    report = run_3120_testing(junit_xml=junit_xml)
    feedback = json.loads(cat_feedback_file.read_text(encoding="utf-8"))
    if not isinstance(feedback, dict) or not isinstance(feedback.get("record_count"), int):
        raise ValueError("CAT_FEEDBACK_UNREADABLE")
    rejections = feedback.get("rejections", [])
    if not isinstance(rejections, list):
        raise ValueError("CAT_FEEDBACK_UNREADABLE")
    summary: dict[str, Any] = {
        "phase": "A",
        "wsp_register_version": report.register_version,
        "wsp_register_status": "CLEAR" if report.exception_count == 0 else "EXCEPTIONS",
        "wsp_row_count": len(report.tests),
        "3120_passed_count": sum(item.status == "PASS" for item in report.tests),
        "3120_exception_count": report.exception_count,
        "3120_label": "Phase A",
        "cat_record_count": feedback["record_count"],
        "cat_feedback_count": len(rejections),
        "aml_alert_count": len(aml_cases),
        "surveillance_dispositions": list(surveillance_dispositions),
    }
    publication.mkdir(parents=True, exist_ok=True)
    (publication / "public-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
