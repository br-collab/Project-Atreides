"""Pure FICC GSD novation and netting with an attested publication boundary.

This is the Treasury path.  It is deliberately separate from the NSCC equities
continuous-net-settlement implementation in :mod:`atreides.rails.cns`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from cannae_kernel.canonical import Digest, canonical_bytes, digest_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.clearing.access import AccessDetermination, AccessStatus

__all__ = [
    "ClearingAgency",
    "ClearingStatus",
    "EvidenceFact",
    "EvidenceStage",
    "FactStatus",
    "FiccGsdNettingDocument",
    "FiccGsdNettingRequest",
    "FiccGsdResult",
    "FiccGsdResultHeader",
    "NetSettlementObligation",
    "NovatedObligation",
    "ObservationSeat",
    "produce_ficc_gsd_result",
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ClearingAgency(StrEnum):
    """Declared United States Treasury clearing agency."""

    FICC_GSD = "FICC_GSD"
    CME_SECURITIES_CLEARING = "CME_SECURITIES_CLEARING"


class ClearingStatus(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    INDETERMINATE = "INDETERMINATE"


class ObservationSeat(StrEnum):
    """Perspective represented by the net settlement result."""

    FICC_MEMBER = "FICC_MEMBER"


class EvidenceStage(StrEnum):
    CLEARING_ACCEPTANCE = "CLEARING_ACCEPTANCE"
    NOVATION = "NOVATION"
    NETTING = "NETTING"
    SETTLEMENT_INSTRUCTION = "SETTLEMENT_INSTRUCTION"
    SETTLEMENT_FINALITY = "SETTLEMENT_FINALITY"


class FactStatus(StrEnum):
    RECORDED = "RECORDED"
    NOT_RECORDED = "NOT_RECORDED"


class EvidenceFact(_Model):
    """One fact only; recording it never establishes the following stage."""

    stage: EvidenceStage
    status: FactStatus
    evidence_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _status_has_evidence_or_reason(self) -> Self:
        if self.status is FactStatus.RECORDED:
            if not self.evidence_id or self.reason is not None:
                raise ValueError("RECORDED requires evidence_id and no absence reason")
        elif self.evidence_id is not None or not self.reason:
            raise ValueError("NOT_RECORDED requires a reason and no evidence_id")
        return self


class NovatedObligation(_Model):
    """One novated obligation before member/security/date netting."""

    obligation_id: str = Field(min_length=1)
    trade_ids: tuple[str, ...] = Field(min_length=1)
    member_id: str = Field(min_length=1)
    cusip: str = Field(pattern=r"^[0-9A-Z*@#]{9}$")
    settlement_date: date
    signed_quantity: Decimal
    signed_settlement_amount: Decimal
    settlement_currency: str = Field(pattern=r"^[A-Z]{3}$")
    novation_evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _quantity_and_lineage_are_real(self) -> Self:
        if self.signed_quantity == 0:
            raise ValueError("a novated obligation cannot have zero quantity")
        if self.signed_settlement_amount == 0:
            raise ValueError("a DvP obligation cannot have zero settlement amount")
        if self.signed_quantity * self.signed_settlement_amount > 0:
            raise ValueError("security and money legs must have opposite signs")
        if len(set(self.trade_ids)) != len(self.trade_ids):
            raise ValueError("trade_ids must be unique within an obligation")
        return self


class NetSettlementObligation(_Model):
    """The settlement obligation after FICC member-level netting."""

    member_id: str
    cusip: str
    settlement_date: date
    net_quantity: Decimal
    net_settlement_amount: Decimal
    settlement_currency: str = Field(pattern=r"^[A-Z]{3}$")
    source_obligation_ids: tuple[str, ...] = Field(min_length=1)
    source_trade_ids: tuple[str, ...] = Field(min_length=1)


class FiccGsdNettingRequest(_Model):
    clearing_agency: ClearingAgency
    access: AccessDetermination
    obligations: tuple[NovatedObligation, ...] = Field(min_length=1)
    clearing_acceptance_evidence_id: str = Field(min_length=1)
    netting_evidence_id: str = Field(min_length=1)
    settlement_instruction_evidence_id: str | None = None
    settlement_finality_evidence_id: str | None = None

    @model_validator(mode="after")
    def _identities_and_fact_order_are_unambiguous(self) -> Self:
        ids = [item.obligation_id for item in self.obligations]
        if len(set(ids)) != len(ids):
            raise ValueError("obligation_id must be unique")
        if self.settlement_finality_evidence_id and not self.settlement_instruction_evidence_id:
            raise ValueError("finality evidence cannot appear without instruction evidence")
        return self


class FiccGsdNettingDocument(_Model):
    schema_version: str = "atreides.ficc_gsd_netting/2"
    clearing_agency: ClearingAgency
    clearing_method: str = "FICC_GSD_NOVATED_NETTED"
    observation_seat: ObservationSeat = ObservationSeat.FICC_MEMBER
    observed_member_id: str = Field(min_length=1)
    access_path: str
    rule_set_version: str
    processing_calendar_id: str
    facts: tuple[EvidenceFact, ...] = Field(min_length=5, max_length=5)
    novated_obligations: tuple[NovatedObligation, ...]
    net_settlement_obligations: tuple[NetSettlementObligation, ...]


class FiccGsdResultHeader(_Model):
    schema_version: str = "atreides.ficc_gsd_netting_header/2"
    payload_digest: Digest
    clearing_agency: ClearingAgency
    clearing_method: str = "FICC_GSD_NOVATED_NETTED"


class FiccGsdResult(_Model):
    status: ClearingStatus
    reason: str | None = None
    header: FiccGsdResultHeader | None = None
    payload: bytes | None = None

    @model_validator(mode="after")
    def _status_matches_result(self) -> Self:
        if self.status is ClearingStatus.ESTABLISHED:
            if self.reason is not None or self.header is None or self.payload is None:
                raise ValueError("ESTABLISHED requires header and payload")
        elif self.reason is None or self.header is not None or self.payload is not None:
            raise ValueError("INDETERMINATE requires only a reason")
        return self


def _fact(stage: EvidenceStage, evidence_id: str | None, absent_reason: str) -> EvidenceFact:
    if evidence_id is not None:
        return EvidenceFact(stage=stage, status=FactStatus.RECORDED, evidence_id=evidence_id)
    return EvidenceFact(stage=stage, status=FactStatus.NOT_RECORDED, reason=absent_reason)


def _net(obligations: tuple[NovatedObligation, ...]) -> tuple[NetSettlementObligation, ...]:
    grouped: dict[tuple[str, str, date], list[NovatedObligation]] = defaultdict(list)
    for obligation in obligations:
        grouped[(obligation.member_id, obligation.cusip, obligation.settlement_date)].append(
            obligation
        )

    results: list[NetSettlementObligation] = []
    for (member_id, cusip, settlement_date), members in sorted(grouped.items()):
        results.append(
            NetSettlementObligation(
                member_id=member_id,
                cusip=cusip,
                settlement_date=settlement_date,
                net_quantity=sum((item.signed_quantity for item in members), Decimal(0)),
                net_settlement_amount=sum(
                    (item.signed_settlement_amount for item in members), Decimal(0)
                ),
                settlement_currency=members[0].settlement_currency,
                source_obligation_ids=tuple(sorted(item.obligation_id for item in members)),
                source_trade_ids=tuple(
                    sorted(trade_id for item in members for trade_id in item.trade_ids)
                ),
            )
        )
    return tuple(results)


def produce_ficc_gsd_result(request: FiccGsdNettingRequest) -> FiccGsdResult:
    """Assess the declared agency/access and emit exact attested result bytes."""

    if request.clearing_agency is ClearingAgency.CME_SECURITIES_CLEARING:
        return FiccGsdResult(
            status=ClearingStatus.INDETERMINATE,
            reason="clearing agency declared, rules not built",
        )
    if request.access.status is AccessStatus.INDETERMINATE:
        return FiccGsdResult(
            status=ClearingStatus.INDETERMINATE,
            reason=f"FICC GSD access is indeterminate: {request.access.reason}",
        )

    arrangement = request.access.arrangement
    if arrangement is None:  # Defensive even though AccessDetermination validates this.
        return FiccGsdResult(status=ClearingStatus.INDETERMINATE, reason="access is absent")

    observed_member_id = arrangement.clearing_member.party_id
    member_ids = {item.member_id for item in request.obligations}
    if member_ids != {observed_member_id}:
        return FiccGsdResult(
            status=ClearingStatus.INDETERMINATE,
            reason=(
                "member-seat result requires every obligation to belong to clearing member "
                f"{observed_member_id}; received {','.join(sorted(member_ids))}"
            ),
        )

    currencies_by_position: dict[tuple[str, str, date], set[str]] = defaultdict(set)
    for obligation in request.obligations:
        currencies_by_position[
            (obligation.member_id, obligation.cusip, obligation.settlement_date)
        ].add(obligation.settlement_currency)
    if any(len(currencies) != 1 for currencies in currencies_by_position.values()):
        return FiccGsdResult(
            status=ClearingStatus.INDETERMINATE,
            reason="one member/CUSIP/settlement-date position cannot mix settlement currencies",
        )

    novation_ids = sorted({item.novation_evidence_id for item in request.obligations})
    document = FiccGsdNettingDocument(
        clearing_agency=request.clearing_agency,
        observed_member_id=observed_member_id,
        access_path=arrangement.path.value,
        rule_set_version=arrangement.rule_set_version,
        processing_calendar_id=arrangement.processing_calendar_id,
        facts=(
            _fact(
                EvidenceStage.CLEARING_ACCEPTANCE,
                request.clearing_acceptance_evidence_id,
                "clearing acceptance was not recorded",
            ),
            _fact(EvidenceStage.NOVATION, ",".join(novation_ids), "novation was not recorded"),
            _fact(EvidenceStage.NETTING, request.netting_evidence_id, "netting was not recorded"),
            _fact(
                EvidenceStage.SETTLEMENT_INSTRUCTION,
                request.settlement_instruction_evidence_id,
                "settlement instruction was not recorded",
            ),
            _fact(
                EvidenceStage.SETTLEMENT_FINALITY,
                request.settlement_finality_evidence_id,
                "settlement finality was not recorded",
            ),
        ),
        novated_obligations=request.obligations,
        net_settlement_obligations=_net(request.obligations),
    )
    payload = canonical_bytes(document)
    return FiccGsdResult(
        status=ClearingStatus.ESTABLISHED,
        header=FiccGsdResultHeader(
            payload_digest=digest_bytes(payload),
            clearing_agency=request.clearing_agency,
        ),
        payload=payload,
    )
