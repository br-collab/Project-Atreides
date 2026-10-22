from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
    ReserveActivity,
    ReserveSourceFact,
)
from atreides.books.projections import project_customer_protection, project_margin_accounts
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import ReserveInputs, compute_reserve
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from atreides.margin.engine import MarginResult, compute_margin

NOW = datetime(2026, 10, 22, 14, tzinfo=UTC)
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "7" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-books",
    entitlement_refs=(),
    authenticated=True,
)


def entry(event: str = "1", entry_id: str = "entry-1", **changes: object) -> JournalEntry:
    source_id = "evt_" + event * 26
    fields: dict[str, object] = {
        "entry_id": entry_id,
        "source_event_id": source_id,
        "source": PostingSource.CNS_SETTLEMENT,
        "effective_date": date(2026, 10, 22),
        "effective_date_basis": "SETTLEMENT_DATE",
        "authority": "NSCC_SYNTHETIC",
        "lines": (
            LedgerLine(
                account_id="CUSTOMER-1",
                account_type=AccountType.CUSTOMER_MARGIN,
                record_side=RecordSide.OWNERSHIP,
                issue="ACME",
                quantity=Decimal(10),
            ),
            LedgerLine(
                account_id="DTC",
                account_type=AccountType.DTC,
                record_side=RecordSide.LOCATION,
                issue="ACME",
                quantity=Decimal(-10),
            ),
            LedgerLine(
                account_id="CUSTOMER-1",
                account_type=AccountType.CUSTOMER_MARGIN,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=Decimal(-1000),
            ),
            LedgerLine(
                account_id="CLEARING",
                account_type=AccountType.CASH,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=Decimal(1000),
            ),
        ),
        "posting": BooksPosting(
            posted_record_id=entry_id,
            posting_authority=ACTOR,
            effective_time=NOW,
            source_event_id=EventId(source_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
    }
    fields.update(changes)
    return JournalEntry.model_validate(fields)


def test_balanced_append_duplicate_reversal_replay_and_break() -> None:
    books = EquitiesBooks(break_owner="stock-record-control")
    first = entry()
    assert books.post(first).posted
    duplicate = books.post(entry(entry_id="duplicate"))
    assert not duplicate.posted and duplicate.duplicate is not None
    assert books.verify_stock_record() == ()
    breaks = books.verify_stock_record(observed_locations={"ACME": Decimal(9)})
    assert breaks[0].owner == "stock-record-control" and breaks[0].difference == 1
    assert books.verify_stock_record(observed_locations={"ACME": Decimal(8)}) == breaks
    reversal = entry(
        "2",
        "reversal-1",
        source=PostingSource.REVERSAL,
        reverses_entry_id="entry-1",
        lines=tuple(
            line.model_copy(update={"quantity": -line.quantity, "money": -line.money})
            for line in first.lines
        ),
    )
    assert books.post(reversal).posted
    assert books.canonical_replay() == books.canonical_replay()
    assert books.digest().startswith("sha256:")


def test_refusals_are_reasoned() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        LedgerLine(account_id="x", account_type=AccountType.CASH, record_side=RecordSide.MONEY)
    with pytest.raises(ValidationError, match="exactly one"):
        LedgerLine(
            account_id="x",
            account_type=AccountType.CASH,
            record_side=RecordSide.MONEY,
            issue="ACME",
            quantity=1,
            currency="USD",
            money=1,
        )
    with pytest.raises(ValidationError, match="ownership or location"):
        LedgerLine(
            account_id="x",
            account_type=AccountType.DTC,
            record_side=RecordSide.MONEY,
            issue="ACME",
            quantity=1,
        )
    with pytest.raises(ValidationError, match="MONEY side"):
        LedgerLine(
            account_id="x",
            account_type=AccountType.CASH,
            record_side=RecordSide.OWNERSHIP,
            currency="USD",
            money=1,
        )
    bad = list(entry().lines)
    bad[0] = bad[0].model_copy(update={"quantity": Decimal(11)})
    with pytest.raises(ValidationError, match="unbalanced"):
        entry(lines=tuple(bad))
    with pytest.raises(ValidationError, match="different source event"):
        entry(
            posting=entry().posting.model_copy(
                update={"source_event_id": EventId("evt_" + "2" * 26)}
            )
        )
    with pytest.raises(ValidationError, match="must name"):
        entry(source=PostingSource.REVERSAL)
    with pytest.raises(ValidationError, match="only a reversal"):
        entry(reverses_entry_id="entry-0")
    with pytest.raises(ValidationError, match="labelled synthetic"):
        entry(source=PostingSource.MARGIN_INTEREST)
    books = EquitiesBooks(break_owner="owner")
    with pytest.raises(ValueError, match="not present"):
        books.post(entry(source=PostingSource.REVERSAL, reverses_entry_id="missing"))


def test_synthetic_margin_interest_is_accepted() -> None:
    assert entry(source=PostingSource.MARGIN_INTEREST, synthetic=True).synthetic


def _margin_results(books: EquitiesBooks) -> tuple[MarginResult, ...]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    return tuple(
        compute_margin(
            account,
            trade_date=date(2026, 10, 22),
            calendar=calendar,
            house_maintenance_rate=Decimal("0.30"),
            maintenance_call_due_business_days=2,
        )
        for account in project_margin_accounts(books, prices={"ACME": Decimal(100)})
    )


def test_all_protection_inputs_project_from_one_replay_byte_for_byte() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry())
    first = project_customer_protection(
        books,
        as_of=date(2026, 10, 22),
        prices={"ACME": Decimal(100)},
        net_worth=Decimal(1_000_000),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=_margin_results(books),
    )
    second = project_customer_protection(
        books,
        as_of=date(2026, 10, 22),
        prices={"ACME": Decimal(100)},
        net_worth=Decimal(1_000_000),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=_margin_results(books),
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.audit.derived == ("15c3-3a.item.01", "15c3-3a.item.10")
    assert first.firm_profile.synthetic
    assert first.audit.synthetic_firm_profile == first.firm_profile.profile_name
    assert "15c3-3a.item.02" in first.audit.not_derived
    rules = load_rule_table()
    reserve = compute_reserve(first.reserve, rules)
    capital = compute_net_capital(first.net_capital, rules)
    control = check_possession_or_control(first.control, rules)
    assert reserve.missing_inputs
    assert capital.net_capital is not None
    assert "reports_lending_activity_monthly" in capital.missing_inputs
    assert "securities_loaned_and_repo_payable" in capital.missing_inputs
    assert "securities_borrowed_and_reverse_repo_value" in capital.missing_inputs
    assert control.issues[0].conserved is True


def _reserve_entry(
    *,
    event: str,
    account_type: AccountType,
    activity: ReserveActivity,
    quantity: Decimal,
    contract_price: Decimal,
    settlement_date: date,
) -> JournalEntry:
    return entry(
        event,
        f"reserve-{event}",
        source=PostingSource.CNS_FAIL,
        effective_date=settlement_date,
        lines=(
            LedgerLine(
                account_id=f"{activity.value}-{account_type.value}",
                account_type=account_type,
                record_side=RecordSide.LOCATION,
                issue="ACME",
                quantity=quantity,
            ),
            LedgerLine(
                account_id="DTC",
                account_type=AccountType.DTC,
                record_side=RecordSide.LOCATION,
                issue="ACME",
                quantity=-quantity,
            ),
        ),
        reserve_source_facts=(
            ReserveSourceFact(
                account_type=account_type,
                issue="ACME",
                activity=activity,
                settlement_date=settlement_date,
                contract_price=contract_price,
            ),
        ),
    )


def _line_amount(inputs: ReserveInputs, rule_id: str) -> Decimal | None:
    return next(line.amount for line in inputs.lines if line.rule_id == rule_id)


def test_exhibit_a_classifies_contract_value_ages_fails_and_requires_finop_review() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(
        _reserve_entry(
            event="3",
            account_type=AccountType.FAIL_TO_RECEIVE,
            activity=ReserveActivity.CUSTOMER,
            quantity=Decimal(10),
            contract_price=Decimal(80),
            settlement_date=date(2026, 9, 18),
        )
    )
    books.post(
        _reserve_entry(
            event="4",
            account_type=AccountType.STOCK_BORROWED,
            activity=ReserveActivity.PAB,
            quantity=Decimal(5),
            contract_price=Decimal(90),
            settlement_date=date(2026, 10, 21),
        )
    )
    books.post(
        _reserve_entry(
            event="5",
            account_type=AccountType.FAIL_TO_DELIVER,
            activity=ReserveActivity.FIRM,
            quantity=Decimal(2),
            contract_price=Decimal(70),
            settlement_date=date(2026, 10, 21),
        )
    )
    books.post(
        _reserve_entry(
            event="6",
            account_type=AccountType.FAIL_TO_DELIVER,
            activity=ReserveActivity.CUSTOMER,
            quantity=Decimal(3),
            contract_price=Decimal(70),
            settlement_date=date(2026, 9, 18),
        )
    )
    projected = project_customer_protection(
        books,
        as_of=date(2026, 10, 22),
        prices={"ACME": Decimal(100)},
        net_worth=Decimal(1_000_000),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=(),
    )
    assert _line_amount(projected.reserve, "15c3-3a.item.04") == 1000
    assert _line_amount(projected.reserve, "15c3-3a.item.11") is None
    assert _line_amount(projected.reserve, "15c3-3a.item.12") is None
    assert _line_amount(projected.pab_reserve, "15c3-3a.item.11") == 450
    assert _line_amount(projected.pab_reserve, "15c3-3a.item.04") is None
    assert projected.audit.review_label == "FINOP review required"
    assert {item.activity for item in projected.audit.exclusions} == {
        ReserveActivity.CUSTOMER,
        ReserveActivity.FIRM,
    }
    aged = next(
        item for item in projected.audit.exclusions if item.activity is ReserveActivity.CUSTOMER
    )
    assert aged.age_calendar_days == 34
    assert "older than 30" in aged.reason


def test_fail_or_borrow_line_without_source_fact_is_refused() -> None:
    with pytest.raises(ValidationError, match="matching source fact"):
        entry(
            lines=(
                LedgerLine(
                    account_id="FAIL",
                    account_type=AccountType.FAIL_TO_DELIVER,
                    record_side=RecordSide.LOCATION,
                    issue="ACME",
                    quantity=1,
                ),
                LedgerLine(
                    account_id="DTC",
                    account_type=AccountType.DTC,
                    record_side=RecordSide.LOCATION,
                    issue="ACME",
                    quantity=-1,
                ),
            )
        )
    with pytest.raises(ValidationError, match="fail or stock borrow"):
        ReserveSourceFact(
            account_type=AccountType.DTC,
            issue="ACME",
            activity=ReserveActivity.CUSTOMER,
            settlement_date=date(2026, 10, 22),
            contract_price=Decimal(100),
        )


@pytest.mark.parametrize(
    ("settlement_date", "reason"),
    [
        (date(2026, 10, 18), "loaded business day"),
        (date(2026, 10, 23), "cannot be after"),
    ],
)
def test_reserve_source_date_must_be_a_past_business_day(
    settlement_date: date, reason: str
) -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(
        _reserve_entry(
            event="7",
            account_type=AccountType.FAIL_TO_RECEIVE,
            activity=ReserveActivity.CUSTOMER,
            quantity=Decimal(1),
            contract_price=Decimal(100),
            settlement_date=settlement_date,
        )
    )
    with pytest.raises(ValueError, match=reason):
        project_customer_protection(
            books,
            as_of=date(2026, 10, 22),
            prices={"ACME": Decimal(100)},
            net_worth=Decimal(1_000_000),
            calendar=MarketCalendar.load(Market.US_EQUITIES),
            margin_results=(),
        )
