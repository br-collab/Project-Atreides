"""Atreides' internal parse target for settlement-obligation payload bytes."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SELLER_CAPACITIES",
    "CandidatePathDescriptor",
    "CashLeg",
    "Correction",
    "ExpectedFinality",
    "ObligationCandidate",
    "Participant",
    "SecuritiesLeg",
    "SourceManifest",
    "SourceReference",
]

ExactDecimal = Annotated[Decimal, Field(strict=False)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

#: INST-1 Amendment 3 (WP2b): the capacity of the account that delivers the securities,
#: carried in the digest-bound payload so Atreides never takes it from a caller.
SELLER_CAPACITIES = frozenset({"CUSTOMER", "PAB", "PROPRIETARY"})
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceReference(_Payload):
    kind: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SourceManifest(_Payload):
    references: tuple[SourceReference, ...] = ()


class Participant(_Payload):
    participant_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    role: str = Field(min_length=1)


class SecuritiesLeg(_Payload):
    instrument_id: str | None = None
    quantity: ExactDecimal | None = None
    delivering_account_id: str | None = None
    receiving_account_id: str | None = None


class CashLeg(_Payload):
    principal: ExactDecimal | None = None
    accrued: ExactDecimal | None = None
    total: ExactDecimal | None = None
    currency: str | None = None
    value_date: IsoDate | None = None
    paying_account_id: str | None = None
    receiving_account_id: str | None = None


class CandidatePathDescriptor(_Payload):
    path_id: str = Field(min_length=1)
    rail: str = Field(min_length=1)
    securities_route: str = Field(min_length=1)
    cash_route: str = Field(min_length=1)
    delivery_pattern: str | None = None


class ExpectedFinality(_Payload):
    leg: str
    finality_type: str
    governing_rule_set: str = Field(min_length=1)


class Correction(_Payload):
    correction_id: str = Field(min_length=1)
    supersedes_payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str = Field(min_length=1)


class ObligationCandidate(_Payload):
    """Parsed L.C.-owned payload; never the cross-domain boundary type."""

    source_manifest: SourceManifest | None = None
    securities_leg: SecuritiesLeg | None = None
    cash_leg: CashLeg | None = None
    participants: tuple[Participant, ...] = ()
    delivery_pattern: str | None = None
    candidate_paths: tuple[CandidatePathDescriptor, ...] = ()
    expected_finality: tuple[ExpectedFinality, ...] = ()
    corrections: tuple[Correction, ...] = ()
    #: Capacity of the delivering account (``SELLER_CAPACITIES``). L.C. sets it from the
    #: attested account-capacity document. Absent on a DELIVER obligation means HOLD.
    seller_capacity: str | None = None
    #: Digest of the attested account-capacity document (``atreides.equities_account_capacity``)
    #: the capacity was read from. A stated capacity with no attested source HOLDs.
    account_capacity_digest: Sha256Digest | None = None
    #: Digest of the participant registry version L.C. formed this obligation against.
    #: ``prepare_instruction`` refuses a registry whose digest differs.
    participant_registry_digest: Sha256Digest | None = None
