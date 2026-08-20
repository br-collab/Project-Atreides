"""Tests for the Clearing Operator Cockpit (AUR-COCKPIT-001 v0.1).

Covers the six primitives, the full five-beat cycle, and — most
importantly — the cardinal doctrinal boundaries:

  * never submits / no submission object is constructible
  * never holds credentials (no credential field on any model)
  * CCP and CSD contexts stay separate (never flattened)
  * a held gate emits no package
  * material magnitude HOLDS for quorum under CAOM-001 (no package)
  * Tier 0 Halt propagates across every primitive
  * reconciliation classifies breaks by leg and routes them to the workbench
  * the cycle produces one replayable ledger

Run: pytest tests/cockpit/  (Python 3.11+ in the repo; the sandbox uses a
3.11-compat shim + a DSOR double — the gate logic under test is the real
SettlementOperationsAnalyst.)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail
from atreides.cockpit import (
    BreakLeg,
    ClearingCockpit,
    CockpitHalted,
    InstructionPackage,
    PackageDisposition,
    PortalRegime,
)
from atreides.contracts.dsor_stub import CAOMTier

SETTLE_DATE = datetime(2026, 7, 16, tzinfo=UTC)


def _capture(cockpit, *, regime=PortalRegime.CCP, clean=True, notional=Decimal("1000000"),
             clearing_ok=True, credit_limit=Decimal("100000000"),
             credit_usage=Decimal("10000000"), net_delivery=Decimal("1000000"),
             ficc_published=None):
    return cockpit.capture_tasking(
        regime=regime,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-ALPHA",
        settlement_date=SETTLE_DATE,
        authority_id="operator-bill",
        authority_tier=CAOMTier.T1,
        cusip="912828Xlike",
        net_delivery_quantity=net_delivery,
        net_payment_amount=notional,
        ficc_published_net_delivery=ficc_published if ficc_published is not None else net_delivery,
        intraday_credit_limit=credit_limit,
        intraday_credit_current_usage=credit_usage,
        ficc_clearing_fund_compliant=clearing_ok,
    )


# --------------------------------------------------------------------------
# Happy path — full five-beat cycle
# --------------------------------------------------------------------------


def test_full_cycle_emits_package_and_reconciles_clean():
    cp = ClearingCockpit()
    t = _capture(cp)
    gate = cp.run_validation_gates(t)
    assert gate.passed is True

    pkg = cp.emit_instruction_package(t, gate)
    assert pkg.disposition is PackageDisposition.EMIT_FOR_HUMAN_ENTRY
    assert pkg.for_human_entry is True
    assert pkg.is_submission is False
    assert pkg.dsor_pre_trade_record_id == gate.dsor_pre_trade_record_id

    rb = cp.ingest_portal_readback(
        operation_id=t.operation_id, regime=PortalRegime.CCP,
        position_balance=t.net_delivery_quantity,
        ccp_net_obligation=t.net_payment_amount,
        clearing_fund_deficit=Decimal("0"),
        intraday_credit_usage=Decimal("10000000"),
    )
    recon = cp.reconcile_expected_actual(pkg, rb)
    assert recon.matched is True
    assert recon.breaks == ()

    ledger = cp.get_cycle_ledger(t.operation_id)
    beats = [e["beat"] for e in ledger]
    # gather -> validate -> prepare -> (ingest readback) reconcile -> reconcile
    assert beats == ["gather", "validate", "prepare", "reconcile", "reconcile"]


# --------------------------------------------------------------------------
# Beat 2 — a held gate emits NO package
# --------------------------------------------------------------------------


def test_clearing_fund_deficiency_holds_gate_no_package():
    cp = ClearingCockpit()
    t = _capture(cp, clearing_ok=False)
    gate = cp.run_validation_gates(t)
    assert gate.passed is False
    assert gate.discrepancy_code == "clearing_fund_deficiency"

    pkg = cp.emit_instruction_package(t, gate)
    assert pkg.disposition is PackageDisposition.GATE_HELD
    assert pkg.for_human_entry is False


def test_intraday_credit_at_limit_holds_gate():
    cp = ClearingCockpit()
    t = _capture(cp, credit_limit=Decimal("50000000"), credit_usage=Decimal("50000000"))
    gate = cp.run_validation_gates(t)
    assert gate.passed is False
    assert gate.discrepancy_code == "intraday_credit_threshold"


def test_net_obligation_mismatch_holds_gate():
    cp = ClearingCockpit()
    t = _capture(cp, net_delivery=Decimal("1000000"), ficc_published=Decimal("999999"))
    gate = cp.run_validation_gates(t)
    assert gate.passed is False
    assert gate.discrepancy_code == "net_obligation_mismatch"


# --------------------------------------------------------------------------
# Beat 3 — material magnitude HOLDS for quorum under CAOM-001
# --------------------------------------------------------------------------


def test_material_magnitude_holds_for_quorum_under_caom():
    cp = ClearingCockpit(material_magnitude_threshold=Decimal("50000000"))
    t = _capture(cp, notional=Decimal("75000000"))  # above threshold
    gate = cp.run_validation_gates(t)
    assert gate.passed is True  # gates pass; the HOLD is a magnitude routing decision

    pkg = cp.emit_instruction_package(t, gate)
    assert pkg.disposition is PackageDisposition.QUORUM_REQUIRED_HOLD
    assert pkg.quorum_required is True
    assert pkg.for_human_entry is False
    assert "CAOM-transition" in pkg.notes


def test_submaterial_magnitude_emits():
    cp = ClearingCockpit(material_magnitude_threshold=Decimal("50000000"))
    t = _capture(cp, notional=Decimal("49999999"))
    gate = cp.run_validation_gates(t)
    pkg = cp.emit_instruction_package(t, gate)
    assert pkg.disposition is PackageDisposition.EMIT_FOR_HUMAN_ENTRY


# --------------------------------------------------------------------------
# Section VI — CCP and CSD contexts stay separate
# --------------------------------------------------------------------------


def test_ccp_and_csd_contexts_are_separate():
    cp = ClearingCockpit()
    ccp_t = _capture(cp, regime=PortalRegime.CCP)
    csd_t = _capture(cp, regime=PortalRegime.CSD)
    assert ccp_t.operation_id != csd_t.operation_id
    # A CCP readback cannot resolve against the CSD context and vice-versa.
    with pytest.raises(Exception):
        cp.ingest_portal_readback(operation_id=ccp_t.operation_id, regime=PortalRegime.CSD)
    # Correct-regime readback resolves.
    rb = cp.ingest_portal_readback(operation_id=csd_t.operation_id, regime=PortalRegime.CSD)
    assert rb.regime is PortalRegime.CSD


# --------------------------------------------------------------------------
# Section VII — reconciliation breaks by leg -> workbench
# --------------------------------------------------------------------------


def test_reconcile_classifies_breaks_by_leg_and_routes_to_workbench():
    cp = ClearingCockpit()
    t = _capture(cp)
    gate = cp.run_validation_gates(t)
    pkg = cp.emit_instruction_package(t, gate)

    rb = cp.ingest_portal_readback(
        operation_id=t.operation_id, regime=PortalRegime.CCP,
        position_balance=Decimal("999000"),               # POSITION break
        ccp_net_obligation=Decimal("1234567"),            # NET_OBLIGATION break
        clearing_fund_deficit=Decimal("250000"),          # CLEARING_FUND break
        intraday_credit_usage=Decimal("100000000"),       # FUNDING break (>= limit)
    )
    recon = cp.reconcile_expected_actual(pkg, rb)
    assert recon.matched is False
    assert set(recon.breaks) == {
        BreakLeg.POSITION, BreakLeg.NET_OBLIGATION,
        BreakLeg.CLEARING_FUND, BreakLeg.FUNDING,
    }
    tickets = cp.raise_break(recon, gate.dsor_pre_trade_record_id)
    assert len(tickets) == 4
    assert all(tk.status == "OPEN_ON_WORKBENCH" for tk in tickets)
    assert len(cp.workbench) == 4


# --------------------------------------------------------------------------
# Axiom 9 — Tier 0 Halt propagates across every primitive
# --------------------------------------------------------------------------


def test_tier0_halt_refuses_every_primitive():
    halted = {"on": False}
    cp = ClearingCockpit(halt_check=lambda: halted["on"])
    t = _capture(cp)  # captured while clear
    gate = cp.run_validation_gates(t)
    pkg = cp.emit_instruction_package(t, gate)
    rb = cp.ingest_portal_readback(operation_id=t.operation_id, regime=PortalRegime.CCP)
    recon = cp.reconcile_expected_actual(pkg, rb)

    halted["on"] = True
    for call in (
        lambda: _capture(cp),
        lambda: cp.run_validation_gates(t),
        lambda: cp.emit_instruction_package(t, gate),
        lambda: cp.ingest_portal_readback(operation_id=t.operation_id, regime=PortalRegime.CCP),
        lambda: cp.reconcile_expected_actual(pkg, rb),
        lambda: cp.raise_break(recon, gate.dsor_pre_trade_record_id),
    ):
        with pytest.raises(CockpitHalted):
            call()


# --------------------------------------------------------------------------
# Cardinal boundary — the surface cannot submit and holds no credentials
# --------------------------------------------------------------------------


def test_no_submission_surface_exists():
    # No method on the cockpit submits, auto-sends, or holds credentials.
    forbidden = ("submit", "send", "post_to_portal", "auto_submit", "scrape",
                 "credentials", "login", "authenticate_portal")
    names = dir(ClearingCockpit)
    assert not any(f in names for f in forbidden)


def test_instruction_package_is_never_a_submission():
    # is_submission is pinned to Literal[False]; a True value is rejected.
    with pytest.raises(Exception):
        InstructionPackage(
            operation_id=uuid.uuid4(),
            regime=PortalRegime.CCP,
            disposition=PackageDisposition.EMIT_FOR_HUMAN_ENTRY,
            rail=SettlementRail.FICC_GSD_DVP,
            settlement_kind=SettlementKind.DVP,
            cusip=None,
            net_delivery_quantity=None,
            net_payment_amount=None,
            dsor_pre_trade_record_id=uuid.uuid4(),
            authority_stamp={},
            quorum_required=False,
            for_human_entry=True,
            is_submission=True,  # must be rejected
        )


def test_no_credential_field_anywhere_on_models():
    from atreides.cockpit.clearing_cockpit import (
        CockpitTasking,
        PortalReadback,
    )
    from atreides.cockpit.clearing_cockpit import (
        InstructionPackage as IP,
    )
    for model in (CockpitTasking, IP, PortalReadback):
        fields = set(model.model_fields)
        assert not any(
            key in f for f in fields
            for key in ("credential", "password", "secret", "token", "entitlement")
        )


# ---------------------------------------------------------------------------
# Break tickets must carry the figures that produced them
# ---------------------------------------------------------------------------


def test_every_break_leg_has_a_detail_key() -> None:
    """Exhaustiveness, so adding a leg without its key fails here rather than
    shipping a blank ticket. The previous derivation - splitting the member
    value on the first underscore - worked for two legs and silently failed
    for the other two."""
    from atreides.cockpit.clearing_cockpit import _DETAIL_KEY, BreakLeg

    assert set(_DETAIL_KEY) == set(BreakLeg)


def test_a_clearing_fund_ticket_carries_the_deficit() -> None:
    from atreides.cockpit.clearing_cockpit import BreakLeg

    cockpit = ClearingCockpit()
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 20, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=Decimal("1000"),
        net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000"),
    )
    gate = cockpit.run_validation_gates(tasking)
    package = cockpit.emit_instruction_package(tasking, gate)
    readback = cockpit.ingest_portal_readback(
        operation_id=tasking.operation_id,
        regime=PortalRegime.CCP,
        clearing_fund_deficit=Decimal("2500000"),
    )
    recon = cockpit.reconcile_expected_actual(package, readback)
    tickets = cockpit.raise_break(recon, uuid.uuid4())
    ticket = next(t for t in tickets if t.leg is BreakLeg.CLEARING_FUND)
    assert "2500000" in ticket.detail


def test_a_net_obligation_ticket_carries_expected_and_actual() -> None:
    from atreides.cockpit.clearing_cockpit import BreakLeg

    cockpit = ClearingCockpit()
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 20, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=Decimal("1000"),
        net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000"),
    )
    gate = cockpit.run_validation_gates(tasking)
    package = cockpit.emit_instruction_package(tasking, gate)
    readback = cockpit.ingest_portal_readback(
        operation_id=tasking.operation_id,
        regime=PortalRegime.CCP,
        ccp_net_obligation=Decimal("999999"),
    )
    recon = cockpit.reconcile_expected_actual(package, readback)
    tickets = cockpit.raise_break(recon, uuid.uuid4())
    ticket = next(t for t in tickets if t.leg is BreakLeg.NET_OBLIGATION)
    assert "1000000" in ticket.detail
    assert "999999" in ticket.detail


def test_no_break_ticket_reaches_the_workbench_empty() -> None:
    """The general form. A well-formed ticket with no figures in it is worse
    than no ticket, because it looks worked."""
    cockpit = ClearingCockpit()
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 20, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=Decimal("1000"),
        net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000"),
        intraday_credit_limit=Decimal("10000000"),
        intraday_credit_current_usage=Decimal("1000"),
    )
    gate = cockpit.run_validation_gates(tasking)
    package = cockpit.emit_instruction_package(tasking, gate)
    readback = cockpit.ingest_portal_readback(
        operation_id=tasking.operation_id,
        regime=PortalRegime.CCP,
        position_balance=Decimal("900"),
        clearing_fund_deficit=Decimal("2500000"),
        ccp_net_obligation=Decimal("999999"),
        intraday_credit_usage=Decimal("10000000"),
    )
    recon = cockpit.reconcile_expected_actual(package, readback)
    tickets = cockpit.raise_break(recon, uuid.uuid4())
    assert len(tickets) == 4
    for ticket in tickets:
        assert ticket.detail != "{}", ticket.leg.value
