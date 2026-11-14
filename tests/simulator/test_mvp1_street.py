"""MVP-1 independent street-side reconciliation acceptance."""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack
from simulator.street import (
    DepositoryPosition,
    SyntheticDepository,
    reconcile,
    reconciliation_calendar,
)


def test_street_module_does_not_import_books() -> None:
    source = Path("simulator/street.py").read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        name == "atreides.books" or name.startswith("atreides.books.") for name in imported
    )
    assert "atreides.books" not in source


def test_breaks_are_owned_aged_and_start_unclassified() -> None:
    street = SyntheticDepository((DepositoryPosition("ACME", "DTC", Decimal(-10)),))
    first = reconcile({("ACME", "DTC"): Decimal(-9)}, street.statement(date(2027, 1, 4)))
    aged = reconcile(
        {("ACME", "DTC"): Decimal(-9)}, street.statement(date(2027, 1, 6)), first
    )
    assert aged[0].owner == "SCF1_SETTLEMENT_CONTROL"
    assert aged[0].opened_at == date(2027, 1, 4)
    assert aged[0].age_calendar_days == 2
    assert aged[0].cause == "UNCLASSIFIED"


def test_four_ordered_mutations_make_i3_false_with_owned_breaks() -> None:
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/3"), "small")
    assert run_firm(profile, days=1, verify_replay=False).days[0].invariants[
        "I3_STOCK_RECORD_EQUALS_STREET"
    ]
    for mutation in (
        "BOOKED_QUANTITY_STREET_LACKS",
        "STREET_MOVEMENT_BOOKS_MISSED",
        "WRONG_LOCATION_BOOKING",
        "DUPLICATE_BOOKING",
    ):
        day = run_firm(
            profile, days=1, mutation=mutation, verify_replay=False
        ).days[0]
        assert not day.invariants["I3_STOCK_RECORD_EQUALS_STREET"]
        assert day.invariants["I4_EVERY_DIFFERENCE_OWNED"]
        assert day.street_breaks
        assert all(item.owner and item.cause == "UNCLASSIFIED" for item in day.street_breaks)


def test_calendar_reports_ran_and_not_run() -> None:
    results = reconciliation_calendar(date(2027, 1, 4))
    assert {item.status for item in results} == {"RAN", "NOT_RUN"}
    ran = next(item for item in results if item.item_id == "stock-record-to-street")
    assert ran.status == "RAN"
