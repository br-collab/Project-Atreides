"""Adapters that put the three existing agents under the supervisor (W3 § WP-A1).

No agent is reimplemented here and no gate is re-decided. Each runner calls the
agent's own published entry point, reads what it returned and states it as a
:class:`~atreides.activation.supervisor.Finding`. If a runner and its agent ever
disagree, the agent is right and the runner is the defect — which is why these
are thin enough to read in one sitting.

Why each output is a ``POLICY_RESULT``
--------------------------------------
All three agents are deterministic gate ladders: they evaluate named checks in a
fixed order and return what the checks said. That is precisely what
``POLICY_RESULT`` means, so each runner carries the gates it evaluated as the
:class:`~atreides.activation.outputs.PolicyExecution` behind the claim (A-T1).
A runner that could not name its gates would have to claim ``RECOMMENDATION``
instead, and the type system would make it — that is the check working, not a
formality.

What the advisory disposition means
-----------------------------------
``PASS`` here is *this agent found nothing that holds the operation*. It is not
an approval, and nothing downstream may treat it as one: CAOM-001 (Consolidated
Authority Operating Mode) requires explicit operator action at every approval
gate, and :class:`~atreides.activation.outputs.AgentRecommendation` authorizes
nothing by construction.

Input origin
------------
Every unit in the synthetic flow arrives ``OPERATOR_DIRECT`` under CAOM-001,
carrying the recorded absence that AMD1 § 3b requires while no C2 (Command and
Control) runtime exists. :class:`LateralProbeRunner` is the deliberate exception:
it offers a lateral input on every tick so that the refusal path is exercised
continuously rather than only in a test. An activation whose refusal path is
never taken cannot demonstrate that it works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cannae_kernel.absence import Recorded
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import ActorId
from cannae_kernel.provenance import Provenance

from atreides.activation import synthetic
from atreides.activation.handoff import (
    OPERATOR_DIRECT_BASIS,
    InputOrigin,
    basis_from_lineage,
)
from atreides.activation.outputs import AgentIdentity, AgentTier, PolicyExecution
from atreides.activation.supervisor import Finding, WorkUnit
from atreides.agents.tier1.investigation_outputs import InvestigationEscalation
from atreides.agents.tier1.settlement_investigation_analyst import (
    SettlementInvestigationAnalyst,
)
from atreides.agents.tier1.settlement_operations_analyst import (
    GATE_ORDER,
    validate_tasking,
)
from atreides.agents.tier2.fiat_operations_specialist import (
    FIATOperationsSpecialist,
    MagnitudeThresholdPolicy,
)
from atreides.agents.tier2.outputs import RoutingDecision
from atreides.agents.tier2.routing_tables import default_routing_tables
from atreides.dsor import DSORStore

__all__ = [
    "FiatOperationsRunner",
    "LateralProbeRunner",
    "SettlementInvestigationRunner",
    "SettlementOperationsRunner",
    "default_runners",
]


def _identity(agent_id: str, tier: AgentTier, kind: ActorKind, role: str) -> AgentIdentity:
    """An agent's identity. The actor id is derived from the name, not minted.

    A stable identifier across restarts, so the Common Operating Picture is
    describing the same agent after a redeploy as before one. The kernel refuses
    an actor kind that may authorize, which is checked in
    :class:`~atreides.activation.outputs.AgentIdentity`.
    """
    return AgentIdentity(
        agent_id=agent_id,
        tier=tier,
        actor=ActorRef(
            actor_id=ActorId(_ACTOR_IDS[agent_id]),
            actor_kind=kind,
            role=role,
            entitlement_refs=("CAOM-001:advisory",),
            authenticated=True,
        ),
    )


#: Fixed actor identifiers for the activated agents. Written down rather than
#: generated so that the same agent carries the same identifier across restarts
#: and across machines; a lineage record whose actor changed on redeploy would
#: not be one lineage record.
_ACTOR_IDS = {
    "settlement-operations-analyst": "act_01M2P20SY00000000000000A01",
    "settlement-investigation-analyst": "act_01M2P20SY00000000000000A02",
    "fiat-operations-specialist": "act_01M2P20SY00000000000000A03",
    "lateral-handoff-probe": "act_01M2P20SY00000000000000A04",
}


@dataclass
class SettlementOperationsRunner:
    """Tier 1 · Thifur-R, driven through its pure ``validate_tasking`` stage.

    The validation stage and not ``emit``: validation reads the tasking and
    returns what the gates said, selecting no route, creating no instruction
    reference, reading no clock and writing nothing. That separation was earned
    in Wave 2 — one ``run`` used to do both, so validating a clean tasking
    persisted telemetry carrying a rail acknowledgement before any instruction
    existed. Advisory activation wants exactly the half that has no effects.
    """

    identity: AgentIdentity = field(
        default_factory=lambda: _identity(
            "settlement-operations-analyst",
            AgentTier.TIER_1,
            ActorKind.AGENT_R,
            "Settlement Operations Analyst",
        )
    )

    expects_refusal: bool = False

    def next_unit(self, tick: int, at: datetime) -> WorkUnit:
        tasking = synthetic.settlement_tasking_unit(tick, at)
        return WorkUnit(
            operation_id=tasking.operation_id,
            origin=InputOrigin.OPERATOR_DIRECT,
            handoff_basis=basis_from_lineage(tasking.lineage_stub.c2_handoff_id),
        )

    def observe(self, unit: WorkUnit, tick: int, at: datetime) -> Finding:
        tasking = synthetic.settlement_tasking_unit(tick, at)
        validation = validate_tasking(tasking)
        gates = validation.checks_evaluated or GATE_ORDER
        if validation.passed:
            summary = f"Pre-routing gates clear for {tasking.rail.value}"
            disposition = Disposition.PASS
        else:
            code = validation.discrepancy_code
            summary = (
                f"Pre-routing hold ({code.value if code else 'unspecified'}): "
                f"{validation.failure_detail}"
            )
            disposition = Disposition.HOLD
        return Finding(
            provenance=Provenance.POLICY_RESULT,
            disposition=disposition,
            summary=summary,
            policy_execution=Recorded[PolicyExecution](
                value=PolicyExecution(
                    policy="atreides.agents.tier1.settlement_operations_analyst.validate_tasking",
                    gates=tuple(gates),
                    outcome=disposition,
                )
            ),
        )


@dataclass
class SettlementInvestigationRunner:
    """Tier 1 · Thifur-R, assembling a cash-leg evidence timeline each tick.

    The analyst persists what it assembles, so this runner owns an in-memory
    Decision System of Record (DSOR) store for the advisory pass. Advisory
    activation must not write the operational record: a recommendation is not a
    lifecycle fact, and a store shared with production would make it look like
    one. The store is SQLite ``:memory:`` and dies with the process, which is the
    correct lifetime for something that never was evidence.
    """

    identity: AgentIdentity = field(
        default_factory=lambda: _identity(
            "settlement-investigation-analyst",
            AgentTier.TIER_1,
            ActorKind.AGENT_R,
            "Settlement Investigation Analyst",
        )
    )
    analyst: SettlementInvestigationAnalyst = field(
        default_factory=SettlementInvestigationAnalyst
    )
    store: DSORStore = field(default_factory=lambda: DSORStore(":memory:"))

    expects_refusal: bool = False

    def next_unit(self, tick: int, at: datetime) -> WorkUnit:
        lineage = synthetic.investigation_lineage(tick, at)
        return WorkUnit(
            operation_id=lineage.operation_id,
            origin=InputOrigin.OPERATOR_DIRECT,
            handoff_basis=basis_from_lineage(lineage.c2_handoff_id),
        )

    def observe(self, unit: WorkUnit, tick: int, at: datetime) -> Finding:
        lineage = synthetic.investigation_lineage(tick, at)
        items, gaps = synthetic.investigation_unit(tick, at)
        output, _record = self.analyst.run(
            operation_id=lineage.operation_id,
            task_id=synthetic.synthetic_operation_id("investigation-task", tick),
            lineage_stub=lineage,
            observations=items,
            gaps=gaps,
            store=self.store,
            now=at,
        )
        if isinstance(output, InvestigationEscalation):
            disposition = Disposition.HOLD
            summary = (
                f"Investigation escalated ({output.discrepancy_code.value}): "
                f"{len([g for g in output.gaps if g.escalates])} source(s) unaccounted for"
            )
        else:
            disposition = Disposition.PASS
            summary = f"Evidence timeline complete: {len(output.items)} observations"
        return Finding(
            provenance=Provenance.POLICY_RESULT,
            disposition=disposition,
            summary=summary,
            policy_execution=Recorded[PolicyExecution](
                value=PolicyExecution(
                    policy="atreides.agents.tier1.settlement_investigation_analyst.run",
                    gates=("assemble_timeline", "account_for_every_expected_source"),
                    outcome=disposition,
                )
            ),
        )


@dataclass
class FiatOperationsRunner:
    """Tier 2 · Thifur-J, running one path-selection dimension each tick.

    Thifur-J selects among pre-approved paths; it never invents one. The
    guardrail sequence the agent runs is its own — eligibility, then
    jurisdictional attribution, then approved paths — and this runner reports
    which side of it the operation came out on.
    """

    identity: AgentIdentity = field(
        default_factory=lambda: _identity(
            "fiat-operations-specialist",
            AgentTier.TIER_2,
            ActorKind.AGENT_J,
            "FIAT Operations Specialist",
        )
    )
    agent: FIATOperationsSpecialist = field(
        default_factory=lambda: FIATOperationsSpecialist(
            routing_tables=default_routing_tables(),
            magnitude_threshold_policy=MagnitudeThresholdPolicy(),
        )
    )

    expects_refusal: bool = False

    def next_unit(self, tick: int, at: datetime) -> WorkUnit:
        request = synthetic.path_selection_unit(tick, at)
        return WorkUnit(
            operation_id=synthetic.synthetic_operation_id("fiat-operations-specialist", tick),
            origin=InputOrigin.OPERATOR_DIRECT,
            handoff_basis=basis_from_lineage(request.operation.lineage.c2_handoff_id),
        )

    def observe(self, unit: WorkUnit, tick: int, at: datetime) -> Finding:
        request = synthetic.path_selection_unit(tick, at)
        output = self.agent.select_multi_currency_rail_routing(
            request, currency="USD", jurisdiction="US"
        )
        if isinstance(output, RoutingDecision):
            disposition = Disposition.PASS
            summary = f"Path selected: {output.recommendation.chosen_path}"
        else:
            disposition = Disposition.HOLD
            summary = f"Routing escalated: {type(output).__name__}"
        return Finding(
            provenance=Provenance.POLICY_RESULT,
            disposition=disposition,
            summary=summary,
            policy_execution=Recorded[PolicyExecution](
                value=PolicyExecution(
                    policy=(
                        "atreides.agents.tier2.fiat_operations_specialist"
                        ".select_multi_currency_rail_routing"
                    ),
                    gates=(
                        "material_magnitude",
                        "guardrail_4_eligibility",
                        "guardrail_5_jurisdictional_attribution",
                        "guardrail_1_approved_paths",
                    ),
                    outcome=disposition,
                )
            ),
        )


@dataclass
class LateralProbeRunner:
    """Offers a lateral agent-to-agent input every tick, so it is refused every tick.

    Not a fourth agent: a standing probe of WP-A2. It presents work as though it
    had arrived from another agent, with no recorded C2 handoff — because nothing
    can issue one — and the receiving agent's own type check refuses it. The
    refusal is recorded, so the Common Operating Picture shows the refusal path
    working rather than asserting that it would.

    Its ``observe`` exists only to satisfy the protocol. Reaching it would mean
    a lateral input had been admitted with no recorded handoff, so it raises
    rather than returning a finding: a probe that silently started passing would
    be worse than no probe.
    """

    identity: AgentIdentity = field(
        default_factory=lambda: _identity(
            "lateral-handoff-probe",
            AgentTier.TIER_1,
            ActorKind.AGENT_R,
            "Lateral handoff probe (WP-A2)",
        )
    )

    expects_refusal: bool = True
    """This probe is healthy when its input is refused, not when it runs."""

    def next_unit(self, tick: int, at: datetime) -> WorkUnit:
        return WorkUnit(
            operation_id=synthetic.synthetic_operation_id("lateral-handoff-probe", tick),
            origin=InputOrigin.AGENT_LATERAL,
            handoff_basis=OPERATOR_DIRECT_BASIS,
        )

    def observe(self, unit: WorkUnit, tick: int, at: datetime) -> Finding:
        raise AssertionError(
            "a lateral input was admitted with no recorded C2 handoff authorization; "
            "WP-A2's refusal at the consumer has stopped working"
        )


def default_runners() -> tuple[
    SettlementOperationsRunner,
    SettlementInvestigationRunner,
    FiatOperationsRunner,
    LateralProbeRunner,
]:
    """The agents Phase A activates, plus the standing lateral-handoff probe."""
    return (
        SettlementOperationsRunner(),
        SettlementInvestigationRunner(),
        FiatOperationsRunner(),
        LateralProbeRunner(),
    )
