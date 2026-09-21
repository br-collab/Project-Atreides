"""What an activated agent is allowed to emit (W3 § WP-A1, WP-A4; A-T1, A-T2, A-T6).

Authority delta: zero. CAOM-001 (Consolidated Authority Operating Mode) already
governs these agents and its terms are unchanged — *agents provide analysis,
surface signals and enforce pre-configured doctrine rules; agents do not make
approval decisions; every approval gate requires explicit operator action*.
Nothing here widens that. What it does is make the boundary a type rather than a
convention, so an agent cannot step over it by accident.

Three invariants, each earned
-----------------------------
**A-T1 — provenance is mandatory, and ``POLICY_RESULT`` has to be true.**
Every output states what kind of claim it is. ``POLICY_RESULT`` means *a
deterministic gate ran and this is what it returned*, so an output claiming it
must carry the execution that backs it. An advisory opinion labelled as a policy
result is the most expensive kind of wrong value in this programme: it is the one
a downstream reader stops questioning.

**A-T2 — an agent output never moves a lifecycle object.**
:func:`refuse_lifecycle_transition` is the only entry point from an agent
observation to a lifecycle transition, and it has no success path. It returns the
refusal as a record to be written, because a refusal nobody can read afterwards
is indistinguishable from work that never happened.

**A-T6 — the handoff basis is never a bare null (AMD1 § 3b).**
``handoff_basis`` has no default. A record that omits it cannot be constructed,
and ``None`` is refused rather than coerced. Absence is stated with its reason —
:data:`~atreides.activation.handoff.OPERATOR_DIRECT_BASIS` while no C2 (Command
and Control) runtime exists — or it is not stated at all.

Missing evidence never reads as a pass
--------------------------------------
Where :attr:`policy_execution` is absent, the disposition may not be ``PASS``
(AUR-I-10, ATR-I-05, and the standing constraint in the tasking order). The
kernel already answers this for any absence — ``Absent.disposition`` is
``INDETERMINATE`` — and the validator here stops an output from claiming
otherwise alongside it.

External effects are declared, not assumed
------------------------------------------
Every output carries an :class:`~cannae_kernel.effects.OperationEffects` built
from the kernel's effect vocabulary (W3 § R4; AMD1 § 3a forbids locally spelled
effect names). Advisory activation is *contained* — it sends nothing, pays
nothing, submits nothing, publishes nothing, writes no foreign store and spends
no metered third-party quota — and :data:`ADVISORY_EFFECTS` says so explicitly,
because the defect R4 exists to prevent is a containment claim nobody made on
purpose.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self
from uuid import UUID, uuid4

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.authority import AUTHORIZING_KINDS
from cannae_kernel.disposition import Disposition
from cannae_kernel.effects import OperationEffects
from cannae_kernel.ids import LifecycleId
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.activation.handoff import Admission, HandoffBasis

__all__ = [
    "ADVISORY_EFFECTS",
    "ADVISORY_PROVENANCE",
    "AgentIdentity",
    "AgentOutput",
    "AgentRecommendation",
    "AgentRefusal",
    "AgentTier",
    "PolicyExecution",
    "RefusalCode",
    "refuse_lifecycle_transition",
]

#: The kinds of claim an activated agent may make. Notably absent:
#: ``FACT_EXTERNAL`` and ``FACT_SYNTHETIC`` — an agent reports what it was told
#: by a venue or an emulator, it does not itself become the authority for it —
#: and ``HUMAN_JUDGMENT``, which no agent may ever claim.
ADVISORY_PROVENANCE: Final[frozenset[Provenance]] = frozenset(
    {Provenance.RECOMMENDATION, Provenance.FORECAST, Provenance.POLICY_RESULT}
)

#: Advisory activation reaches nothing outside this process. Stated, not assumed.
ADVISORY_EFFECTS: Final = OperationEffects(
    operation="atreides.activation.advisory_output",
    effects=(),
    note=(
        "Contained. An advisory agent output is analysis written to this process's own "
        "record: it sends nothing, pays nothing, submits nothing to a rail, publishes "
        "nothing outside the process, writes no store this process does not own, and "
        "spends no metered third-party allowance. Atreides never submits to a rail and "
        "never holds submission credentials, so the SUBMITS class cannot arise here."
    ),
)


class AgentTier(StrEnum):
    """Which tier of the Aureon Asset-Services Workforce an agent belongs to."""

    TIER_1 = "TIER_1"
    """Thifur-R: deterministic, zero variance, no path selection."""

    TIER_2 = "TIER_2"
    """Thifur-J: selects among pre-approved paths. Never invents one."""


class RefusalCode(StrEnum):
    """Why an agent's own type check refused. Each is a gate, not an error."""

    NO_RECORDED_HANDOFF = "NO_RECORDED_HANDOFF"
    """A lateral agent-to-agent input with no recorded C2 handoff (W3 § R1, WP-A2)."""

    HANDOFF_BASIS_NULL = "HANDOFF_BASIS_NULL"
    """The handoff basis was null rather than absent-with-reason (AMD1 § 3b, A-T6)."""

    LIFECYCLE_TRANSITION_FROM_AGENT = "LIFECYCLE_TRANSITION_FROM_AGENT"
    """An agent output was used to move a lifecycle object (A-T2)."""

    HALT_ACTIVE = "HALT_ACTIVE"
    """A halt covering Atreides is in effect; every agent refuses new work (A-T5)."""


