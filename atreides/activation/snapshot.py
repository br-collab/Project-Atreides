"""The agent state the Common Operating Picture reads (W3 § WP-A4, WP-A3; A-T4).

WP-A4 in one sentence: *an agent that has produced nothing renders as absent
with a reason, never as a pass and never as a blank that reads like one.* This
module is the shape that makes that possible on the other side of a network
boundary, before the same rule lands in the contracts.

Why a snapshot type at all
--------------------------
Legiones Cannenses (L.C., the Legate surface) never calls into Atreides. It
reads a document. So the absence has to survive serialisation: if
:class:`~cannae_kernel.absence.Absent` were flattened to ``null`` on the way out,
the surface would receive exactly the value R2 exists to abolish and would have
nothing truthful left to show. Every optional value here is
``Recorded[T] | Absent``, and both carry a ``state`` discriminator, so the
absence and its reason cross the wire intact.

The surface must be *able* to refuse
------------------------------------
WP-A3 requires the surface to refuse to render a state the record does not hold.
A surface can only do that if the record distinguishes the states — so
:attr:`AgentView.last_summary` is never an empty string standing in for "nothing
yet", and :attr:`AgentView.disposition` is never ``PASS`` on an agent that has
produced nothing. The reading is computed here, once, rather than in each
renderer, because the fifteen-defect class of Wave 2 was renderers each making
their own cheerful guess.

The probe reads inverted, and says so
-------------------------------------
:attr:`AgentView.expects_refusal` marks the standing lateral-handoff probe,
whose healthy state is to be refused. A consumer that ignored the flag would
report a working refusal as a failure; one that ignored the probe entirely would
lose the only continuous evidence that WP-A2 still holds. The flag is on the
record so neither has to be guessed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.effects import OperationEffects
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

from atreides.activation.outputs import ADVISORY_EFFECTS, AgentRefusal, AgentTier
from atreides.activation.supervisor import ActivationState, AgentState

__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "ActivationSnapshot",
    "AgentView",
    "RefusalView",
    "build_snapshot",
]

#: Bumped whenever a field is added, removed or changes meaning. The Legate
#: reader checks it and refuses a shape it does not know, rather than reading a
#: renamed field as absent — a source that changed shape cannot be trusted field
#: by field.
SNAPSHOT_SCHEMA_VERSION: Final = 1


class RefusalView(BaseModel):
    """A refusal, as the surface needs to show it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    observed_at: datetime


class AgentView(BaseModel):
    """One agent, with every empty slot carrying its reason."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    tier: AgentTier
    role: str = Field(min_length=1)
    up: bool
    expects_refusal: bool
    disposition: Disposition
    """Never ``PASS`` for an agent that has produced nothing: see
    :meth:`~atreides.activation.supervisor.AgentState.disposition`."""
    stopped_reason: Recorded[str] | Absent
    last_summary: Recorded[str] | Absent
    last_observed_at: Recorded[datetime] | Absent
    last_provenance: Recorded[Provenance] | Absent
    last_handoff_basis: Recorded[str] | Absent
    """The C2 (Command and Control) handoff the last output arrived under, or the
    recorded reason there is none — ``operator-direct under CAOM-001`` while no
    C2 runtime exists (AMD1 § 3b)."""
    last_refusal: Recorded[RefusalView] | Absent
    recommendations: int = Field(ge=0)
    refusals: int = Field(ge=0)


class ActivationSnapshot(BaseModel):
    """Everything Legate needs about Phase A, at one instant."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    domain: Domain = Domain.ATREIDES
    phase: str = "A"
    synthetic: bool = True
    """Phase A runs against the synthetic flow. Stated so no surface has to infer
    it, and so a reader is never left thinking these are venue facts."""
    taken_at: datetime
    tick: Recorded[int] | Absent
    """The last completed tick, or the reason none has run."""
    last_tick_at: Recorded[datetime] | Absent
    halted: bool
    """Server-side halt state, read from the halt context (A-T5). Never a control's
    own idea of whether it was pressed."""
    halt_reason: Recorded[str] | Absent
    disposition: Disposition
    effects: OperationEffects = ADVISORY_EFFECTS
    agents: tuple[AgentView, ...]


def _stopped_reason(state: AgentState) -> Recorded[str] | Absent:
    if state.stopped_reason is not None:
        return Recorded[str](value=state.stopped_reason)
    return Absent(
        kind=AbsenceKind.NOT_APPLICABLE,
        reason="this agent is running" if state.up else "no reason was recorded",
    )


def _basis_text(state: AgentState) -> Recorded[str] | Absent:
    """The last output's handoff basis, flattened to text but never to null.

    An ``Absent`` basis stays ``Absent`` and keeps its reason; a recorded one
    becomes the identifier. The one thing that cannot happen is the reason being
    dropped on the way to the surface.
    """
    if isinstance(state.last_output, Absent):
        return state.last_output
    basis = state.last_output.value.handoff_basis
    if isinstance(basis, Absent):
        return basis
    return Recorded[str](value=basis.value)


def _view(state: AgentState) -> AgentView:
    if isinstance(state.last_output, Absent):
        missing = state.last_output
        summary: Recorded[str] | Absent = missing
        observed_at: Recorded[datetime] | Absent = missing
        provenance: Recorded[Provenance] | Absent = missing
    else:
        output = state.last_output.value
        summary = Recorded[str](value=output.summary)
        observed_at = Recorded[datetime](value=output.observed_at)
        provenance = Recorded[Provenance](value=output.provenance)

    last_refusal: Recorded[RefusalView] | Absent
    if isinstance(state.last_refusal, Absent):
        last_refusal = state.last_refusal
    else:
        refusal: AgentRefusal = state.last_refusal.value
        last_refusal = Recorded[RefusalView](
            value=RefusalView(
                code=refusal.code.value,
                detail=refusal.refused_detail,
                observed_at=refusal.observed_at,
            )
        )

    return AgentView(
        agent_id=state.identity.agent_id,
        tier=state.identity.tier,
        role=state.identity.actor.role,
        up=state.up,
        expects_refusal=state.expects_refusal,
        disposition=state.disposition,
        stopped_reason=_stopped_reason(state),
        last_summary=summary,
        last_observed_at=observed_at,
        last_provenance=provenance,
        last_handoff_basis=_basis_text(state),
        last_refusal=last_refusal,
        recommendations=state.recommendations,
        refusals=state.refusals,
    )


def build_snapshot(state: ActivationState, *, taken_at: datetime) -> ActivationSnapshot:
    """Turn the supervisor's state into the document Legate reads.

    ``taken_at`` is passed in rather than read: the snapshot is a value, and a
    value that samples the wall clock cannot be compared with the one before it.
    """
    tick: Recorded[int] | Absent
    if state.tick < 0:
        tick = Absent(
            kind=AbsenceKind.NOT_YET_KNOWN,
            reason="no tick has completed since activation started",
        )
    else:
        tick = Recorded[int](value=state.tick)
    return ActivationSnapshot(
        taken_at=taken_at,
        tick=tick,
        last_tick_at=state.last_tick_at,
        halted=state.halted,
        halt_reason=state.halt_reason,
        disposition=state.disposition,
        agents=tuple(_view(agent) for agent in state.agents),
    )
