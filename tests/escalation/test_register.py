"""Tests for the escalation register.

The load-bearing assertion in this file is that raising is not delivering.
Everything else supports it or tests the refusals that make it hold.
"""

from __future__ import annotations

import re
import uuid

import pytest

from atreides.escalation import (
    Acknowledgement,
    Escalation,
    EscalationAlreadyAcknowledgedError,
    EscalationNotFoundError,
    EscalationRegister,
    EscalationState,
    absent_acknowledgement,
)


def _escalation(
    escalation_id: str = "E-1",
    *,
    raised_at: int = 0,
    deadline: int | None = 900,
) -> Escalation:
    return Escalation(
        escalation_id=escalation_id,
        operation_id=uuid.uuid4(),
        raised_at_offset_seconds=raised_at,
        reason="counterparty under review on a material leg",
        routed_to="credit-desk",
        acknowledge_by_offset_seconds=deadline,
    )


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_raising_is_not_delivering() -> None:
    """The whole point. A raised escalation nobody has taken is RAISED, not
    delivered, and it appears in the number a firm should be watching."""
    register = EscalationRegister()
    register.raise_escalation(_escalation())
    assert register.state("E-1", as_of_offset_seconds=0) is EscalationState.RAISED
    assert len(register.unacknowledged(as_of_offset_seconds=0)) == 1
    assert register.acknowledgement_for("E-1") is None


def test_an_acknowledgement_names_a_person() -> None:
    register = EscalationRegister()
    register.raise_escalation(_escalation())
    ack = register.acknowledge("E-1", by="j.doe", at_offset_seconds=120)
    assert ack.acknowledged_by == "j.doe"
    assert register.state("E-1", as_of_offset_seconds=120) is (
        EscalationState.ACKNOWLEDGED
    )
    assert register.unacknowledged(as_of_offset_seconds=120) == ()


def test_an_anonymous_acknowledgement_is_refused() -> None:
    """An acknowledgement with no name answers 'has somebody got this' with
    'something has', which is the answer that made this register necessary."""
    with pytest.raises(ValueError, match="must name who"):
        Acknowledgement(
            escalation_id="E-1", acknowledged_by="", acknowledged_at_offset_seconds=1
        )


# ---------------------------------------------------------------------------
# Overdue: the finding this exists to produce
# ---------------------------------------------------------------------------


def test_an_unacknowledged_escalation_past_its_deadline_is_overdue() -> None:
    register = EscalationRegister()
    register.raise_escalation(_escalation(deadline=900))
    assert register.state("E-1", as_of_offset_seconds=901) is EscalationState.OVERDUE
    assert len(register.overdue(as_of_offset_seconds=901)) == 1


def test_the_deadline_boundary_is_inclusive() -> None:
    register = EscalationRegister()
    register.raise_escalation(_escalation(deadline=900))
    assert register.state("E-1", as_of_offset_seconds=900) is EscalationState.RAISED
    assert register.overdue(as_of_offset_seconds=900) == ()


def test_late_acknowledgement_is_distinct_from_timely_acknowledgement() -> None:
    """'Somebody got to it eventually' and 'somebody got to it in time' are
    different facts about a control, and a review that cannot separate them
    cannot tell whether the control works."""
    register = EscalationRegister()
    register.raise_escalation(_escalation(deadline=900))
    register.acknowledge("E-1", by="j.doe", at_offset_seconds=5000)
    assert register.state("E-1", as_of_offset_seconds=5000) is (
        EscalationState.ACKNOWLEDGED_LATE
    )


def test_an_escalation_with_no_deadline_is_never_overdue() -> None:
    """Not leniency. An escalation nobody put a deadline on cannot be late,
    and reporting it as late would be this register inventing a bound the
    firm declined to set. It stays in unacknowledged, where it belongs."""
    register = EscalationRegister()
    register.raise_escalation(_escalation(deadline=None))
    assert register.overdue(as_of_offset_seconds=10**9) == ()
    assert len(register.unacknowledged(as_of_offset_seconds=10**9)) == 1
    assert register.state("E-1", as_of_offset_seconds=10**9) is EscalationState.RAISED


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_acknowledging_something_never_raised_is_refused() -> None:
    register = EscalationRegister()
    with pytest.raises(EscalationNotFoundError, match="never raised"):
        register.acknowledge("E-GHOST", by="j.doe", at_offset_seconds=1)


