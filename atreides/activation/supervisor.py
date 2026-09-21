"""Running the agents continuously, and the state that produces (W3 § WP-A1, A-T5).

Before this work package the agents ran when something called them. WP-A1 asks
for them to run *continuously against the synthetic flow*, so that the Common
Operating Picture has something current to show and so that the escalation paths
are exercised rather than merely present. :class:`AgentSupervisor` is that loop's
body: one :meth:`AgentSupervisor.tick` is one pass over every registered agent.

The loop is a function of its inputs
------------------------------------
A tick takes the time it runs at. Nothing here reads the wall clock, starts a
thread or sleeps, so the whole of activation can be replayed: the same ticks
against the same flow produce the same outputs, byte for byte. Driving it on a
timer is the caller's business and stays outside this module, where it can be
tested for what it is.

What a tick does to one agent
-----------------------------
1. **Halt first (A-T5).** If a halt covering Atreides is in effect, the agent
   refuses new work and the refusal is recorded. The halt is read from the
   context passed in — the server-side state — and never from anything a button
   set. The control that read "✓ SYSTEM HALTED" while the server kept executing
   is why this is the first thing checked and why it is checked here rather than
   inside each agent's own gates.
2. **The agent's own handoff check (WP-A2).** The input is admitted or refused
   by :func:`~atreides.activation.handoff.admit` at the consumer. A refused
   input produces a refusal record and no recommendation.
3. **The agent runs**, and its finding is wrapped in an
   :class:`~atreides.activation.outputs.AgentRecommendation` carrying
   provenance, a disposition and the handoff basis.

A stopped agent is absent, not quiet (WP-A4)
--------------------------------------------
:meth:`AgentSupervisor.stop` takes a reason and requires one. A stopped agent's
state carries that reason, and every derived value it would have produced is a
kernel ``Absent`` — so the surface above has something truthful to render and
never has to choose between a blank and a green. An agent that has simply not
produced anything yet is ``NOT_YET_KNOWN``; one that was stopped is
``NOTHING_RECORDED``. Those are different facts and the record keeps them apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar
from uuid import UUID

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext, gate_under_halt
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

from atreides.activation.handoff import (
    Admission,
    HandoffBasis,
    InputOrigin,
    admit,
)
from atreides.activation.outputs import (
    AgentIdentity,
    AgentOutput,
    AgentRecommendation,
    AgentRefusal,
    PolicyExecution,
    RefusalCode,
)

_ValueT = TypeVar("_ValueT")

__all__ = [
    "ActivationState",
    "AgentRunner",
    "AgentState",
    "AgentSupervisor",
    "Finding",
    "WorkUnit",
]


class Finding(BaseModel):
    """What an agent concluded about one unit of work.

    The agent-specific part of an output. The supervisor supplies everything
    else — identity, handoff basis, admission, effects — so that no runner can
    forget an envelope invariant, and so that adding an agent cannot weaken one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provenance: Provenance
    disposition: Disposition
    summary: str = Field(min_length=1)
    policy_execution: Recorded[PolicyExecution] | Absent


@dataclass(frozen=True)
class WorkUnit:
    """One unit of work from the flow, with how it reached the agent."""

    operation_id: UUID
    origin: InputOrigin
    handoff_basis: HandoffBasis | None
    """The basis this work arrived under.

    ``None`` is representable on purpose. A runner that never states the basis is
    exactly the defect A-T6 names, and a type that made it unrepresentable here
    would move the failure to whatever built the unit instead of catching it at
    the agent. The supervisor refuses it and records the refusal; see
    :func:`~atreides.activation.handoff.basis_from_lineage` for the conversion
    that produces a stated basis from a lineage stub."""


class AgentRunner(Protocol):
    """An activated agent, as the supervisor needs to see it.

    Deliberately narrow. A runner adapts one existing agent; it does not get to
    decide what an output looks like, whether an input was admissible or what
    happens under a halt.
    """

    @property
    def identity(self) -> AgentIdentity: ...

    @property
    def expects_refusal(self) -> bool:
        """True for a standing probe whose healthy state is to be refused.

        A probe that offers an inadmissible input on every tick is working when
        its input is refused, and broken when it is not. Without this, a probe
        doing its job would hold the whole picture at BLOCK for ever, and a board
        that is permanently red hides a real failure exactly as well as one that
        is permanently green.
        """
        ...

    def next_unit(self, tick: int, at: datetime) -> WorkUnit:
        """The unit of work this agent takes on ``tick``."""
        ...

    def observe(self, unit: WorkUnit, tick: int, at: datetime) -> Finding:
        """Run the agent over ``unit``. Advisory only: it authorizes nothing."""
        ...


