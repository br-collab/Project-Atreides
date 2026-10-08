"""Collection-time validation for requirement markers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

__all__ = ["MarkedItem", "validate_requirement_markers"]


class MarkedItem(Protocol):
    nodeid: str

    def iter_markers(self, name: str) -> Iterable[Any]: ...


def validate_requirement_markers(items: Sequence[MarkedItem], known_ids: frozenset[str]) -> None:
    """Reject malformed or unknown requirement markers during collection."""
    import pytest

    for item in items:
        for marker in item.iter_markers(name="requirement"):
            if len(marker.args) != 1 or not isinstance(marker.args[0], str):
                raise pytest.UsageError(
                    f"{item.nodeid}: requirement marker needs exactly one string ID"
                )
            requirement_id = marker.args[0]
            if requirement_id not in known_ids:
                raise pytest.UsageError(f"{item.nodeid}: unknown requirement ID {requirement_id!r}")
