"""Unit tests for the activation guards the acceptance tests do not reach.

Every case here is a refusal that would otherwise be written and never
exercised. A guard nobody has run is a guard nobody knows works.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition, coerce_disposition
from cannae_kernel.ids import ActorId
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.activation import (
    ADVISORY_EFFECTS,
    OPERATOR_DIRECT_BASIS,
    AgentIdentity,
    AgentRecommendation,
    AgentRefusal,
    AgentSupervisor,
    AgentTier,
    InputOrigin,
    RefusedAtConsumerError,
    admit,
    basis_from_lineage,
    default_runners,
    require_handoff,
)
from atreides.activation.outputs import PolicyExecution, RefusalCode, no_policy_execution
from atreides.activation.runners import LateralProbeRunner
from atreides.activation.snapshot import SNAPSHOT_SCHEMA_VERSION, build_snapshot
from atreides.activation.supervisor import Finding, WorkUnit

AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _actor(kind: ActorKind) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01M2P20SY00000000000000Z01"),
        actor_kind=kind,
        role="test actor",
        entitlement_refs=("CAOM-001:advisory",),
        authenticated=True,
    )


class TestHandoffRule:
    def test_operator_direct_carrying_a_handoff_identifier_is_refused(self) -> None:
        """It claims an authority nothing issued, so it is not admitted on trust."""
        decision = admit(InputOrigin.OPERATOR_DIRECT, Recorded[str](value="c2h-invented"))
        assert decision.disposition is Disposition.BLOCK
        assert "cannot be checked" in decision.detail

    def test_require_handoff_returns_the_decision_when_admitted(self) -> None:
        decision = require_handoff(InputOrigin.OPERATOR_DIRECT, OPERATOR_DIRECT_BASIS)
        assert decision.admitted

    def test_the_raised_error_carries_the_decision_not_just_a_message(self) -> None:
        with pytest.raises(RefusedAtConsumerError) as raised:
            require_handoff(InputOrigin.AGENT_LATERAL, OPERATOR_DIRECT_BASIS)
        assert raised.value.decision.origin is InputOrigin.AGENT_LATERAL

    def test_basis_from_lineage_maps_none_to_the_recorded_absence(self) -> None:
        basis = basis_from_lineage(None)
        assert isinstance(basis, Absent)
        assert basis.reason == "operator-direct under CAOM-001"

    def test_basis_from_lineage_keeps_an_identifier(self) -> None:
        basis = basis_from_lineage("c2h-1")
        assert isinstance(basis, Recorded)
        assert basis.value == "c2h-1"

    def test_an_admission_is_never_indeterminate(self) -> None:
        """"I could not tell" would let the work through on the next reading."""
        for origin in InputOrigin:
            for basis in (None, OPERATOR_DIRECT_BASIS, Recorded[str](value="c2h")):
                decision = admit(origin, basis)
                assert decision.disposition in {Disposition.PASS, Disposition.BLOCK}


class TestAgentIdentityGuards:
    def test_an_authorizing_actor_kind_is_not_an_agent(self) -> None:
        for kind in (ActorKind.HUMAN, ActorKind.DETERMINISTIC_SERVICE):
            with pytest.raises(ValidationError, match="may authorize"):
                AgentIdentity(agent_id="a", tier=AgentTier.TIER_1, actor=_actor(kind))

    def test_the_adaptive_h_class_is_not_activated_in_phase_a(self) -> None:
        with pytest.raises(ValidationError, match="Phase C"):
            AgentIdentity(
                agent_id="thifur-h", tier=AgentTier.TIER_2, actor=_actor(ActorKind.AGENT_H)
            )

    def test_the_r_and_j_classes_are_accepted(self) -> None:
        for kind in (ActorKind.AGENT_R, ActorKind.AGENT_J):
            identity = AgentIdentity(agent_id="a", tier=AgentTier.TIER_1, actor=_actor(kind))
            assert identity.actor.actor_kind is kind


class TestOutputGuards:
    """The envelope invariants, each tried on for size.

    Built field by field rather than from a shared dictionary: these assertions
    are about which field is wrong, so the field has to be visible in the test.
    """

    IDENTITY = AgentIdentity(
        agent_id="a", tier=AgentTier.TIER_1, actor=_actor(ActorKind.AGENT_R)
    )
    OPERATION = UUID("00000000-0000-4000-8000-000000000001")
    ADMISSION = admit(InputOrigin.OPERATOR_DIRECT, OPERATOR_DIRECT_BASIS)
    EXECUTION = Recorded[PolicyExecution](
        value=PolicyExecution(policy="p", gates=("g",), outcome=Disposition.BLOCK)
    )

    def test_a_naive_observed_at_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            AgentRecommendation(
                agent=self.IDENTITY,
                operation_id=self.OPERATION,
                observed_at=datetime(2026, 9, 21, 12, 0),
                provenance=Provenance.RECOMMENDATION,
                disposition=Disposition.HOLD,
                handoff_basis=OPERATOR_DIRECT_BASIS,
                admission=self.ADMISSION,
                policy_execution=no_policy_execution("no gate ran"),
                summary="s",
            )

    def test_the_admission_and_the_basis_must_describe_the_same_input(self) -> None:
        """Otherwise the output describes an input the agent did not admit."""
        with pytest.raises(ValidationError, match="disagree"):
            AgentRecommendation(
                agent=self.IDENTITY,
                operation_id=self.OPERATION,
                observed_at=AT,
                provenance=Provenance.RECOMMENDATION,
                disposition=Disposition.HOLD,
                handoff_basis=Recorded[str](value="c2h-mismatched"),
                admission=self.ADMISSION,
                policy_execution=no_policy_execution("no gate ran"),
                summary="s",
            )

    def test_a_refusal_that_does_not_block_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="recorded as BLOCK"):
            AgentRefusal(
                agent=self.IDENTITY,
                operation_id=self.OPERATION,
                observed_at=AT,
                provenance=Provenance.POLICY_RESULT,
                disposition=Disposition.HOLD,
                handoff_basis=OPERATOR_DIRECT_BASIS,
                admission=self.ADMISSION,
                policy_execution=self.EXECUTION,
                summary="s",
                code=RefusalCode.HALT_ACTIVE,
                refused_detail="d",
            )

    def test_a_refusal_claiming_it_is_only_advice_is_refused(self) -> None:
        """A refusal is a gate outcome. Labelling it advice would make it
        arguable, and a type check's refusal is not a matter of opinion."""
        with pytest.raises(ValidationError, match="POLICY_RESULT"):
            AgentRefusal(
                agent=self.IDENTITY,
                operation_id=self.OPERATION,
                observed_at=AT,
                provenance=Provenance.RECOMMENDATION,
                disposition=Disposition.BLOCK,
                handoff_basis=OPERATOR_DIRECT_BASIS,
                admission=self.ADMISSION,
                policy_execution=self.EXECUTION,
                summary="s",
                code=RefusalCode.HALT_ACTIVE,
                refused_detail="d",
            )

    def test_the_advisory_effect_set_is_contained_and_says_why(self) -> None:
        assert ADVISORY_EFFECTS.is_contained
        assert not ADVISORY_EFFECTS.is_irreversible_outside
        assert "never submits to a rail" in ADVISORY_EFFECTS.note


