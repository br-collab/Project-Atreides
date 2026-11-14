"""MVP-1B per-fail identity and independent aging regressions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from atreides.books.ledger import AccountType, EquitiesBooks, ReserveActivity, ReserveSourceFact
from atreides.books.projections import ProjectionSourceFactMissingError
from tests.books.test_fix12_protection_inputs import _project
from tests.books.test_ledger import _reserve_entry, entry


def _ftr(
    event: str,
    quantity: int,
    opened: date,
    fail_id: str,
    price: int = 80,
):  # type: ignore[no-untyped-def]
    return _reserve_entry(
        event=event,
        account_type=AccountType.FAIL_TO_RECEIVE,
        activity=ReserveActivity.CUSTOMER,
        quantity=Decimal(quantity),
        contract_price=Decimal(price),
        settlement_date=opened,
        fail_id=fail_id,
    )


def test_reopened_fail_uses_its_own_age_and_contract_value() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry("1", "base"))
    books.post(_ftr("2", 10, date(2026, 8, 20), "OLD"))
    books.post(_ftr("3", -10, date(2026, 8, 20), "OLD"))
    books.post(_ftr("4", 5, date(2026, 10, 20), "NEW"))
    projected = _project(books)
    pending = [
        item
        for item in projected.control.issues[0].holdings
        if item.location == "15c3-3.pending-fail-to-receive"
    ]
    assert [(item.quantity, item.location) for item in pending] == [
        (Decimal(5), "15c3-3.pending-fail-to-receive")
    ]
    item_4 = next(
        line.amount for line in projected.reserve.lines if line.rule_id == "15c3-3a.item.04"
    )
    assert item_4 == 400


def test_two_open_fails_on_one_issue_keep_separate_ages_and_values() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry("1", "base"))
    books.post(_ftr("2", 4, date(2026, 9, 11), "OLD", 70))
    books.post(_ftr("3", 5, date(2026, 10, 19), "NEW", 80))
    projected = _project(books)
    by_location = {
        item.location: item.quantity for item in projected.control.issues[0].holdings
    }
    assert by_location["15c3-3.noncontrol.d2"] == 4
    assert by_location["15c3-3.pending-fail-to-receive"] == 5
    item_4 = next(
        line.amount for line in projected.reserve.lines if line.rule_id == "15c3-3a.item.04"
    )
    assert item_4 == 800


def test_partial_close_of_older_fail_does_not_age_newer_fail() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry("1", "base"))
    books.post(_ftr("2", 6, date(2026, 9, 11), "OLD"))
    books.post(_ftr("3", -2, date(2026, 9, 11), "OLD"))
    books.post(_ftr("4", 5, date(2026, 10, 19), "NEW"))
    projected = _project(books)
    by_location = {
        item.location: item.quantity
        for item in projected.control.issues[0].holdings
        if "fail-to-receive" in item.location or item.location == "15c3-3.noncontrol.d2"
    }
    assert by_location == {
        "15c3-3.noncontrol.d2": Decimal(4),
        "15c3-3.pending-fail-to-receive": Decimal(5),
    }


def test_ftr_fact_requires_fail_id_at_posting() -> None:
    with pytest.raises(ValueError, match="FAIL_TO_RECEIVE_FAIL_ID_MISSING"):
        ReserveSourceFact(
            account_type=AccountType.FAIL_TO_RECEIVE,
            issue="ACME",
            activity=ReserveActivity.CUSTOMER,
            settlement_date=date(2026, 10, 22),
            contract_price=Decimal(80),
        )


def test_non_ftr_fact_refuses_fail_id() -> None:
    with pytest.raises(ValueError, match="fail_id is only valid"):
        ReserveSourceFact(
            account_type=AccountType.FAIL_TO_DELIVER,
            issue="ACME",
            activity=ReserveActivity.CUSTOMER,
            settlement_date=date(2026, 10, 22),
            contract_price=Decimal(80),
            fail_id="NOT-AN-FTR",
        )


def test_ftr_opening_date_cannot_change_for_same_fail_id() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry("1", "base"))
    books.post(_ftr("2", 5, date(2026, 10, 19), "FAIL-2"))
    books.post(_ftr("3", -1, date(2026, 10, 20), "FAIL-2"))
    with pytest.raises(ValueError, match="FAIL_TO_RECEIVE_OPENING_DATE_CHANGED"):
        _project(books)


def test_ftr_missing_fail_id_is_named_projection_refusal() -> None:
    books = EquitiesBooks(break_owner="owner")
    valid = _ftr("7", 1, date(2026, 10, 22), "FAIL-7")
    fact = valid.reserve_source_facts[0].model_copy(update={"fail_id": None})
    books._entries.append(valid.model_copy(update={"reserve_source_facts": (fact,)}))
    with pytest.raises(
        ProjectionSourceFactMissingError, match="FAIL_TO_RECEIVE_FAIL_ID_MISSING"
    ):
        _project(books)
