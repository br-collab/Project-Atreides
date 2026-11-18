"""MVP-5B cash-account posting conservation."""

from decimal import Decimal

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.books.ledger import RecordSide
from simulator.estate import cash_account_purchase_lines


@seed(20261117)
@settings(max_examples=200)
@given(
    quantity=st.integers(min_value=1, max_value=1_000_000),
    price_cents=st.integers(min_value=1, max_value=10_000_000),
)
def test_cash_purchase_conserves_quantity_and_money_to_the_cent(
    quantity: int, price_cents: int
) -> None:
    price = Decimal(price_cents) / Decimal(100)
    consideration = (Decimal(quantity) * price).quantize(Decimal("0.01"))
    ownership, money = cash_account_purchase_lines(
        account_id="SYN-PROPERTY-ACCOUNT",
        issue="SYN-PROPERTY-EQUITY",
        quantity=Decimal(quantity),
        consideration=consideration,
    )

    assert ownership.quantity == Decimal(quantity)
    assert ownership.record_side is RecordSide.OWNERSHIP
    assert money.money == -consideration
    assert money.record_side is RecordSide.MONEY
