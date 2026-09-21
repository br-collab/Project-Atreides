"""Phase A of agent activation: advisory, continuous, and authorizing nothing.

Per the tasking order ``_tasking/W3-agent-activation.md`` and its amendment
``W3-agent-activation-AMD1.md``. CAOM = Consolidated Authority Operating Mode.
C2 = Command and Control. COP = Common Operating Picture.

**Authority delta: zero.** CAOM-001 already governs these agents: they provide
analysis, surface signals and enforce pre-configured doctrine rules; they do not
make approval decisions; every approval gate requires explicit operator action.
Phase A wires existing agents to already-published doctrine and already-published
contracts. It adds no orchestration design, and in particular nothing that
issues a handoff, assembles a lineage record or packages an escalation — those
are Phase B and are held on the Research Charter § 18.5 decision (AMD1 § 4).

The modules
-----------
- :mod:`~atreides.activation.handoff` — WP-A2. The receiving agent's own type
  check, which refuses any input that did not arrive with a recorded handoff
  authorization. The load-bearing one.
- :mod:`~atreides.activation.outputs` — the advisory output envelope: provenance,
  disposition, the handoff basis that is never null, and a declared effect set.
- :mod:`~atreides.activation.synthetic` — the synthetic flow the agents run
  against. Every value in it is invented and it reaches nothing outside this
  process.
- :mod:`~atreides.activation.supervisor` — WP-A1. One tick, every agent, halt
  checked first against server-side state.
- :mod:`~atreides.activation.runners` — thin adapters over the three existing
  agents, plus the standing lateral-handoff probe.
- :mod:`~atreides.activation.snapshot` — WP-A4. The serialisable state the COP
  reads, in which an agent that produced nothing is absent *with a reason*.
"""

from atreides.activation.handoff import (
    OPERATOR_DIRECT_BASIS,
    Admission,
    HandoffBasis,
    InputOrigin,
    RefusedAtConsumerError,
    admit,
    basis_from_lineage,
    require_handoff,
)
from atreides.activation.outputs import (
    ADVISORY_EFFECTS,
    AgentIdentity,
    AgentOutput,
    AgentRecommendation,
    AgentRefusal,
    AgentTier,
    PolicyExecution,
    RefusalCode,
    refuse_lifecycle_transition,
)
from atreides.activation.runners import default_runners
from atreides.activation.supervisor import (
    ActivationState,
    AgentRunner,
    AgentState,
    AgentSupervisor,
    Finding,
    WorkUnit,
)

__all__ = [
    "ADVISORY_EFFECTS",
    "OPERATOR_DIRECT_BASIS",
    "ActivationState",
    "Admission",
    "AgentIdentity",
    "AgentOutput",
    "AgentRecommendation",
    "AgentRefusal",
    "AgentRunner",
    "AgentState",
    "AgentSupervisor",
    "AgentTier",
    "Finding",
    "HandoffBasis",
    "InputOrigin",
    "PolicyExecution",
    "RefusalCode",
    "RefusedAtConsumerError",
    "WorkUnit",
    "admit",
    "basis_from_lineage",
    "default_runners",
    "refuse_lifecycle_transition",
    "require_handoff",
]
