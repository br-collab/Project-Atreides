"""Obligation acceptance (ATR-I-01), ``0.1-draft``.

Atreides accepts, holds, rejects or declines to decide on an obligation formed
elsewhere; it never rewrites the economics. See :mod:`atreides.acceptance.service`.
"""

from atreides.acceptance.candidate import (
    CANDIDATE_SCHEMA_VERSION,
    CashLeg,
    ExpectedFinality,
    ObligationCandidate,
    Participant,
    SecuritiesLeg,
    SourceReference,
)
from atreides.acceptance.record import (
    ACCEPTANCE_RULE_VERSION,
    AcceptanceOutcome,
    ObligationAcceptanceRecord,
    PredicateResult,
    outcome_for,
)
from atreides.acceptance.service import (
    PreparationRefusedError,
    evaluate_candidate,
    prepare_instruction,
)

__all__ = [
    "ACCEPTANCE_RULE_VERSION",
    "CANDIDATE_SCHEMA_VERSION",
    "AcceptanceOutcome",
    "CashLeg",
    "ExpectedFinality",
    "ObligationAcceptanceRecord",
    "ObligationCandidate",
    "Participant",
    "PredicateResult",
    "PreparationRefusedError",
    "SecuritiesLeg",
    "SourceReference",
    "evaluate_candidate",
    "outcome_for",
    "prepare_instruction",
]
