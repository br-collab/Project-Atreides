"""Typed I/O contracts for the Settlement Operations Analyst (Tier 1 · Thifur-R).

Per AUR-CANONICAL-001 v1.5.1 Section IV (settlement-operations-analyst v0.3)
and AUR-CUSTODY-001 v1.0 Section VI (R-class roles — zero variance,
no path selection, immediate escalation on any gate failure).

Module layout
-------------
Enumerations: SettlementRail, SettlementKind, CreditFacilityType,
    GCFPoolCustodian, DiscrepancyCode

Input contract: SettlementTaskingRecord — frozen, delivered by Thifur-C2.

Validation result: SettlementValidation — the pure outcome of the
    pre-routing gates, before anything is emitted (ATR-I-02).

Output contracts: SettlementTelemetry (success path), SettlementEscalation
    (any pre-routing gate failure). Discriminated on ``kind``.

Rail acknowledgement: RailAcknowledgment — built only from a verified
    readback, never from local emission (ATR-I-02).

SettlementOutput — union alias used by DSORStore type adapter.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.contracts import DSORLineageStub
from atreides.messaging.readback import ReadbackMatch, SettlementStatus

CURRENT_DOCTRINE_VERSION: Final = "AUR-CANONICAL-001-v1.5.1"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SettlementRail(StrEnum):
    FICC_GSD_DVP = "ficc_gsd_dvp"
    FICC_GCF_REPO = "ficc_gcf_repo"
    FICC_SPONSORED_DVP = "ficc_sponsored_dvp"
    FEDWIRE_FUNDS = "fedwire_funds"
    FEDWIRE_SECURITIES = "fedwire_securities"
    SWIFT_MT202 = "swift_mt202"


class SettlementKind(StrEnum):
    DVP = "dvp"
    MTM_MARGIN_CALL = "mtm_margin_call"
    EOD_NET_FUNDING = "eod_net_funding"


class CreditFacilityType(StrEnum):
    DIRECT_FED = "direct_fed"
    CORRESPONDENT = "correspondent"


class GCFPoolCustodian(StrEnum):
    BNY_MELLON = "bny_mellon"


class DiscrepancyCode(StrEnum):
    DSOR_MISMATCH = "dsor_mismatch"
    RAIL_UNAVAILABLE = "rail_unavailable"
    COUNTERPARTY_TIMEOUT = "counterparty_timeout"
    INSTRUCTION_REJECTED = "instruction_rejected"
    CLEARING_FUND_DEFICIENCY = "clearing_fund_deficiency"
    INTRADAY_CREDIT_THRESHOLD = "intraday_credit_threshold"
    NET_OBLIGATION_MISMATCH = "net_obligation_mismatch"
    FICC_MTM_DEADLINE_BREACH = "ficc_mtm_deadline_breach"
    RAIL_CONFIRMATION_MISMATCH = "rail_confirmation_mismatch"


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


class SettlementTaskingRecord(BaseModel):
    """Tasking record delivered by Thifur-C2 to the Settlement Operations Analyst.

    Frozen at delivery. The analyst may read but never mutate this record.
    All optional FICC-specific fields default to None; the analyst gates on
    their presence before applying the corresponding pre-routing checks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    operation_id: UUID
    rail: SettlementRail
    settlement_kind: SettlementKind
    counterparty_id: str
    deadline: datetime
    dsor_pre_trade_record_id: UUID
    lineage_stub: DSORLineageStub
    doctrine_version: str = CURRENT_DOCTRINE_VERSION

    # Net settlement obligation (FICC GSD — set for DVP and GCF Repo)
    net_cusip: str | None = None
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None

    # FICC-published net position (v0.3: net obligation modeling check)
    ficc_published_net_delivery: Decimal | None = None
    ficc_published_net_payment: Decimal | None = None

    # v0.3 — intraday funding position (Reg F / cap net debit cap)
    intraday_credit_limit: Decimal | None = None
    intraday_credit_current_usage: Decimal | None = None
    credit_facility_type: CreditFacilityType | None = None

    # v0.3 — FICC margin mechanics (clearing fund VaR + FICC intraday MTM call)
    ficc_clearing_fund_compliant: bool = True
    ficc_mtm_call_amount: Decimal | None = None
    ficc_mtm_call_deadline: datetime | None = None

    # v0.3 — FICC netting configuration surfaces
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


