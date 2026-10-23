"""Effective-dated reference data used by the GR-1 Treasury slice."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provenance: str = Field(min_length=1)
    effective_date: date


class InstrumentRecord(_Record):
    cusip: str = Field(pattern=r"^[0-9A-Z*@#]{9}$")
    figi: str = Field(pattern=r"^BBG[0-9A-Z]{9}$")
    description: str = Field(min_length=1)


class LegalEntityRecord(_Record):
    lei: str = Field(pattern=r"^[0-9A-Z]{20}$")
    entity_id: str = Field(min_length=1)
    parent_lei: str | None = Field(default=None, pattern=r"^[0-9A-Z]{20}$")


class AccountRecord(_Record):
    account_id: str = Field(min_length=1)
    owner_lei: str = Field(pattern=r"^[0-9A-Z]{20}$")
    account_type: str = Field(min_length=1)


class SettlementInstructionRecord(_Record):
    ssi_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    settlement_location: str = Field(min_length=1)
    cash_account_id: str = Field(min_length=1)
    securities_account_id: str = Field(min_length=1)
