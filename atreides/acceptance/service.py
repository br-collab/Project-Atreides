"""Obligation acceptance: evaluate a candidate, and gate instruction preparation on the result.

ATR-I-01. Atreides accepts or refuses an obligation formed elsewhere (L.C.); it
never rewrites the economics. :func:`evaluate_candidate` is a pure function: it
reads the candidate, the CATO-F decision and the halt context, and returns an
:class:`~atreides.acceptance.record.ObligationAcceptanceRecord`. It writes
nothing and changes nothing; persisting the record is the caller's job.

Predicates (``obligation-acceptance/0.1-draft``) and what failing each means:

========================  ==============================  ==============
Predicate                 Fails when                      Disposition
========================  ==============================  ==============
required_fields_present   a required field is absent      BLOCK
no_unknown_enums          an enum value is not a member   INDETERMINATE
leg_linkage               legs disagree with the          BLOCK
                          obligation on lifecycle or
                          delivery pattern
halt_not_active           a halt covering Atreides is     HOLD
                          in effect
funding_bound             no CATO-F decision, or one not  INDETERMINATE
                          bound to this obligation id
                          and digest
                          the bound decision holds or     HOLD
                          escalates
========================  ==============================  ==============

The record's disposition is the most severe predicate result, in the order
BLOCK, INDETERMINATE, HOLD, PASS. Missing evidence is never PASS.

:func:`prepare_instruction` is the ``INSTRUCTION_PREPARED`` step for the
obligation path: it refuses unless an ACCEPTED record exists for the exact
digest of the candidate being prepared.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import cannae_kernel
from cannae_kernel.canonical import digest
from cannae_kernel.delivery import DeliveryPattern
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.finality import FinalityType
from cannae_kernel.halt import HaltContext, gate_under_halt

from atreides.acceptance.candidate import ObligationCandidate
from atreides.acceptance.record import (
    ACCEPTANCE_RULE_VERSION,
    ObligationAcceptanceRecord,
    PredicateResult,
    outcome_for,
)
from atreides.messaging.canonical import CashLegInstruction
from atreides.messaging.emit import InstructionArtifact, emit_instruction_artifact
from atreides.messaging.profile import BASE_ISO_20022, DepositoryProfile
from atreides.rails.cato_f import CatoFDecision, GateDecision

__all__ = ["PreparationRefusedError", "evaluate_candidate", "prepare_instruction"]

_SEVERITY: tuple[Disposition, ...] = (
    Disposition.BLOCK,
    Disposition.INDETERMINATE,
    Disposition.HOLD,
    Disposition.PASS,
)

_NO_SECURITIES_LEG = {DeliveryPattern.PAYMENT_ONLY.value, DeliveryPattern.PVP.value}
_NO_CASH_LEG = {DeliveryPattern.FOP.value}


def _result(name: str, disposition: Disposition, detail: str, *codes: str) -> PredicateResult:
    return PredicateResult(
        predicate=name, disposition=disposition, reason_codes=codes, detail=detail
    )


def _passed(name: str, detail: str) -> PredicateResult:
    return _result(name, Disposition.PASS, detail)


def _required_fields(c: ObligationCandidate) -> PredicateResult:
    missing: list[str] = []
    if c.obligation_version is None:
        missing.append("obligation_version")
    if c.lifecycle_id is None:
        missing.append("lifecycle_id")
    if c.delivery_pattern is None:
        missing.append("delivery_pattern")
    if not c.source_references:
        missing.append("source_references")
    if not c.participants:
        missing.append("participants")
    pattern = c.delivery_pattern
    if pattern not in _NO_SECURITIES_LEG:
        leg = c.securities_leg
        if leg is None:
            missing.append("securities_leg")
        else:
            missing += [
                f"securities_leg.{f}"
                for f in (
                    "lifecycle_id",
                    "delivery_pattern",
                    "instrument_id",
                    "quantity",
                    "deliverer_participant_id",
                    "receiver_participant_id",
                )
                if getattr(leg, f) is None
            ]
        if not any(e.leg == "securities" for e in c.expected_finality):
            missing.append("expected_finality.securities")
    if pattern not in _NO_CASH_LEG:
        cash = c.cash_leg
        if cash is None:
            missing.append("cash_leg")
        else:
            missing += [
                f"cash_leg.{f}"
                for f in (
                    "lifecycle_id",
                    "delivery_pattern",
                    "total",
                    "currency",
                    "value_date",
                    "payer_participant_id",
                    "payee_participant_id",
                )
                if getattr(cash, f) is None
            ]
        if not any(e.leg == "cash" for e in c.expected_finality):
            missing.append("expected_finality.cash")
    if missing:
        return _result(
            "required_fields_present",
            Disposition.BLOCK,
            f"Required fields absent: {', '.join(missing)}.",
            *(f"MISSING:{m}" for m in missing),
        )
    return _passed("required_fields_present", "Every required field is present.")


def _unknown_enums(c: ObligationCandidate) -> PredicateResult:
    patterns = {p.value for p in DeliveryPattern}
    finality = {f.value for f in FinalityType}
    unknown: list[str] = []
    for where, value in (
        ("delivery_pattern", c.delivery_pattern),
        ("securities_leg.delivery_pattern", c.securities_leg and c.securities_leg.delivery_pattern),
        ("cash_leg.delivery_pattern", c.cash_leg and c.cash_leg.delivery_pattern),
    ):
        if value is not None and value not in patterns:
            unknown.append(f"{where}={value!r}")
    for i, expected in enumerate(c.expected_finality):
        if expected.finality_type not in finality:
            unknown.append(f"expected_finality[{i}].finality_type={expected.finality_type!r}")
    if unknown:
        return _result(
            "no_unknown_enums",
            Disposition.INDETERMINATE,
            f"Values that name no member exactly: {', '.join(unknown)}. Not guessed at (ATR-I-05).",
            *(f"UNKNOWN_ENUM:{u.split('=', 1)[0]}" for u in unknown),
        )
    return _passed("no_unknown_enums", "Every enum value names a member exactly.")


def _leg_linkage(c: ObligationCandidate) -> PredicateResult:
    codes: list[str] = []
    for name, leg in (("securities_leg", c.securities_leg), ("cash_leg", c.cash_leg)):
        if leg is None:
            continue
        if leg.lifecycle_id is not None and leg.lifecycle_id != c.lifecycle_id:
            codes.append(f"LEG_LIFECYCLE_MISMATCH:{name}")
        if leg.delivery_pattern is not None and leg.delivery_pattern != c.delivery_pattern:
            codes.append(f"LEG_DELIVERY_PATTERN_MISMATCH:{name}")
    if codes:
        return _result(
            "leg_linkage",
            Disposition.BLOCK,
            "A leg does not share the obligation's lifecycle and delivery pattern, so the "
            "legs are not one settlement.",
            *codes,
        )
    return _passed("leg_linkage", "Present legs share the lifecycle and delivery pattern.")


def _halt(halt: HaltContext | None) -> PredicateResult:
    if halt is None:
        return _passed("halt_not_active", "No halt context supplied; none recorded as active.")
    if gate_under_halt(halt, Domain.ATREIDES) is Disposition.BLOCK:
        return _result(
            "halt_not_active",
            Disposition.HOLD,
            f"Halt {halt.halt_id} (version {halt.version}) is active for Atreides: {halt.reason}.",
            "HALT_ACTIVE",
        )
    return _passed("halt_not_active", f"Halt context version {halt.version} does not block.")


def _funding(
    c: ObligationCandidate, candidate_digest: str, decision: CatoFDecision | None
) -> PredicateResult:
    name = "funding_bound"
    if c.delivery_pattern in _NO_CASH_LEG:
        return _passed(name, "Free of payment: no cash leg, so no cash gate decision applies.")
    if decision is None:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "No CATO-F decision supplied. Funding is unassessed, not assumed.",
            "CASH_GATE_DECISION_MISSING",
        )
    if not decision.bound:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "The CATO-F decision names no obligation, so it is not evidence about this one.",
            "CASH_GATE_UNBOUND",
        )
    if decision.obligation_id != c.obligation_id:
        return _result(
            name,
            Disposition.INDETERMINATE,
            f"The CATO-F decision governs {decision.obligation_id}, not {c.obligation_id}.",
            "CASH_GATE_OTHER_OBLIGATION",
        )
    if decision.obligation_digest != candidate_digest:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "The CATO-F decision was made for a different version of this obligation "
            f"({decision.obligation_digest}, not {candidate_digest}).",
            "CASH_GATE_STALE_DIGEST",
        )
    if decision.decision is not GateDecision.PROCEED:
        return _result(
            name,
            Disposition.HOLD,
            f"CATO-F returned {decision.decision.value} ({decision.reason_code.value}): "
            f"{decision.rationale}",
            f"CASH_GATE_{decision.decision.value}:{decision.reason_code.value}",
        )
    return _passed(name, "CATO-F PROCEED is bound to this obligation id and digest.")


def evaluate_candidate(
    candidate: ObligationCandidate,
    *,
    acceptance_id: UUID,
    evaluated_at: datetime,
    gate_decision: CatoFDecision | None,
    halt: HaltContext | None,
) -> ObligationAcceptanceRecord:
    """Evaluate a candidate. Pure: reads its inputs, returns a record, changes nothing."""
    candidate_digest = digest(candidate)
    predicates = (
        _required_fields(candidate),
        _unknown_enums(candidate),
        _leg_linkage(candidate),
        _halt(halt),
        _funding(candidate, candidate_digest, gate_decision),
    )
    disposition = next(
        severity for severity in _SEVERITY if any(p.disposition is severity for p in predicates)
    )
    outcome = outcome_for(disposition)
    data_versions: list[tuple[str, str]] = [
        ("candidate_schema", candidate.schema_version),
        ("cannae_kernel", cannae_kernel.__version__),
    ]
    if gate_decision is not None:
        data_versions.append(("cato_f_gate_set", gate_decision.gate_set_version))
    return ObligationAcceptanceRecord(
        operation_id=acceptance_id,
        obligation_id=candidate.obligation_id,
        obligation_version=candidate.obligation_version,
        lifecycle_id=candidate.lifecycle_id,
        obligation_digest=candidate_digest,
        disposition=disposition,
        outcome=outcome,
        evaluated_predicates=predicates,
        rule_version=ACCEPTANCE_RULE_VERSION,
        data_versions=tuple(data_versions),
        reason_codes=tuple(code for p in predicates for code in p.reason_codes),
        halt_context_version=None if halt is None else halt.version,
        evaluated_at=evaluated_at,
        accepted_at=evaluated_at if disposition is Disposition.PASS else None,
    )


class PreparationRefusedError(RuntimeError):
    """Raised instead of preparing an instruction for an obligation that was not accepted."""


def prepare_instruction(
    candidate: ObligationCandidate,
    acceptance: ObligationAcceptanceRecord | None,
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
    *,
    halt: HaltContext | None = None,
) -> InstructionArtifact:
    """``INSTRUCTION_PREPARED`` for an obligation: only against an ACCEPTED record, same digest.

    Refuses with :class:`PreparationRefusedError` when there is no record, when the record
    is not ACCEPTED, or when it was made for another obligation or another version of
    this one. A halt in effect still refuses in :func:`emit_instruction_artifact`.
    """
    if acceptance is None:
        raise PreparationRefusedError(
            f"No acceptance record for {candidate.obligation_id}; nothing is prepared (ATR-I-01)."
        )
    if not acceptance.accepted:
        raise PreparationRefusedError(
            f"Obligation {candidate.obligation_id} was {acceptance.outcome.value}, not "
            f"ACCEPTED; nothing is prepared (ATR-I-01)."
        )
    candidate_digest = digest(candidate)
    if (
        acceptance.obligation_id != candidate.obligation_id
        or acceptance.obligation_digest != candidate_digest
    ):
        raise PreparationRefusedError(
            f"The acceptance record is for {acceptance.obligation_id} at "
            f"{acceptance.obligation_digest}, not {candidate.obligation_id} at "
            f"{candidate_digest}; nothing is prepared (ATR-I-01)."
        )
    return emit_instruction_artifact(instruction, profile, halt=halt)