@dataclass(frozen=True)
class AgentState:
    """One agent's state, as the Common Operating Picture needs it (WP-A4)."""

    identity: AgentIdentity
    up: bool
    expects_refusal: bool
    """True for a standing probe: see :attr:`AgentRunner.expects_refusal`."""
    stopped_reason: str | None
    last_output: Recorded[AgentOutput] | Absent
    """The newest output of either kind, or the recorded reason there is none."""
    last_recommendation: Recorded[AgentRecommendation] | Absent
    last_refusal: Recorded[AgentRefusal] | Absent
    recommendations: int
    refusals: int

    @property
    def disposition(self) -> Disposition:
        """The worst thing this agent has to say, and never a pass on silence.

        A stopped agent, or one that has produced nothing, is ``INDETERMINATE``
        — the kernel's answer for any absence, reached by asking the absence
        rather than by a rule written again here.

        For a probe the reading inverts: a refusal is the healthy outcome and a
        recommendation means an inadmissible input was admitted, which is the
        one failure WP-A2 exists to prevent and so is ``BLOCK``.
        """
        if isinstance(self.last_output, Absent):
            return self.last_output.disposition
        output = self.last_output.value
        if self.expects_refusal:
            if isinstance(output, AgentRefusal):
                return Disposition.PASS
            return Disposition.BLOCK
        return output.disposition


@dataclass(frozen=True)
class ActivationState:
    """Every agent's state after a tick, plus the halt as the server has it."""

    tick: int
    last_tick_at: Recorded[datetime] | Absent
    """When the last tick ran, or the recorded reason none has."""
    halted: bool
    """Read from the halt context, which is server-side state (A-T5)."""
    halt_reason: Recorded[str] | Absent
    agents: tuple[AgentState, ...]

    @property
    def disposition(self) -> Disposition:
        """The worst of every agent's, so silence anywhere is visible above."""
        worst = Disposition.PASS
        order = {
            Disposition.PASS: 0,
            Disposition.HOLD: 1,
            Disposition.INDETERMINATE: 2,
            Disposition.BLOCK: 3,
        }
        for agent in self.agents:
            if order[agent.disposition] > order[worst]:
                worst = agent.disposition
        return worst


def _never_ran() -> Absent:
    return Absent(
        kind=AbsenceKind.NOT_YET_KNOWN,
        reason="this agent has not produced an output since activation started",
    )


def _stopped(reason: str) -> Absent:
    return Absent(
        kind=AbsenceKind.NOTHING_RECORDED,
        reason=f"agent stopped: {reason}",
    )


@dataclass
class _Slot:
    runner: AgentRunner
    up: bool = True
    stopped_reason: str | None = None
    last_output: AgentOutput | None = None
    last_recommendation: AgentRecommendation | None = None
    last_refusal: AgentRefusal | None = None
    recommendations: int = 0
    refusals: int = 0