class TestSupervisorLifecycle:
    def test_two_agents_cannot_share_a_name(self) -> None:
        runners = (LateralProbeRunner(), LateralProbeRunner())
        with pytest.raises(ValueError, match="two agents registered"):
            AgentSupervisor(runners=runners)

    def test_an_unknown_agent_cannot_be_stopped_or_started(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        with pytest.raises(KeyError, match="no agent registered"):
            supervisor.stop("nobody", "reason")
        with pytest.raises(KeyError, match="no agent registered"):
            supervisor.start("nobody")

    def test_a_restarted_agent_produces_current_state_again(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        supervisor.tick(AT)
        supervisor.stop("fiat-operations-specialist", "maintenance")
        supervisor.start("fiat-operations-specialist")
        state = supervisor.tick(AT + timedelta(minutes=1))
        agent = next(a for a in state.agents if a.identity.agent_id == "fiat-operations-specialist")
        assert agent.up
        assert isinstance(agent.last_output, Recorded)

    def test_a_stopped_agent_is_skipped_rather_than_run(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        supervisor.stop("settlement-operations-analyst", "stopped before the first tick")
        supervisor.tick(AT)
        agent = next(
            a
            for a in supervisor.state().agents
            if a.identity.agent_id == "settlement-operations-analyst"
        )
        assert agent.recommendations == 0
        assert agent.refusals == 0

    def test_the_probe_refuses_to_run_if_it_is_ever_admitted(self) -> None:
        """Its ``observe`` is unreachable while WP-A2 holds, and says so loudly
        if it is ever reached."""
        probe = LateralProbeRunner()
        unit = probe.next_unit(0, AT)
        with pytest.raises(AssertionError, match="stopped working"):
            probe.observe(unit, 0, AT)

    def test_a_probe_that_gets_admitted_takes_the_whole_picture_to_block(self) -> None:
        """The alarm this design exists to raise.

        A probe offering an inadmissible input is healthy while it is refused. If
        it is ever *admitted* and returns a recommendation, WP-A2's refusal at the
        consumer has stopped working, and that is not a HOLD — it is the failure
        the whole work package prevents.
        """
        supervisor = AgentSupervisor(runners=(_AdmittedProbeRunner(),))
        state = supervisor.tick(AT)
        agent = state.agents[0]
        assert agent.expects_refusal
        assert isinstance(agent.last_output, Recorded)
        assert isinstance(agent.last_output.value, AgentRecommendation)
        assert agent.disposition is Disposition.BLOCK
        assert state.disposition is Disposition.BLOCK

    def test_state_before_any_tick_reports_no_tick(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        state = supervisor.state()
        assert state.tick == -1
        assert isinstance(state.last_tick_at, Absent)
        assert state.last_tick_at.kind is AbsenceKind.NOT_YET_KNOWN
        assert state.disposition is Disposition.INDETERMINATE


class TestSnapshot:
    def test_the_snapshot_round_trips_through_json_keeping_its_absences(self) -> None:
        """The whole reason absence is a type: it has to survive the wire."""
        from atreides.activation.snapshot import ActivationSnapshot

        supervisor = AgentSupervisor(runners=default_runners())
        supervisor.tick(AT)
        supervisor.stop("fiat-operations-specialist", "stopped for the round-trip test")
        snapshot = build_snapshot(supervisor.state(), taken_at=AT)
        replayed = ActivationSnapshot.model_validate_json(snapshot.model_dump_json())
        assert replayed == snapshot
        stopped = next(a for a in replayed.agents if a.agent_id == "fiat-operations-specialist")
        assert isinstance(stopped.last_summary, Absent)
        assert "stopped for the round-trip test" in stopped.last_summary.label

    def test_the_schema_version_is_carried(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        snapshot = build_snapshot(supervisor.state(), taken_at=AT)
        assert snapshot.schema_version == SNAPSHOT_SCHEMA_VERSION
        assert snapshot.synthetic is True
        assert snapshot.phase == "A"

    def test_a_running_agents_stopped_reason_is_not_applicable(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        supervisor.tick(AT)
        snapshot = build_snapshot(supervisor.state(), taken_at=AT)
        running = snapshot.agents[0]
        assert isinstance(running.stopped_reason, Absent)
        assert running.stopped_reason.kind is AbsenceKind.NOT_APPLICABLE

    def test_the_recorded_handoff_basis_reaches_the_surface_as_text(self) -> None:
        supervisor = AgentSupervisor(
            runners=(_RecordedBasisRunner(),),
        )
        supervisor.tick(AT)
        snapshot = build_snapshot(supervisor.state(), taken_at=AT)
        basis = snapshot.agents[0].last_handoff_basis
        assert isinstance(basis, Recorded)
        assert basis.value == "c2h-from-a-future-c2"

    def test_every_disposition_the_surface_may_see_is_kernel_vocabulary(self) -> None:
        supervisor = AgentSupervisor(runners=default_runners())
        supervisor.tick(AT)
        snapshot = build_snapshot(supervisor.state(), taken_at=AT)
        for agent in snapshot.agents:
            assert coerce_disposition(agent.disposition.value) is agent.disposition


class _RecordedBasisRunner:
    """An agent whose input arrives with a recorded handoff, as one would after C2."""

    expects_refusal = False

    def __init__(self) -> None:
        self.identity = AgentIdentity(
            agent_id="recorded-basis-agent",
            tier=AgentTier.TIER_1,
            actor=ActorRef(
                actor_id=ActorId("act_01M2P20SY00000000000000Z02"),
                actor_kind=ActorKind.AGENT_R,
                role="test agent",
                entitlement_refs=("CAOM-001:advisory",),
                authenticated=True,
            ),
        )

    def next_unit(self, tick: int, when: datetime) -> WorkUnit:
        return WorkUnit(
            operation_id=uuid4(),
            origin=InputOrigin.AGENT_LATERAL,
            handoff_basis=Recorded[str](value="c2h-from-a-future-c2"),
        )

    def observe(self, unit: WorkUnit, tick: int, when: datetime) -> Finding:
        return Finding(
            provenance=Provenance.RECOMMENDATION,
            disposition=Disposition.HOLD,
            summary="admitted on a recorded handoff",
            policy_execution=no_policy_execution("advisory pass, no gate"),
        )


class _AdmittedProbeRunner:
    """A probe whose input is admitted — the state that must never occur.

    It exists only so the alarm above can be fired in a test. Nothing registers
    it outside this module.
    """

    expects_refusal = True

    def __init__(self) -> None:
        self.identity = AgentIdentity(
            agent_id="admitted-probe",
            tier=AgentTier.TIER_1,
            actor=ActorRef(
                actor_id=ActorId("act_01M2P20SY00000000000000Z03"),
                actor_kind=ActorKind.AGENT_R,
                role="test probe",
                entitlement_refs=("CAOM-001:advisory",),
                authenticated=True,
            ),
        )

    def next_unit(self, tick: int, when: datetime) -> WorkUnit:
        # Operator-direct, so the admission rule lets it through: the point is a
        # probe whose input was admitted, however that came about.
        return WorkUnit(
            operation_id=uuid4(),
            origin=InputOrigin.OPERATOR_DIRECT,
            handoff_basis=OPERATOR_DIRECT_BASIS,
        )

    def observe(self, unit: WorkUnit, tick: int, when: datetime) -> Finding:
        # HOLD, not PASS: with no policy execution behind it a PASS is refused by
        # the envelope itself, which is a different invariant and not the one
        # under test here.
        return Finding(
            provenance=Provenance.RECOMMENDATION,
            disposition=Disposition.HOLD,
            summary="a probe that should have been refused",
            policy_execution=no_policy_execution("advisory pass, no gate"),
        )
