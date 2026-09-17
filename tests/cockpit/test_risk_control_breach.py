"""ATR-I-07 regression: a declared risk-control breach always breaks and escalates.

Before Wave 2 the cockpit ingested ``risk_control_status`` and never read it,
so a readback reporting BREACHED with every amount matching reconciled clean
(stress case H7.5). Fixed in W2A-1: a typed ``RISK_CONTROL`` break plus an
escalation in the cockpit's register.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail
from atreides.cockpit import BreakLeg, ClearingCockpit, PortalRegime
from atreides.contracts.dsor_stub import CAOMTier
from atreides.escalation import EscalationRegister

D = Decimal


def _cycle(cockpit: ClearingCockpit, status: str | None):  # type: ignore[no-untyped-def]
    t = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 19, tzinfo=UTC),
        authority_id="OP-1",
        authority_tier=CAOMTier.T1,
        net_delivery_quantity=D("1000"),
        net_payment_amount=D("1000000"),
        ficc_published_net_delivery=D("1000"),
    )
    gate = cockpit.run_validation_gates(t)
    pkg = cockpit.emit_instruction_package(t, gate)
    rb = cockpit.ingest_portal_readback(
        operation_id=t.operation_id,
        regime=PortalRegime.CCP,
        position_balance=D("1000"),
        ccp_net_obligation=D("1000000"),
        risk_control_status=status,
    )
    return t, gate, cockpit.reconcile_expected_actual(pkg, rb)


def test_stress_h7_5_breach_with_matching_amounts_breaks_and_escalates() -> None:
    register = EscalationRegister()
    cockpit = ClearingCockpit(escalation_register=register)
    t, gate, recon = _cycle(cockpit, "BREACHED")
    assert not recon.matched
    assert recon.breaks == (BreakLeg.RISK_CONTROL,)
    assert recon.detail["risk_control"] == {"status": "BREACHED"}
    assert cockpit.escalations is register
    (escalation,) = register.raised
    assert recon.escalation_ids == (escalation.escalation_id,)
    assert escalation.operation_id == t.operation_id
    assert escalation.routed_to == "authority_tier:T1"
    assert "ATR-I-07" in escalation.reason
    assert escalation.raised_at_offset_seconds >= 0
    tickets = cockpit.raise_break(recon, gate.dsor_pre_trade_record_id)
    assert [(tk.leg, tk.detail) for tk in tickets] == [
        (BreakLeg.RISK_CONTROL, '{"status": "BREACHED"}')
    ]


@pytest.mark.parametrize("status", ["breached", " Breached ", "BREACHED\n"])
def test_misspelt_breach_still_breaks(status: str) -> None:
    _, _, recon = _cycle(ClearingCockpit(), status)
    assert recon.breaks == (BreakLeg.RISK_CONTROL,)
    assert len(recon.escalation_ids) == 1


@pytest.mark.parametrize("status", [None, "WITHIN_LIMITS", ""])
def test_no_breach_reported_means_no_risk_control_break(status: str | None) -> None:
    cockpit = ClearingCockpit()
    _, _, recon = _cycle(cockpit, status)
    assert recon.matched
    assert recon.escalation_ids == ()
    assert len(cockpit.escalations) == 0


def test_each_breach_raises_its_own_escalation() -> None:
    cockpit = ClearingCockpit()
    first = _cycle(cockpit, "BREACHED")[2]
    second = _cycle(cockpit, "BREACHED")[2]
    assert first.escalation_ids != second.escalation_ids
    assert len(cockpit.escalations) == 2
