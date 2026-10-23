"""The single append-only equities book of record.

Cash Treasury and repo remain on their existing paths and are the next sources
to wire. Every equities posting is balanced, attributable and replayable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.dsor.books import BooksPosting


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountType(StrEnum):
    CUSTOMER_CASH = "CUSTOMER_CASH"
    CUSTOMER_MARGIN = "CUSTOMER_MARGIN"
    FIRM_PROPRIETARY = "FIRM_PROPRIETARY"
    PAB = "PAB"
    FAIL_TO_RECEIVE = "FAIL_TO_RECEIVE"
    STOCK_BORROWED = "STOCK_BORROWED"
    DTC = "DTC"
    BANK_CONTROL = "BANK_CONTROL"
    FAIL_TO_DELIVER = "FAIL_TO_DELIVER"
    STOCK_LOANED = "STOCK_LOANED"
    IN_TRANSFER = "IN_TRANSFER"
    CASH = "CASH"


class RecordSide(StrEnum):
    OWNERSHIP = "OWNERSHIP"
    LOCATION = "LOCATION"
    MONEY = "MONEY"


class PostingSource(StrEnum):
    TRADE_CAPTURE = "TRADE_CAPTURE"
    ALLOCATION = "ALLOCATION"
    CNS_SETTLEMENT = "CNS_SETTLEMENT"
    CNS_FAIL = "CNS_FAIL"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    CASH_MOVEMENT = "CASH_MOVEMENT"
    MARGIN_INTEREST = "MARGIN_INTEREST"
    REVERSAL = "REVERSAL"


class ReserveActivity(StrEnum):
    CUSTOMER = "CUSTOMER"
    PAB = "PAB"
    FIRM = "FIRM"


class ReserveSourceFact(_Frozen):
    """Source-trade facts needed to classify and value Exhibit A lines."""

    account_type: AccountType
    issue: str = Field(min_length=1)
    activity: ReserveActivity
    settlement_date: date
    contract_price: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def _is_reserve_source(self) -> Self:
        if self.account_type not in {
            AccountType.FAIL_TO_RECEIVE,
            AccountType.STOCK_BORROWED,
            AccountType.FAIL_TO_DELIVER,
        }:
            raise ValueError("reserve source fact must name a fail or stock borrow account type")
        return self


class LedgerLine(_Frozen):
    account_id: str = Field(min_length=1)
    account_type: AccountType
    record_side: RecordSide
    issue: str | None = None
    quantity: Decimal = Decimal(0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    money: Decimal = Decimal(0)

    @model_validator(mode="after")
    def _one_unit(self) -> Self:
        security = self.issue is not None and self.quantity != 0 and self.currency is None
        cash = self.currency is not None and self.money != 0 and self.issue is None
        if security == cash:
            raise ValueError("ledger line must carry exactly one of security quantity or money")
        if security and self.record_side is RecordSide.MONEY:
            raise ValueError("security line requires an ownership or location side")
        if cash and self.record_side is not RecordSide.MONEY:
            raise ValueError("money line requires the MONEY side")
        return self


class JournalEntry(_Frozen):
    entry_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    source: PostingSource
    effective_date: date
    effective_date_basis: str = Field(pattern=r"^(TRADE_DATE|SETTLEMENT_DATE|PAY_DATE|VALUE_DATE)$")
    authority: str = Field(min_length=1)
    lines: tuple[LedgerLine, ...] = Field(min_length=2)
    posting: BooksPosting
    reserve_source_facts: tuple[ReserveSourceFact, ...] = ()
    reverses_entry_id: str | None = None
    synthetic: bool = False

    @model_validator(mode="after")
    def _balanced_and_attributable(self) -> Self:
        if str(self.posting.source_event_id) != self.source_event_id:
            raise ValueError("posting evidence names a different source event")
        securities: dict[str, Decimal] = defaultdict(Decimal)
        money: dict[str, Decimal] = defaultdict(Decimal)
        for line in self.lines:
            if line.issue is not None:
                securities[line.issue] += line.quantity
            if line.currency is not None:
                money[line.currency] += line.money
        unbalanced_issues = sorted(issue for issue, amount in securities.items() if amount != 0)
        unbalanced_currencies = sorted(ccy for ccy, amount in money.items() if amount != 0)
        if unbalanced_issues or unbalanced_currencies:
            raise ValueError(
                "journal entry is unbalanced: "
                f"issues={unbalanced_issues}, currencies={unbalanced_currencies}"
            )
        if self.source is PostingSource.REVERSAL and self.reverses_entry_id is None:
            raise ValueError("a reversal must name the entry it reverses")
        if self.source is not PostingSource.REVERSAL and self.reverses_entry_id is not None:
            raise ValueError("only a reversal may name a reversed entry")
        if self.source is PostingSource.MARGIN_INTEREST and not self.synthetic:
            raise ValueError("margin interest accrual must be labelled synthetic")
        reserve_lines = {
            (line.account_type, line.issue)
            for line in self.lines
            if line.account_type
            in {
                AccountType.FAIL_TO_RECEIVE,
                AccountType.STOCK_BORROWED,
                AccountType.FAIL_TO_DELIVER,
            }
        }
        reserve_facts = {(fact.account_type, fact.issue) for fact in self.reserve_source_facts}
        if reserve_lines != reserve_facts:
            raise ValueError("every fail and stock borrow line requires one matching source fact")
        return self


class DuplicatePosting(_Frozen):
    source_event_id: str
    original_entry_id: str
    duplicate_entry_id: str


class StockRecordBreak(_Frozen):
    break_id: str
    issue: str
    ownership_quantity: Decimal
    location_quantity: Decimal
    difference: Decimal
    owner: str = Field(min_length=1)
    state: str = "OPEN"


class PostingResult(_Frozen):
    posted: bool
    entry: JournalEntry
    duplicate: DuplicatePosting | None = None
    break_reason: str | None = None


class EquitiesBooks:
    """In-memory append-only journal; serialized entries are the durable record."""

    def __init__(self, *, break_owner: str) -> None:
        self.break_owner = break_owner
        self._entries: list[JournalEntry] = []
        self._by_source: dict[str, JournalEntry] = {}
        self._breaks: list[StockRecordBreak] = []

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    @property
    def breaks(self) -> tuple[StockRecordBreak, ...]:
        return tuple(self._breaks)

    def post(self, entry: JournalEntry) -> PostingResult:
        if original := self._by_source.get(entry.source_event_id):
            identical = canonical_bytes_of(original) == canonical_bytes_of(entry)
            return PostingResult(
                posted=False,
                entry=original,
                duplicate=DuplicatePosting(
                    source_event_id=entry.source_event_id,
                    original_entry_id=original.entry_id,
                    duplicate_entry_id=entry.entry_id,
                ),
                break_reason=None if identical else (
                    "source_event_id was reused with different posting economics"
                ),
            )
        if entry.reverses_entry_id is not None and not any(
            prior.entry_id == entry.reverses_entry_id for prior in self._entries
        ):
            raise ValueError("reversal refers to an entry not present in the journal")
        self._entries.append(entry)
        self._by_source[entry.source_event_id] = entry
        return PostingResult(posted=True, entry=entry)

    def quantities(self) -> dict[str, dict[RecordSide, Decimal]]:
        result: dict[str, dict[RecordSide, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for entry in self._entries:
            for line in entry.lines:
                if line.issue is not None:
                    result[line.issue][line.record_side] += line.quantity
        return {issue: dict(sides) for issue, sides in result.items()}

    def verify_stock_record(
        self, *, observed_locations: dict[str, Decimal] | None = None
    ) -> tuple[StockRecordBreak, ...]:
        for issue, sides in self.quantities().items():
            ownership = sides.get(RecordSide.OWNERSHIP, Decimal(0))
            location = (
                observed_locations.get(issue, Decimal(0))
                if observed_locations is not None
                else -sides.get(RecordSide.LOCATION, Decimal(0))
            )
            difference = ownership - location
            existing = next(
                (item for item in self._breaks if item.issue == issue and item.state == "OPEN"),
                None,
            )
            if difference and existing is not None and existing.difference != difference:
                self._breaks.remove(existing)
                existing = None
            if difference and existing is None:
                self._breaks.append(
                    StockRecordBreak(
                        break_id=f"STOCK-RECORD-{issue}-{len(self._breaks) + 1}",
                        issue=issue,
                        ownership_quantity=ownership,
                        location_quantity=location,
                        difference=difference,
                        owner=self.break_owner,
                    )
                )
        return self.breaks

    def canonical_replay(self) -> bytes:
        return canonical_bytes_of(tuple(self._entries))

    def digest(self) -> str:
        return str(digest_bytes(self.canonical_replay()))