class AgentIdentity(BaseModel):
    """Which agent produced an output, as a kernel actor reference.

    The actor kind is checked here rather than trusted: no agent class may
    authorize anything (JUM-D-07), so an identity whose kind sits in the kernel's
    :data:`~cannae_kernel.authority.AUTHORIZING_KINDS` is refused at construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    """Stable name, for example ``settlement-operations-analyst``."""
    tier: AgentTier
    actor: ActorRef

    @model_validator(mode="after")
    def _an_agent_may_not_authorize(self) -> Self:
        kind = self.actor.actor_kind
        if kind in AUTHORIZING_KINDS:
            raise ValueError(
                f"{kind.value} may authorize, so it is not an agent identity; agents "
                f"recommend and never authorize (JUM-D-07)"
            )
        if kind is ActorKind.AGENT_H:
            raise ValueError(
                "the adaptive Thifur-H class is Phase C and is not activated; it may not "
                "produce output in Phase A"
            )
        return self


class PolicyExecution(BaseModel):
    """Evidence that a deterministic gate actually ran, and what it returned.

    Required behind any output claiming ``POLICY_RESULT`` (A-T1). ``gates`` is
    the gate names in evaluation order, and it may not be empty: a policy that
    evaluated no gate did not execute, whatever it returned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy: str = Field(min_length=1)
    gates: tuple[str, ...] = Field(min_length=1)
    outcome: Disposition


class _AgentOutputBase(BaseModel):
    """What every activated agent output carries, whatever it says.

    ``handoff_basis`` has no default on purpose: A-T6 is enforced by the field
    existing rather than by a check that could be skipped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    output_id: UUID = Field(default_factory=uuid4)
    agent: AgentIdentity
    operation_id: UUID
    observed_at: datetime
    provenance: Provenance
    disposition: Disposition
    handoff_basis: HandoffBasis
    """The C2 handoff this work arrived under, or the recorded reason there is
    none. Never ``None`` (AMD1 § 3b)."""
    admission: Admission
    """The receiving agent's own decision about the input (WP-A2)."""
    effects: OperationEffects = ADVISORY_EFFECTS
    policy_execution: Recorded[PolicyExecution] | Absent
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _observed_at_is_utc(self) -> Self:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self

    @model_validator(mode="after")
    def _provenance_is_one_an_agent_may_claim(self) -> Self:
        if self.provenance not in ADVISORY_PROVENANCE:
            raise ValueError(
                f"an agent output may not claim {self.provenance.value}; allowed: "
                f"{', '.join(sorted(p.value for p in ADVISORY_PROVENANCE))}"
            )
        return self

    @model_validator(mode="after")
    def _policy_result_has_a_policy_behind_it(self) -> Self:
        """A-T1: no policy execution, no ``POLICY_RESULT``."""
        if self.provenance is Provenance.POLICY_RESULT and isinstance(
            self.policy_execution, Absent
        ):
            raise ValueError(
                f"an output with no policy execution behind it cannot be recorded as "
                f"POLICY_RESULT ({self.policy_execution.label})"
            )
        return self

    @model_validator(mode="after")
    def _absent_evidence_is_never_a_pass(self) -> Self:
        """AUR-I-10, ATR-I-05: missing required evidence is HOLD or INDETERMINATE."""
        if isinstance(self.policy_execution, Absent) and self.disposition is Disposition.PASS:
            raise ValueError(
                "an output with no policy execution behind it may not be recorded as PASS; "
                "missing evidence is HOLD or INDETERMINATE (AUR-I-10, ATR-I-05)"
            )
        return self

    @model_validator(mode="after")
    def _the_admission_describes_this_basis(self) -> Self:
        if self.admission.basis != self.handoff_basis:
            raise ValueError(
                "the admission decision and the recorded handoff basis disagree; the "
                "output would describe an input the agent did not admit"
            )
        return self


