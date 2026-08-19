"""Escalation delivery, and the acknowledgement that makes it delivery.

Before this package existed, an escalation in this framework was a label on
an object. ``EscalationRequired.escalation_tier`` named a tier; nothing routed
to it, nothing queued it, nothing notified anybody, and nothing recorded that
a human had picked it up. An escalation "went to" ``store.append()`` - a row
in SQLite - and whether anybody ever read that row was outside the framework
entirely.

That is the gap the stress probe reported as NO_TARGET for the escalation
family: there was nothing to attack, because there was nothing there.
"""

from atreides.escalation.register import (
    Acknowledgement,
    Escalation,
    EscalationAlreadyAcknowledgedError,
    EscalationNotFoundError,
    EscalationRegister,
    EscalationState,
    absent_acknowledgement,
)

__all__ = [
    "Acknowledgement",
    "Escalation",
    "EscalationAlreadyAcknowledgedError",
    "EscalationNotFoundError",
    "EscalationRegister",
    "EscalationState",
    "absent_acknowledgement",
]
