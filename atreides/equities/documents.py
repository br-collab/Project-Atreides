"""Atreides-owned equities documents and attested wire emission."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from cannae_kernel.canonical import canonical_bytes, digest_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountPosition(_Wire):
    issue: str = Field(min_length=1)
    quantity: Decimal


class AccountCapacity(_Wire):
    account_id: str = Field(min_length=1)
    buying_power: Decimal = Field(ge=0)
    margin_excess: Decimal
    positions: tuple[AccountPosition, ...]


class AccountCapacityDocument(_Wire):
    schema_version: Literal["atreides.equities_account_capacity/1"] = (
        "atreides.equities_account_capacity/1"
    )
    as_of: datetime
    maximum_age_seconds: int = Field(gt=0)
    synthetic: Literal[True] = True
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
