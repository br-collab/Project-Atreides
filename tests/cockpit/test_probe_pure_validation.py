"""ATR-I-02 probe: validation must be pure.

Reproduces the Atreides inventory probe (15 Sep 2026, commit 31b62f0): a clean
CockpitTasking passed ``run_validation_gates``, and in doing so the Settlement
Operations Analyst persisted ``SettlementTelemetry`` with
``rail_acknowledgment_dtg`` set, before any InstructionPackage existed.
Validation manufactured a rail acknowledgement that no rail sent.

Marked strict xfail: CI stays green while the defect stands, and the run fails
the day the Wave 2 fix (work package T2) lands without the marker being removed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail, SettlementTelemetry
from atreides.cockpit import ClearingCockpit, PortalRegime
from atreides.contracts.dsor_stub import CAOMTier
from atreides.dsor import DSORStore


class _RecordingStore(DSORStore):
    """The real in-memory store, keeping a list of every output appended to it."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.appended: list[Any] = []

    def append(self, output: Any, **kwargs: Any) -> Any:
        self.appended.append(output)
        return super().append(output, **kwargs)


@pytest.mark.xfail(strict=True, reason="ATR-I-02 — fixed in Wave 2")
def test_clean_validation_persists_no_telemetry_or_rail_acknowledgement() -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-ALPHA",
        settlement_date=datetime(2026, 7, 16, tzinfo=UTC),
        authority_id="operator-bill",
        authority_tier=CAOMTier.T1,
        cusip="912828Xlike",
        net_delivery_quantity=Decimal("1000000"),
        net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000000"),
        intraday_credit_limit=Decimal("100000000"),
        intraday_credit_current_usage=Decimal("10000000"),
        ficc_clearing_fund_compliant=True,
    )

    cockpit.run_validation_gates(tasking)

    assert [o for o in store.appended if isinstance(o, SettlementTelemetry)] == []
    assert [
        o for o in store.appended if getattr(o, "rail_acknowledgment_dtg", None) is not None
    ] == []
