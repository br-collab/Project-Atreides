"""ATR-I-02 regression: validation is pure; only emission writes, and never an acknowledgement.

Before Wave 2 a clean ``CockpitTasking`` passed ``run_validation_gates`` and in
doing so the Settlement Operations Analyst routed, generated a reference and
persisted ``SettlementTelemetry`` with ``rail_acknowledgment_dtg`` set, before
any InstructionPackage existed (inventory probe, 15 Sep 2026, commit 31b62f0).
The gate result then called that telemetry record its
``dsor_pre_trade_record_id``.

Fixed in W2A-2:

- ``validate_tasking`` is a pure function; ``SettlementOperationsAnalyst.emit``
  is the explicitly named emission stage.
- ``run_validation_gates`` writes nothing to the DSOR; Beat 3
  (``emit_instruction_package``) does, and the package carries ``dsor_record_id``.
- A rail acknowledgement exists only from a verified readback
  (``RailAcknowledgment.from_readback``), recorded as a correction.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from atreides.agents.tier1.outputs import (
    RailAcknowledgment,
    SettlementKind,
    SettlementRail,
    SettlementTelemetry,
)
from atreides.agents.tier1.settlement_operations_analyst import (
    SettlementOperationsAnalyst,
    validate_tasking,
)
from atreides.cockpit import ClearingCockpit, PackageDisposition, PortalRegime
from atreides.contracts.dsor_stub import CAOMTier
from atreides.dsor import DSORStore
from atreides.messaging.readback import (
    ReadbackMatch,
    SettlementStatus,
    StatusEntry,
    StatusReport,
    absent_readback,
)


class _RecordingStore(DSORStore):
    """The real in-memory store, keeping a list of every output appended to it."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.appended: list[Any] = []

    def append(self, output: Any, **kwargs: Any) -> Any:
        self.appended.append(output)
        return super().append(output, **kwargs)

    def row_count(self) -> int:
        conn: sqlite3.Connection = self._conn  # type: ignore[attr-defined]
        (count,) = conn.execute("SELECT COUNT(*) FROM dsor_records").fetchone()
        return int(count)


def _capture(cockpit: ClearingCockpit, **changes: Any):  # type: ignore[no-untyped-def]
    fields: dict[str, Any] = {
        "regime": PortalRegime.CCP,
        "rail": SettlementRail.FICC_GSD_DVP,
        "settlement_kind": SettlementKind.DVP,
        "counterparty_id": "CP-ALPHA",
        "settlement_date": datetime(2026, 7, 16, tzinfo=UTC),
        "authority_id": "operator-bill",
        "authority_tier": CAOMTier.T1,
        "cusip": "912828Xlike",
        "net_delivery_quantity": Decimal("1000000"),
        "net_payment_amount": Decimal("1000000"),
        "ficc_published_net_delivery": Decimal("1000000"),
        "intraday_credit_limit": Decimal("100000000"),
        "intraday_credit_current_usage": Decimal("10000000"),
        "ficc_clearing_fund_compliant": True,
    }
    fields.update(changes)
    return cockpit.capture_tasking(**fields)


def test_clean_validation_persists_no_telemetry_or_rail_acknowledgement() -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    gate = cockpit.run_validation_gates(_capture(cockpit))
    assert gate.passed
    assert store.appended == []


@pytest.mark.parametrize("clearing_ok", [True, False])
def test_validation_leaves_the_dsor_store_unchanged(clearing_ok: bool) -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    before = store.row_count()
    gate = cockpit.run_validation_gates(_capture(cockpit, ficc_clearing_fund_compliant=clearing_ok))
    assert gate.passed is clearing_ok
    assert store.row_count() == before == 0
    assert gate.checks_evaluated


def test_validation_is_deterministic_and_creates_no_reference() -> None:
    cockpit = ClearingCockpit()
    tasking = _capture(cockpit)
    first = cockpit.run_validation_gates(tasking)
    second = cockpit.run_validation_gates(tasking)
    assert first == second
    assert not hasattr(first, "dsor_pre_trade_record_id")


