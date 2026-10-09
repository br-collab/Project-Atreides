"""Evidence that funding was actually secured.

A projection from ``project_funding`` says what the ladder expects. It is not
an observation that money was secured. Unknown availability has no amount.
It is not zero, and it is not a pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, Self

from cannae_kernel._model import KernelModel, UtcDatetime
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance
from pydantic import Field, ValidationError, model_validator

from atreides.rails.funding_state import FundingProjection

__all__ = [
    "FundingAssessment",
    "SecuredFunding",
    "assess_secured_funding",
    "read_secured_funding",
]


class SecuredFunding(KernelModel):
    """One observation that funds were secured. The amount was stated."""

    authoritative_source: str = Field(min_length=1, description="Who reported the secured funds.")
    amount: Decimal = Field(ge=0, description="The quantified amount that was observed.")
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO currency code of the amount.")
    account_or_facility: str = Field(
        min_length=1,
        description="The account or facility where the funds were observed.",
    )
    observation_time: UtcDatetime = Field(
        description="When the secured funds were observed, in UTC."
    )
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC] = Field(
        description="A fact from outside, or from a synthetic emulator."
    )

    @model_validator(mode="after")
    def _source_is_an_identifier(self) -> Self:
        if self.authoritative_source != self.authoritative_source.strip():
            raise ValueError("authoritative source must not have leading or trailing whitespace")
        if self.account_or_facility != self.account_or_facility.strip():
            raise ValueError("account or facility must not have leading or trailing whitespace")
        return self


class FundingAssessment(KernelModel):
    """Whether secured funding was observed. The amount is absent when it was not."""

    disposition: Disposition = Field(description="PASS, HOLD, or INDETERMINATE.")
    reason: str = Field(min_length=1, description="Why the disposition was reached.")
    amount: Decimal | None = Field(
        default=None,
        description=(
            "The observed amount. Absent when availability is unknown. Never a default of zero."
        ),
    )


def assess_secured_funding(
    evidence: SecuredFunding | None,
    *,
    projection: FundingProjection | None = None,
) -> FundingAssessment:
    """Grade an observation. A projection does not supply the amount or the pass."""
    del projection
    if evidence is None:
        return FundingAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="secured funding was not observed, so availability is unknown",
            amount=None,
        )
    return FundingAssessment(
        disposition=Disposition.PASS,
        reason="actual secured funding was observed from its named source",
        amount=evidence.amount,
    )


def read_secured_funding(payload: object) -> SecuredFunding | FundingAssessment:
    """Read one observation, or return INDETERMINATE when the payload is not one."""
    try:
        if isinstance(payload, str | bytes):
            return SecuredFunding.model_validate_json(payload)
        if isinstance(payload, Mapping):
            return SecuredFunding.model_validate(dict(payload))
    except ValidationError:
        return FundingAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="the payload is not a readable secured funding observation",
        )
    return FundingAssessment(
        disposition=Disposition.INDETERMINATE,
        reason="the payload is not a readable secured funding observation",
    )
