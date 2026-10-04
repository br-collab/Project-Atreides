"""Money is exact at the boundary; the rule reader lists items by kind."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.customer_protection.common import Frozen, Money, NonNegativeMoney, RuleReader
from atreides.customer_protection.rules import RuleKind, RuleTable


class Balance(Frozen):
    amount: Money
    held: NonNegativeMoney = Decimal(0)


@pytest.mark.parametrize("value", [Decimal("1.10"), "1.10", 1])
def test_exact_money_is_accepted(value: object) -> None:
    assert Balance(amount=value).amount == Decimal(str(value))


@pytest.mark.parametrize("value", [1.1, True, None, [1]])
def test_inexact_money_is_refused(value: object) -> None:
    with pytest.raises(ValueError):
        Balance(amount=value)


def test_a_json_number_with_a_fraction_is_refused() -> None:
    with pytest.raises(ValueError):
        Balance.model_validate_json('{"amount": 1.1}')
    assert Balance.model_validate_json('{"amount": "1.1"}').amount == Decimal("1.1")


def test_non_finite_and_negative_held_money_are_refused() -> None:
    with pytest.raises(ValueError):
        Balance(amount=Decimal("NaN"))
    with pytest.raises(ValueError):
        Balance(amount=Decimal(0), held=Decimal(-1))


def test_models_are_frozen_and_closed() -> None:
    balance = Balance(amount=Decimal(1))
    with pytest.raises(ValueError):
        balance.amount = Decimal(2)  # type: ignore[misc]
    with pytest.raises(ValueError):
        Balance(amount=Decimal(1), extra=Decimal(1))  # type: ignore[call-arg]


def test_the_reader_lists_loaded_items_by_kind(table: RuleTable) -> None:
    reader = RuleReader(table)
    credits = reader.of_kind(RuleKind.EXHIBIT_A_CREDIT)
    assert credits[0] == "15c3-3a.item.01"
    assert len(credits) == 9
    assert len(reader.of_kind(RuleKind.EXHIBIT_A_DEBIT)) == 6
    assert reader.missing == ()
