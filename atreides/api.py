"""Supported functional API for Project Atreides.

The implementation still contains doctrine-named agent classes for compatibility,
but callers should not have to construct them.  This module is the stable boundary:
functions accept the domain inputs and injected stores/registries, then delegate to
the existing deterministic implementations without changing their decisions.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cannae_kernel.halt import HaltContext

from atreides.acceptance import evaluate_candidate, prepare_instruction
from atreides.agents.tier1.investigation_outputs import (
    EvidenceGap,
    EvidenceItem,
    InvestigationOutput,
)
from atreides.agents.tier1.outputs import (
    RailAcknowledgment,
    SettlementOutput,
    SettlementTaskingRecord,
    SettlementTelemetry,
    SettlementValidation,
)
from atreides.agents.tier1.settlement_investigation_analyst import (
    SettlementInvestigationAnalyst,
)
from atreides.agents.tier1.settlement_operations_analyst import (
    SettlementOperationsAnalyst,
    validate_tasking,
)
from atreides.agents.tier2.fiat_operations_specialist import (
    FIATOperationsSpecialist,
    MagnitudeThresholdPolicy,
    PathSelectionRequest,
)
from atreides.agents.tier2.outputs import FIATOperationsOutput
from atreides.agents.tier2.routing_tables import (
    FinalityModel,
    RoutingTables,
    default_routing_tables,
)
from atreides.contracts import DSORLineageStub
from atreides.dsor import DSORRecord, DSORStore
from atreides.rails.cato_cash import evaluate as evaluate_cash_gate
from atreides.rails.funding_state import project_funding


def validate_settlement(
    tasking: SettlementTaskingRecord, *, halt: HaltContext | None = None
) -> SettlementValidation:
    """Evaluate the deterministic pre-routing settlement gates without effects."""
    return validate_tasking(tasking, halt=halt)


def run_settlement(
    tasking: SettlementTaskingRecord,
    store: DSORStore,
    *,
    now: datetime | None = None,
    halt: HaltContext | None = None,
) -> tuple[SettlementOutput, DSORRecord]:
    """Validate, emit and persist one settlement outcome."""
    return SettlementOperationsAnalyst().run(tasking, store, now=now, halt=halt)


def emit_settlement(
    tasking: SettlementTaskingRecord,
    validation: SettlementValidation,
    store: DSORStore,
    *,
    now: datetime | None = None,
    halt: HaltContext | None = None,
) -> tuple[SettlementOutput, DSORRecord]:
    """Emit and persist a previously validated settlement outcome."""
    return SettlementOperationsAnalyst().emit(
        tasking, validation, store, now=now, halt=halt
    )


def record_settlement_acknowledgment(
    record: DSORRecord,
    acknowledgment: RailAcknowledgment,
    store: DSORStore,
    *,
    now: datetime | None = None,
) -> tuple[SettlementTelemetry, DSORRecord]:
    """Append a verified rail acknowledgment as a correction record."""
    return SettlementOperationsAnalyst().record_rail_acknowledgment(
        record, acknowledgment, store, now=now
    )


def assemble_settlement_investigation(
    *,
    operation_id: UUID,
    task_id: UUID,
    lineage_stub: DSORLineageStub,
    observations: tuple[EvidenceItem, ...] | list[EvidenceItem],
    store: DSORStore,
    gaps: tuple[EvidenceGap, ...] | list[EvidenceGap] = (),
    now: datetime | None = None,
) -> tuple[InvestigationOutput, DSORRecord]:
    """Assemble and persist a deterministic evidence timeline or escalation."""
    return SettlementInvestigationAnalyst().run(
        operation_id=operation_id,
        task_id=task_id,
        lineage_stub=lineage_stub,
        observations=observations,
        gaps=gaps,
        store=store,
        now=now,
    )


def select_multi_currency_rail(
    request: PathSelectionRequest,
    *,
    currency: str,
    jurisdiction: str | None = None,
    finality_preference: FinalityModel | None = None,
    routing_tables: RoutingTables | None = None,
    magnitude_threshold_policy: MagnitudeThresholdPolicy | None = None,
) -> FIATOperationsOutput:
    """Select a pre-approved multi-currency rail or return a governed escalation."""
    service = FIATOperationsSpecialist(
        routing_tables=routing_tables or default_routing_tables(),
        magnitude_threshold_policy=(
            magnitude_threshold_policy or MagnitudeThresholdPolicy()
        ),
    )
    return service.select_multi_currency_rail_routing(
        request,
        currency=currency,
        jurisdiction=jurisdiction,
        finality_preference=finality_preference,
    )


__all__ = [
    "assemble_settlement_investigation",
    "emit_settlement",
    "evaluate_candidate",
    "evaluate_cash_gate",
    "prepare_instruction",
    "project_funding",
    "record_settlement_acknowledgment",
    "run_settlement",
    "select_multi_currency_rail",
    "validate_settlement",
]