def test_emission_is_the_stage_that_writes_and_it_sets_no_acknowledgement() -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    tasking = _capture(cockpit)
    gate = cockpit.run_validation_gates(tasking)
    pkg = cockpit.emit_instruction_package(tasking, gate)
    assert pkg.disposition is PackageDisposition.EMIT_FOR_HUMAN_ENTRY
    (telemetry,) = store.appended
    assert isinstance(telemetry, SettlementTelemetry)
    assert telemetry.rail_acknowledgment is None
    assert telemetry.rail_acknowledgment_dtg is None
    assert pkg.dsor_record_id is not None
    assert store.replay(pkg.dsor_record_id) == telemetry


def test_held_gate_persists_its_escalation_at_emission_not_validation() -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    tasking = _capture(cockpit, ficc_clearing_fund_compliant=False)
    gate = cockpit.run_validation_gates(tasking)
    assert store.appended == []
    pkg = cockpit.emit_instruction_package(tasking, gate)
    assert pkg.disposition is PackageDisposition.GATE_HELD
    assert [o.kind for o in store.appended] == ["settlement_escalation"]


def test_quorum_hold_persists_nothing() -> None:
    store = _RecordingStore()
    cockpit = ClearingCockpit(store)
    tasking = _capture(cockpit, net_payment_amount=Decimal("999000000000"))
    pkg = cockpit.emit_instruction_package(tasking, cockpit.run_validation_gates(tasking))
    assert pkg.disposition is PackageDisposition.QUORUM_REQUIRED_HOLD
    assert pkg.dsor_record_id is None
    assert store.appended == []


def test_validate_tasking_is_pure() -> None:
    cockpit = ClearingCockpit()
    record = cockpit._tasking_record(_capture(cockpit))
    first = validate_tasking(record)
    assert first == validate_tasking(record)
    assert first.passed
    assert first.checks_evaluated == (
        "monitor_intraday_funding_position",
        "verify_ficc_clearing_fund_compliance",
        "model_ficc_net_settlement_obligation",
        "verify_dsor_pre_trade_record",
    )


# ---- Rail acknowledgement only from a verified readback -------------------------------------


def _match(status: SettlementStatus, *, breaks: tuple[Any, ...] = ()) -> ReadbackMatch:
    report = StatusReport(
        message_id="MSG-1",
        created_at="2026-07-16T14:05:00+00:00",
        namespace="urn:iso:std:iso:20022:tech:xsd:pacs.002.001.14",
        original_message_id="ORIG-1",
        original_message_name_id="pacs.009.001.13",
        group_status_code=None,
        entries=(
            StatusEntry(
                status_code="ACSC",
                status=status,
                end_to_end_id="E2E-1",
                acceptance_datetime="2026-07-16T14:04:30Z",
            ),
        ),
    )
    return ReadbackMatch(report=report, matched={"E2E-1": status}, breaks=breaks)


def _emitted(store: DSORStore, **changes: Any):  # type: ignore[no-untyped-def]
    cockpit = ClearingCockpit(store)
    return SettlementOperationsAnalyst().run(
        cockpit._tasking_record(_capture(cockpit, **changes)), store
    )


def test_acknowledgement_from_a_verified_readback_is_recorded_as_a_correction() -> None:
    store = DSORStore(":memory:")
    telemetry, record = _emitted(store)
    ack = RailAcknowledgment.from_readback(_match(SettlementStatus.SETTLED), "E2E-1")
    acknowledged, correction = SettlementOperationsAnalyst().record_rail_acknowledgment(
        record, ack, store
    )
    assert correction.correction_of == record.record_id
    assert acknowledged.rail_acknowledgment_dtg == datetime(2026, 7, 16, 14, 4, 30, tzinfo=UTC)
    assert store.replay(record.record_id) == telemetry  # the original is untouched
    assert store.replay(correction.record_id) == acknowledged


@pytest.mark.parametrize(
    "status",
    [
        SettlementStatus.REJECTED,
        SettlementStatus.CANCELLED,
        SettlementStatus.ACCEPTED_WITH_CHANGE,
        SettlementStatus.UNRECOGNIZED,
    ],
)
def test_non_acknowledging_status_is_refused(status: SettlementStatus) -> None:
    with pytest.raises(ValueError, match="not an acknowledgement"):
        RailAcknowledgment.from_readback(_match(status), "E2E-1")


