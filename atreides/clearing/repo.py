"""Synthetic FICC GSD DVP and GCF repo clearing from the member seat."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Self, cast

from cannae_kernel.canonical import Digest, canonical_bytes, digest_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.clearing.access import AccessDetermination, AccessStatus
from atreides.clearing.ficc import (
    ClearingAgency,
    ClearingStatus,
    EvidenceFact,
    EvidenceStage,
    FactStatus,
    NovatedObligation,
)
from atreides.deadlines.calendar import Market, MarketCalendar


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class RepoService(StrEnum):
    DVP = "FICC_GSD_DVP_REPO"
    GCF = "FICC_GCF_REPO"


class RepoTerm(StrEnum):
    OVERNIGHT = "OVERNIGHT"
    TERM = "TERM"
    OPEN = "OPEN"


class RepoLeg(StrEnum):
    START = "START"
    CLOSE = "CLOSE"


class SponsoredExecution(StrEnum):
    DONE_WITH = "DONE_WITH"
    DONE_AWAY = "DONE_AWAY"


_REPO_CALENDAR = MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES)


class RepoTrade(_Model):
    trade_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    service: RepoService
    term: RepoTerm
    start_date: date
    close_date: date | None
    collateral_par: Decimal = Field(gt=0)
    start_money: Decimal = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    repo_rate_percent: Decimal = Field(ge=0)
    day_count_basis: int = Field(default=360, gt=0)
    cusip: str | None = Field(default=None, pattern=r"^[0-9A-Z*@#]{9}$")
    collateral_class: str | None = None
    clearing_bank: str | None = None
    haircut_percent: Decimal = Field(ge=0)
    member_margin_approximation: Decimal = Field(ge=0)
    sponsored_execution: SponsoredExecution | None = None

    @model_validator(mode="after")
    def _service_and_term_are_complete(self) -> Self:
        if self.term is RepoTerm.OPEN and self.close_date is not None:
            raise ValueError("OPEN repo has no fixed close date")
        if self.term is not RepoTerm.OPEN and (
            self.close_date is None or self.close_date <= self.start_date
        ):
            raise ValueError("overnight and term repo require a later close date")
        if self.close_date is not None and not _REPO_CALENDAR.is_business_day(self.close_date):
            raise ValueError("repo close date must be a government securities business day")
        if self.close_date is not None:
            business_days = _REPO_CALENDAR.business_days_after(self.start_date, self.close_date)
            if self.term is RepoTerm.OVERNIGHT and business_days != 1:
                raise ValueError("OVERNIGHT repo must close exactly one business day after start")
            if self.term is RepoTerm.TERM and business_days <= 1:
                raise ValueError("TERM repo must close more than one business day after start")
        if self.service is RepoService.DVP and (
            self.cusip is None
            or self.collateral_class is not None
            or self.clearing_bank is not None
        ):
            raise ValueError("DVP requires CUSIP and has no generic collateral allocation")
        if self.service is RepoService.GCF and (
            self.cusip is not None or not self.collateral_class or not self.clearing_bank
        ):
            raise ValueError("GCF requires CUSIP-less collateral class and clearing bank")
        return self

    def close_money(self) -> Decimal | None:
        if self.close_date is None:
            return None
        days = Decimal((self.close_date - self.start_date).days)
        return (
            self.start_money
            + self.start_money
            * self.repo_rate_percent
            / Decimal(100)
            * days
            / Decimal(self.day_count_basis)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


class RepoLegObligation(_Model):
    obligation_id: str
    trade_id: str
    leg: RepoLeg
    settlement_date: date | None
    signed_par: Decimal
    signed_money: Decimal | None
    currency: str
    cusip: str | None
    collateral_class: str | None
    settlement_path: str
    facts: tuple[EvidenceFact, ...] = Field(min_length=5, max_length=5)


class GcfAllocation(_Model):
    trade_id: str
    collateral_class: str
    clearing_bank: str
    allocated_par: Decimal
    returned_par: Decimal | None


class RepoDocument(_Model):
    schema_version: str = "atreides.ficc_repo/1"
    clearing_agency: ClearingAgency
    clearing_method: RepoService
    observation_seat: str = "FICC_MEMBER"
    observed_member_id: str
    access_path: str
    sponsored_execution: SponsoredExecution | None
    repo_rate_percent: Decimal
    day_count_basis: int
    term: RepoTerm
    haircut_percent: Decimal
    member_margin_approximation: Decimal
    member_margin_method: str = "SYNTHETIC_APPROXIMATION_NOT_FICC_VAR"
    legs: tuple[RepoLegObligation, ...]
    gcf_allocation: GcfAllocation | None = None


class RepoResult(_Model):
    status: ClearingStatus
    reason: str | None = None
    payload_digest: Digest | None = None
    payload: bytes | None = None


def _facts(prefix: str, finality: bool) -> tuple[EvidenceFact, ...]:
    values = []
    for stage in EvidenceStage:
        recorded = stage is not EvidenceStage.SETTLEMENT_FINALITY or finality
        values.append(
            EvidenceFact(
                stage=stage,
                status=FactStatus.RECORDED if recorded else FactStatus.NOT_RECORDED,
                evidence_id=f"{prefix}:{stage.value}" if recorded else None,
                reason=None if recorded else "settlement finality was not recorded",
            )
        )
    return tuple(values)


def produce_repo_result(
    *,
    trade: RepoTrade,
    access: AccessDetermination,
    agency: ClearingAgency = ClearingAgency.FICC_GSD,
    settled_legs: tuple[RepoLeg, ...] = (),
) -> RepoResult:
    if agency is ClearingAgency.CME_SECURITIES_CLEARING:
        return RepoResult(
            status=ClearingStatus.INDETERMINATE,
            reason="CME Securities Clearing repo rules are declared but not built",
        )
    if access.status is AccessStatus.INDETERMINATE or access.arrangement is None:
        return RepoResult(
            status=ClearingStatus.INDETERMINATE,
            reason=f"repo access is indeterminate: {access.reason}",
        )
    member = access.arrangement.clearing_member.party_id
    if member != trade.member_id:
        return RepoResult(
            status=ClearingStatus.INDETERMINATE,
            reason="trade is not observed from the relied-on FICC member seat",
        )
    if access.arrangement.path.value == "FICC_SPONSORED" and trade.sponsored_execution is None:
        return RepoResult(
            status=ClearingStatus.INDETERMINATE,
            reason="sponsored repo requires done-with or done-away evidence",
        )
    close_money = trade.close_money()
    legs = [
        RepoLegObligation(
            obligation_id=f"{trade.trade_id}:START",
            trade_id=trade.trade_id,
            leg=RepoLeg.START,
            settlement_date=trade.start_date,
            signed_par=trade.collateral_par,
            signed_money=-trade.start_money,
            currency=trade.currency,
            cusip=trade.cusip,
            collateral_class=trade.collateral_class,
            settlement_path="DVP_NETTING" if trade.service is RepoService.DVP else "GCF_TRIPARTY",
            facts=_facts(f"{trade.trade_id}:START", RepoLeg.START in settled_legs),
        )
    ]
    if close_money is not None:
        legs.append(
            RepoLegObligation(
                obligation_id=f"{trade.trade_id}:CLOSE",
                trade_id=trade.trade_id,
                leg=RepoLeg.CLOSE,
                settlement_date=trade.close_date,
                signed_par=-trade.collateral_par,
                signed_money=close_money,
                currency=trade.currency,
                cusip=trade.cusip,
                collateral_class=trade.collateral_class,
                settlement_path="DVP_NETTING"
                if trade.service is RepoService.DVP
                else "GCF_TRIPARTY",
                facts=_facts(f"{trade.trade_id}:CLOSE", RepoLeg.CLOSE in settled_legs),
            )
        )
    allocation = None
    if trade.service is RepoService.GCF:
        allocation = GcfAllocation(
            trade_id=trade.trade_id,
            collateral_class=trade.collateral_class or "",
            clearing_bank=trade.clearing_bank or "",
            allocated_par=trade.collateral_par,
            returned_par=trade.collateral_par if close_money is not None else None,
        )
    document = RepoDocument(
        clearing_agency=agency,
        clearing_method=trade.service,
        observed_member_id=member,
        access_path=access.arrangement.path.value,
        sponsored_execution=trade.sponsored_execution,
        repo_rate_percent=trade.repo_rate_percent,
        day_count_basis=trade.day_count_basis,
        term=trade.term,
        haircut_percent=trade.haircut_percent,
        member_margin_approximation=trade.member_margin_approximation,
        legs=tuple(legs),
        gcf_allocation=allocation,
    )
    payload = canonical_bytes(document)
    return RepoResult(
        status=ClearingStatus.ESTABLISHED, payload_digest=digest_bytes(payload), payload=payload
    )


def dvp_legs_for_netting(result: RepoResult) -> tuple[NovatedObligation, ...]:
    if result.status is not ClearingStatus.ESTABLISHED or result.payload is None:
        return ()
    doc = RepoDocument.model_validate_json(result.payload)
    if doc.clearing_method is not RepoService.DVP:
        return ()
    if any(leg.settlement_date is None or leg.signed_money is None for leg in doc.legs):
        raise ValueError("DVP netting requires dated cash obligations")
    return tuple(
        NovatedObligation(
            obligation_id=leg.obligation_id,
            trade_ids=(leg.trade_id,),
            member_id=doc.observed_member_id,
            cusip=leg.cusip or "",
            settlement_date=cast(date, leg.settlement_date),
            signed_quantity=leg.signed_par,
            signed_settlement_amount=cast(Decimal, leg.signed_money),
            settlement_currency=leg.currency,
            novation_evidence_id=f"{leg.obligation_id}:NOVATION",
        )
        for leg in doc.legs
    )
