"""Closed synthetic break snapshot published for the display-only COP."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from cannae_kernel.canonical import Digest, digest_bytes
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from atreides.cockpit.breaks import BreakRecord

__all__ = ["BreaksPublication", "records_digest"]

Records = Annotated[tuple[BreakRecord, ...], Field(min_length=1)]


def records_digest(records: tuple[BreakRecord, ...]) -> Digest:
    """Digest the exact records in stable break identifier order."""
    ordered = sorted(records, key=lambda record: record.break_id)
    return digest_bytes(b"".join(record.canonical_bytes() for record in ordered))


class BreaksPublication(BaseModel):
    """A complete, tamper-evident synthetic break-register snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    synthetic: Literal[True] = True
    enforcement_status: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    claim_label: Literal["EXPERIMENTAL"] = "EXPERIMENTAL"
    complete: Literal[True] = True
    taken_at: AwareDatetime
    input_digest: Digest
    records: Records

    @field_validator("taken_at")
    @classmethod
    def _taken_at_is_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("taken_at must be UTC")
        return value

    @model_validator(mode="after")
    def _unique_and_intact(self) -> Self:
        ids = tuple(record.break_id for record in self.records)
        if len(ids) != len(set(ids)):
            raise ValueError("break_id values must be unique")
        if self.input_digest != records_digest(self.records):
            raise ValueError("input_digest does not match the published break records")
        return self
