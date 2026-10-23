"""GR-1 inbound street loop for one synthetic FICC GSD Treasury DVP trade."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from cannae_kernel.canonical import canonical_bytes_of
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.reference_data import (
    AccountRecord,
    InstrumentRecord,
    LegalEntityRecord,
    SettlementInstructionRecord,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuntimeProfile(StrEnum):
    RESEARCH = "RESEARCH"
    PRODUCTION = "PRODUCTION"


class InboundStatus(StrEnum):
    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    UNMATCHED = "UNMATCHED"
    SETTLED = "SETTLED"


class TreasuryDvpInstruction(_Model):
    trade_id: str
    obligation_id: str
    member_id: str
    cusip: str = Field(pattern=r"^[0-9A-Z*@#]{9}$")
    quantity: Decimal = Field(gt=0)
    cash_amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    settlement_date: date
    instrument: InstrumentRecord
    member: LegalEntityRecord
    account: AccountRecord
    ssi: SettlementInstructionRecord
    is_submission: bool = False

    @model_validator(mode="after")
    def _reference_data_joins(self) -> TreasuryDvpInstruction:
        if self.cusip != self.instrument.cusip:
            raise ValueError("trade CUSIP does not match the instrument master")
        if (
            self.account.owner_lei != self.member.lei
            or self.ssi.account_id != self.account.account_id
        ):
            raise ValueError("member, account, and SSI do not join")
        if any(
            record.effective_date > self.settlement_date
            for record in (self.instrument, self.member, self.account, self.ssi)
        ):
            raise ValueError("reference data is not effective by settlement date")
        if self.is_submission:
            raise ValueError("Atreides never submits")
        return self


class InboundStreetFact(_Model):
    trade_id: str
    status: InboundStatus
    ccp_obligation_amount: Decimal
    cash_movement_amount: Decimal
    securities_movement_quantity: Decimal
    observed_at: datetime
    provenance: Provenance
    pacs002: bytes
    camt054: bytes
    ficc_status: bytes
    late: bool = False


class OwnedBreak(_Model):
    code: str
    owner: str
    age_business_days: int = Field(ge=0)
    detail: str


class ClosedTradeResult(_Model):
    disposition: str
    obligation_amount: Decimal
    ccp_output_amount: Decimal
    cash_movement_amount: Decimal
    securities_movement_quantity: Decimal
    breaks: tuple[OwnedBreak, ...]
    books_posted: bool
    economics_bytes: bytes


def close_treasury_trade(
    instruction: TreasuryDvpInstruction,
    fact: InboundStreetFact,
    *,
    profile: RuntimeProfile,
    break_owner: str,
    age_business_days: int,
) -> ClosedTradeResult:
    """Reconcile the inbound fact and close or break the DVP trade.

    ORDER-GR-1 finding 3 governs this function: reconciliation closes
    "obligation equals CCP output equals cash movement", and every difference
    becomes an owned, aged break. Finding 4 requires the production profile
    to refuse ``FACT_SYNTHETIC`` provenance.
    """
    if profile is RuntimeProfile.PRODUCTION and fact.provenance is Provenance.FACT_SYNTHETIC:
        raise ValueError("production profile refuses FACT_SYNTHETIC economic facts")
    problems: list[str] = []
    if fact.trade_id != instruction.trade_id:
        problems.append("inbound status is unmatched")
    if fact.status is InboundStatus.PARTIAL:
        problems.append("inbound settlement is partial")
    if fact.status is InboundStatus.UNMATCHED:
        problems.append("inbound status is unmatched")
    if fact.late:
        problems.append("inbound status arrived late")
    if fact.ccp_obligation_amount != instruction.cash_amount:
        problems.append("obligation differs from CCP output")
    if fact.cash_movement_amount != fact.ccp_obligation_amount:
        problems.append("CCP output differs from cash movement")
    if fact.securities_movement_quantity != instruction.quantity:
        problems.append("securities movement differs from obligation")
    breaks = tuple(
        OwnedBreak(
            code="GR1_RECONCILIATION",
            owner=break_owner,
            age_business_days=age_business_days,
            detail=detail,
        )
        for detail in problems
    )
    economics = {
        "trade_id": instruction.trade_id,
        "cusip": instruction.cusip,
        "quantity": instruction.quantity,
        "cash_amount": instruction.cash_amount,
        "currency": instruction.currency,
        "settlement_date": instruction.settlement_date,
        "ccp_obligation_amount": fact.ccp_obligation_amount,
        "cash_movement_amount": fact.cash_movement_amount,
        "securities_movement_quantity": fact.securities_movement_quantity,
    }
    return ClosedTradeResult(
        disposition="PASS" if not breaks and fact.status is InboundStatus.SETTLED else "HOLD",
        obligation_amount=instruction.cash_amount,
        ccp_output_amount=fact.ccp_obligation_amount,
        cash_movement_amount=fact.cash_movement_amount,
        securities_movement_quantity=fact.securities_movement_quantity,
        breaks=breaks,
        books_posted=not breaks and fact.status is InboundStatus.SETTLED,
        economics_bytes=canonical_bytes_of(economics),
    )
