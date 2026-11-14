"""MVP-1B independent-source, fail-identity and observed-calendar acceptance."""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack
from simulator.street import (
    DepositoryPosition,
    LoanInstruction,
    OpenFail,
    SettlementOutcome,
    SyntheticDepository,
    cns_fail_source,
    loan_register_source,
    observed_reconcile,
    reconcile,
    reconciliation_calendar,
)


def test_source_module_has_no_books_or_firm_import() -> None:
    source = Path("simulator/street.py").read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(name.startswith("atreides.books") for name in imported)
    assert "simulator.firm" not in imported


def test_full_day_sources_do_not_read_raising_books() -> None:
    class RaisingBooks:
        @property
        def entries(self) -> object:
            raise AssertionError("source read books.entries")

        def quantities(self) -> object:
            raise AssertionError("source read books.quantities")

    books = RaisingBooks()
    opening = (DepositoryPosition("ACME", "DTC", Decimal(-100)),)
    depository = SyntheticDepository(opening)
    depository.apply_settlements(
        (SettlementOutcome("ACME", Decimal(10), Decimal(9), date(2027, 1, 5)),)
    )
    fail = OpenFail(
        "FAIL-1", "ACME", Decimal(1), Decimal(100), date(2027, 1, 5), Decimal(100)
    )
    instruction = LoanInstruction("LOAN-1", "ACME", Decimal(5), date(2027, 1, 4))
    depository.apply_instructions((instruction,))
    sources = (
        depository.source(date(2027, 1, 4)),
        cns_fail_source(date(2027, 1, 5), (fail,)),
        loan_register_source(date(2027, 1, 4), (instruction,)),
    )
    assert books is not None
    assert {source.location for source in sources} == {
        "DTC",
        "FAIL_TO_RECEIVE",
        "STOCK_LOANED",
    }
    assert all(item.location == "DTC" for item in sources[0].positions)


def test_upstream_mutations_are_detected_and_owned() -> None:
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/3"), "small")
    for mutation, days in (
        ("UPSTREAM_ALLOCATION_QUANTITY", 1),
        ("UPSTREAM_FAIL_QUANTITY", 2),
    ):
        day = run_firm(
            profile, days=days, mutation=mutation, verify_replay=False
        ).days[-1]
        assert not day.invariants["I3_STOCK_RECORD_EQUALS_STREET"]
        assert day.invariants["I4_EVERY_DIFFERENCE_OWNED"]
        assert day.street_breaks


def test_books_location_without_source_is_owned_unreconciled() -> None:
    as_of = date(2027, 1, 4)
    source = SyntheticDepository(
        (DepositoryPosition("ACME", "DTC", Decimal(-10)),)
    ).source(as_of)
    breaks, _ = reconcile(
        {("ACME", "DTC"): Decimal(-10), ("ACME", "BANK_CONTROL"): Decimal(2)},
        (source,),
        as_of=as_of,
    )
    assert [(item.location, item.cause, item.owner) for item in breaks] == [
        ("BANK_CONTROL", "UNSOURCED_LOCATION", "SCF1_SETTLEMENT_CONTROL")
    ]


def test_calendar_uses_observed_failed_and_missing_completion() -> None:
    as_of = date(2027, 1, 4)
    def forced_exception():  # type: ignore[no-untyped-def]
        raise RuntimeError("forced source exception")

    _, failed = observed_reconcile({}, (forced_exception,), as_of=as_of)
    results = reconciliation_calendar(as_of, (failed,))
    stock = next(item for item in results if item.item_id == "stock-record-to-street")
    fails = next(item for item in results if item.item_id == "ftr-to-cns-fail-statement")
    assert stock.status == "FAILED" and "forced source exception" in stock.reason
    assert fails.status == "NOT_RUN" and fails.reason == "no completion record"
