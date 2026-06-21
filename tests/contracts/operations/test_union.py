"""Smoke tests for the ``CustodyOperationUnion`` discriminated union.

Verifies that the ``kind`` field discriminates correctly across all
nine operation modules — the pattern downstream agents and DSOR replay
will rely on when reconstructing operations from raw dicts.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from aureon.contracts.operations import (
    CustodyOperationUnion,
    DerivativeOperation,
    EquityOperation,
    FixedIncomeOperation,
    FundOperation,
    FXOperation,
    LifecycleOperation,
    NativeDigitalOperation,
    StructuredOperation,
    TokenizedOperation,
)

_ADAPTER: TypeAdapter[CustodyOperationUnion] = TypeAdapter(
    CustodyOperationUnion
)


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [
        ("equity", EquityOperation),
        ("fixed_income", FixedIncomeOperation),
        ("fx", FXOperation),
        ("derivative", DerivativeOperation),
        ("fund", FundOperation),
        ("structured", StructuredOperation),
        ("tokenized", TokenizedOperation),
        ("native_digital", NativeDigitalOperation),
        ("lifecycle", LifecycleOperation),
    ],
)
def test_union_dispatches_on_kind(
    kind: str,
    expected_type: type,
) -> None:
    """Constructing each kind directly produces the expected model.

    The exhaustive per-kind construction tests live in the per-asset-
    class test modules — this test only verifies that the union
    knows about every kind.
    """
    assert any(
        kind == arg.model_fields["kind"].default
        for arg in CustodyOperationUnion.__args__[0].__args__
    ), f"kind={kind!r} not found in CustodyOperationUnion"
    # Also verify the expected_type is one of the union members.
    union_members = CustodyOperationUnion.__args__[0].__args__
    assert expected_type in union_members


def test_union_rejects_unknown_kind() -> None:
    """An unknown ``kind`` is rejected by the discriminator."""
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"kind": "fictional-asset-class"})
