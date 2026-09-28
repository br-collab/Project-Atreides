"""Contract tests for the activation snapshot writer.

The reader models below are copied from L.C. ``cop/agents.py`` at ``ae76aa7``.
Atreides must not import the consumer package merely to prove the wire shape.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from cannae_kernel.absence import Absent, Recorded
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

from atreides.activation.snapshot_writer import write_snapshot

SUPPORTED_SCHEMA_VERSION = 1


class ReaderRefusalView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    code: str
    detail: str
    observed_at: datetime


class ReaderAgentView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    agent_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    role: str = Field(min_length=1)
    up: bool
    expects_refusal: bool
    disposition: Disposition
    stopped_reason: Recorded[str] | Absent
    last_summary: Recorded[str] | Absent
    last_observed_at: Recorded[datetime] | Absent
    last_provenance: Recorded[Provenance] | Absent
    last_handoff_basis: Recorded[str] | Absent
    last_refusal: Recorded[ReaderRefusalView] | Absent
    recommendations: int = Field(ge=0)
    refusals: int = Field(ge=0)


class ReaderAgentsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    schema_version: int
    phase: str = Field(min_length=1)
    synthetic: bool
    taken_at: datetime
    tick: Recorded[int] | Absent
    last_tick_at: Recorded[datetime] | Absent
    halted: bool
    halt_reason: Recorded[str] | Absent
    disposition: Disposition
    agents: tuple[ReaderAgentView, ...]


def parse_as_lc(raw: bytes) -> ReaderAgentsSnapshot:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("activation snapshot is not an object")
    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError("unsupported activation snapshot schema version")
    return ReaderAgentsSnapshot.model_validate_json(raw)


def test_writer_round_trips_through_lc_shape_without_losing_absence(
    tmp_path: Path, at: datetime
) -> None:
    output = tmp_path / "agents.json"
    write_snapshot(output, taken_at=at)

    parsed = parse_as_lc(output.read_bytes())

    assert parsed.schema_version == 1
    assert parsed.taken_at == at
    probe = next(agent for agent in parsed.agents if agent.agent_id == "lateral-handoff-probe")
    assert probe.expects_refusal is True
    assert isinstance(probe.last_refusal, Recorded)
    for agent in parsed.agents:
        assert isinstance(agent.stopped_reason, Absent)
        assert agent.stopped_reason.reason


def test_lc_shape_rejects_a_mutated_schema_version(tmp_path: Path, at: datetime) -> None:
    output = tmp_path / "agents.json"
    write_snapshot(output, taken_at=at)
    document = json.loads(output.read_bytes())
    document["schema_version"] = 2

    with pytest.raises(ValueError, match="unsupported"):
        parse_as_lc(json.dumps(document).encode())
