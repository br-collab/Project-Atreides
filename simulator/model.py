"""Strict records for generated SIM-1 economics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class AssetClass(StrEnum):
    EQUITY = "EQUITY"
    TREASURY_NOTE = "TREASURY_NOTE"
    TREASURY_BILL = "TREASURY_BILL"


class Order(Record):
    order_id: str
    issue: str
    asset_class: AssetClass
    side: Side
    quantity: int = Field(gt=0)
    limit_price: Decimal
    arrived_at: datetime
    account_weights: tuple[int, ...] = (1,)


class Print(Record):
    print_id: str
    order_id: str
    issue: str
    quantity: int = Field(gt=0)
    price: Decimal
    matched_at: datetime
    reported_at: datetime
    provenance: str = "FACT_SYNTHETIC"
    session: str = "CONTINUOUS"


class Movement(Record):
    message_name: str
    issue: str
    securities: int
    money: Decimal
    status: str
    provenance: str = "FACT_SYNTHETIC"


class Break(Record):
    invariant: str
    owner: str
    age_business_days: int = Field(ge=0)
    reason: str


class CloseResult(Record):
    business_date: date
    invariant_results: dict[str, bool]
    breaks: tuple[Break, ...]
    holds: tuple[str, ...]
    fails_by_age: dict[str, int]
    market_access_refusals: dict[str, int]
    money_residual: Decimal
    replay_digest_check: bool
    economics_digest: str
    scenarios: tuple[str, ...]
