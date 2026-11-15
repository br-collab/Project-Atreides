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
    ObservedSourceReader,
    SyntheticDepository,
    build_independent_sources,
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
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"source read books.{name}")

    profile = load_firm_profile(load_calibration_pack("firm-synthetic/5"), "small")
    run = run_firm(profile, days=2, verify_replay=False)
    assert any(day.source_inputs.open_fails for day in run.days)
    assert any(day.source_inputs.loan_instructions for day in run.days)
    for day in run.days:
        readers = build_independent_sources(RaisingBooks(), day.source_inputs)
        sources = tuple(reader.read() for reader in readers)
        assert sources == day.reconciled_sources
        assert {source.location for source in sources} == {
            "DTC",
            "FAIL_TO_RECEIVE",
            "STOCK_LOANED",
        }


def test_upstream_mutations_are_detected_and_owned() -> None:
    profile = load_firm_profile(load_calibration_pack("firm-synthetic/4"), "small")
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

    _, failed = observed_reconcile(
        {},
        (ObservedSourceReader("forced source", forced_exception),),
        as_of=as_of,
    )
    results = reconciliation_calendar(as_of, (failed,))
    stock = next(item for item in results if item.item_id == "stock-record-to-street")
    fails = next(item for item in results if item.item_id == "ftr-to-cns-fail-statement")
    assert stock.status == "FAILED" and "forced source exception" in stock.reason
    assert fails.status == "NOT_RUN" and fails.reason == "no completion record"
