"""The throughput probe must keep running, and keep being honest.

These are not performance assertions. Pinning a microsecond number in a test
would make the suite fail on a slower machine, which teaches a team to
ignore it. What is asserted is that the probe runs, that it reports the
fields a reader needs, and that its own caveats have not been quietly
deleted - because the caveats are what keep the number from being quoted as
something it is not.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import throughput_probe  # noqa: E402


@pytest.mark.parametrize("name", sorted(throughput_probe._stages()))
def test_every_stage_benchmarks(name: str) -> None:
    fn, description = throughput_probe._stages()[name]
    result = throughput_probe._bench(fn, iterations=50, repeats=2)
    assert result["per_call_microseconds"] > 0
    assert result["calls_per_second"] > 0
    assert description, f"{name} has no description of what one call is"


def test_the_probe_states_what_it_does_not_measure() -> None:
    """The caveats are load-bearing. A number from this tool is quotable only
    alongside them, and deleting them is how a benchmark becomes a lie."""
    doc = throughput_probe.__doc__ or ""
    assert "does **not** measure settlement throughput" in doc
    assert "single-threaded" in doc
    assert "excludes serialisation" in doc.lower()
    assert "shaped by the author's assumptions" in doc


def test_every_stage_is_a_pure_call_with_no_arguments() -> None:
    """If a stage needed I/O or state threaded in, it would not be benchable
    this way - and the fact that none does is the property being measured."""
    for _name, (fn, _desc) in throughput_probe._stages().items():
        fn()  # callable with no arguments, twice, with no setup between
        fn()
