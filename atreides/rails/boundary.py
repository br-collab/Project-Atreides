"""Enum coercion at the boundary (ATR-I-05).

The gate and the funding model compare enum members by identity (``is``). A
value that arrives from JSON, a dict or a caller as a plain string is never
identical to a member, so before Wave 2 it skipped every branch and landed in
the most forgiving one: a raw ``"CORRESPONDENT_DEPENDENT"`` returned FUNDED
where the member returned INDETERMINATE.

The rule here is the one ``Counterparty`` already applied to its standing, now
shared:

- a member stays a member;
- a plain string equal to a member's value becomes that member;
- anything else (a wrongly-cased spelling, an unknown word, another type) is
  left as it is and reported as unrecognised, so the caller can refuse it.

Matching is exact. ``"correspondent_dependent"`` is not ``"CORRESPONDENT_DEPENDENT"``:
guessing at a spelling is how a boundary turns one value into another.

PURE, NO I/O, NO CLOCK.
"""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

__all__ = ["coerce_member", "describe", "unrecognised"]

E = TypeVar("E", bound=Enum)


def coerce_member(enum_cls: type[E], value: object) -> E | object:
    """The member ``value`` names exactly, or ``value`` unchanged."""
    if isinstance(value, enum_cls):
        return value
    if type(value) is str:
        for member in enum_cls:
            if member.value == value:
                return member
    return value


def unrecognised(**fields: tuple[type[Enum], object]) -> tuple[str, ...]:
    """Names of the fields whose value is not a member of its enum.

    ``fields`` maps a field name to ``(enum class, value)``. ``None`` is not
    handled here; callers pass only fields that must hold a member.
    """
    return tuple(
        name for name, (enum_cls, value) in fields.items() if not isinstance(value, enum_cls)
    )


def describe(value: object) -> str:
    """A member's value, or an explicit marker for anything unrecognised."""
    if isinstance(value, Enum):
        return str(value.value)
    return f"UNRECOGNISED:{value!r}"
