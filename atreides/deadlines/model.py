"""Closed models for hash-pinned deadline rules and advisory assessments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from cannae_kernel.disposition import Disposition
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RuleUnit(StrEnum):
    BUSINESS_DAYS = "BUSINESS_DAYS"
    SETTLEMENT_DAYS = "SETTLEMENT_DAYS"
    CALENDAR_DAYS = "CALENDAR_DAYS"
    MONTHS = "MONTHS"
    CLOCK_TIME = "CLOCK_TIME"


class RuleSource(_Frozen):
    source_id: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    url: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_dtg: str = Field(pattern=r"^\d{12}$")
    effective_date: date | None = None
    expires_at: date | None = None


class DeadlineRule(_Frozen):
    rule_id: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote: str = Field(min_length=1)
    figure: str = Field(min_length=1)
    applicability: str = Field(min_length=1)
    value: Decimal = Field(allow_inf_nan=False, ge=0)
    unit: RuleUnit
    requires_caller_opening_time: bool = False

    @model_validator(mode="after")
    def _figure_is_quoted(self) -> Self:
        if self.figure not in self.quote:
            raise ValueError("figure must appear in the cited quote")
        return self


class DeadlineRuleTable(_Frozen):
    schema_version: Literal[1]
    table_version: str = Field(min_length=1)
    sources: tuple[RuleSource, ...]
    rules: tuple[DeadlineRule, ...]
    rejected: tuple[str, ...] = ()

    def get(self, rule_id: str) -> DeadlineRule | None:
        return next((rule for rule in self.rules if rule.rule_id == rule_id), None)


class DeadlineAssessment(_Frozen):
    schema_version: Literal["atreides.deadline/0.1-experimental"] = (
        "atreides.deadline/0.1-experimental"
    )
    claim_label: Literal["EXPERIMENTAL"] = "EXPERIMENTAL"
    enforcement_status: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    disposition: Disposition
    due_at: AwareDatetime | None = None
    missing_rules: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    breaches: tuple[str, ...]
    evaluated_at: AwareDatetime