class SettlementValidation(BaseModel):
    """The outcome of the pre-routing gates, and nothing else (ATR-I-02).

    Pure data: no time, no route, no instruction reference, no DSOR record.
    Validation used to route, generate a reference and persist telemetry with
    a rail acknowledgement set before any instruction existed. That work now
    belongs to :meth:`SettlementOperationsAnalyst.emit`, an explicitly named
    stage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    passed: bool
    #: Gate names in the order they were evaluated, up to and including the
    #: first that held.
    checks_evaluated: tuple[str, ...]
    discrepancy_code: DiscrepancyCode | None = None
    failure_detail: str | None = None
    intraday_credit_usage: Decimal | None = None
    intraday_credit_limit: Decimal | None = None
    clearing_fund_deficiency: bool = False
    net_obligation_discrepancy: str | None = None

    @model_validator(mode="after")
    def _held_says_why(self) -> Self:
        if self.passed != (self.discrepancy_code is None):
            raise ValueError("a held validation names its discrepancy; a passed one does not")
        if not self.passed and not self.failure_detail:
            raise ValueError("a held validation carries its failure detail")
        if not self.checks_evaluated:
            raise ValueError("a validation that evaluated no check is not a validation")
        return self


#: Venue statuses that acknowledge an instruction. REJECTED, CANCELLED,
#: ACCEPTED_WITH_CHANGE and UNRECOGNIZED do not.
ACKNOWLEDGING_STATUSES: Final[frozenset[SettlementStatus]] = frozenset(
    {
        SettlementStatus.RECEIVED,
        SettlementStatus.IN_PROGRESS,
        SettlementStatus.ACCEPTED_NOT_POSTED,
        SettlementStatus.SETTLED,
    }
)


class RailAcknowledgment(BaseModel):
    """The rail's acknowledgement of an instruction, from a verified readback.

    Build it with :meth:`from_readback`. The rail acknowledged the instruction
    only when the venue's own status report, reconciled against what was
    prepared, says so. A time this framework chose locally is not an
    acknowledgement (ATR-I-02).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["verified_readback"] = "verified_readback"
    end_to_end_id: str = Field(min_length=1)
    status: SettlementStatus
    status_report_message_id: str = Field(min_length=1)
    acknowledged_at: datetime

    @model_validator(mode="after")
    def _status_acknowledges(self) -> Self:
        if self.status not in ACKNOWLEDGING_STATUSES:
            raise ValueError(f"venue status {self.status.value!r} is not an acknowledgement")
        if self.acknowledged_at.tzinfo is None:
            raise ValueError("acknowledged_at must be timezone-aware")
        return self

    @classmethod
    def from_readback(cls, match: ReadbackMatch, end_to_end_id: str) -> RailAcknowledgment:
        """The acknowledgement a reconciled status report establishes, or raise.

        Refuses when nothing came back, when the report carries any break for
        this instruction, when the instruction was not matched, or when the
        venue's status is not an acknowledgement. The time is the venue's
        acceptance time where it gave one, else the report's creation time.
        """
        if match.is_absent:
            raise ValueError("no readback: silence is not an acknowledgement")
        if any(b.end_to_end_id == end_to_end_id for b in match.breaks):
            raise ValueError(f"the readback for {end_to_end_id!r} did not reconcile cleanly")
        status = match.matched.get(end_to_end_id)
        if status is None:
            raise ValueError(f"the readback does not match instruction {end_to_end_id!r}")
        entry = next(e for e in match.report.entries if e.end_to_end_id == end_to_end_id)
        stamp = entry.acceptance_datetime or match.report.created_at
        return cls(
            end_to_end_id=end_to_end_id,
            status=status,
            status_report_message_id=match.report.message_id,
            acknowledged_at=datetime.fromisoformat(stamp.replace("Z", "+00:00")),
        )


class _SettlementOutputBase(BaseModel):
    """Common fields for all Settlement Operations Analyst outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    task_id: UUID
    doctrine_version: str
    lineage_stub: DSORLineageStub
    emitted_at: datetime
    rail: SettlementRail | None


class SettlementTelemetry(_SettlementOutputBase):
    """Emitted on successful settlement instruction routing (success path).

    ``kind`` is always ``"settlement_telemetry"`` and serves as the DSOR
    discriminator. The instruction reference is a deterministic routing token
    generated from the task_id and rail; in production it is replaced by the
    rail-assigned acknowledgment reference (FICC CNS sequence number or
    Fedwire sequence).
    """

    kind: Literal["settlement_telemetry"] = "settlement_telemetry"
    settlement_kind: SettlementKind
    instruction_reference: str
    net_cusip: str | None = None
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None
    #: Set only from a verified readback (ATR-I-02). ``None`` means the rail
    #: has not acknowledged, which is the state of every freshly emitted
    #: instruction.
    rail_acknowledgment: RailAcknowledgment | None = None
    clearing_fund_compliant: bool
    intraday_credit_usage_at_execution: Decimal | None = None
    intraday_credit_limit: Decimal | None = None
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_fabricated_acknowledgment(cls, data: Any) -> Any:
        # Records written before Wave 2 carry rail_acknowledgment_dtg, which
        # was always the local emission time and never an acknowledgement.
        # They are read without it rather than refused, so old DSOR records
        # still replay; the value was not evidence of anything.
        if isinstance(data, dict) and "rail_acknowledgment_dtg" in data:
            data = {k: v for k, v in data.items() if k != "rail_acknowledgment_dtg"}
        return data

    @property
    def rail_acknowledgment_dtg(self) -> datetime | None:
        """Deprecated until Wave 3: use ``rail_acknowledgment.acknowledged_at``.

        ``None`` until a verified readback acknowledges the instruction.
        """
        ack = self.rail_acknowledgment
        return None if ack is None else ack.acknowledged_at


class SettlementEscalation(_SettlementOutputBase):
    """Emitted when a pre-routing gate fails (escalation path).

    ``rail`` is ``None`` when the escalation fires before routing (the
    common case for all pre-routing gates). ``clearing_fund_deficiency``
    is only ``True`` when ``discrepancy_code`` is
    ``CLEARING_FUND_DEFICIENCY``; it is ``False`` for all other codes.
    """

    kind: Literal["settlement_escalation"] = "settlement_escalation"
    discrepancy_code: DiscrepancyCode
    failure_detail: str
    intraday_credit_usage: Decimal | None = None
    intraday_credit_limit: Decimal | None = None
    clearing_fund_deficiency: bool = False
    net_obligation_discrepancy: str | None = None


SettlementOutput = SettlementTelemetry | SettlementEscalation

__all__ = [
    "ACKNOWLEDGING_STATUSES",
    "CURRENT_DOCTRINE_VERSION",
    "CreditFacilityType",
    "DiscrepancyCode",
    "GCFPoolCustodian",
    "RailAcknowledgment",
    "SettlementEscalation",
    "SettlementKind",
    "SettlementOutput",
    "SettlementRail",
    "SettlementTaskingRecord",
    "SettlementTelemetry",
    "SettlementValidation",
]
