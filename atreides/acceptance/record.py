"""The obligation acceptance record (ATR-I-01; CL-JUM-001 §13).

DRAFT, ``0.1-draft`` (JUM-D-26). It references the obligation by id and
``sha256:`` digest and never copies its economics: whoever needs the amounts
reads the candidate the digest names.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from cannae_kernel.canonical import Digest, canonical_bytes_of, digest_bytes
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import ObligationId
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ACCEPTANCE_RULE_VERSION",
    "AcceptanceOutcome",
    "ObligationAcceptanceRecord",
    "PredicateResult",
    "outcome_for",
]

#: Version of the predicate set in :mod:`atreides.acceptance.service`.
ACCEPTANCE_RULE_VERSION = "obligation-acceptance/0.1-draft"


class AcceptanceOutcome(StrEnum):
    """The domain word for each kernel disposition (CL-JUM-001 §5.3)."""

    ACCEPTED = "ACCEPTED"
    HELD = "HELD"
    REJECTED = "REJECTED"
    INDETERMINATE = "INDETERMINATE"


_OUTCOME: dict[Disposition, AcceptanceOutcome] = {
    Disposition.PASS: AcceptanceOutcome.ACCEPTED,
    Disposition.HOLD: AcceptanceOutcome.HELD,
    Disposition.BLOCK: AcceptanceOutcome.REJECTED,
    Disposition.INDETERMINATE: AcceptanceOutcome.INDETERMINATE,
}


def outcome_for(disposition: Disposition) -> AcceptanceOutcome:
    return _OUTCOME[disposition]


class PredicateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    predicate: str = Field(min_length=1)
    disposition: Disposition
    reason_codes: tuple[str, ...] = ()
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def _non_pass_names_a_reason(self) -> Self:
        if self.disposition is not Disposition.PASS and not self.reason_codes:
            raise ValueError("a predicate that did not pass names a reason code")
        return self


class ObligationAcceptanceRecord(BaseModel):
    """Atreides' answer to an obligation candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["obligation_acceptance"] = "obligation_acceptance"
    schema_version: Literal["0.1-draft"] = "0.1-draft"
    #: The record's own id; the DSOR store's record subject.
    operation_id: UUID
    obligation_id: ObligationId
    obligation_version: int | None
    obligation_digest: Digest
    disposition: Disposition
    outcome: AcceptanceOutcome
    evaluated_predicates: tuple[PredicateResult, ...] = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    #: Versions of the evidence consulted, e.g. the CATO-F gate set.
    data_versions: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]
    #: The halt context version consulted; ``None`` when no halt context was supplied.
    halt_context_version: int | None
    evaluated_at: datetime
    #: Set only when the outcome is ACCEPTED.
    accepted_at: datetime | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.outcome is not outcome_for(self.disposition):
            raise ValueError("outcome must be the domain word for the disposition")
        if (self.outcome is AcceptanceOutcome.ACCEPTED) != (self.accepted_at is not None):
            raise ValueError("accepted_at is set exactly when the outcome is ACCEPTED")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return self

    @property
    def accepted(self) -> bool:
        return self.outcome is AcceptanceOutcome.ACCEPTED

    def digest(self) -> str:
        """``sha256:`` digest of this record's kernel canonical bytes.

        The kernel's canonical form has no rule for a UUID, so the record's own
        id is rendered as its standard string first.
        """
        fields = self.model_dump(mode="python")
        fields["operation_id"] = str(self.operation_id)
        return digest_bytes(canonical_bytes_of(fields))
