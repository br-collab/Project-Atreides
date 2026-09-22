"""DSOR record — immutable, DTG-stamped wrapper around any Aureon agent output.

Per AUR-CANONICAL-001 v1.6 Axiom 4 (One Lineage Record): the lineage
record is stamped at execution and never modified post-execution. A
correction is a new :class:`DSORRecord` with ``correction_of`` referencing
the original ``record_id``; the original record is preserved unchanged.

``record_id`` is independent of the embedded output's ``operation_id`` —
one operation may accumulate multiple records over its lifecycle (the
initial record plus one or more corrections). The ``correction_of``
pointer forms an auditable correction chain without mutating any record.

``SettlementDomainOutput`` is the unified discriminated union of every output
type that can be stored in the DSOR. The ``kind`` field on every output type
serves as the discriminator. It was called ``AureonOutput``, a name that
collided with Aureon's own outputs (CL-JUM-001 §5.3); ``AureonOutput`` remains
as a deprecated alias until Wave 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from atreides.acceptance.record import ObligationAcceptanceRecord
from atreides.agents.tier1.investigation_outputs import (
    EvidenceTimeline,
    InvestigationEscalation,
)
from atreides.agents.tier1.outputs import SettlementEscalation, SettlementTelemetry
from atreides.agents.tier2.outputs import (
    EscalationRequired,
    QuorumAuthorityRequired,
    RoutingDecision,
)
from atreides.dsor.lifecycle_records import (
    FinalityAssertedRecord,
    HaltRecord,
    InstructionPreparedRecord,
    RailStatusObservedRecord,
    ReconciliationResultRecord,
)
from atreides.rails.cato_cash_record import CatoCashDecisionRecord

SettlementDomainOutput = (
    RoutingDecision | EscalationRequired | QuorumAuthorityRequired
    | SettlementTelemetry | SettlementEscalation
    | EvidenceTimeline | InvestigationEscalation
    | CatoCashDecisionRecord | ObligationAcceptanceRecord | HaltRecord
    | InstructionPreparedRecord | RailStatusObservedRecord
    | FinalityAssertedRecord | ReconciliationResultRecord
)

#: Deprecated until Wave 3: use ``SettlementDomainOutput``.
AureonOutput = SettlementDomainOutput

RecordKind = Literal[
    "routing_decision",
    "escalation_required",
    "quorum_authority_required",
    "settlement_telemetry",
    "settlement_escalation",
    "evidence_timeline",
    "investigation_escalation",
    "cash_gate_decision",
    "obligation_acceptance",
    "halt_context",
    "instruction_prepared",
    "rail_status_observed",
    "finality_asserted",
    "reconciliation_result",
]


class DSORRecord(BaseModel):
    """Immutable DSOR record wrapping one :data:`SettlementDomainOutput`.

    Assembled by :meth:`assemble` at record-creation time. The model is
    frozen and extra-forbid to guarantee the immutability invariant at the
    Pydantic layer — no field may be set after construction.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    record_id: UUID = Field(
        default_factory=uuid4,
        description=(
            "Unique record identifier. Independent of the embedded output's "
            "operation_id — a correction for the same operation gets a new "
            "record_id."
        ),
    )
    dtg: datetime = Field(
        description="UTC DTG stamp at record assembly time.",
    )
    kind: RecordKind = Field(
        description="Discriminator matching output.kind.",
    )
    output: SettlementDomainOutput = Field(
        description="The agent output this record wraps.",
    )
    correction_of: UUID | None = Field(
        default=None,
        description=(
            "record_id of the record this corrects. The original is preserved "
            "unchanged per Axiom 4 (immutable lineage). None for initial records."
        ),
    )

    @classmethod
    def assemble(
        cls,
        output: SettlementDomainOutput,
        dtg: datetime,
        correction_of: UUID | None = None,
    ) -> DSORRecord:
        """Assemble a new :class:`DSORRecord` from a :data:`SettlementDomainOutput`."""
        return cls(
            dtg=dtg,
            kind=output.kind,
            output=output,
            correction_of=correction_of,
        )


__all__ = ["AureonOutput", "DSORRecord", "RecordKind", "SettlementDomainOutput"]
