"""The volume probe must keep running, and keep being reproducible.

No distribution is asserted here. What the right hold rate is depends on the
firm and the book, and pinning a number would turn an operator judgment into
a build failure. What IS asserted is that the probe runs, that the sample is
seeded so two runs agree, and that the flatness metric still detects a
collapsed distribution - because that metric is the only thing standing
between "each gate is correct" and "the gates are correct together".
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import volume_probe  # noqa: E402


def test_the_sample_is_reproducible() -> None:
    """A probe whose output moves on its own teaches nobody anything."""
    assert volume_probe.run(200) == volume_probe.run(200)


def test_every_distribution_is_reported() -> None:
    result = volume_probe.run(100)
    for key in (
        "gate_decision",
        "gate_reason",
        "funding_disposition",
        "queue_ranks_unassessed",
        "queue_ranks_triaged",
    ):
        assert result[key], f"{key} is empty"


def test_the_counts_account_for_every_event() -> None:
    n = 300
    result = volume_probe.run(n)
    for key in ("gate_decision", "gate_reason", "funding_disposition"):
        assert sum(result[key].values()) == n, key  # type: ignore[union-attr]


def test_flatness_detects_a_collapsed_queue() -> None:
    """The metric that found the defect. In the shipped state every venue
    profile is flagged, so every break is INDETERMINATE for an unstated
    reason and the queue takes exactly one rank."""
    result = volume_probe.run(200)
    assert result["flatness"]["queue_unassessed"] == 1.0  # type: ignore[index]


def test_naming_the_reason_restores_an_ordering() -> None:
    """Triage does not invent information. It records which of three
    remedies applies, and the queue orders itself once it has."""
    result = volume_probe.run(200)
    flat = result["flatness"]  # type: ignore[index]
    assert flat["queue_triaged"] < flat["queue_unassessed"]  # type: ignore[index]
    assert len(result["queue_ranks_triaged"]) > 1  # type: ignore[arg-type]


def test_the_human_touch_rate_is_reported() -> None:
    """The number the approval-fatigue argument turns on. Not asserted
    against a threshold - surfaced so somebody has to look at it."""
    result = volume_probe.run(100)
    assert 0.0 <= result["human_touch_rate"] <= 1.0  # type: ignore[operator]