@dataclass
class AgentSupervisor:
    """Runs every registered agent once per tick and keeps the resulting state.

    Not thread-safe and deliberately so: one supervisor, one loop, one caller.
    Concurrency belongs to whatever drives :meth:`tick`, where it can be seen.
    """

    runners: Sequence[AgentRunner]
    _slots: dict[str, _Slot] = field(init=False, default_factory=dict)
    _tick: int = field(init=False, default=-1)
    _at: datetime | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        for runner in self.runners:
            agent_id = runner.identity.agent_id
            if agent_id in self._slots:
                raise ValueError(f"two agents registered under {agent_id!r}")
            self._slots[agent_id] = _Slot(runner=runner)

    # Lifecycle ------------------------------------------------------------------------

    def stop(self, agent_id: str, reason: str) -> None:
        """Stop an agent. The reason is required and is what the surface shows."""
        if not reason.strip():
            raise ValueError("stopping an agent requires a reason; the surface shows it")
        slot = self._slot(agent_id)
        slot.up = False
        slot.stopped_reason = reason

    def start(self, agent_id: str) -> None:
        slot = self._slot(agent_id)
        slot.up = True
        slot.stopped_reason = None

    def _slot(self, agent_id: str) -> _Slot:
        try:
            return self._slots[agent_id]
        except KeyError:
            raise KeyError(f"no agent registered under {agent_id!r}") from None

    # The loop -------------------------------------------------------------------------

    def tick(self, at: datetime, *, halt: HaltContext | None = None) -> ActivationState:
        """One pass over every agent that is up. Returns the state it produced."""
        self._tick += 1
        self._at = at
        halted = halt is not None and gate_under_halt(halt, Domain.ATREIDES) is Disposition.BLOCK
        for slot in self._slots.values():
            if not slot.up:
                continue
            output = self._run_one(slot, self._tick, at, halt=halt, halted=halted)
            slot.last_output = output
            if isinstance(output, AgentRefusal):
                slot.last_refusal = output
                slot.refusals += 1
            else:
                slot.last_recommendation = output
                slot.recommendations += 1
        return self.state(halt=halt)

    def _run_one(
        self,
        slot: _Slot,
        tick: int,
        at: datetime,
        *,
        halt: HaltContext | None,
        halted: bool,
    ) -> AgentOutput:
        runner = slot.runner
        unit = runner.next_unit(tick, at)
        decision = admit(unit.origin, unit.handoff_basis)
        if halted:
            assert halt is not None
            return self._halt_refusal(runner.identity, unit, decision, at, halt)
        if not decision.admitted:
            return self._handoff_refusal(runner.identity, unit, decision, at)
        finding = runner.observe(unit, tick, at)
        return AgentRecommendation(
            agent=runner.identity,
            operation_id=unit.operation_id,
            observed_at=at,
            provenance=finding.provenance,
            disposition=finding.disposition,
            # The admission's basis, not the unit's: they are the same value
            # wherever the unit stated one, and where it did not the admission
            # holds the recorded absence that replaced the null.
            handoff_basis=decision.basis,
            admission=decision,
            policy_execution=finding.policy_execution,
            summary=finding.summary,
        )

    @staticmethod
    def _halt_refusal(
        identity: AgentIdentity,
        unit: WorkUnit,
        decision: Admission,
        at: datetime,
        halt: HaltContext,
    ) -> AgentRefusal:
        return AgentRefusal(
            agent=identity,
            operation_id=unit.operation_id,
            observed_at=at,
            provenance=Provenance.POLICY_RESULT,
            disposition=Disposition.BLOCK,
            handoff_basis=decision.basis,
            admission=decision,
            policy_execution=Recorded[PolicyExecution](
                value=PolicyExecution(
                    policy="cannae_kernel.halt.gate_under_halt",
                    gates=("halt_covers_atreides",),
                    outcome=Disposition.BLOCK,
                )
            ),
            summary=f"New work refused: halt {halt.halt_id} is active",
            code=RefusalCode.HALT_ACTIVE,
            refused_detail=(
                f"Refused: halt {halt.halt_id} (version {halt.version}) is active and covers "
                f"Atreides: {halt.reason}. Every agent refuses new work while it is in "
                f"effect (ATR-I-06, A-T5). This refusal reflects the halt context the "
                f"server holds, not a control a surface displayed."
            ),
        )

    @staticmethod
    def _handoff_refusal(
        identity: AgentIdentity,
        unit: WorkUnit,
        decision: Admission,
        at: datetime,
    ) -> AgentRefusal:
        code = (
            RefusalCode.HANDOFF_BASIS_NULL
            if unit.handoff_basis is None
            else RefusalCode.NO_RECORDED_HANDOFF
        )
        return AgentRefusal(
            agent=identity,
            operation_id=unit.operation_id,
            observed_at=at,
            provenance=Provenance.POLICY_RESULT,
            disposition=Disposition.BLOCK,
            handoff_basis=decision.basis,
            admission=decision,
            policy_execution=Recorded[PolicyExecution](
                value=PolicyExecution(
                    policy="atreides.activation.handoff.admit",
                    gates=("input_carries_a_recorded_handoff_authorization",),
                    outcome=Disposition.BLOCK,
                )
            ),
            summary="Input refused at the receiving agent's own type check",
            code=code,
            refused_detail=decision.detail,
        )

    # State ----------------------------------------------------------------------------

    def state(self, *, halt: HaltContext | None = None) -> ActivationState:
        """The current state. Safe to call before any tick; the absences say so."""
        halted = halt is not None and gate_under_halt(halt, Domain.ATREIDES) is Disposition.BLOCK
        halt_reason: Recorded[str] | Absent
        if halted and halt is not None:
            halt_reason = Recorded[str](value=halt.reason)
        else:
            halt_reason = Absent(
                kind=AbsenceKind.NOT_APPLICABLE,
                reason="no halt covering Atreides is in effect",
            )
        last_tick_at: Recorded[datetime] | Absent
        if self._at is None:
            last_tick_at = Absent(
                kind=AbsenceKind.NOT_YET_KNOWN,
                reason="no tick has run since this supervisor was built",
            )
        else:
            last_tick_at = Recorded[datetime](value=self._at)
        return ActivationState(
            tick=self._tick,
            last_tick_at=last_tick_at,
            halted=halted,
            halt_reason=halt_reason,
            agents=tuple(self._state_of(slot) for slot in self._slots.values()),
        )

    @staticmethod
    def _state_of(slot: _Slot) -> AgentState:
        """One agent's state, with every empty slot given a reason.

        ``NOTHING_RECORDED`` for a stopped agent — it produced nothing and will
        not now — against ``NOT_YET_KNOWN`` for one that is up and has simply not
        reached its first tick. A surface that showed both as blank would be
        claiming they are the same, and they are not.
        """
        reason = slot.stopped_reason
        stopped = not slot.up and reason is not None
        missing = _stopped(reason) if stopped and reason is not None else _never_ran()

        # A stopped agent has no *current* state, whatever it last produced.
        # Carrying the last recommendation forward is how a stopped agent comes
        # to render as a pass — the fifteen-defect class of Wave 2, arriving on a
        # new surface. The counts stay, because how much it produced while it ran
        # is history and history did happen.
        def recorded_or(value: _ValueT | None) -> Recorded[_ValueT] | Absent:
            if stopped or value is None:
                return missing
            return Recorded[_ValueT](value=value)

        return AgentState(
            identity=slot.runner.identity,
            up=slot.up,
            expects_refusal=slot.runner.expects_refusal,
            stopped_reason=reason,
            last_output=recorded_or(slot.last_output),
            last_recommendation=recorded_or(slot.last_recommendation),
            last_refusal=recorded_or(slot.last_refusal),
            recommendations=slot.recommendations,
            refusals=slot.refusals,
        )
