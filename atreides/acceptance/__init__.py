"""Obligation acceptance (ATR-I-01), ``0.1-draft``.

Atreides accepts, holds, rejects or declines to decide on an obligation formed
elsewhere; it never rewrites the economics. See :mod:`atreides.acceptance.service`.
"""

from cannae_kernel.envelopes import ObligationAcceptanceRecord

from atreides.acceptance.candidate import (
    CandidatePathDescriptor,
    CashLeg,
    Correction,
    ExpectedFinality,
    ObligationCandidate,
    Participant,
    SecuritiesLeg,
    SourceManifest,
    SourceReference,
)
from atreides.acceptance.record import (
    ACCEPTANCE_RULE_VERSION,
    AcceptanceOutcome,
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
    "AcceptanceOutcome",
    "CandidatePathDescriptor",
    "CashLeg",
    "Correction",
    "ExpectedFinality",
    "ObligationAcceptanceRecord",
    "ObligationCandidate",
    "Participant",
    "PredicateResult",
    "PreparationRefusedError",
    "SecuritiesLeg",
    "SourceManifest",
    "SourceReference",
    "evaluate_candidate",
    "outcome_for",
    "prepare_instruction",
]
