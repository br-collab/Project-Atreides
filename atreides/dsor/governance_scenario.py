"""Decision System of Record evidence for synthetic governance scenarios."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from cannae_kernel.governance import ActionClass, AutonomyLevel
from pydantic import BaseModel, ConfigDict, Field


class GovernanceScenarioEvidence(BaseModel):
    """One immutable observation or controlled response from SIM-1."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["governance_scenario"] = "governance_scenario"
    operation_id: UUID
    scenario: Literal["G1", "G2", "G3"]
    stage: str = Field(min_length=1)
    observed_at: datetime
    autonomy_level: AutonomyLevel
    action_class: ActionClass
    result: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    model_version: str | None = None


__all__ = ["GovernanceScenarioEvidence"]
