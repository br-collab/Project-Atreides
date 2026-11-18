from datetime import date
from decimal import Decimal

from atreides.books.ps1 import ControlBreak, _compare


def test_planted_breaks_receive_ranked_causes() -> None:
    day = date(2026, 11, 18)
    quantity = _compare(
        item_id="cash-to-bank",
        books_values={"A": Decimal("2")},
        outside_values={"A": Decimal("1")},
        owner="TREASURY_CONTROL",
        as_of=day,
        sources_read=("books", "bank"),
    )
    missing = _compare(
        item_id="cash-to-bank",
        books_values={"A": Decimal("2")},
        outside_values={},
        owner="TREASURY_CONTROL",
        as_of=day,
        sources_read=(),
    )
    prior = ControlBreak(
        "cash-to-bank",
        "A",
        Decimal("2"),
        Decimal("1"),
        Decimal("1"),
        "TREASURY_CONTROL",
        date(2026, 11, 17),
        0,
        "QUANTITY_DIFFERENCE",
    )
    timing = _compare(
        item_id="cash-to-bank",
        books_values={"A": Decimal("2")},
        outside_values={"A": Decimal("1")},
        owner="TREASURY_CONTROL",
        as_of=day,
        prior_breaks=(prior,),
        sources_read=("books", "bank"),
    )
    assert quantity.breaks[0].cause == "QUANTITY_DIFFERENCE"
    assert missing.breaks[0].cause == "MISSING_INSTRUCTION"
    assert timing.breaks[0].cause == "TIMING"
