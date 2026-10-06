"""Acceptance tests for the synthetic advisory publication document."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from atreides.customer_protection.publication import AdvisoryPublication
from atreides.customer_protection.publication_writer import (
    publication_bytes,
    write_publication,
)
from atreides.customer_protection.scenarios import build_publication


def test_publication_round_trips_with_a_closed_schema() -> None:
    document = build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC))
    assert AdvisoryPublication.model_validate_json(document.model_dump_json()) == document


def test_writer_is_byte_deterministic() -> None:
    taken_at = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
    assert publication_bytes(taken_at) == publication_bytes(taken_at)


def test_real_scenarios_yield_all_three_advisory_dispositions() -> None:
    document = build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC))
    assert {
        advisory.disposition.value
        for scenario in document.scenarios
        for advisory in scenario.advisories
    } == {
        "PASS",
        "HOLD",
        "INDETERMINATE",
    }


@pytest.mark.parametrize("schema_version", [0, 2, "1"])
def test_publication_rejects_unknown_schema_versions(schema_version: object) -> None:
    document = build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC)).model_dump()
    document["schema_version"] = schema_version
    with pytest.raises(ValidationError):
        AdvisoryPublication.model_validate(document)


def test_publication_rejects_empty_scenarios_and_advisories() -> None:
    document = build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC)).model_dump()
    document["scenarios"] = []
    with pytest.raises(ValidationError):
        AdvisoryPublication.model_validate(document)

    document = build_publication(datetime(2026, 10, 6, 20, 0, tzinfo=UTC)).model_dump()
    document["scenarios"][0]["advisories"] = []
    with pytest.raises(ValidationError):
        AdvisoryPublication.model_validate(document)


def test_writer_round_trip_preserves_every_advisory_field(tmp_path: Path) -> None:
    output = tmp_path / "advisories.json"
    written = write_publication(
        output, taken_at=datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
    )
    raw = json.loads(output.read_bytes())
    first = raw["scenarios"][0]["advisories"][0]
    assert set(first) == set(type(written.scenarios[0].advisories[0]).model_fields)
    assert first["enforcement_status"] == "ADVISORY_ONLY"
    assert first["claim_label"] == "EXPERIMENTAL"
