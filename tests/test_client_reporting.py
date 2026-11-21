from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.canonical import canonical_bytes_of, digest_bytes

from atreides.books.ledger import EquitiesBooks
from atreides.client_reporting import (
    CustomerSideFacts,
    StatementTieOutError,
    build_statement_draft,
    customer_side_facts_from_furnished_confirmations,
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
    assert "Rule 10b-10(a)(2) capacity and remuneration" in confirmation.not_claimed


def test_customer_side_position_reads_the_furnished_confirmation() -> None:
    result = run_golden_path()
    assert result.confirmation is not None
    assert result.confirmation_furnished is not None
    facts = customer_side_facts_from_furnished_confirmations(
        deposit_instructions=(Decimal("10000"),),
        venue_fills=((ISSUE, Decimal("999"), Decimal("100")),),
        furnished_confirmations=((result.confirmation, result.confirmation_furnished),),
    )
    assert facts.confirmations == ((ISSUE, Decimal(10)),)


def test_customer_side_position_refuses_a_different_furnished_record() -> None:
    result = run_golden_path()
    assert result.confirmation is not None
    assert result.confirmation_furnished is not None
    wrong = result.confirmation_furnished.model_copy(update={"confirmation_id": "CONF-WRONG"})
    with pytest.raises(ValueError, match="FURNISHED_CONFIRMATION_ID_MISMATCH"):
        customer_side_facts_from_furnished_confirmations(
            deposit_instructions=(),
            venue_fills=(),
            furnished_confirmations=((result.confirmation, wrong),),
        )


def test_correction_and_cancellation_reference_immutable_original() -> None:
    result = run_golden_path()
    original = result.confirmation
    assert original is not None
    assert result.venue_execution_event is not None
    assert result.venue_execution_report is not None
    book_entry = next(
        item for item in result.books_entries if item.entry_id == original.book_entry_id
    )
    original_json = original.model_dump_json()

    correction = generate_trade_confirmation(
        account_id=ACCOUNT,
        book_entry=book_entry,
        execution_event=result.venue_execution_event,
        execution_report=result.venue_execution_report,
        replaces=original,
        correction_kind="CORRECTION",
        correction_reason="synthetic display correction",
    )
    cancellation = generate_trade_confirmation(
        account_id=ACCOUNT,
        book_entry=book_entry,
        execution_event=result.venue_execution_event,
        execution_report=result.venue_execution_report,
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
    assert statement.closing_cash == Decimal("9000.00")
    assert statement.closing_margin == Decimal("0")
    assert statement.cost_basis == {ISSUE: Decimal("1000.00")}
    assert statement.unrealized_gain_loss == {ISSUE: Decimal()}
    assert statement.tax_disclaimer == "Synthetic illustration only; not tax advice"
    assert "cost basis" not in statement.not_claimed
    assert "tax lots" not in statement.not_claimed
    activity_cash = sum(
        (item.money for item in statement.activity if item.account_type == "CUSTOMER_CASH"),
        Decimal(),
    )
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


def test_customer_side_oracle_refuses_eleven_booked_shares_against_ten_share_fill() -> None:
    books, _ = _replayed_books()
    draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=AccountStatus.ACTIVE,
        period_start=START.date(),
        period_end=START.date(),
    )
    facts = CustomerSideFacts(
        deposit_instructions=(Decimal("10000"),),
        venue_fills=((ISSUE, Decimal(10), Decimal(100)),),
        confirmations=((ISSUE, Decimal(10)),),
    )
    broken = draft.model_copy(update={"closing_positions": {ISSUE: Decimal(11)}})
    with pytest.raises(StatementTieOutError, match="does not tie"):
        issue_statement(
            broken,
            books,
            issued_at=datetime(2026, 11, 15, tzinfo=UTC),
            customer_side_facts=facts,
        )


def test_confirmation_refuses_fill_price_that_disagrees_with_books() -> None:
    result = run_golden_path()
    assert result.confirmation is not None
    assert result.venue_execution_report is not None
    assert result.venue_execution_event is not None
    report = result.venue_execution_report.model_copy(update={"price": Decimal("101")})
    event = result.venue_execution_event.model_copy(
        update={"payload_digest": digest_bytes(canonical_bytes_of(report))}
    )
    entry = next(
        item for item in result.books_entries if item.entry_id == result.confirmation.book_entry_id
    )

    with pytest.raises(ValueError, match="consideration does not match"):
        generate_trade_confirmation(
            account_id=ACCOUNT,
            book_entry=entry,
            execution_event=event,
            execution_report=report,
        )


def test_sale_confirmation_has_negative_quantity_positive_proceeds_from_books() -> None:
    result = run_golden_path()
    assert result.confirmation is not None
    assert result.venue_execution_report is not None
    assert result.venue_execution_event is not None
    original = next(
        item for item in result.books_entries if item.entry_id == result.confirmation.book_entry_id
    )
    sale = original.model_copy(
        update={
            "entry_id": original.entry_id + "-SALE",
            "lines": tuple(
                line.model_copy(update={"quantity": -line.quantity, "money": -line.money})
                if line.account_id == ACCOUNT
                else line
                for line in original.lines
            ),
        }
    )
    confirmation = generate_trade_confirmation(
        account_id=ACCOUNT,
        book_entry=sale,
        execution_event=result.venue_execution_event,
        execution_report=result.venue_execution_report,
    )
    fields = {item.name: item.value for item in confirmation.fields}
    book_proceeds = sum(
        line.money
        for line in sale.lines
        if line.account_id == ACCOUNT and line.record_side.value == "MONEY"
    )
    assert fields["side"] == "SELL"
    assert Decimal(fields["quantity"]) < 0
    assert book_proceeds > 0
    assert confirmation.book_entry_id == sale.entry_id


def test_statement_issuance_refuses_a_defect_in_draft_balance_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atreides.client_reporting as reporting

    books, _ = _replayed_books()
    original = reporting._balances

    def defective(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        cash, margin, positions = original(*args, **kwargs)  # type: ignore[arg-type]
        return cash + Decimal("1.00"), margin, positions

    monkeypatch.setattr(reporting, "_balances", defective)
    draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=AccountStatus.ACTIVE,
        period_start=START.date(),
        period_end=START.date(),
    )
    with pytest.raises(StatementTieOutError, match="does not tie"):
        issue_statement(draft, books, issued_at=datetime(2026, 11, 15, tzinfo=UTC))


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
