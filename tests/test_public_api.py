"""The supported functional facade delegates without changing domain behavior."""

from datetime import UTC, datetime

from atreides import api
from atreides.activation.synthetic import settlement_tasking_unit
from atreides.agents.tier1.outputs import RailAcknowledgment, SettlementTelemetry
from atreides.dsor import DSORStore
from atreides.messaging import SettlementStatus


def test_public_api_exports_functions_not_agent_classes() -> None:
    assert "run_settlement" in api.__all__
    assert "select_multi_currency_rail" in api.__all__
    assert all("Analyst" not in name and "Specialist" not in name for name in api.__all__)


def test_settlement_lifecycle_uses_functional_entrypoints() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    tasking = settlement_tasking_unit(0, now)

    with DSORStore(":memory:") as store:
        output, record = api.run_settlement(tasking, store, now=now)
        assert isinstance(output, SettlementTelemetry)
        assert store.replay(record.record_id) == output

        acknowledgment = RailAcknowledgment(
            end_to_end_id=output.instruction_reference,
            status=SettlementStatus.SETTLED,
            status_report_message_id="public-api-test",
            acknowledged_at=now,
        )
        acknowledged, correction = api.record_settlement_acknowledgment(
            record, acknowledgment, store, now=now
        )

        assert acknowledged.rail_acknowledgment == acknowledgment
        assert correction.correction_of == record.record_id
