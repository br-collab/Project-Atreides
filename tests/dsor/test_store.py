"""Tests for DSORStore — the three DSOR gate checks.

Gate Check 1 — Replay determinism:
    replay() called twice with the same record_id returns byte-identical
    FIATOperationsOutput instances.

Gate Check 2 — Append-only enforcement:
    Appending the same operation_id twice without correction_of raises
    DSORAppendOnlyError. Providing correction_of=<original_record_id>
    succeeds and the original is still replayable.

Gate Check 3 — Survives restart:
    Write to an on-disk store, close it, reopen it, and replay —
    returns the same output that was appended.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from aureon.agents.tier2.outputs import EscalationRequired, RoutingDecision
from aureon.dsor import DSORAppendOnlyError, DSORRecordNotFoundError, DSORStore

# ---------------------------------------------------------------------------
# Gate Check 1 — Replay determinism
# ---------------------------------------------------------------------------


class TestReplayDeterminism:
    def test_routing_decision_replay_byte_identical(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = mem_store.append(routing_decision_output, dtg=dtg)
        r1 = mem_store.replay(record.record_id)
        r2 = mem_store.replay(record.record_id)
        assert r1.model_dump_json() == r2.model_dump_json()

    def test_escalation_replay_byte_identical(
        self,
        mem_store: DSORStore,
        escalation_output: EscalationRequired,
        dtg: datetime,
    ) -> None:
        record = mem_store.append(escalation_output, dtg=dtg)
        r1 = mem_store.replay(record.record_id)
        r2 = mem_store.replay(record.record_id)
        assert r1.model_dump_json() == r2.model_dump_json()

    def test_replay_returns_output_matching_original(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = mem_store.append(routing_decision_output, dtg=dtg)
        replayed = mem_store.replay(record.record_id)
        assert replayed.model_dump_json() == routing_decision_output.model_dump_json()

    def test_replay_unknown_record_id_raises(
        self,
        mem_store: DSORStore,
    ) -> None:
        with pytest.raises(DSORRecordNotFoundError):
            mem_store.replay(uuid4())


# ---------------------------------------------------------------------------
# Gate Check 2 — Append-only enforcement
# ---------------------------------------------------------------------------


class TestAppendOnlyEnforcement:
    def test_duplicate_operation_id_without_correction_raises(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        mem_store.append(routing_decision_output, dtg=dtg)
        with pytest.raises(DSORAppendOnlyError):
            mem_store.append(routing_decision_output, dtg=dtg)

    def test_correction_with_correction_of_succeeds(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        original = mem_store.append(routing_decision_output, dtg=dtg)
        correction = mem_store.append(
            routing_decision_output,
            dtg=dtg,
            correction_of=original.record_id,
        )
        assert correction.correction_of == original.record_id
        assert correction.record_id != original.record_id

    def test_original_preserved_after_correction(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        original = mem_store.append(routing_decision_output, dtg=dtg)
        mem_store.append(
            routing_decision_output,
            dtg=dtg,
            correction_of=original.record_id,
        )
        replayed_original = mem_store.replay(original.record_id)
        assert replayed_original.model_dump_json() == routing_decision_output.model_dump_json()

    def test_correction_itself_replayable(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        original = mem_store.append(routing_decision_output, dtg=dtg)
        correction = mem_store.append(
            routing_decision_output,
            dtg=dtg,
            correction_of=original.record_id,
        )
        replayed = mem_store.replay(correction.record_id)
        assert replayed.model_dump_json() == routing_decision_output.model_dump_json()

    def test_two_independent_operations_both_succeed(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        escalation_output: EscalationRequired,
        dtg: datetime,
    ) -> None:
        r1 = mem_store.append(routing_decision_output, dtg=dtg)
        r2 = mem_store.append(escalation_output, dtg=dtg)
        assert r1.record_id != r2.record_id
        assert (
            mem_store.replay(r1.record_id).model_dump_json()
            == routing_decision_output.model_dump_json()
        )
        assert (
            mem_store.replay(r2.record_id).model_dump_json()
            == escalation_output.model_dump_json()
        )


# ---------------------------------------------------------------------------
# Gate Check 3 — Survives restart
# ---------------------------------------------------------------------------


class TestSurvivesRestart:
    def test_record_survives_close_and_reopen(
        self,
        tmp_path: Path,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        db_path = tmp_path / "dsor_restart.db"

        with DSORStore(db_path) as store:
            record = store.append(routing_decision_output, dtg=dtg)
            record_id = record.record_id

        with DSORStore(db_path) as store:
            replayed = store.replay(record_id)

        assert replayed.model_dump_json() == routing_decision_output.model_dump_json()

    def test_append_only_enforced_after_reopen(
        self,
        tmp_path: Path,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        db_path = tmp_path / "dsor_ao_restart.db"

        with DSORStore(db_path) as store:
            store.append(routing_decision_output, dtg=dtg)

        with DSORStore(db_path) as store:
            with pytest.raises(DSORAppendOnlyError):
                store.append(routing_decision_output, dtg=dtg)

    def test_correction_survives_reopen(
        self,
        tmp_path: Path,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        db_path = tmp_path / "dsor_correction_restart.db"
        expected_json = routing_decision_output.model_dump_json()

        with DSORStore(db_path) as store:
            original = store.append(routing_decision_output, dtg=dtg)
            correction = store.append(
                routing_decision_output,
                dtg=dtg,
                correction_of=original.record_id,
            )
            original_id = original.record_id
            correction_id = correction.record_id

        with DSORStore(db_path) as store:
            assert store.replay(original_id).model_dump_json() == expected_json
            assert store.replay(correction_id).model_dump_json() == expected_json


# ---------------------------------------------------------------------------
# Additional: correct return types from replay
# ---------------------------------------------------------------------------


class TestReplayReturnType:
    def test_routing_decision_replay_returns_routing_decision(
        self,
        mem_store: DSORStore,
        routing_decision_output: RoutingDecision,
        dtg: datetime,
    ) -> None:
        record = mem_store.append(routing_decision_output, dtg=dtg)
        replayed = mem_store.replay(record.record_id)
        assert isinstance(replayed, RoutingDecision)

    def test_escalation_replay_returns_escalation_required(
        self,
        mem_store: DSORStore,
        escalation_output: EscalationRequired,
        dtg: datetime,
    ) -> None:
        record = mem_store.append(escalation_output, dtg=dtg)
        replayed = mem_store.replay(record.record_id)
        assert isinstance(replayed, EscalationRequired)
