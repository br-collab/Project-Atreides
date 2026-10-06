"""Versioned synthetic advisory document published for the Common Operating Picture.

The document is display input only. Every embedded result remains
``ADVISORY_ONLY`` and ``EXPERIMENTAL`` exactly as the engine emitted it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from atreides.customer_protection.advisory import CustomerProtectionAdvisory
from atreides.customer_protection.common import Frozen

__all__ = ["AdvisoryPublication", "AdvisoryScenario"]

OneLine = Annotated[str, Field(min_length=1)]
Advisories = Annotated[tuple[CustomerProtectionAdvisory, ...], Field(min_length=1)]
Scenarios = Annotated[tuple["AdvisoryScenario", ...], Field(min_length=1)]


class AdvisoryScenario(Frozen):
    """One named synthetic scenario and the advisories its real engine emitted."""

    scenario_id: str = Field(min_length=1)
    description: OneLine
    advisories: Advisories

    @field_validator("description")
    @classmethod
    def _description_is_one_line(cls, value: str) -> str:
        if value != value.strip() or "\n" in value or "\r" in value:
            raise ValueError("description must be one nonblank line without surrounding space")
        return value


class AdvisoryPublication(Frozen):
    """Closed wire document containing committed synthetic engine scenarios."""

    schema_version: Literal[1] = 1
    synthetic: Literal[True] = True
    taken_at: AwareDatetime
    scenarios: Scenarios

    @field_validator("taken_at")
    @classmethod
    def _taken_at_is_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("taken_at must be UTC")
        return value

    @model_validator(mode="after")
    def _scenario_ids_are_unique(self) -> Self:
        ids = tuple(scenario.scenario_id for scenario in self.scenarios)
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_id values must be unique")
        return self
