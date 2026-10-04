"""The DSOR record of one customer protection computation, and its replay check.

EXPERIMENTAL (charter section 18.6). The advisory inside every record is
ADVISORY_ONLY: it enforces nothing, and no Aureon consumer reads it.

WHAT IS RECORDED
----------------
Every computation is written to the DSOR (Decision System of Record) as one
:class:`CustomerProtectionComputationRecord` of kind
``customer_protection_computation``: the inputs exactly as given, the result
exactly as computed, the version of every rule source read, the rule table's
version and digest, and the advisory. Nothing is recorded by reference only,
so the record alone is enough to recompute the result.

THE DIRECTION OF THE IMPORT
---------------------------
:mod:`atreides.dsor.record` imports this module to admit the record into its
closed ``SettlementDomainOutput`` union. This package never imports the DSOR,
which keeps the dependency one way and the import graph acyclic.

REPLAY
------
:func:`verify_replay` re-runs the engine on the recorded inputs against a rule
table and compares, byte for byte in canonical form, the recomputed result and
advisory with the recorded ones. A stored record that has been altered fails.
A rule table other than the one recorded cannot confirm or refute the record,
so the answer is INDETERMINATE rather than a false failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from cannae_kernel.canonical import Digest, canonical_bytes, digest
from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import Field, field_validator

from atreides.customer_protection.advisory import (
    ENFORCEMENT_STATUS,
    CustomerProtectionAdvisory,
    advise,
)
from atreides.customer_protection.challenger import ChallengerInputs, ChallengerReport, challenge
from atreides.customer_protection.common import Frozen
from atreides.customer_protection.control import (
    ControlInputs,
    ControlResult,
    check_possession_or_control,
)
from atreides.customer_protection.net_capital import (
    NetCapitalInputs,
    NetCapitalResult,
    compute_net_capital,
)
from atreides.customer_protection.reserve import ReserveInputs, ReserveResult, compute_reserve
from atreides.customer_protection.rules.model import (
    CLAIM_LABEL,
    DTG_PATTERN,
    RuleTable,
    RuleVersion,
)

__all__ = [
    "ChallengerComputation",
    "Computation",
    "ControlComputation",
    "CustomerProtectionComputationRecord",
    "NetCapitalComputation",
    "ReplayVerification",
    "ReserveComputation",
    "compute",
    "record_computation",
    "verify_replay",
]


class ReserveComputation(Frozen):
    """A reserve formula computation: what went in and what came out."""

    engine: Literal["reserve"] = "reserve"
    inputs: ReserveInputs
    result: ReserveResult


class NetCapitalComputation(Frozen):
    """A net capital computation: what went in and what came out."""

    engine: Literal["net_capital"] = "net_capital"
    inputs: NetCapitalInputs
    result: NetCapitalResult


class ControlComputation(Frozen):
    """A possession or control check: what went in and what came out."""

    engine: Literal["possession_or_control"] = "possession_or_control"
    inputs: ControlInputs
    result: ControlResult


class ChallengerComputation(Frozen):
    """A challenger comparison: the engine's and the vendor's figures, and the report."""

    engine: Literal["challenger"] = "challenger"
    inputs: ChallengerInputs
    result: ChallengerReport


Computation = Annotated[
    ReserveComputation | NetCapitalComputation | ControlComputation | ChallengerComputation,
    Field(discriminator="engine"),
]
_Inputs = ReserveInputs | NetCapitalInputs | ControlInputs | ChallengerInputs
_Computation = (
    ReserveComputation | NetCapitalComputation | ControlComputation | ChallengerComputation
)


class CustomerProtectionComputationRecord(Frozen):
    """DSOR output for one computation. Its advisory is ADVISORY_ONLY and enforces nothing."""

    kind: Literal["customer_protection_computation"] = "customer_protection_computation"
    schema_version: Literal["0.1-draft"] = "0.1-draft"
    #: The record's own identifier, and the DSOR store's record subject.
    operation_id: UUID
    #: When the record was assembled, as a DTG (date-time group), UTC, ``YYYYMMDDHHMM``.
    recorded_dtg: str = Field(pattern=DTG_PATTERN)
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    enforcement_status: Literal["ADVISORY_ONLY"] = ENFORCEMENT_STATUS
    rule_table_version: str
    rule_table_digest: Digest
    rule_versions: tuple[RuleVersion, ...]
    computation: Computation
    advisory: CustomerProtectionAdvisory


class ReplayVerification(Frozen):
    """Whether a recorded computation recomputes to exactly what was recorded."""

    operation_id: UUID
    disposition: Disposition
    verified: bool
    findings: tuple[str, ...]

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)


def compute(inputs: _Inputs, table: RuleTable) -> _Computation:
    """Run the engine the inputs belong to. The challenger compares; it reads no rules."""
    if isinstance(inputs, ChallengerInputs):
        return ChallengerComputation(inputs=inputs, result=challenge(inputs))
    if isinstance(inputs, ReserveInputs):
        return ReserveComputation(inputs=inputs, result=compute_reserve(inputs, table))
    if isinstance(inputs, NetCapitalInputs):
        return NetCapitalComputation(inputs=inputs, result=compute_net_capital(inputs, table))
    return ControlComputation(inputs=inputs, result=check_possession_or_control(inputs, table))


def record_computation(
    inputs: _Inputs,
    table: RuleTable,
    *,
    operation_id: UUID,
    recorded_at: datetime,
) -> CustomerProtectionComputationRecord:
    """Compute, advise, and assemble the DSOR record. Pure: the caller supplies id and time."""
    computation = compute(inputs, table)
    advisory = advise(inputs, computation.result, table)
    return CustomerProtectionComputationRecord(
        operation_id=operation_id,
        recorded_dtg=recorded_at.astimezone(UTC).strftime("%Y%m%d%H%M"),
        rule_table_version=table.table_version,
        rule_table_digest=table.table_digest,
        rule_versions=advisory.rule_versions,
        computation=computation,
        advisory=advisory,
    )


def verify_replay(
    record: CustomerProtectionComputationRecord, table: RuleTable
) -> ReplayVerification:
    """Recompute ``record`` against ``table`` and compare it, byte for byte, with what is stored."""
    findings: list[str] = []
    if record.rule_table_digest != table.table_digest:
        return ReplayVerification(
            operation_id=record.operation_id,
            disposition=Disposition.INDETERMINATE,
            verified=False,
            findings=(
                f"recorded against rule table {record.rule_table_digest}, "
                f"offered {table.table_digest}: replay cannot confirm or refute it",
            ),
        )
    inputs = record.computation.inputs
    recomputed = compute(inputs, table)
    advisory = advise(inputs, recomputed.result, table)
    if canonical_bytes(recomputed.result) != canonical_bytes(record.computation.result):
        findings.append("the recorded result is not what the recorded inputs compute to")
    if digest(inputs) != record.advisory.input_digest:
        findings.append("the recorded inputs do not match the advisory's input digest")
    if digest(record.computation.result) != record.advisory.result_digest:
        findings.append("the recorded result does not match the advisory's result digest")
    if canonical_bytes(advisory) != canonical_bytes(record.advisory):
        findings.append("the recorded advisory is not the advisory the computation gives")
    if record.rule_versions != advisory.rule_versions:
        findings.append("the recorded rule versions are not the ones the computation read")
    verified = not findings
    return ReplayVerification(
        operation_id=record.operation_id,
        disposition=Disposition.PASS if verified else Disposition.HOLD,
        verified=verified,
        findings=tuple(findings),
    )
