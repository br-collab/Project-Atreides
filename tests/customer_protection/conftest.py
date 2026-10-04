"""Fixtures for the customer protection tests.

Every balance in these tests is SYNTHETIC: invented to exercise the arithmetic,
not taken from any firm's books or from the rule text.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from atreides.customer_protection.rules import RuleTable, load_rule_table
from atreides.customer_protection.rules.loader import DEFAULT_SOURCES_DIR, DEFAULT_TABLE_PATH


@pytest.fixture(scope="session")
def table() -> RuleTable:
    return load_rule_table()


TableEditor = Callable[[Callable[[dict[str, Any]], None]], RuleTable]


@pytest.fixture
def edited_table(tmp_path: Path) -> TableEditor:
    """Load a copy of the committed table after applying ``edit`` to its JSON document."""

    def _load(edit: Callable[[dict[str, Any]], None]) -> RuleTable:
        sources = tmp_path / "sources"
        if not sources.exists():
            shutil.copytree(DEFAULT_SOURCES_DIR, sources)
        document = json.loads(DEFAULT_TABLE_PATH.read_text(encoding="utf-8"))
        edit(document)
        path = tmp_path / "table.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_rule_table(path, sources)

    return _load


def without(*rule_ids: str) -> Callable[[dict[str, Any]], None]:
    """An edit that removes rows, as if those items had never been loaded."""

    def _edit(document: dict[str, Any]) -> None:
        document["items"] = [row for row in document["items"] if row["id"] not in rule_ids]

    return _edit
