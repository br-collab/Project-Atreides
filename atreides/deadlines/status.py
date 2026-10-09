"""Fail-closed disposition derivation shared by deadline clocks."""

from __future__ import annotations

from datetime import datetime

from cannae_kernel.disposition import Disposition, coerce_disposition

from atreides.deadlines.model import DeadlineAssessment


def assess(
    *,
    evaluated_at: datetime,
    due_at: datetime | None = None,
    missing_rules: tuple[str, ...] = (),
    missing_inputs: tuple[str, ...] = (),
    breaches: tuple[str, ...] = (),
) -> DeadlineAssessment:
    """Return INDETERMINATE for missing rules, HOLD for missing inputs or breaches."""
    if missing_rules:
        disposition = Disposition.INDETERMINATE
    elif missing_inputs or breaches:
        disposition = Disposition.HOLD
    else:
        disposition = Disposition.PASS
    return DeadlineAssessment(
        disposition=coerce_disposition(disposition),
        due_at=due_at,
        missing_rules=tuple(sorted(set(missing_rules))),
        missing_inputs=tuple(sorted(set(missing_inputs))),
        breaches=tuple(sorted(set(breaches))),
        evaluated_at=evaluated_at,
    )