def test_absent_broken_or_unmatched_readback_is_refused() -> None:
    from atreides.messaging.readback import ReadbackBreak, ReadbackBreakCode

    with pytest.raises(ValueError, match="silence"):
        RailAcknowledgment.from_readback(absent_readback(), "E2E-1")
    broken = _match(
        SettlementStatus.SETTLED,
        breaks=(ReadbackBreak(ReadbackBreakCode.AMOUNT_MISMATCH, "echoed 1 != 2", "E2E-1"),),
    )
    with pytest.raises(ValueError, match="did not reconcile"):
        RailAcknowledgment.from_readback(broken, "E2E-1")
    with pytest.raises(ValueError, match="does not match"):
        RailAcknowledgment.from_readback(_match(SettlementStatus.SETTLED), "E2E-OTHER")


def test_only_emitted_telemetry_can_be_acknowledged() -> None:
    store = DSORStore(":memory:")
    _, record = _emitted(store, ficc_clearing_fund_compliant=False)
    ack = RailAcknowledgment.from_readback(_match(SettlementStatus.SETTLED), "E2E-1")
    with pytest.raises(ValueError, match="only emitted settlement telemetry"):
        SettlementOperationsAnalyst().record_rail_acknowledgment(record, ack, store)


def test_legacy_record_with_a_fabricated_acknowledgement_still_replays() -> None:
    cockpit = ClearingCockpit()
    tasking = _capture(cockpit)
    pkg = cockpit.emit_instruction_package(tasking, cockpit.run_validation_gates(tasking))
    assert pkg.dsor_record_id is not None
    telemetry = cockpit._store.replay(pkg.dsor_record_id)  # type: ignore[attr-defined]
    legacy = telemetry.model_dump(mode="json")
    legacy["rail_acknowledgment_dtg"] = legacy["emitted_at"]
    del legacy["rail_acknowledgment"]
    restored = SettlementTelemetry.model_validate(legacy)
    assert restored.rail_acknowledgment is None
    assert restored.rail_acknowledgment_dtg is None


def test_gate_result_mismatch_with_changed_tasking_is_refused() -> None:
    from atreides.cockpit import CockpitBoundaryError

    cockpit = ClearingCockpit()
    clean = _capture(cockpit)
    held = _capture(cockpit, ficc_clearing_fund_compliant=False)
    gate = cockpit.run_validation_gates(clean)
    forged = gate.model_copy(update={"operation_id": held.operation_id})
    with pytest.raises(CockpitBoundaryError, match="re-run Beat 2"):
        cockpit.emit_instruction_package(held, forged)


def test_settlement_validation_is_internally_consistent() -> None:
    from pydantic import ValidationError

    from atreides.agents.tier1.outputs import DiscrepancyCode, SettlementValidation

    op = _capture(ClearingCockpit()).operation_id
    with pytest.raises(ValidationError, match="names its discrepancy"):
        SettlementValidation(
            operation_id=op,
            passed=True,
            checks_evaluated=("x",),
            discrepancy_code=DiscrepancyCode.DSOR_MISMATCH,
        )
    with pytest.raises(ValidationError, match="failure detail"):
        SettlementValidation(
            operation_id=op,
            passed=False,
            checks_evaluated=("x",),
            discrepancy_code=DiscrepancyCode.DSOR_MISMATCH,
        )
    with pytest.raises(ValidationError, match="evaluated no check"):
        SettlementValidation(operation_id=op, passed=True, checks_evaluated=())


def test_acknowledgement_requires_an_aware_time() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="timezone-aware"):
        RailAcknowledgment(
            end_to_end_id="E2E-1",
            status=SettlementStatus.SETTLED,
            status_report_message_id="MSG-1",
            acknowledged_at=datetime(2026, 7, 16, 14, 4),
        )


def test_emission_refuses_a_validation_for_another_operation() -> None:
    cockpit = ClearingCockpit()
    one = cockpit._tasking_record(_capture(cockpit))
    other = cockpit._tasking_record(_capture(cockpit))
    with pytest.raises(ValueError, match="different operations"):
        SettlementOperationsAnalyst().emit(one, validate_tasking(other), DSORStore(":memory:"))
