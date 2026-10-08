"""Deterministic, advisory-only traceability evidence from a pytest run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from atreides.traceability.register import RequirementRegister

__all__ = [
    "RequirementEvidence",
    "RunScope",
    "TestOutcome",
    "TraceStatus",
    "TraceabilityDocument",
    "build_traceability",
    "traceability_digest",
    "write_traceability",
]


class TraceStatus(StrEnum):
    """Fail-closed status of one requirement in one test run."""

    COVERED = "COVERED"
    UNTESTED = "UNTESTED"
    FAILING = "FAILING"
    NOT_RUN = "NOT_RUN"


class TestOutcome(StrEnum):
    """Observed terminal outcome of one collected marked test."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class RunScope(StrEnum):
    """Whether pytest was invoked for the complete repository or a subset."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RequirementEvidence(_Frozen):
    requirement_id: str
    status: TraceStatus
    test_node_ids: tuple[str, ...]


class TraceabilityDocument(_Frozen):
    """Published shape produced from a complete pytest session."""

    schema_version: Literal[1] = 1
    synthetic: Literal[True] = True
    enforcement_status: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    claim_label: Literal["EXPERIMENTAL"] = "EXPERIMENTAL"
    run_scope: RunScope
    run_commit_sha: str
    run_timestamp: str
    requirements: tuple[RequirementEvidence, ...]
    digest: str


def _status(outcomes: Iterable[TestOutcome]) -> TraceStatus:
    observed = tuple(outcomes)
    if not observed:
        return TraceStatus.UNTESTED
    if TestOutcome.FAILED in observed:
        return TraceStatus.FAILING
    if TestOutcome.NOT_RUN in observed:
        return TraceStatus.NOT_RUN
    return TraceStatus.COVERED


def _digest(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _document_payload(document: TraceabilityDocument) -> dict[str, object]:
    return {
        "schema_version": document.schema_version,
        "synthetic": document.synthetic,
        "enforcement_status": document.enforcement_status,
        "claim_label": document.claim_label,
        "run_scope": document.run_scope.value,
        "run_commit_sha": document.run_commit_sha,
        "run_timestamp": document.run_timestamp,
        "requirements": [row.model_dump(mode="json") for row in document.requirements],
    }


def traceability_digest(document: TraceabilityDocument) -> str:
    """Recompute the digest over every field except the digest itself."""
    return _digest(_document_payload(document))


def build_traceability(
    register: RequirementRegister,
    node_requirements: Mapping[str, Iterable[str]],
    outcomes: Mapping[str, TestOutcome],
    *,
    run_scope: RunScope,
    run_commit_sha: str,
    run_timestamp: str,
) -> TraceabilityDocument:
    """Build a stable document from collected markers and observed outcomes."""
    nodes_by_requirement: dict[str, list[str]] = {
        requirement.requirement_id: [] for requirement in register.requirements
    }
    for node_id, requirement_ids in node_requirements.items():
        for requirement_id in requirement_ids:
            nodes_by_requirement[requirement_id].append(node_id)

    evidence = tuple(
        RequirementEvidence(
            requirement_id=requirement_id,
            status=_status(
                outcomes.get(node_id, TestOutcome.NOT_RUN) for node_id in sorted(node_ids)
            ),
            test_node_ids=tuple(sorted(node_ids)),
        )
        for requirement_id, node_ids in sorted(nodes_by_requirement.items())
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "synthetic": True,
        "enforcement_status": "ADVISORY_ONLY",
        "claim_label": "EXPERIMENTAL",
        "run_scope": run_scope.value,
        "run_commit_sha": run_commit_sha,
        "run_timestamp": run_timestamp,
        "requirements": [row.model_dump(mode="json") for row in evidence],
    }
    return TraceabilityDocument(
        run_scope=run_scope,
        run_commit_sha=run_commit_sha,
        run_timestamp=run_timestamp,
        requirements=evidence,
        digest=_digest(payload),
    )


def write_traceability(path: Path, document: TraceabilityDocument) -> None:
    """Write one complete JSON document, replacing no file until serialization succeeds."""
    content = document.model_dump_json(indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
