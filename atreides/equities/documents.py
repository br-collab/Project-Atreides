"""Atreides-owned equities documents and attested wire emission."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from cannae_kernel.canonical import canonical_bytes, digest, digest_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.books.ledger import AccountType
from atreides.margin.engine import MarginAccount, MarginResult

#: Customer-protection capacity of an ownership account, from its books classification.
#: Rule 15c3-3 protects CUSTOMER securities ((b)(1)) and PAB securities ((b)(5)); the firm's
#: own PROPRIETARY securities need neither.
CAPACITY_BY_ACCOUNT_TYPE: dict[AccountType, Literal["CUSTOMER", "PAB", "PROPRIETARY"]] = {
    AccountType.CUSTOMER_CASH: "CUSTOMER",
    AccountType.CUSTOMER_MARGIN: "CUSTOMER",
    AccountType.PAB: "PAB",
    AccountType.FIRM_PROPRIETARY: "PROPRIETARY",
}


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountPosition(_Wire):
    issue: str = Field(min_length=1)
    quantity: Decimal


class AccountCapacity(_Wire):
    account_id: str = Field(min_length=1)
    #: INST-1 Amendment 3 (WP1b item 4): the account's capacity, from its books type.
    capacity: Literal["CUSTOMER", "PAB", "PROPRIETARY"]
    buying_power: Decimal = Field(ge=0)
    margin_excess: Decimal
    margin_result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    positions: tuple[AccountPosition, ...]


class AccountCapacityDocument(_Wire):
    schema_version: Literal["atreides.equities_account_capacity/3"] = (
        "atreides.equities_account_capacity/3"
    )
    as_of: datetime
    maximum_age_seconds: int = Field(gt=0)
    synthetic: Literal[True] = True
    journal_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    #: INST-1 Amendment 3 (WP1b item 1): the carrying firm's settlement participant, through
    #: which every account in this document settles.
    firm_participant_id: str = Field(min_length=1)
    accounts: tuple[AccountCapacity, ...]

    @model_validator(mode="after")
    def _aware_and_unique(self) -> Self:
        if self.as_of.tzinfo is None:
            raise ValueError("capacity as_of must be timezone-aware")
        ids = [account.account_id for account in self.accounts]
        if len(ids) != len(set(ids)):
            raise ValueError("capacity account ids must be unique")
        return self


class LocateRecord(_Wire):
    locate_id: str = Field(min_length=1)
    source: Literal["SYNTHETIC_EASY_TO_BORROW", "SYNTHETIC_LENDER"]
    located_at: datetime
    expires_at: datetime
    issue: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def _window(self) -> Self:
        if self.located_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("locate timestamps must be timezone-aware")
        if self.expires_at <= self.located_at:
            raise ValueError("locate expiry must follow its timestamp")
        return self


class LocateDocument(_Wire):
    schema_version: Literal["atreides.equities_locates/1"] = "atreides.equities_locates/1"
    as_of: datetime
    synthetic: Literal[True] = True
    locates: tuple[LocateRecord, ...]


class AttestedDocument(_Wire):
    schema_version: Literal["atreides.attested_document/1"] = "atreides.attested_document/1"
    document_type: Literal["ACCOUNT_CAPACITY", "LOCATES"]
    payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload: bytes


def attest_capacity(document: AccountCapacityDocument) -> AttestedDocument:
    payload = canonical_bytes(document)
    return AttestedDocument(
        document_type="ACCOUNT_CAPACITY", payload_digest=digest_bytes(payload), payload=payload
    )


def project_capacity(
    *,
    journal_digest: str,
    as_of: datetime,
    maximum_age_seconds: int,
    margin_results: tuple[MarginResult, ...],
    accounts: tuple[MarginAccount, ...],
    account_types: Mapping[str, AccountType],
    firm_participant_id: str,
) -> AccountCapacityDocument:
    """Project remaining capacity only from the journal-derived margin results.

    Each account's capacity comes from its books ownership type (``classify_accounts``); an
    account with no ownership type is refused rather than given a default.
    """
    by_account = {account.account_id: account for account in accounts}
    projected: list[AccountCapacity] = []
    for result in margin_results:
        if result.excess_or_deficiency is None:
            raise ValueError("capacity requires a determinate margin result")
        initial_rate = next(
            (trace.value for trace in result.rules_used if trace.rule_id == "reg_t.initial"), None
        )
        if initial_rate is None or initial_rate <= 0:
            raise ValueError("capacity requires the pinned Reg T initial rate")
        account = by_account[result.account_id]
        account_type = account_types.get(result.account_id)
        capacity = CAPACITY_BY_ACCOUNT_TYPE.get(account_type) if account_type else None
        if capacity is None:
            raise ValueError(f"capacity requires an ownership account type for {result.account_id}")
        excess = result.excess_or_deficiency
        projected.append(
            AccountCapacity(
                account_id=result.account_id,
                capacity=capacity,
                buying_power=max(excess, Decimal(0)) / initial_rate,
                margin_excess=excess,
                margin_result_digest=digest(result),
                positions=tuple(
                    AccountPosition(issue=position.issue, quantity=position.quantity)
                    for position in account.positions
                ),
            )
        )
    return AccountCapacityDocument(
        as_of=as_of,
        maximum_age_seconds=maximum_age_seconds,
        journal_digest=journal_digest,
        firm_participant_id=firm_participant_id,
        accounts=tuple(projected),
    )


def attest_locates(document: LocateDocument) -> AttestedDocument:
    payload = canonical_bytes(document)
    return AttestedDocument(
        document_type="LOCATES", payload_digest=digest_bytes(payload), payload=payload
    )


class LocateInventory:
    """Quantity-limited locate consumption; reuse beyond the record fails closed."""

    def __init__(self, document: LocateDocument) -> None:
        self.document = document
        self._used: dict[str, Decimal] = {}

    def consume(self, locate_id: str, *, issue: str, quantity: Decimal, at: datetime) -> str | None:
        record = next((item for item in self.document.locates if item.locate_id == locate_id), None)
        if record is None:
            return "LOCATE_MISSING"
        if record.issue != issue:
            return "LOCATE_ISSUE_MISMATCH"
        if at > record.expires_at:
            return "LOCATE_EXPIRED"
        remaining = record.quantity - self._used.get(locate_id, Decimal(0))
        if quantity > remaining:
            return "LOCATE_INSUFFICIENT"
        self._used[locate_id] = self._used.get(locate_id, Decimal(0)) + quantity
        return None
