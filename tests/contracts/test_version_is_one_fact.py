"""The version the package reports is the version that was installed.

`atreides/__init__.py` carried `__version__ = "0.1.0"` as a literal. The
distribution was at 0.5.0 by the time anyone noticed, so anything reading
`atreides.__version__` — a log line, a report header, a compatibility check —
got an answer that had been wrong for four releases and never failed anything.

It is the wave's own defect class in miniature: a value that looks authoritative,
that nothing computes, and that no test disagreed with. So it is now derived from
the installed distribution metadata, and this asserts the two cannot part company.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import atreides

ROOT = Path(__file__).resolve().parents[2]


def test_the_package_reports_the_installed_distribution_version() -> None:
    assert atreides.__version__ == version("atreides")


def test_the_installed_version_is_the_one_pyproject_declares() -> None:
    """Catches an editable install left behind by a version bump."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert version("atreides") == declared, (
        f"pyproject declares {declared} and the installed distribution is "
        f"{version('atreides')}; reinstall, or the bump is incomplete"
    )


def test_the_version_is_derived_and_not_a_release_number_in_the_source() -> None:
    """A literal release number is what drifted. If one comes back, this says so.

    The sentinel the uninstalled-source branch falls back to is deliberately not a
    plausible release, so it cannot be mistaken for one in a log line — and this
    test would fail if somebody replaced it with one that could.
    """
    import re

    source = (ROOT / "atreides" / "__init__.py").read_text(encoding="utf-8")
    assert "importlib.metadata" in source, "the version is no longer derived"

    literals = re.findall(r'__version__\s*=\s*"([^"]+)"', source)
    for literal in literals:
        assert not re.fullmatch(r"\d+\.\d+(\.\d+)?", literal), (
            f"__version__ is assigned the release number {literal!r}; derive it from "
            "the distribution metadata so it cannot disagree with what was installed"
        )


def test_the_doctrine_version_has_one_home() -> None:
    """A second, unused copy sat in __init__.py and could drift from the real one."""
    from atreides.contracts.dsor_stub import CURRENT_DOCTRINE_VERSION

    assert CURRENT_DOCTRINE_VERSION
    assert not hasattr(atreides, "DOCTRINE_VERSION"), (
        "a second copy of the doctrine version is back in atreides/__init__.py; "
        "CURRENT_DOCTRINE_VERSION in contracts.dsor_stub is the one records carry"
    )
