"""Shared pytest configuration.

Hypothesis runs at a low example count by default so the suite stays fast
enough that people actually run it, and offers a deep profile for the
occasions when you want it hunting rather than confirming::

    pytest --hypothesis-profile=deep tests/test_properties.py

Deep is the mode to run before a release or after changing anything a
property asserts, not the mode to run on every save.

**No wall-clock figure is quoted here on purpose.** Runtime depends on the
machine, the Python build and what else it is doing, and a timing measured
somewhere else is a number without provenance - the same defect this
framework refuses everywhere it holds a venue figure. What is fixed and
quotable is the example count: 200 by default, 2,000 on deep.

Note also that deep is not ten times default. Hypothesis spends
proportionally more effort on shrinking and on replaying its database of
previously interesting examples as the count rises, so the honest guidance
is to run it once on your own hardware and use that as your baseline.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from atreides.traceability import (
    MarkedItem,
    RunScope,
    TestOutcome,
    build_traceability,
    load_register,
    validate_requirement_markers,
    write_traceability,
)

REGISTER_PATH = Path(__file__).resolve().parents[1] / "docs/requirements/register.json"
REPOSITORY_ROOT = REGISTER_PATH.parents[2]
TRACEABILITY_PATH = REPOSITORY_ROOT / "traceability.json"

_node_requirements: dict[str, tuple[str, ...]] = {}
_outcomes: dict[str, TestOutcome] = {}
_run_timestamp = [""]
_run_scope = [RunScope.FULL]


def pytest_configure(config: pytest.Config) -> None:
    """Treat every explicitly selected path or node as a partial run."""
    has_selector = any(not argument.startswith("-") for argument in config.invocation_params.args)
    _run_scope[0] = RunScope.PARTIAL if has_selector else RunScope.FULL


def pytest_sessionstart() -> None:
    """Capture one timestamp for the complete test session."""
    _node_requirements.clear()
    _outcomes.clear()
    _run_timestamp[0] = datetime.now(UTC).isoformat()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Fail collection when a test claims an identifier absent from the register."""
    register = load_register(REGISTER_PATH)
    marked_items: list[MarkedItem] = items  # type: ignore[assignment]
    validate_requirement_markers(marked_items, register.ids)
    for item in items:
        requirement_ids = tuple(
            str(marker.args[0]) for marker in item.iter_markers(name="requirement")
        )
        if requirement_ids:
            _node_requirements[item.nodeid] = requirement_ids


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Retain the fail-closed terminal outcome of each marked test."""
    if report.nodeid not in _node_requirements:
        return
    if report.failed:
        _outcomes[report.nodeid] = TestOutcome.FAILED
    elif report.skipped and _outcomes.get(report.nodeid) is not TestOutcome.FAILED:
        _outcomes[report.nodeid] = TestOutcome.NOT_RUN
    elif report.when == "call" and report.passed and report.nodeid not in _outcomes:
        _outcomes[report.nodeid] = TestOutcome.PASSED


def _run_commit_sha() -> str:
    supplied = os.environ.get("GITHUB_SHA")
    if supplied:
        return supplied
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def pytest_sessionfinish() -> None:
    """Write traceability evidence after every complete pytest session."""
    document = build_traceability(
        load_register(REGISTER_PATH),
        _node_requirements,
        _outcomes,
        run_scope=_run_scope[0],
        run_commit_sha=_run_commit_sha(),
        run_timestamp=_run_timestamp[0],
    )
    write_traceability(TRACEABILITY_PATH, document)


settings.register_profile(
    "default",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "deep",
    max_examples=2_000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
# Never loaded by default. One derandomized example per property test, so a
# coverage run under it measures what the example tests cover on their own,
# and a coverage floor cannot depend on which examples Hypothesis happened to
# generate (ORDER HYG-1). CI's coverage step runs under it::
#
#     pytest --hypothesis-profile=floor --cov=atreides --cov-branch
#
# It is not a bug-finding mode. One example finds almost nothing, which is
# why CI's plain pytest step still runs the default profile.
settings.register_profile(
    "floor",
    max_examples=1,
    derandomize=True,
    deadline=None,
)
settings.load_profile("default")
