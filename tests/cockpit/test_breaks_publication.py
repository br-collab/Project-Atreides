"""Acceptance tests for the complete synthetic break publication."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from atreides.cockpit.break_scenarios import build_synthetic_records
from atreides.cockpit.breaks import BreakState
from atreides.cockpit.breaks_publication import BreaksPublication
from atreides.cockpit.breaks_publication_writer import (
    build_publication,
    main,
    publication_bytes,
    write_publication,
)

TAKEN_AT = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)


def test_writer_is_byte_deterministic_and_complete() -> None:
    assert publication_bytes(TAKEN_AT) == publication_bytes(TAKEN_AT)
    publication = BreaksPublication.model_validate_json(publication_bytes(TAKEN_AT))
    assert publication.complete is True
    assert publication.synthetic is True
    assert publication.enforcement_status == "ADVISORY_ONLY"
    assert publication.claim_label == "EXPERIMENTAL"


def test_writer_refuses_a_partial_snapshot() -> None:
    records = build_synthetic_records()
    with pytest.raises(ValueError, match="partial or unexpected"):
        build_publication(records[:1], taken_at=TAKEN_AT)


def test_tampered_record_fails_digest_validation() -> None:
    document = json.loads(publication_bytes(TAKEN_AT))
    document["records"][0]["difference"] = "tampered"
    with pytest.raises(ValidationError, match="input_digest"):
        BreaksPublication.model_validate_json(json.dumps(document))


def test_missing_owner_survives_publication_as_absent() -> None:
    publication = BreaksPublication.model_validate_json(publication_bytes(TAKEN_AT))
    unowned = next(record for record in publication.records if record.owner is None)
    assert unowned.owner_absence_reason == "awaiting production owner assignment"
    assert unowned.state is BreakState.INTAKE_UNASSIGNED
    assert unowned.owner_missing is True


def test_writer_round_trip_preserves_every_break_field(tmp_path: Path) -> None:
    output = tmp_path / "breaks.json"
    written = write_publication(output, taken_at=TAKEN_AT)
    raw = json.loads(output.read_bytes())
    assert set(raw["records"][0]) == set(type(written.records[0]).model_fields)


def test_command_writes_the_complete_document(tmp_path: Path) -> None:
    output = tmp_path / "breaks.json"
    assert main([str(output)]) == 0
    publication = BreaksPublication.model_validate_json(output.read_bytes())
    assert {record.break_id for record in publication.records} == {
        "BRK-SYNTHETIC-FUNDING",
        "BRK-SYNTHETIC-POSITION",
    }
