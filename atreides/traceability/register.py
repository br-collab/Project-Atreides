"""Closed schema and loader for the requirement-to-evidence register."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AutomationLevel",
    "CriticalityTier",
    "Requirement",
    "RequirementRegister",
    "TextSource",
    "load_register",
]

AutomationLevel = Annotated[int, Field(ge=1, le=6)]
CriticalityTier = Annotated[int, Field(ge=0, le=3)]


class TextSource(StrEnum):
    """Whether the cited source contains actual requirement text."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Requirement(_Frozen):
    """One sourced requirement or explicitly text-absent source identifier."""

    requirement_id: str = Field(pattern=r"^(?:BR|TR|NF)-\d{2}$|^SC-[RMPG]-\d{2}$")
    title: str = Field(min_length=1)
    source_document: str = Field(min_length=1)
    source_clause: str = Field(min_length=1)
    text_source: TextSource
    criticality_tier: CriticalityTier | None
    automation_level: AutomationLevel | None
    control_objective: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)


class RequirementRegister(_Frozen):
    """The complete frozen input register used by later trace generation."""

    schema_version: Literal[1] = 1
    synthetic: Literal[True] = True
    enforcement_status: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    claim_label: Literal["EXPERIMENTAL"] = "EXPERIMENTAL"
    requirements: tuple[Requirement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        ids = tuple(row.requirement_id for row in self.requirements)
        if len(ids) != len(set(ids)):
            raise ValueError("requirement_id values must be unique")
        return self

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(row.requirement_id for row in self.requirements)


def load_register(path: Path) -> RequirementRegister:
    """Load and strictly validate the complete JSON register."""
    return RequirementRegister.model_validate_json(path.read_bytes())
