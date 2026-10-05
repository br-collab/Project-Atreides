"""The SC-2 rule table and its sources are declared as package data.

The loader reads ``table.json`` and ``sources/`` through ``Path(__file__)``. An editable
install reads them in place, so nothing fails until Atreides is installed from a wheel,
which is how aureon installs it. This test fails if a file the loader reads is not
matched by the package-data declaration in ``pyproject.toml``.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

from atreides.customer_protection.rules.loader import (
    DEFAULT_SOURCES_DIR,
    DEFAULT_TABLE_PATH,
    RULES_DIR,
)

REPO = Path(__file__).resolve().parents[2]
PACKAGE = "atreides.customer_protection.rules"


def declared() -> list[str]:
    with (REPO / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    return list(config["tool"]["setuptools"]["package-data"][PACKAGE])


def runtime_files() -> list[str]:
    files = [DEFAULT_TABLE_PATH, *sorted(p for p in DEFAULT_SOURCES_DIR.iterdir() if p.is_file())]
    return [f.relative_to(RULES_DIR).as_posix() for f in files]


def test_the_loader_reads_the_table_and_its_sources() -> None:
    names = runtime_files()
    assert "table.json" in names
    assert any(name.startswith("sources/") for name in names)


def test_every_file_the_loader_reads_is_declared_as_package_data() -> None:
    patterns = declared()
    undeclared = [
        name for name in runtime_files() if not any(fnmatch.fnmatch(name, p) for p in patterns)
    ]
    assert undeclared == []
