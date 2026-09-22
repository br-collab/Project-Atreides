"""The Cato Cash decision as a decision of record (ATR-I-04; stress case E7.5).

Cato Cash is pure and writes nothing, by architectural contract. Before Wave 2
that left its output with no supported type in the DSOR: nothing in the
output union could carry a gate decision, so the cash gate's own verdict could
not be stored or replayed.

:class:`CatoCashDecisionRecord` carries every input ``evaluate()`` took and the
decision it returned. :meth:`CatoCashDecisionRecord.replay` re-runs the gate on
the recorded inputs; a record whose replay differs from its decision either
was tampered with or was evaluated under a different gate-set version, and
:meth:`CatoCashDecisionRecord.reproduces` says which.

Store subject
-------------
The DSOR store allows one original record per ``operation_id``. A settlement
operation already has its telemetry or escalation, so a gate decision cannot
use the operation's id without colliding. ``operation_id`` here is the
decision's own identifier, supplied by the application service that records
it; the governed operation is ``settlement_operation_id``.

PURE, NO I/O: building and replaying a record touch no store. Writing it is
the caller's (an application service's) job: ``store.append(record)``.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import LifecycleId
from pydantic import BaseModel, ConfigDict, Field

from atreides.rails.cato_cash import (
    GATE_SET_VERSION,
    CashRail,
    CatoCashDecision,
    FreshnessPolicy,
    FundingState,
    OperationContext,
    RailState,
    evaluate,
)

__all__ = ["CASH_GATE_DECISION_SCHEMA", "CatoCashDecisionRecord"]

CASH_GATE_DECISION_SCHEMA: Literal["cash_gate_decision/0.1"] = "cash_gate_decision/0.1"


class CatoCashDecisionRecord(BaseModel):
    """A Cato Cash decision with the inputs that produced it. Replayable."""

    # NaN and infinite stress readings are inputs the gate names explicitly
    # (STRESS_READING_UNUSABLE); they must survive JSON to replay.
    model_config = ConfigDict(frozen=True, extra="forbid", ser_json_inf_nan="strings")

    kind: Literal["cash_gate_decision"] = "cash_gate_decision"
    schema_version: Literal["cash_gate_decision/0.1"] = CASH_GATE_DECISION_SCHEMA
    #: The decision's own identifier; the DSOR store's record subject.
    operation_id: UUID
    #: The settlement operation the decision governs, where there is one.
    settlement_operation_id: UUID | None = None
    #: The lifecycle the governed obligation belongs to, for journalling.
    lifecycle_id: LifecycleId | None = None

    # -- Inputs to evaluate(), exactly as supplied --------------------------
    operation: OperationContext
    funding: FundingState
    rails: dict[CashRail, RailState]
    ofr_stlfsi4: float
    dsor_lineage_uri: str | None = None
    stress_reading_age_seconds: int | None = None
    freshness_policy: FreshnessPolicy | None = None
    obligation_id: str | None = None
    obligation_digest: str | None = None
    halt: HaltContext | None = None

    # -- Output --------------------------------------------------------------
    decision: CatoCashDecision
    gate_set_version: str = Field(default=GATE_SET_VERSION, min_length=1)

    @classmethod
    def capture(
        cls,
        *,
        decision_id: UUID,
        operation: OperationContext,
        funding: FundingState,
        rails: dict[CashRail, RailState],
        ofr_stlfsi4: float,
        settlement_operation_id: UUID | None = None,
        lifecycle_id: str | None = None,
        dsor_lineage_uri: str | None = None,
        stress_reading_age_seconds: int | None = None,
        freshness_policy: FreshnessPolicy | None = None,
        obligation_id: str | None = None,
        obligation_digest: str | None = None,
        halt: HaltContext | None = None,
    ) -> CatoCashDecisionRecord:
        """Evaluate the gate and package inputs and decision together."""
        inputs = {
            "operation": operation,
            "funding": funding,
            "rails": rails,
            "ofr_stlfsi4": ofr_stlfsi4,
            "dsor_lineage_uri": dsor_lineage_uri,
            "stress_reading_age_seconds": stress_reading_age_seconds,
            "freshness_policy": freshness_policy,
            "obligation_id": obligation_id,
            "obligation_digest": obligation_digest,
            "halt": halt,
        }
        return cls(
            operation_id=decision_id,
            settlement_operation_id=settlement_operation_id,
            lifecycle_id=lifecycle_id,
            decision=evaluate(**inputs),  # type: ignore[arg-type]
            **inputs,
        )

    def replay(self) -> CatoCashDecision:
        """Re-run the gate on the recorded inputs. Pure."""
        return evaluate(
            operation=self.operation,
            funding=self.funding,
            rails=dict(self.rails),
            ofr_stlfsi4=self.ofr_stlfsi4,
            dsor_lineage_uri=self.dsor_lineage_uri,
            stress_reading_age_seconds=self.stress_reading_age_seconds,
            freshness_policy=self.freshness_policy,
            obligation_id=self.obligation_id,
            obligation_digest=self.obligation_digest,
            halt=self.halt,
        )

    def reproduces(self) -> bool | None:
        """True when replay reproduces the recorded decision.

        ``None`` when the record was made under a different gate-set version:
        a mismatch then is not evidence of tampering, and a match is not
        evidence of anything either.
        """
        if self.gate_set_version != GATE_SET_VERSION:
            return None
        return self.replay() == self.decision
