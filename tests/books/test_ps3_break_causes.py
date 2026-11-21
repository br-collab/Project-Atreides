"""Break causes come from what the two sides show; age is reported, never a cause.

Inventory finding N1 (19 November 2026): every carried break used to be labelled TIMING,
which hid aged, unexplained differences. These tests plant breaks through the real firm run.
"""

from datetime import date
from decimal import Decimal

from atreides.books.ps1 import _break_cause
from simulator.calibration import load_calibration_pack
from simulator.firm import load_firm_profile, run_firm


def _cash_breaks(days: int, mutation: str | None) -> list[tuple[date, str, int, bool]]:
    run = run_firm(
        load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small"),
        days=days,
        verify_replay=False,
        mutation=mutation,
    )
    return [
        (day.business_date, item.cause, item.age_calendar_days, item.carried)
        for day in run.days
        for item in day.control_breaks
        if item.item_id == "cash-to-bank"
    ]


def test_a_carried_cash_break_keeps_its_cause_and_reports_its_age() -> None:
    rows = _cash_breaks(3, "UNPOSTED_DEPOSIT_INSTRUCTION")
    assert len(rows) == 3, rows
    causes = {cause for _, cause, _, _ in rows}
    assert causes == {"MISSING_BOOK_ENTRY"}, rows  # the books never posted the instruction
    assert "TIMING" not in causes
    first, second, third = rows
    assert (first[2], first[3]) == (0, False)
    assert second[3] and third[3]
    assert first[2] < second[2] < third[2]


def test_a_clean_run_has_no_control_breaks() -> None:
    assert _cash_breaks(2, None) == []


def test_causes_are_read_from_the_two_sides() -> None:
    def cause(
        books: dict[str, str], outside: dict[str, str], unsourced: frozenset[str] = frozenset()
    ) -> str:
        return _break_cause(
            key="A",
            books_values={k: Decimal(v) for k, v in books.items()},
            outside_values={k: Decimal(v) for k, v in outside.items()},
            unsourced_keys=unsourced,
        )

    assert cause({"A": "2"}, {"A": "1"}) == "QUANTITY_DIFFERENCE"
    assert cause({"A": "2"}, {}) == "MISSING_OUTSIDE_RECORD"
    assert cause({}, {"A": "2"}) == "MISSING_BOOK_ENTRY"
    assert cause({"A": "2"}, {"A": "-2"}) == "SIGN_DIFFERENCE"
    assert cause({"A": "2"}, {"A": "1"}, frozenset({"A"})) == "UNSOURCED_LOCATION"
