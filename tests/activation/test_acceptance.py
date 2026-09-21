"""The six Phase A acceptance tests, A-T1 to A-T6.

Named and ordered as ``_tasking/W3-agent-activation.md`` names them, with A-T6
added by ``W3-agent-activation-AMD1.md`` § 3b. Each must fail before the change
and pass after. They are kept in one module, separate from the unit tests, so
that "did Phase A meet its acceptance criteria" is one file and one answer.

A-T5 is written against the server-side halt state on purpose. The tasking order
is blunt about why: the halt control that read "✓ SYSTEM HALTED" while the
server kept executing was found six hours before the order was written.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.disposition import Disposition
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import LifecycleId
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.activation import (
    OPERATOR_DIRECT_BASIS,
    AgentIdentity,
    AgentRecommendation,
    AgentRefusal,
    AgentSupervisor,
    Finding,
    InputOrigin,
    RefusedAtConsumerError,
    admit,
    refuse_lifecycle_transition,
    require_handoff,
)
from atreides.activation.outputs import PolicyExecution, RefusalCode, no_policy_execution
from atreides.activation.snapshot import AgentView, build_snapshot
from atreides.activation.supervisor import WorkUnit

LIFECYCLE = LifecycleId("lif_01M2P20SY00000000000000001")


def _first_output(supervisor: AgentSupervisor, agent_id: str) -> AgentRecommendation | AgentRefusal:
    state = next(a for a in supervisor.state().agents if a.identity.agent_id == agent_id)
    assert isinstance(state.last_output, Recorded)
    return state.last_output.value


# A-T1 ------------------------------------------------------------------------------------


class TestAT1ProvenanceIsCarriedAndPolicyResultIsEarned:
    """Every agent output carries provenance; an output with no policy execution
    behind it cannot be recorded as ``POLICY_RESULT``."""

    def test_every_output_of_a_tick_carries_provenance(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        state = supervisor.tick(at)
        assert state.agents, "the tick produced no agent state at all"
        for agent in state.agents:
            assert isinstance(agent.last_output, Recorded)
            output = agent.last_output.value
            assert isinstance(output.provenance, Provenance)

    def test_policy_result_without_a_policy_execution_is_refused(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """The claim and the evidence for it are checked together, at construction."""
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        assert template.provenance is Provenance.POLICY_RESULT

        with pytest.raises(ValidationError, match="cannot be recorded as POLICY_RESULT"):
            AgentRecommendation(
                agent=template.agent,
                operation_id=template.operation_id,
                observed_at=at,
                provenance=Provenance.POLICY_RESULT,
                # HOLD, not PASS: this test is about the POLICY_RESULT claim, and
                # a PASS would also trip the absent-evidence rule below it.
                disposition=Disposition.HOLD,
                handoff_basis=template.handoff_basis,
                admission=template.admission,
                policy_execution=no_policy_execution("no deterministic gate ran"),
                summary="an opinion dressed as a policy result",
            )

    def test_the_same_output_is_fine_when_it_claims_only_a_recommendation(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """Advice with no gate behind it is allowed — it just may not claim to be
        a policy result. The rule bites the claim, not the absence."""
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        advice = AgentRecommendation(
            agent=template.agent,
            operation_id=template.operation_id,
            observed_at=at,
            provenance=Provenance.RECOMMENDATION,
            disposition=Disposition.HOLD,
            handoff_basis=template.handoff_basis,
            admission=template.admission,
            policy_execution=no_policy_execution("no deterministic gate ran"),
            summary="advice, and labelled as advice",
        )
        assert advice.provenance is Provenance.RECOMMENDATION

    def test_absent_evidence_may_not_be_recorded_as_a_pass(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """AUR-I-10, ATR-I-05 and the order's standing constraint, in one place."""
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        with pytest.raises(ValidationError, match="may not be recorded as PASS"):
            AgentRecommendation(
                agent=template.agent,
                operation_id=template.operation_id,
                observed_at=at,
                provenance=Provenance.RECOMMENDATION,
                disposition=Disposition.PASS,
                handoff_basis=template.handoff_basis,
                admission=template.admission,
                policy_execution=no_policy_execution("no deterministic gate ran"),
                summary="a pass with nothing behind it",
            )

    def test_an_agent_may_not_claim_a_provenance_reserved_for_others(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """No agent reports a venue fact as its own, and none claims human judgment."""
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        for claimed in (Provenance.FACT_EXTERNAL, Provenance.HUMAN_JUDGMENT):
            with pytest.raises(ValidationError, match="may not claim"):
                AgentRecommendation(
                    agent=template.agent,
                    operation_id=template.operation_id,
                    observed_at=at,
                    provenance=claimed,
                    disposition=Disposition.HOLD,
                    handoff_basis=template.handoff_basis,
                    admission=template.admission,
                    policy_execution=template.policy_execution,
                    summary="a claim this agent is not entitled to make",
                )

    def test_a_policy_execution_that_evaluated_no_gate_is_not_an_execution(self) -> None:
        with pytest.raises(ValidationError):
            PolicyExecution(policy="p", gates=(), outcome=Disposition.PASS)


# A-T2 ------------------------------------------------------------------------------------


class TestAT2AgentOutputNeverTransitionsALifecycleObject:
    """An attempt to transition a lifecycle object directly from an agent output
    is refused, and the refusal is written to the record."""

    def test_the_attempt_is_refused_and_returns_a_record(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        supervisor.tick(at)
        output = _first_output(supervisor, "settlement-operations-analyst")
        refusal = refuse_lifecycle_transition(
            agent=output.agent,
            operation_id=output.operation_id,
            lifecycle_id=LIFECYCLE,
            from_state="INSTRUCTED",
            to_state="SETTLED",
            observed_at=at,
            handoff_basis=output.handoff_basis,
            admission=output.admission,
        )
        assert isinstance(refusal, AgentRefusal)
        assert refusal.disposition is Disposition.BLOCK
        assert refusal.code is RefusalCode.LIFECYCLE_TRANSITION_FROM_AGENT
        assert refusal.lifecycle_id == LIFECYCLE

    def test_the_refusal_is_written_to_the_record_with_its_reason(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        supervisor.tick(at)
        output = _first_output(supervisor, "settlement-operations-analyst")
        refusal = refuse_lifecycle_transition(
            agent=output.agent,
            operation_id=output.operation_id,
            lifecycle_id=LIFECYCLE,
            from_state="INSTRUCTED",
            to_state="SETTLED",
            observed_at=at,
            handoff_basis=output.handoff_basis,
            admission=output.admission,
        )
        # A record, not a log line: it round-trips and keeps its reason.
        replayed = AgentRefusal.model_validate(refusal.model_dump())
        assert replayed == refusal
        assert "SETTLED" in replayed.refused_detail
        assert "did not occur" in replayed.refused_detail
        assert isinstance(replayed.policy_execution, Recorded)
        assert replayed.policy_execution.value.outcome is Disposition.BLOCK

    def test_there_is_no_success_path(self) -> None:
        """The refusal function returns a refusal for every input it accepts."""
        import inspect

        from atreides.activation import outputs

        source = inspect.getsource(outputs.refuse_lifecycle_transition)
        assert source.count("return ") == 1, (
            "refuse_lifecycle_transition has gained a second return; a lifecycle "
            "transition from an agent output must have no success path (A-T2)"
        )


# A-T3 ------------------------------------------------------------------------------------


class TestAT3LateralInputIsRefusedByTheConsumersOwnTypeCheck:
    """A lateral agent-to-agent input, with no recorded handoff authorization, is
    refused **by the receiving agent's own type check** — not by a filter above it."""

    def test_the_consumer_refuses_with_nothing_above_it(self) -> None:
        """No supervisor, no registry, no caller. Only the check the agent runs."""
        decision = admit(InputOrigin.AGENT_LATERAL, OPERATOR_DIRECT_BASIS)
        assert decision.disposition is Disposition.BLOCK
        assert not decision.admitted
        assert "receiving agent" in decision.detail

    def test_require_handoff_raises_and_carries_the_refusal(self) -> None:
        with pytest.raises(RefusedAtConsumerError) as raised:
            require_handoff(InputOrigin.AGENT_LATERAL, OPERATOR_DIRECT_BASIS)
        assert raised.value.decision.disposition is Disposition.BLOCK

    def test_even_if_a_filter_above_admitted_it_the_type_still_refuses(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """The assertion with teeth: bypass every layer above and try to build the
        recommendation anyway. The consumer's own type refuses it."""
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        refused = admit(InputOrigin.AGENT_LATERAL, OPERATOR_DIRECT_BASIS)
        assert not refused.admitted
        with pytest.raises(ValidationError, match="refused input"):
            AgentRecommendation(
                agent=template.agent,
                operation_id=template.operation_id,
                observed_at=at,
                provenance=Provenance.RECOMMENDATION,
                disposition=Disposition.HOLD,
                handoff_basis=refused.basis,
                admission=refused,
                policy_execution=no_policy_execution("lateral input was never run"),
                summary="a recommendation that should not exist",
            )

    def test_the_standing_probe_is_refused_on_every_tick(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        for offset in range(3):
            supervisor.tick(at + timedelta(minutes=offset))
        probe = next(
            a for a in supervisor.state().agents if a.identity.agent_id == "lateral-handoff-probe"
        )
        assert probe.refusals == 3
        assert probe.recommendations == 0
        assert isinstance(probe.last_refusal, Recorded)
        assert probe.last_refusal.value.code is RefusalCode.NO_RECORDED_HANDOFF

    def test_a_recorded_handoff_is_admitted_so_the_refusal_is_not_blanket(self) -> None:
        """The check refuses lateral input for want of an authorization, not
        because it refuses lateral input on principle. C2 must be able to grant
        one later without this rule having to change."""
        decision = admit(InputOrigin.AGENT_LATERAL, Recorded[str](value="c2h-issued-later"))
        assert decision.admitted


# A-T4 ------------------------------------------------------------------------------------


class TestAT4StoppedAgentRendersAbsentWithAReason:
    """With an agent stopped, the COP renders it absent-with-reason. The rendered
    string is not "pass", not "recorded", and not empty."""

    STOPPED = "the operator stopped this agent"

    def _snapshot_view(self, supervisor: AgentSupervisor, at: datetime) -> AgentView:
        supervisor.tick(at)
        supervisor.stop("fiat-operations-specialist", self.STOPPED)
        snapshot = build_snapshot(supervisor.state(), taken_at=at + timedelta(minutes=1))
        return next(a for a in snapshot.agents if a.agent_id == "fiat-operations-specialist")

    def test_the_rendered_string_names_the_absence_and_its_reason(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        view = self._snapshot_view(supervisor, at)
        assert isinstance(view.last_summary, Absent)
        rendered = view.last_summary.label
        assert rendered.strip(), "an absence rendered as empty is the defect, not the fix"
        assert "pass" not in rendered.lower()
        assert "recorded" not in rendered.lower().replace("nothing recorded", "")
        assert self.STOPPED in rendered

    def test_a_stopped_agent_is_never_a_pass(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        view = self._snapshot_view(supervisor, at)
        assert view.disposition is Disposition.INDETERMINATE
        assert view.up is False

    def test_the_last_recommendation_is_not_carried_forward_as_current(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """It produced a recommendation before it was stopped. That recommendation
        is not its current state, and a surface must not be handed it as one."""
        view = self._snapshot_view(supervisor, at)
        assert view.recommendations == 1, "the historical count is still a fact"
        assert isinstance(view.last_observed_at, Absent)
        assert isinstance(view.last_provenance, Absent)

    def test_an_agent_that_never_ran_is_a_different_absence(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """Not-yet-known is in flight; nothing-recorded is settled. A consumer that
        treated them alike would be making a claim it has not checked."""
        snapshot = build_snapshot(supervisor.state(), taken_at=at)
        never_ran = snapshot.agents[0]
        assert isinstance(never_ran.last_summary, Absent)
        assert never_ran.last_summary.kind is AbsenceKind.NOT_YET_KNOWN

        view = self._snapshot_view(supervisor, at)
        assert isinstance(view.last_summary, Absent)
        assert view.last_summary.kind is AbsenceKind.NOTHING_RECORDED

    def test_stopping_without_a_reason_is_refused(self, supervisor: AgentSupervisor) -> None:
        with pytest.raises(ValueError, match="requires a reason"):
            supervisor.stop("fiat-operations-specialist", "   ")


# A-T5 ------------------------------------------------------------------------------------


class TestAT5HaltIsReadFromServerState:
    """With halt engaged, every agent refuses new work and the picture reports
    halted **only** when the server-side state is halted."""

    def test_every_agent_refuses_new_work_under_halt(
        self, supervisor: AgentSupervisor, at: datetime, atreides_halt: HaltContext
    ) -> None:
        state = supervisor.tick(at, halt=atreides_halt)
        assert state.halted
        for agent in state.agents:
            assert isinstance(agent.last_output, Recorded)
            output = agent.last_output.value
            assert isinstance(output, AgentRefusal), f"{agent.identity.agent_id} did not refuse"
            assert output.code is RefusalCode.HALT_ACTIVE
            assert output.disposition is Disposition.BLOCK

    def test_the_halt_is_asserted_against_server_state_not_a_control(
        self, supervisor: AgentSupervisor, at: datetime, cleared_halt: HaltContext
    ) -> None:
        """A halt context exists and names Atreides, but its server-side ``active``
        is False. Nothing may report halted on the strength of the context's
        existence alone."""
        state = supervisor.tick(at, halt=cleared_halt)
        assert cleared_halt.active is False
        assert state.halted is False
        snapshot = build_snapshot(state, taken_at=at)
        assert snapshot.halted is False
        assert isinstance(snapshot.halt_reason, Absent)
        assert not any(
            isinstance(a.last_output, Recorded) and isinstance(a.last_output.value, AgentRefusal)
            and a.last_output.value.code is RefusalCode.HALT_ACTIVE
            for a in state.agents
        )

    def test_a_halt_scoped_elsewhere_does_not_halt_atreides(
        self, supervisor: AgentSupervisor, at: datetime, atreides_halt: HaltContext
    ) -> None:
        from cannae_kernel.domains import Domain

        elsewhere = atreides_halt.model_copy(update={"scope": (Domain.AUREON,)})
        state = supervisor.tick(at, halt=elsewhere)
        assert state.halted is False

    def test_the_snapshot_carries_the_halt_reason_when_halted(
        self, supervisor: AgentSupervisor, at: datetime, atreides_halt: HaltContext
    ) -> None:
        state = supervisor.tick(at, halt=atreides_halt)
        snapshot = build_snapshot(state, taken_at=at)
        assert snapshot.halted is True
        assert isinstance(snapshot.halt_reason, Recorded)
        assert snapshot.halt_reason.value == atreides_halt.reason


# A-T6 ------------------------------------------------------------------------------------


class TestAT6HandoffBasisIsNeverABareNull:
    """An agent output whose handoff basis is null, rather than
    absent-with-reason, is refused (AMD1 § 3b)."""

    def test_a_null_basis_is_refused_by_the_admission_rule(self) -> None:
        decision = admit(InputOrigin.OPERATOR_DIRECT, None)
        assert decision.disposition is Disposition.BLOCK
        assert isinstance(decision.basis, Absent)
        assert "null is not a record" in decision.basis.reason

    def test_an_output_cannot_be_constructed_with_a_null_basis(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        payload = template.model_dump()
        payload["handoff_basis"] = None
        with pytest.raises(ValidationError):
            type(template).model_validate(payload)

    def test_an_output_cannot_omit_the_basis_either(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        payload = template.model_dump()
        del payload["handoff_basis"]
        with pytest.raises(ValidationError):
            type(template).model_validate(payload)

    def test_a_runner_offering_a_null_basis_is_refused_and_recorded(
        self, supervisor: AgentSupervisor, at: datetime
    ) -> None:
        """End to end: the null reaches the supervisor from a runner, and what
        comes out is a recorded refusal, not a crash and not a recommendation."""

        class NullBasisRunner:
            expects_refusal = True

            def __init__(self, identity: AgentIdentity) -> None:
                self.identity = identity

            def next_unit(self, tick: int, when: datetime) -> WorkUnit:
                return WorkUnit(
                    operation_id=template.operation_id,
                    origin=InputOrigin.OPERATOR_DIRECT,
                    handoff_basis=None,
                )

            def observe(
                self, unit: WorkUnit, tick: int, when: datetime
            ) -> Finding:  # pragma: no cover - must not be reached
                raise AssertionError("a null handoff basis was admitted")

        supervisor.tick(at)
        template = _first_output(supervisor, "settlement-operations-analyst")
        solo = AgentSupervisor(runners=(NullBasisRunner(template.agent),))
        state = solo.tick(at)
        agent = state.agents[0]
        assert isinstance(agent.last_output, Recorded)
        refusal = agent.last_output.value
        assert isinstance(refusal, AgentRefusal)
        assert refusal.code is RefusalCode.HANDOFF_BASIS_NULL
        assert isinstance(refusal.handoff_basis, Absent)
        assert refusal.handoff_basis.reason

    def test_the_operator_direct_basis_is_the_absence_the_amendment_names(self) -> None:
        assert isinstance(OPERATOR_DIRECT_BASIS, Absent)
        assert OPERATOR_DIRECT_BASIS.kind is AbsenceKind.NOTHING_RECORDED
        assert OPERATOR_DIRECT_BASIS.reason == "operator-direct under CAOM-001"
        assert OPERATOR_DIRECT_BASIS.disposition is Disposition.INDETERMINATE
