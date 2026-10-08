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

from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from atreides.traceability import MarkedItem, load_register, validate_requirement_markers

REGISTER_PATH = Path(__file__).resolve().parents[1] / "docs/requirements/register.json"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Fail collection when a test claims an identifier absent from the register."""
    register = load_register(REGISTER_PATH)
    marked_items: list[MarkedItem] = items  # type: ignore[assignment]
    validate_requirement_markers(marked_items, register.ids)


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
