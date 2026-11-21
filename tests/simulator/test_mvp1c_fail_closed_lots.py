"""MVP-1C fail-closed reconciliation, fail lots, and loan-register controls."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from simulator import firm, street
from simulator.calibration import load_calibration_pack
from simulator.street import (
    LoanInstruction,
    LoanRegister,
    OpenFail,
    ReconciliationCompletion,
    ReconciliationStatus,
    reconciliation_calendar,
)


def _profile() -> firm.FirmProfile:
    return firm.load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small")


def test_failed_reconciliation_makes_i3_false(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def failed(*args, **kwargs):  # type: ignore[no-untyped-def]
        return (), ReconciliationCompletion(
            item_id=str(kwargs.get("item_id", "stock-record-to-street")),
            close_date=kwargs["as_of"],
            sources_read=("Atreides equities books", "forced failure"),
            break_count=1,
            status=ReconciliationStatus.FAILED,
            error="RuntimeError: forced reconciliation failure",
        )

    monkeypatch.setattr(firm, "reconcile_observed_street", failed)
    day = firm.run_firm(_profile(), days=1, verify_replay=False).days[0]
    assert not day.invariants["I3_STOCK_RECORD_EQUALS_STREET"]
    assert all(item.status == "FAILED" for item in day.reconciliation_calendar[:3])


def test_only_cns_source_failure_is_failed_and_closes_i3(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def failed_cns(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced CNS source failure")

    monkeypatch.setattr(street, "cns_fail_source", failed_cns)
    day = firm.run_firm(_profile(), days=1, verify_replay=False).days[0]
    statuses = {item.item_id: item.status for item in day.reconciliation_calendar}
    assert statuses["stock-record-to-street"] == "RAN"
    assert statuses["ftr-to-cns-fail-statement"] == "FAILED"
    assert statuses["stock-loan-to-contract-register"] == "RAN"
    assert not day.invariants["I3_STOCK_RECORD_EQUALS_STREET"]
    assert any(item.cause == "RECONCILIATION_FAILED" for item in day.street_breaks)


def test_calendar_never_reports_ran_without_completion() -> None:
    results = reconciliation_calendar(date(2027, 1, 4), ())
    assert results
    assert all(item.status == "NOT_RUN" for item in results)


def test_missing_required_completion_makes_i3_false() -> None:
    completion = ReconciliationCompletion(
        "stock-record-to-street",
        date(2027, 1, 4),
        ("books", "DTC"),
        0,
        ReconciliationStatus.COMPLETED,
    )
    assert not firm._reconciliation_held(  # acceptance seam
        (completion,),
        ("stock-record-to-street", "ftr-to-cns-fail-statement"),
        (),
    )


def test_fail_growth_creates_a_later_lot() -> None:
    old = OpenFail(
        "OLD", "ACME", Decimal(5), Decimal(500), date(2027, 1, 4), Decimal(100)
    )
    lots = firm._roll_fail_lots(
        "ACME",
        Decimal(8),
        Decimal(800),
        (old,),
        date(2027, 1, 5),
        Decimal(100),
    )
    assert [(item.fail_id, item.quantity, item.opening_settlement_date) for item in lots] == [
        ("OLD", Decimal(5), date(2027, 1, 4)),
        ("CNS-FAIL-ACME-2027-01-05-2", Decimal(3), date(2027, 1, 5)),
    ]


def test_fail_direction_flip_closes_old_id_and_opens_new_id() -> None:
    old = OpenFail(
        "OLD", "ACME", Decimal(-5), Decimal(-500), date(2027, 1, 4), Decimal(100)
    )
    lots = firm._roll_fail_lots(
        "ACME",
        Decimal(3),
        Decimal(300),
        (old,),
        date(2027, 1, 5),
        Decimal(100),
    )
    assert len(lots) == 1
    assert lots[0].fail_id != old.fail_id
    assert lots[0].quantity == 3


def test_oldest_fail_lot_settles_first() -> None:
    oldest = OpenFail(
        "OLD", "ACME", Decimal(10), Decimal(1000), date(2027, 1, 5), Decimal(100)
    )
    newest = OpenFail(
        "NEW", "ACME", Decimal(10), Decimal(1000), date(2027, 1, 6), Decimal(100)
    )
    lots = firm._roll_fail_lots(
        "ACME",
        Decimal(12),
        Decimal(1200),
        (oldest, newest),
        date(2027, 1, 7),
        Decimal(100),
    )
    assert [(item.fail_id, item.quantity) for item in lots] == [
        ("OLD", Decimal(2)),
        ("NEW", Decimal(10)),
    ]


def test_five_day_run_never_grows_or_flips_a_fail_id() -> None:
    run = firm.run_firm(_profile(), days=5, verify_replay=False)
    prior: dict[str, Decimal] = {}
    violations = []
    for day in run.days:
        current = {item.fail_id: item.quantity for item in day.source_inputs.open_fails}
        for fail_id, quantity in current.items():
            old = prior.get(fail_id)
            if old is not None and (
                abs(quantity) > abs(old) or (quantity > 0) != (old > 0)
            ):
                violations.append((fail_id, old, quantity))
        prior = current
    assert violations == []


def test_recall_quantity_comes_from_register_without_reading_books() -> None:
    class PostingOnlyBooks:
        def __init__(self) -> None:
            self.posted = []

        def post(self, entry):  # type: ignore[no-untyped-def]
            self.posted.append(entry)

        def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
            if name in {"post", "posted", "__dict__", "__class__"}:
                return object.__getattribute__(self, name)
            raise AssertionError(f"recall read books.{name}")

    register = LoanRegister()
    register.record(LoanInstruction("OPEN", "SYN-SCF1-ISSUE-0000", Decimal(17), date(2027, 1, 5)))
    books = PostingOnlyBooks()
    instructions = firm._post_control_deficit(
        books,
        register,
        replace(
            _profile(),
            control_deficit=(0, 0, Decimal(17)),
        ),
        date(2027, 1, 6),
        {},
        1,
        2,
    )
    assert [item.quantity for item in instructions] == [Decimal(-17)]
    assert register.open_quantity("SYN-SCF1-ISSUE-0000", date(2027, 1, 6)) == 0
    assert books.posted[0].lines[0].quantity == -17
