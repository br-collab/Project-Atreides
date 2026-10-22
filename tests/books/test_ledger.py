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
)
from atreides.books.projections import project_customer_protection
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import compute_reserve
from atreides.customer_protection.rules import load_rule_table
from atreides.dsor.books import BooksPosting

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


def test_all_protection_inputs_project_from_one_replay_byte_for_byte() -> None:
    books = EquitiesBooks(break_owner="owner")
    books.post(entry())
    first = project_customer_protection(
        books, as_of=date(2026, 10, 22), prices={"ACME": Decimal(100)}, net_worth=Decimal(1_000_000)
    )
    second = project_customer_protection(
        books, as_of=date(2026, 10, 22), prices={"ACME": Decimal(100)}, net_worth=Decimal(1_000_000)
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.audit.derived == ("15c3-3a.item.10",)
    assert "15c3-3a.item.01" in first.audit.not_derived
    rules = load_rule_table()
    reserve = compute_reserve(first.reserve, rules)
    capital = compute_net_capital(first.net_capital, rules)
    control = check_possession_or_control(first.control, rules)
    assert reserve.missing_inputs
    assert capital.net_capital is not None
    assert control.issues[0].conserved is True
