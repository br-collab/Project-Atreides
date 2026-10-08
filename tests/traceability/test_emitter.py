"""Acceptance tests for deterministic, fail-closed traceability evidence."""

from __future__ import annotations

import json
from pathlib import Path

from atreides.traceability import (
    RequirementEvidence,
    RunScope,
    TraceabilityDocument,
    TraceStatus,
    build_traceability,
    load_register,
    write_traceability,
)
from atreides.traceability import TestOutcome as Outcome

REGISTER_PATH = Path(__file__).resolve().parents[2] / "docs/requirements/register.json"


def _build(
    nodes: dict[str, tuple[str, ...]], outcomes: dict[str, Outcome]
) -> TraceabilityDocument:
    return build_traceability(
        load_register(REGISTER_PATH),
        nodes,
        outcomes,
        run_scope=RunScope.FULL,
        run_commit_sha="a" * 40,
        run_timestamp="2026-10-08T12:00:00+00:00",
    )


def _row(document: TraceabilityDocument, requirement_id: str) -> RequirementEvidence:
    return next(row for row in document.requirements if row.requirement_id == requirement_id)


def test_same_inputs_give_the_same_digest_regardless_of_collection_order() -> None:
    first = _build(
        {"tests/b.py::test_b": ("SC-G-01",), "tests/a.py::test_a": ("SC-G-01",)},
        {"tests/b.py::test_b": Outcome.PASSED, "tests/a.py::test_a": Outcome.PASSED},
    )
    second = _build(
        {"tests/a.py::test_a": ("SC-G-01",), "tests/b.py::test_b": ("SC-G-01",)},
        {"tests/a.py::test_a": Outcome.PASSED, "tests/b.py::test_b": Outcome.PASSED},
    )
    assert first.digest == second.digest
    assert _row(first, "SC-G-01").test_node_ids == (
        "tests/a.py::test_a",
        "tests/b.py::test_b",
    )


def test_a_failing_marked_test_shows_failing() -> None:
    document = _build({"tests/x.py::test_x": ("SC-G-01",)}, {
        "tests/x.py::test_x": Outcome.FAILED
    })
    assert _row(document, "SC-G-01").status is TraceStatus.FAILING


def test_a_skipped_marked_test_shows_not_run() -> None:
    document = _build({"tests/x.py::test_x": ("SC-G-01",)}, {
        "tests/x.py::test_x": Outcome.NOT_RUN
    })
    assert _row(document, "SC-G-01").status is TraceStatus.NOT_RUN


def test_a_requirement_with_no_marked_test_shows_untested() -> None:
    assert _row(_build({}, {}), "SC-G-01").status is TraceStatus.UNTESTED


def test_only_passing_marked_tests_show_covered() -> None:
    document = _build({"tests/x.py::test_x": ("SC-G-01",)}, {
        "tests/x.py::test_x": Outcome.PASSED
    })
    row = _row(document, "SC-G-01")
    assert row.status is TraceStatus.COVERED
    assert document.synthetic is True
    assert document.enforcement_status == "ADVISORY_ONLY"
    assert document.claim_label == "EXPERIMENTAL"


def test_writer_emits_the_complete_document(tmp_path: Path) -> None:
    destination = tmp_path / "traceability.json"
    document = _build({}, {})
    write_traceability(destination, document)
    assert json.loads(destination.read_text(encoding="utf-8")) == document.model_dump(mode="json")
