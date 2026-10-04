"""Shared types for the customer protection engines.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

MONEY IS DECIMAL, AND ONLY DECIMAL
----------------------------------
A balance arrives as a ``Decimal``, a decimal string, or an integer, all of
which are exact. Anything else is refused at the boundary, which is the point:
a binary floating-point number cannot hold most cent amounts exactly, and an
engine that reports a reserve shortfall to the cent cannot start from a value
that was never the cent amount it claims to be. JSON (JavaScript Object
Notation) numbers with a fraction part arrive as binary floats too, so they are
refused as well; the canonical form writes money as a string.

THE ORDER OF DISPOSITIONS
-------------------------
:func:`decide` is the one place an engine turns its findings into a
:class:`~cannae_kernel.disposition.Disposition`:

1. A rule the computation needs is not loaded: INDETERMINATE. The answer cannot
   be determined from the evidence, so no other finding is trustworthy.
2. An input balance is missing, or the computation found a breach: HOLD.
3. Otherwise PASS, which means only that this computation, on these inputs and
   this rule text, found nothing. It is never a statement of compliance.

No path returns BLOCK. These engines advise; they do not stop anything.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from atreides.customer_protection.rules.model import RuleKind, RuleTable

__all__ = [
    "Frozen",
    "Money",
    "NonNegativeMoney",
    "RuleReader",
    "RuleRef",
    "decide",
]

ZERO = Decimal(0)


def _exact(value: object) -> object:
    if isinstance(value, Decimal | str) or (type(value) is int):
        return value
    raise ValueError(
        f"money must be a Decimal, a decimal string or an integer, not {type(value).__name__}"
    )


Money = Annotated[Decimal, BeforeValidator(_exact), Field(allow_inf_nan=False)]
NonNegativeMoney = Annotated[Decimal, BeforeValidator(_exact), Field(allow_inf_nan=False, ge=ZERO)]


class Frozen(BaseModel):
    """House model configuration: immutable, and an unknown field is an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleRef(Frozen):
    """One rule item a computation read, and the source text it was read from."""

    rule_id: str
    citation: str
    source_id: str
    sha256: str
    value: Decimal | None


class RuleReader:
    """Reads rule items for one computation, remembering what it used and what was missing.

    Every regulatory figure an engine uses goes through :meth:`value` or :meth:`present`.
    A missing item is recorded by name, and :func:`decide` turns any missing name
    into INDETERMINATE.
    """

    def __init__(self, table: RuleTable) -> None:
        self._table = table
        self._missing: set[str] = set()
        self._used: dict[str, RuleRef] = {}

    def _item(self, rule_id: str) -> RuleRef | None:
        item = self._table.get(rule_id)
        if item is None:
            self._missing.add(rule_id)
            return None
        ref = RuleRef(
            rule_id=item.id,
            citation=item.citation,
            source_id=item.source_id,
            sha256=item.sha256,
            value=item.value,
        )
        self._used[rule_id] = ref
        return ref

    def value(self, rule_id: str) -> Decimal | None:
        """The item's value, or ``None`` (recorded as missing) when it is not loaded."""
        ref = self._item(rule_id)
        return None if ref is None else ref.value

    def present(self, rule_id: str) -> bool:
        """Whether a categorical item (a line, a location, a provision) is loaded."""
        return self._item(rule_id) is not None

    def of_kind(self, kind: RuleKind) -> tuple[str, ...]:
        """Ids of every loaded item of ``kind``, in table order."""
        return tuple(item.id for item in self._table.of_kind(kind))

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(sorted(self._missing))

    @property
    def used(self) -> tuple[RuleRef, ...]:
        return tuple(self._used[key] for key in sorted(self._used))


def decide(
    missing_rules: Iterable[str],
    missing_inputs: Iterable[str],
    breaches: Iterable[str],
) -> Disposition:
    """The disposition for one computation. See the module docstring for the order."""
    if any(True for _ in missing_rules):
        return coerce_disposition(Disposition.INDETERMINATE)
    if any(True for _ in missing_inputs) or any(True for _ in breaches):
        return coerce_disposition(Disposition.HOLD)
    return coerce_disposition(Disposition.PASS)
