"""The provisional obligation candidate the acceptance service evaluates (ATR-I-01).

DRAFT, INTERNAL, ``0.1-draft`` (JUM-D-26): Wave 3 freezes the cross-domain
``SettlementObligationEnvelope`` and may change these fields without a
deprecation cycle. The behaviour proven against them may not be weakened.

The candidate is deliberately lenient in shape: every field may be absent and
enum-valued fields hold the raw value as it arrived. That is what lets the
acceptance service *report* a missing field or an unknown enum value as a
predicate result, instead of the candidate failing to construct and leaving no
record at all. The service never modifies a candidate; it is frozen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from cannae_kernel.ids import LifecycleId, ObligationId
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "CashLeg",
    "ExpectedFinality",
    "ObligationCandidate",
    "Participant",
    "SecuritiesLeg",
    "SourceReference",
]

CANDIDATE_SCHEMA_VERSION: Literal["0.1-draft"] = "0.1-draft"

#: Amounts and quantities are exact decimals, never binary floats.
ExactDecimal = Annotated[Decimal, Field(strict=True)]
#: ISO 8601 calendar date, kept as text so the candidate stays canonicalizable.
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class _Draft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceReference(_Draft):
    """Where part of the obligation came from: an intent, order, execution, allocation or match."""

    reference_type: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    digest: str | None = None


class Participant(_Draft):
    participant_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    account: str | None = None


class SecuritiesLeg(_Draft):
    lifecycle_id: LifecycleId | None = None
    #: Raw delivery pattern as it arrived; must name a kernel ``DeliveryPattern``.
    delivery_pattern: str | None = None
    instrument_id: str | None = None
    quantity: ExactDecimal | None = None
    deliverer_participant_id: str | None = None
    receiver_participant_id: str | None = None


class CashLeg(_Draft):
    lifecycle_id: LifecycleId | None = None
    delivery_pattern: str | None = None
    principal: ExactDecimal | None = None
    accrued_interest: ExactDecimal | None = None
    total: ExactDecimal | None = None
    currency: str | None = None
    value_date: IsoDate | None = None
    payer_participant_id: str | None = None
    payee_participant_id: str | None = None


class ExpectedFinality(_Draft):
    leg: Literal["securities", "cash"]
    #: Raw finality type as it arrived; must name a kernel ``FinalityType``.
    finality_type: str


class ObligationCandidate(_Draft):
    """A provisional settlement obligation, as proposed to Atreides for acceptance."""

    schema_version: Literal["0.1-draft"] = CANDIDATE_SCHEMA_VERSION
    obligation_id: ObligationId
    obligation_version: int | None = Field(default=None, ge=1)
    lifecycle_id: LifecycleId | None = None
    delivery_pattern: str | None = None
    source_references: tuple[SourceReference, ...] = ()
    securities_leg: SecuritiesLeg | None = None
    cash_leg: CashLeg | None = None
    participants: tuple[Participant, ...] = ()
    expected_finality: tuple[ExpectedFinality, ...] = ()
