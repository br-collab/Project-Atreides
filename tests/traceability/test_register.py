"""Acceptance tests for the requirement register and marker guard."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from atreides.traceability import (
    RequirementRegister,
    TextSource,
    load_register,
    validate_requirement_markers,
)

REGISTER_PATH = Path(__file__).resolve().parents[2] / "docs/requirements/register.json"


class _Item:
    nodeid = "tests/example.py::test_example"

    def __init__(self, requirement_id: object) -> None:
        self._marker = SimpleNamespace(args=(requirement_id,))

    def iter_markers(self, name: str) -> list[Any]:
        return [self._marker] if name == "requirement" else []


def _document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(REGISTER_PATH.read_text(encoding="utf-8")))


def test_committed_register_contains_every_supplied_pack_identifier() -> None:
    register = load_register(REGISTER_PATH)
    expected = {
        *(f"BR-{number:02d}" for number in range(1, 27)),
        *(f"TR-{number:02d}" for number in range(1, 18)),
        *(f"NF-{number:02d}" for number in range(1, 8)),
    }
    assert expected <= register.ids
    pack_rows = [row for row in register.requirements if row.requirement_id in expected]
    assert all(row.text_source is TextSource.ABSENT for row in pack_rows)


def test_duplicate_requirement_id_fails_load() -> None:
    document = _document()
    document["requirements"].append(document["requirements"][0])
    with pytest.raises(ValidationError, match="requirement_id values must be unique"):
        RequirementRegister.model_validate_json(json.dumps(document))


def test_row_without_source_clause_fails_load() -> None:
    document = _document()
    document["requirements"][0]["source_clause"] = ""
    with pytest.raises(ValidationError, match="source_clause"):
        RequirementRegister.model_validate_json(json.dumps(document))


def test_unknown_requirement_id_fails_collection_validation() -> None:
    with pytest.raises(pytest.UsageError, match="unknown requirement ID"):
        validate_requirement_markers([_Item("BR-99")], load_register(REGISTER_PATH).ids)


def test_known_requirement_id_passes_collection_validation() -> None:
    validate_requirement_markers([_Item("BR-01")], load_register(REGISTER_PATH).ids)


def test_marker_requires_exactly_one_string_id() -> None:
    with pytest.raises(pytest.UsageError, match="exactly one string ID"):
        validate_requirement_markers([_Item(1)], load_register(REGISTER_PATH).ids)