class AgentRecommendation(_AgentOutputBase):
    """Advice. It authorizes nothing and moves nothing (CAOM-001).

    ``disposition`` is the outcome this agent *recommends* to the operator, not
    a decision. Every approval gate still requires explicit operator action.
    """

    kind: Literal["agent_recommendation"] = "agent_recommendation"

    @model_validator(mode="after")
    def _an_admitted_input_lies_behind_it(self) -> Self:
        if not self.admission.admitted:
            raise ValueError(
                "a recommendation cannot be built on a refused input; record an "
                "AgentRefusal instead"
            )
        return self


class AgentRefusal(_AgentOutputBase):
    """A refusal by the agent's own type check, written to the record.

    A refusal is a ``POLICY_RESULT``: a deterministic gate ran and returned
    ``BLOCK``. That is not a formality — it is what makes the refusal auditable
    as a thing the system decided, rather than as a gap where work should be.
    """

    kind: Literal["agent_refusal"] = "agent_refusal"
    code: RefusalCode
    refused_detail: str = Field(min_length=1)
    lifecycle_id: LifecycleId | None = None
    """Set only for :attr:`RefusalCode.LIFECYCLE_TRANSITION_FROM_AGENT`."""

    @model_validator(mode="after")
    def _a_refusal_blocks(self) -> Self:
        if self.disposition is not Disposition.BLOCK:
            raise ValueError("a refusal is recorded as BLOCK")
        if self.provenance is not Provenance.POLICY_RESULT:
            raise ValueError("a refusal is a POLICY_RESULT: a gate ran and returned BLOCK")
        return self


AgentOutput = AgentRecommendation | AgentRefusal


def refuse_lifecycle_transition(
    *,
    agent: AgentIdentity,
    operation_id: UUID,
    lifecycle_id: LifecycleId,
    from_state: str,
    to_state: str,
    observed_at: datetime,
    handoff_basis: HandoffBasis,
    admission: Admission,
) -> AgentRefusal:
    """A-T2. The only route from an agent output to a lifecycle transition.

    It has no success path and no parameter that opens one. The transition is
    refused and the refusal is returned as a record for the caller to persist,
    so that "the agent tried to move this object" is a fact in the journal rather
    than an absence in it.

    Agents recommend a transition; an operator makes it. That is CAOM-001, and
    this function is where the difference stops being a sentence in a document.
    """
    detail = (
        f"Refused: agent {agent.agent_id!r} attempted to transition lifecycle "
        f"{lifecycle_id} from {from_state!r} to {to_state!r} directly from an agent "
        f"output. Agents do not make approval decisions and every approval gate "
        f"requires explicit operator action (CAOM-001). The transition did not occur."
    )
    return AgentRefusal(
        agent=agent,
        operation_id=operation_id,
        observed_at=observed_at,
        provenance=Provenance.POLICY_RESULT,
        disposition=Disposition.BLOCK,
        handoff_basis=handoff_basis,
        admission=admission,
        policy_execution=Recorded[PolicyExecution](
            value=PolicyExecution(
                policy="atreides.activation.lifecycle_transition_boundary",
                gates=("agent_output_may_not_transition_a_lifecycle_object",),
                outcome=Disposition.BLOCK,
            )
        ),
        summary=f"Lifecycle transition refused for {lifecycle_id}",
        code=RefusalCode.LIFECYCLE_TRANSITION_FROM_AGENT,
        refused_detail=detail,
        lifecycle_id=lifecycle_id,
    )


def no_policy_execution(reason: str) -> Absent:
    """The recorded absence of a policy execution, with its reason.

    A helper so that call sites state the reason rather than reaching for
    ``None``. ``NOTHING_RECORDED``: an advisory pass over a flow runs no
    deterministic gate, and none will arrive later for this observation.
    """
    return Absent(kind=AbsenceKind.NOTHING_RECORDED, reason=reason)
