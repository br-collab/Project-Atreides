"""Acceptance tests for the synthetic advisory publication document."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module

import pytest


@pytest.mark.xfail(strict=True, reason="WP-1 publication model is not implemented yet")
def test_publication_round_trips_with_a_closed_schema() -> None:
    publication = import_module("atreides.customer_protection.publication")
    scenarios = import_module("atreides.customer_protection.scenarios")
    document = scenarios.build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC))
    assert publication.AdvisoryPublication.model_validate_json(
        document.model_dump_json()
    ) == document


@pytest.mark.xfail(strict=True, reason="WP-1 publication writer is not implemented yet")
def test_writer_is_byte_deterministic() -> None:
    writer = import_module("atreides.customer_protection.publication_writer")
    taken_at = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
    assert writer.publication_bytes(taken_at) == writer.publication_bytes(taken_at)


@pytest.mark.xfail(strict=True, reason="WP-1 scenarios are not implemented yet")
def test_real_scenarios_yield_all_three_advisory_dispositions() -> None:
    scenarios = import_module("atreides.customer_protection.scenarios")
    document = scenarios.build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC))
    assert {advisory.disposition.value for scenario in document.scenarios for advisory in scenario.advisories} == {
        "PASS",
        "HOLD",
        "INDETERMINATE",
    }
