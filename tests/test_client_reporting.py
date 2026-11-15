from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from cannae_kernel.account import AccountStatus

from atreides.books.ledger import EquitiesBooks
from atreides.client_reporting import (
    StatementTieOutError,
    build_statement_draft,
    generate_trade_confirmation,
    issue_statement,
)
from simulator.account_transfers import _post_transfer
from simulator.conversion import StatementLine
from simulator.golden_path import ACCOUNT, ISSUE, START, GoldenPathResult, run_golden_path


def _replayed_books() -> tuple[EquitiesBooks, GoldenPathResult]:
    result = run_golden_path()
    books = EquitiesBooks(break_owner="MVP4_REPORTING_TEST")
    for entry in result.books_entries:
        books.post(entry)
    return books, result


def test_confirmation_fields_cite_pinned_rule_and_source_record() -> None:
    result = run_golden_path()
    confirmation = result.confirmation

    assert confirmation is not None
    assert {item.name for item in confirmation.fields} == {
        "transaction_date",
        "transaction_time",
        "security_identity",
        "side",
        "price",
        "quantity",
    }
    assert all(
        item.provenance.rule_id == "10b-10.a1.transaction_terms"
        for item in confirmation.fields
    )
    assert all(
        item.provenance.source_record_id == confirmation.trade_id
        for item in confirmation.fields
    )
    assert all(item.provenance.source_sha256 for item in confirmation.fields)
    assert result.confirmation_furnished is not None
    assert result.confirmation_furnished.channel == "SYNTHETIC_PORTAL"


def test_correction_and_cancellation_reference_immutable_original() -> None:
    result = run_golden_path()
    original = result.confirmation
    assert original is not None
    book_entry = next(
        item for item in result.books_entries if item.entry_id == original.book_entry_id
    )
    original_json = original.model_dump_json()

    correction = generate_trade_confirmation(
        account_id=ACCOUNT,
        trade_id=original.trade_id,
        book_entry=book_entry,
        executed_at=START + timedelta(seconds=30),
        issue=ISSUE,
        side="BUY",
        quantity=Decimal(10),
        price=Decimal("100"),
        replaces=original,
        correction_kind="CORRECTION",
        correction_reason="synthetic display correction",
    )
    cancellation = generate_trade_confirmation(
        account_id=ACCOUNT,
        trade_id=original.trade_id,
        book_entry=book_entry,
        executed_at=START + timedelta(seconds=30),
        issue=ISSUE,
        side="BUY",
        quantity=Decimal(10),
        price=Decimal("100"),
        replaces=original,
        correction_kind="CANCELLATION",
        correction_reason="synthetic cancellation",
    )

    assert correction.replaces_confirmation_id == original.confirmation_id
    assert cancellation.replaces_confirmation_id == original.confirmation_id
    assert correction.confirmation_id != cancellation.confirmation_id
    assert original.model_dump_json() == original_json


def test_statement_ties_to_books_for_cash_positions_and_activity() -> None:
    result = run_golden_path()
    statement = result.statement

    assert statement is not None
    activity_cash = sum((item.money for item in statement.activity), Decimal())
    assert statement.opening_cash + activity_cash == statement.closing_cash
    for issue in set(statement.opening_positions) | set(statement.closing_positions):
        activity = sum(
            (
                item.quantity
                for item in statement.activity
                if item.issue == issue and item.record_side == "OWNERSHIP"
            ),
            Decimal(),
        )
        assert (
            statement.opening_positions.get(issue, Decimal()) + activity
            == statement.closing_positions.get(issue, Decimal())
        )
    assert {item.journal_entry_id for item in statement.activity} <= {
        item.entry_id for item in result.books_entries
    }
    assert all(
        item["status"] == "TO_VERIFY_AGAINST_PRIMARY_TEXT"
        for item in statement.finra_requirements
    )


def test_statement_that_does_not_tie_is_refused() -> None:
    books, result = _replayed_books()
    assert result.statement is not None
    draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=AccountStatus.ACTIVE,
        period_start=START.date(),
        period_end=START.date(),
    )
    broken = draft.model_copy(update={"closing_cash": draft.closing_cash + Decimal("0.01")})

    with pytest.raises(StatementTieOutError, match="does not tie"):
        issue_statement(broken, books, issued_at=datetime(2026, 11, 15, tzinfo=UTC))


def test_late_activity_produces_corrected_statement_without_editing_original() -> None:
    books, result = _replayed_books()
    original = result.statement
    assert original is not None
    original_json = original.model_dump_json()
    late_day = original.period_end + timedelta(days=1)
    _post_transfer(
        books,
        StatementLine(account=ACCOUNT, issue=ISSUE, quantity=Decimal(), cash_credit=Decimal(50)),
        transfer_id="MVP4-LATE-ACTIVITY",
        sequence=91,
        quantity=Decimal(),
        cash=Decimal(50),
        day=late_day,
    )
    corrected_draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=AccountStatus.ACTIVE,
        period_start=original.period_start,
        period_end=late_day,
        replaces=original,
    )
    corrected = issue_statement(
        corrected_draft, books, issued_at=datetime(2026, 11, 17, tzinfo=UTC)
    )

    assert corrected.replaces_statement_id == original.statement_id
    assert corrected.statement_id != original.statement_id
    assert corrected.closing_cash == original.closing_cash + Decimal(50)
    assert original.model_dump_json() == original_json


@pytest.mark.parametrize("status", [AccountStatus.RESTRICTED, AccountStatus.CLOSED])
def test_restricted_and_closed_accounts_still_receive_statements(status: AccountStatus) -> None:
    books, result = _replayed_books()
    assert result.statement is not None
    draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=status,
        period_start=START.date(),
        period_end=START.date(),
    )
    statement = issue_statement(draft, books, issued_at=datetime(2026, 11, 15, tzinfo=UTC))

    assert statement.account_status is status