def test_a_second_acknowledgement_is_refused_and_names_the_first() -> None:
    """Two acknowledgements mean two people each believe they have it, and
    the second silently overwriting the first destroys the evidence."""
    register = EscalationRegister()
    register.raise_escalation(_escalation())
    register.acknowledge("E-1", by="j.doe", at_offset_seconds=100)
    with pytest.raises(EscalationAlreadyAcknowledgedError, match=re.escape("j.doe")):
        register.acknowledge("E-1", by="a.smith", at_offset_seconds=200)


def test_re_raising_an_escalation_is_refused() -> None:
    register = EscalationRegister()
    register.raise_escalation(_escalation())
    with pytest.raises(EscalationAlreadyAcknowledgedError, match="already been raised"):
        register.raise_escalation(_escalation())


def test_an_escalation_with_no_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="no reason"):
        Escalation(
            escalation_id="E-1",
            operation_id=uuid.uuid4(),
            raised_at_offset_seconds=0,
            reason="",
            routed_to="credit-desk",
        )


def test_an_escalation_with_no_destination_is_refused() -> None:
    """The condition this register exists to make impossible."""
    with pytest.raises(ValueError, match="no destination"):
        Escalation(
            escalation_id="E-1",
            operation_id=uuid.uuid4(),
            raised_at_offset_seconds=0,
            reason="something",
            routed_to="",
        )


def test_a_deadline_before_the_raising_is_refused() -> None:
    """Overdue at birth says nothing about anybody's response."""
    with pytest.raises(ValueError, match="precedes the raising"):
        Escalation(
            escalation_id="E-1",
            operation_id=uuid.uuid4(),
            raised_at_offset_seconds=1000,
            reason="something",
            routed_to="credit-desk",
            acknowledge_by_offset_seconds=500,
        )


# ---------------------------------------------------------------------------
# Append-only, and replayable
# ---------------------------------------------------------------------------


def test_an_escalation_is_never_removed() -> None:
    register = EscalationRegister()
    register.raise_escalation(_escalation("E-1"))
    register.raise_escalation(_escalation("E-2"))
    register.acknowledge("E-1", by="j.doe", at_offset_seconds=10)
    assert [e.escalation_id for e in register.raised] == ["E-1", "E-2"]
    assert len(register) == 2


def test_state_is_derived_and_not_stored() -> None:
    """A stored status can disagree with the records that produced it. The
    same register answers differently at different instants, from one set of
    immutable records."""
    register = EscalationRegister()
    register.raise_escalation(_escalation(deadline=900))
    assert register.state("E-1", as_of_offset_seconds=0) is EscalationState.RAISED
    assert register.state("E-1", as_of_offset_seconds=5000) is EscalationState.OVERDUE


def test_the_register_reads_no_clock() -> None:
    """Architectural contract, asserted rather than trusted. A register that
    consulted a clock could not answer what a queue looked like yesterday,
    which is the question an investigation asks."""
    import inspect

    from atreides.escalation import register as module

    source = inspect.getsource(module)
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "datetime.now" not in code
    assert "time.time" not in code


# ---------------------------------------------------------------------------
# Deliberate absence
# ---------------------------------------------------------------------------


def test_the_absent_acknowledgement_refusal_is_stated_rather_than_implied() -> None:
    text = absent_acknowledgement("E-1")
    assert "not delivered" in text
    assert "E-1" in text


def test_there_is_no_transport_in_this_package() -> None:
    """A deliberate absence, marked so a reader finds the refusal.

    The moment this acquires a transport it acquires an outage, a credential,
    a retry policy and a duplicate-delivery problem, and none of those belong
    in a governance layer. What it holds is the state of a delivery, so the
    absence of one is measurable.
    """
    import pathlib

    import atreides.escalation.register as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    for transport in ("import socket", "import requests", "import smtplib", "urllib"):
        assert transport not in code
