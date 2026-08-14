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

from hypothesis import HealthCheck, settings

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
settings.load_profile("default")
