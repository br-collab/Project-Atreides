"""CONV-2 account-transfer acceptance and property tests."""

from datetime import date
from decimal import Decimal
from typing import cast

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.books.ledger import EquitiesBooks
from simulator.account_transfers import (
    _account_totals,
    _post_transfer,
    attack_account_transfers,
    run_account_transfers,
)
from simulator.conversion import StatementLine

LINE_DAY = date(2026, 10, 5)


def test_clean_and_residual_transfers_reconcile_per_account() -> None:
    for variant in ("clean", "partial-residual"):
        result = run_account_transfers(variant)
        assert result["finra_license_gate"] == "INDETERMINATE"
        for transfer in cast(list[dict[str, object]], result["transfers"]):
            assert transfer["i10_migration_conserved"] is True


def test_late_transfer_holds_each_affected_account_by_name() -> None:
    result = run_account_transfers("late")
    transfers = cast(list[dict[str, object]], result["transfers"])
    assert {item["account"] for item in transfers} == {"SYN-CUST-101", "SYN-CUST-202"}
    assert all(item["disposition"] == "HOLD" for item in transfers)
    assert all(item["reasons"] for item in transfers)


def test_rejected_transfer_never_posts_and_is_not_given_literal_i10() -> None:
    result = run_account_transfers("reject")
    for transfer in cast(list[dict[str, object]], result["transfers"]):
        assert transfer["posted_quantity"] == "0"
        assert transfer["posted_cash"] == "0"
        assert transfer["i10_migration_conserved"] is None
        assert "not applicable" in transfer["i10_reason"]


def test_real_residual_mutation_reruns_and_turns_i10_false() -> None:
    assert attack_account_transfers() == {"drop-residual": True}


@seed(20261025)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=1_000_000),
    cash_cents=st.integers(min_value=1, max_value=100_000_000_00),
    split=st.integers(min_value=1, max_value=99),
)
def test_partial_and_residual_conserve_every_share_and_cent(
    quantity: int, cash_cents: int, split: int
) -> None:
    line = StatementLine(
        "SYN-PROPERTY-ACCOUNT",
        "SYN-PROPERTY-ISSUE",
        Decimal(quantity),
        Decimal(cash_cents) / 100,
    )
    main_quantity = (line.quantity * Decimal(split) / 100).quantize(Decimal("1"))
    main_cash = (line.cash_credit * Decimal(split) / 100).quantize(Decimal("0.01"))
    books = EquitiesBooks(break_owner="CONV_2_PROPERTY")
    _post_transfer(
        books,
        line,
        transfer_id="SYN-PROPERTY",
        sequence=100,
        quantity=main_quantity,
        cash=main_cash,
        day=LINE_DAY,
    )
    _post_transfer(
        books,
        line,
        transfer_id="SYN-PROPERTY",
        sequence=101,
        quantity=line.quantity - main_quantity,
        cash=line.cash_credit - main_cash,
        day=LINE_DAY,
    )
    assert _account_totals(books, line) == (line.quantity, line.cash_credit)
