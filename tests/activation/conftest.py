"""Fixtures for the Phase A activation tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import ActorId, HaltId

from atreides.activation import AgentSupervisor, default_runners

#: A fixed instant. Every clock in the activation path is injected, so the whole
#: suite is replayable and no assertion depends on when it ran.
AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def at() -> datetime:
    return AT


@pytest.fixture
def supervisor() -> AgentSupervisor:
    return AgentSupervisor(runners=default_runners())


@pytest.fixture
def operator() -> ActorRef:
    """An authenticated human. Only a human may clear a halt (JUM-D-19)."""
    return ActorRef(
        actor_id=ActorId("act_01M2P20SY00000000000000H01"),
        actor_kind=ActorKind.HUMAN,
        role="Tier 0 operator",
        entitlement_refs=("CAOM-001:tier-0",),
        authenticated=True,
    )


@pytest.fixture
def atreides_halt(operator: ActorRef) -> HaltContext:
    """A halt covering Atreides, as the server holds it."""
    return HaltContext(
        halt_id=HaltId("hlt_01M2P20SY00000000000000001"),
        version=1,
        active=True,
        scope=(Domain.ATREIDES,),
        declared_by=operator,
        declared_at=AT,
        reason="Tier 0 emergency halt declared during the activation test",
    )


@pytest.fixture
def cleared_halt(operator: ActorRef) -> HaltContext:
    """The same halt, cleared. Present so a test can assert against server state."""
    return HaltContext(
        halt_id=HaltId("hlt_01M2P20SY00000000000000001"),
        version=2,
        active=False,
        scope=(Domain.ATREIDES,),
        declared_by=operator,
        declared_at=AT,
        reason="Halt cleared by the operator",
    )
