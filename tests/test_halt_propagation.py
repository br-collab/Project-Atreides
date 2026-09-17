"""ATR-I-06 regression: one halt context, honoured by every layer that could proceed.

Before Wave 2 the Tier 0 halt was a predicate the cockpit consulted at its own
primitives only: CATO-F had no halt parameter and returned PROCEED with the
cockpit halted (stress case H6.2). W2A-3 passes the kernel ``HaltContext``
through CATO-F, the Tier 1 analyst, the preparation stage and the cockpit
(the Tier 2 specialist is covered in its own test module), and the cockpit's
``halt_check`` now produces that context rather than being a second mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import ActorId, HaltId

from atreides.agents.tier1.outputs import (
    DiscrepancyCode,
    SettlementEscalation,
    SettlementKind,
    SettlementRail,
)
from atreides.agents.tier1.settlement_operations_analyst import (
    SettlementOperationsAnalyst,
    validate_tasking,
)
from atreides.cockpit import ClearingCockpit, CockpitHalted, PortalRegime
from atreides.cockpit.clearing_cockpit import TIER0_HALT_ID, tier0_halt_context
from atreides.contracts.dsor_stub import CAOMTier
from atreides.dsor import DSORStore
from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import PreparationHaltedError, emit_instruction_artifact
from atreides.rails.cato_f import (
    CashRail,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)

T = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
D = Decimal


def _halt(
    *, active: bool = True, scope: Any = "ALL", kind: ActorKind = ActorKind.HUMAN
) -> HaltContext:
    return HaltContext(
        halt_id=HaltId("hlt_" + "2" * 26),
        version=2,
        active=active,
        scope=scope,
        declared_by=ActorRef(
            actor_id=ActorId("act_" + "2" * 26),
            actor_kind=kind,
            role="operator",
            entitlement_refs=(),
            authenticated=True,
        ),
        declared_at=T,
        reason="rail emulator unavailable",
    )


BLOCKING = [_halt(), _halt(scope=(Domain.ATREIDES,)), _halt(scope=(Domain.LC, Domain.ATREIDES))]
NOT_BLOCKING = [_halt(active=False), _halt(scope=(Domain.AUREON, Domain.LC))]


# ---- CATO-F ---------------------------------------------------------------------------------


def _gate(halt: HaltContext | None) -> Any:
    return evaluate(
        operation=OperationContext(
            notional=D("1000000"), currency="USD", is_material=False, is_lvps_material=False
        ),
        funding=FundingState(D("5000000"), D("1000000"), D("10000000"), True),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=0.0,
        halt=halt,
    )


@pytest.mark.parametrize("halt", BLOCKING)
def test_stress_h6_2_gate_holds_under_a_halt_covering_atreides(halt: HaltContext) -> None:
    decision = _gate(halt)
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.HALT_ACTIVE
    assert decision.checks_evaluated == (("halt", f"active:{halt.halt_id}:v{halt.version}"),)


@pytest.mark.parametrize("halt", [None, *NOT_BLOCKING])
def test_gate_is_unaffected_by_a_halt_that_does_not_cover_atreides(
    halt: HaltContext | None,
) -> None:
    decision = _gate(halt)
    assert decision.decision is GateDecision.PROCEED
    assert decision.checks_evaluated[0][0] == "halt"


# ---- Tier 1 ---------------------------------------------------------------------------------


def _cockpit_record(cockpit: ClearingCockpit) -> Any:
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=T,
        authority_id="OP-1",
        authority_tier=CAOMTier.T1,
        net_delivery_quantity=D("1000"),
        net_payment_amount=D("1000000"),
        ficc_published_net_delivery=D("1000"),
    )
    return tasking, cockpit._tasking_record(tasking)


@pytest.mark.parametrize("halt", BLOCKING)
def test_tier1_validation_holds_under_a_halt(halt: HaltContext) -> None:
    _, record = _cockpit_record(ClearingCockpit())
    validation = validate_tasking(record, halt=halt)
    assert not validation.passed
    assert validation.discrepancy_code is DiscrepancyCode.HALT_ACTIVE
    assert validation.checks_evaluated == ("halt",)


def test_tier1_emission_under_a_halt_persists_an_escalation_not_telemetry() -> None:
    _, record = _cockpit_record(ClearingCockpit())
    passed_before_halt = validate_tasking(record)
    assert passed_before_halt.passed
    store = DSORStore(":memory:")
    output, _ = SettlementOperationsAnalyst().emit(record, passed_before_halt, store, halt=_halt())
    assert isinstance(output, SettlementEscalation)
    assert output.discrepancy_code is DiscrepancyCode.HALT_ACTIVE
    run_output, _ = SettlementOperationsAnalyst().run(
        _cockpit_record(ClearingCockpit())[1], DSORStore(":memory:"), halt=_halt()
    )
    assert isinstance(run_output, SettlementEscalation)


@pytest.mark.parametrize("halt", NOT_BLOCKING)
def test_tier1_is_unaffected_by_a_halt_that_does_not_cover_atreides(halt: HaltContext) -> None:
    _, record = _cockpit_record(ClearingCockpit())
    assert validate_tasking(record, halt=halt).passed


# ---- Preparation stage ----------------------------------------------------------------------


def _instruction() -> CashLegInstruction:
    return CashLegInstruction(
        message_id="AUR20260917000001",
        end_to_end_id="E2E-0001",
        created_at=T,
        amount=D("1000000.00"),
        currency="USD",
        debtor=FinancialInstitution("DDDDUS33"),
        creditor=FinancialInstitution("EEEEUS33"),
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=FinancialInstitution("DDDDUS33"),
        receiver=FinancialInstitution("FFFFUS33"),
    )


def test_preparation_refuses_under_a_halt_and_proceeds_otherwise() -> None:
    with pytest.raises(PreparationHaltedError, match="ATR-I-06"):
        emit_instruction_artifact(_instruction(), halt=_halt())
    assert (
        emit_instruction_artifact(_instruction(), halt=_halt(active=False)).is_submission is False
    )


# ---- Cockpit --------------------------------------------------------------------------------


def test_cockpit_halt_context_refuses_every_primitive() -> None:
    state: dict[str, HaltContext | None] = {"halt": None}
    cockpit = ClearingCockpit(halt=lambda: state["halt"])
    tasking, _ = _cockpit_record(cockpit)
    gate = cockpit.run_validation_gates(tasking)
    pkg = cockpit.emit_instruction_package(tasking, gate)
    rb = cockpit.ingest_portal_readback(operation_id=tasking.operation_id, regime=PortalRegime.CCP)
    recon = cockpit.reconcile_expected_actual(pkg, rb)

    state["halt"] = _halt(scope=(Domain.ATREIDES,))
    assert cockpit.current_halt() == state["halt"]
    for call in (
        lambda: cockpit.run_validation_gates(tasking),
        lambda: cockpit.emit_instruction_package(tasking, gate),
        lambda: cockpit.ingest_portal_readback(
            operation_id=tasking.operation_id, regime=PortalRegime.CCP
        ),
        lambda: cockpit.reconcile_expected_actual(pkg, rb),
        lambda: cockpit.raise_break(recon, pkg.dsor_record_id),
    ):
        with pytest.raises(CockpitHalted, match="ATR-I-06"):
            call()

    state["halt"] = _halt(scope=(Domain.AUREON,))
    assert cockpit.current_halt() is None
    cockpit.run_validation_gates(tasking)


def test_legacy_halt_check_produces_the_kernel_context() -> None:
    cockpit = ClearingCockpit(halt_check=lambda: True)
    ctx = cockpit.current_halt()
    assert ctx is not None
    assert ctx.halt_id == TIER0_HALT_ID
    assert ctx.scope == "ALL"
    assert ctx.declared_by.actor_kind is ActorKind.DETERMINISTIC_SERVICE
    assert tier0_halt_context(T).declared_at == T
    assert ClearingCockpit(halt_check=lambda: False).current_halt() is None
