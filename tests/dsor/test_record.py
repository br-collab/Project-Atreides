"""Tests for DSORRecord assembly.

Verifies the immutable, DTG-stamped record model that wraps
FIATOperationsOutput instances. Covers both output kinds available
from the basic fixture set plus explicit correction-chain semantics.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from aureon.agents.tier2.outputs import EscalationRequired, RoutingDecision
from aureon.dsor.record import DSORRecord


class TestDSORRecordAssembly:
    def test_assemble_routing_decision_kind(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        assert record.kind == "routing_decision"

    def test_assemble_routing_decision_dtg(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        assert record.dtg == dtg

    def test_assemble_routing_decision_output_preserved(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        assert record.output == routing_decision_output

    def test_assemble_no_correction_of_by_default(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        assert record.correction_of is None

    def test_assemble_escalation_required_kind(
        self,
        escalation_output: EscalationRequired,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(escalation_output, dtg=dtg)
        assert record.kind == "escalation_required"

    def test_assemble_with_correction_of(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        original = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        correction = DSORRecord.assemble(
            routing_decision_output,
            dtg=dtg,
            correction_of=original.record_id,
        )
        assert correction.correction_of == original.record_id

    def test_correction_gets_new_record_id(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        original = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        correction = DSORRecord.assemble(
            routing_decision_output,
            dtg=dtg,
            correction_of=original.record_id,
        )
        assert correction.record_id != original.record_id

    def test_two_assemblies_have_unique_record_ids(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        r1 = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        r2 = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        assert r1.record_id != r2.record_id


class TestDSORRecordImmutability:
    def test_frozen_field_assignment_raises(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = DSORRecord.assemble(routing_decision_output, dtg=dtg)
        with pytest.raises((ValidationError, TypeError)):
            record.kind = "escalation_required"  # type: ignore[misc]

    def test_extra_fields_forbidden(
        self,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        with pytest.raises(ValidationError):
            DSORRecord(  # type: ignore[call-arg]
                dtg=dtg,
                kind="routing_decision",
                output=routing_decision_output,
                extra_field_not_in_schema="should_fail",
            )
