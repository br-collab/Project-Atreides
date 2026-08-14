"""The end-to-end probe must keep running.

The four builds landed as islands, each with its own tests and none of them
ever run against the others - so the seams between them were untested by
construction. These tests are cheap and they are the only thing standing
between "each module passes" and "the modules work together".

The determinism assertions matter most. A framework whose whole claim is
byte-for-byte replayability should notice the day that stops being true on
the first run after the change, not when somebody asks for a decision from
three months ago.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import pipeline_probe  # noqa: E402


@pytest.mark.parametrize("name", sorted(pipeline_probe.SCENARIOS))
def test_every_scenario_runs_and_is_deterministic(name: str) -> None:
    trace, deterministic = pipeline_probe.run(name)
    assert trace, f"{name} produced an empty trace"
    assert deterministic, f"{name} produced different traces on identical inputs"


@pytest.mark.parametrize("name", sorted(pipeline_probe.SCENARIOS))
def test_every_trace_is_json_serialisable(name: str) -> None:
    """A trace that cannot be serialised cannot be diffed across runs, which
    is what makes the probe usable for a controlled test over days."""
    trace, _ = pipeline_probe.run(name)
    assert json.loads(json.dumps(trace, sort_keys=True)) == json.loads(
        json.dumps(trace, sort_keys=True)
    )


@pytest.mark.parametrize("name", sorted(pipeline_probe.SCENARIOS))
def test_every_scenario_is_documented(name: str) -> None:
    """A scenario nobody can describe is a scenario nobody will interpret."""
    assert (pipeline_probe.SCENARIOS[name].__doc__ or "").strip()


def test_the_queue_scenario_shows_a_queue_and_not_a_failure() -> None:
    """The doctrine the whole cash leg is built on, asserted end to end
    rather than only in the funding model's own tests."""
    trace, _ = pipeline_probe.run("queued")
    assert trace["funding"]["disposition"] == "will_queue"
    assert trace["funding"]["is_failure"] is False
    assert trace["gate"]["decision"] == "HOLD"
    assert trace["artifact"] is None


def test_the_silence_scenario_establishes_nothing() -> None:
    trace, _ = pipeline_probe.run("silence")
    assert trace["readback"]["is_absent"] is True
    assert trace["readback"]["settled_ids"] == []
    codes = {b["code"] for b in trace["readback"]["breaks"]}
    assert "rejected" not in codes


def test_a_contingent_settlement_carries_two_finality_classes() -> None:
    """The structural point of the fifth class, visible on one decision."""
    trace, _ = pipeline_probe.run("contingent-qualified")
    assert trace["gate"]["rail_finality_class"] == "GROSS_FINAL"
    assert trace["gate"]["obligation_finality_class"] == "DETERMINATION_DEPENDENT"
    assert trace["funding"]["disposition"] == "funded_qualified"
    assert trace["funding"]["settles"] is True


def test_a_partial_batch_reconciles_what_it_can() -> None:
    trace, _ = pipeline_probe.run("partial-batch")
    assert trace["readback"]["entry_count"] == 3
    assert trace["readback"]["parsed_entries"] == 2
    assert trace["readback"]["malformed_entries"] == 1
    assert trace["readback"]["settled_ids"] == ["E2E-0001"]


def test_nothing_the_probe_emits_is_a_submission() -> None:
    """The constraint is permanent and the probe is the place somebody would
    most plausibly forget it."""
    for name in pipeline_probe.SCENARIOS:
        trace, _ = pipeline_probe.run(name)
        artifact = trace.get("artifact")
        if artifact:
            assert artifact["is_submission"] is False
