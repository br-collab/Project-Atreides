"""Shared pytest configuration.

Hypothesis runs at a low example count by default so the suite stays fast
enough that people actually run it, and offers a deep profile for the
occasions when you want it hunting rather than confirming::

    pytest --hypothesis-profile=deep tests/test_properties.py

Deep takes minutes rather than seconds. It is the mode to run before a
release or after changing anything a property asserts, not the mode to run
on every save.
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
