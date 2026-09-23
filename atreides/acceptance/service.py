"""Frozen settlement-obligation acceptance boundary and instruction gate."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import digest, digest_bytes
from cannae_kernel.delivery import DeliveryPattern
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.envelopes import ObligationAcceptanceRecord as FrozenAcceptanceRecord
from cannae_kernel.envelopes import SettlementObligationEnvelope
from cannae_kernel.finality import FinalityType
from cannae_kernel.halt import HaltContext, gate_under_halt
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.acceptance.candidate import ObligationCandidate
from atreides.acceptance.record import ObligationAcceptanceRecord as DraftAcceptanceRecord
from atreides.acceptance.record import PredicateResult
from atreides.messaging.canonical import CashLegInstruction
from atreides.messaging.emit import InstructionArtifact, emit_instruction_artifact
from atreides.messaging.profile import BASE_ISO_20022, DepositoryProfile
from atreides.rails.cato_cash import CatoCashDecision, GateDecision

__all__ = ["PreparationRefusedError", "evaluate_candidate", "prepare_instruction"]

_SEVERITY = (Disposition.BLOCK, Disposition.INDETERMINATE, Disposition.HOLD, Disposition.PASS)
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
    if c.source_manifest is None or not c.source_manifest.references:
        missing.append("source_manifest.references")
    if c.delivery_pattern is None:
        missing.append("delivery_pattern")
    if not c.participants:
        missing.append("participants")
    if not c.candidate_paths:
        missing.append("candidate_paths")
    if c.delivery_pattern not in _NO_SECURITIES_LEG:
        if c.securities_leg is None:
            missing.append("securities_leg")
        else:
            missing += [
                f"securities_leg.{field}"
                for field in (
                    "instrument_id",
                    "quantity",
                    "delivering_account_id",
                    "receiving_account_id",
                )
                if getattr(c.securities_leg, field) is None
            ]
        if not any(item.leg == "SECURITIES" for item in c.expected_finality):
            missing.append("expected_finality.securities")
    if c.delivery_pattern not in _NO_CASH_LEG:
        if c.cash_leg is None:
            missing.append("cash_leg")
        else:
            missing += [
                f"cash_leg.{field}"
                for field in (
                    "principal",
                    "accrued",
                    "total",
                    "currency",
                    "value_date",
                    "paying_account_id",
                    "receiving_account_id",
                )
                if getattr(c.cash_leg, field) is None
            ]
        if not any(item.leg == "CASH" for item in c.expected_finality):
            missing.append("expected_finality.cash")
    if missing:
        return _result(
            "required_fields_present",
            Disposition.BLOCK,
            f"Required fields absent: {', '.join(missing)}.",
            *(f"MISSING:{item}" for item in missing),
        )
    return _passed("required_fields_present", "Every required field is present.")


def _unknown_enums(c: ObligationCandidate) -> PredicateResult:
    patterns = {item.value for item in DeliveryPattern}
    finality = {item.value for item in FinalityType}
    unknown: list[str] = []
    if c.delivery_pattern is not None and c.delivery_pattern not in patterns:
        unknown.append("delivery_pattern")
    for index, path in enumerate(c.candidate_paths):
        if path.delivery_pattern is not None and path.delivery_pattern not in patterns:
            unknown.append(f"candidate_paths[{index}].delivery_pattern")
    for index, expected in enumerate(c.expected_finality):
        if expected.finality_type not in finality:
            unknown.append(f"expected_finality[{index}].finality_type")
    if unknown:
        return _result(
            "no_unknown_enums",
            Disposition.INDETERMINATE,
            f"Values name no enum member exactly: {', '.join(unknown)}.",
            *(f"UNKNOWN_ENUM:{item}" for item in unknown),
        )
    return _passed("no_unknown_enums", "Every enum value names a member exactly.")


def _leg_linkage(c: ObligationCandidate) -> PredicateResult:
    codes: list[str] = []
    accounts = {participant.account_id for participant in c.participants}
    securities_accounts = (
        ()
        if c.securities_leg is None
        else (
            c.securities_leg.delivering_account_id,
            c.securities_leg.receiving_account_id,
        )
    )
    cash_accounts = (
        ()
        if c.cash_leg is None
        else (
            c.cash_leg.paying_account_id,
            c.cash_leg.receiving_account_id,
        )
    )
    if any(account is not None and account not in accounts for account in securities_accounts):
        codes.append("LEG_ACCOUNT_MISMATCH:securities_leg")
    if any(account is not None and account not in accounts for account in cash_accounts):
        codes.append("LEG_ACCOUNT_MISMATCH:cash_leg")
    if any(
        path.delivery_pattern is not None and path.delivery_pattern != c.delivery_pattern
        for path in c.candidate_paths
    ):
        codes.append("LEG_DELIVERY_PATTERN_MISMATCH:candidate_path")
    if codes:
        return _result(
            "leg_linkage",
            Disposition.BLOCK,
            "A leg account or candidate path is not linked to this obligation payload.",
            *codes,
        )
    return _passed("leg_linkage", "Leg accounts and candidate paths are linked.")


def _halt(halt: HaltContext | None) -> PredicateResult:
    if halt is None:
        return _passed("halt_not_active", "No halt context supplied; none recorded as active.")
    if gate_under_halt(halt, Domain.ATREIDES) is Disposition.BLOCK:
        return _result(
            "halt_not_active",
            Disposition.HOLD,
            f"Halt {halt.halt_id} (version {halt.version}) is active for Atreides.",
            "HALT_ACTIVE",
        )
    return _passed("halt_not_active", f"Halt context version {halt.version} does not block.")


def _funding(
    envelope: SettlementObligationEnvelope,
    candidate: ObligationCandidate,
    envelope_digest: str,
    decision: CatoCashDecision | None,
) -> PredicateResult:
    name = "funding_bound"
    if candidate.delivery_pattern in _NO_CASH_LEG:
        return _passed(name, "Free of payment: no cash gate decision applies.")
    if decision is None:
        return _result(
            name, Disposition.INDETERMINATE, "No cash decision.", "CASH_GATE_DECISION_MISSING"
        )
    if not decision.bound:
        return _result(
            name, Disposition.INDETERMINATE, "Cash decision is unbound.", "CASH_GATE_UNBOUND"
        )
    if decision.obligation_id != envelope.obligation_id:
        return _result(
            name, Disposition.INDETERMINATE, "Other obligation.", "CASH_GATE_OTHER_OBLIGATION"
        )
    if decision.obligation_digest != envelope_digest:
        return _result(name, Disposition.INDETERMINATE, "Stale envelope.", "CASH_GATE_STALE_DIGEST")
    if decision.decision is not GateDecision.PROCEED:
        return _result(
            name,
            Disposition.HOLD,
            f"Cato Cash returned {decision.decision.value}.",
            f"CASH_GATE_{decision.decision.value}:{decision.reason_code.value}",
        )
    return _passed(name, "Cato Cash PROCEED is bound to this frozen envelope.")


def _frozen_record(
    envelope: SettlementObligationEnvelope,
    *,
    disposition: Disposition,
    acceptance_id: UUID,
    decided_by: ActorRef,
    reasons: tuple[str, ...],
) -> FrozenAcceptanceRecord:
    dsor = (
        Recorded[str](value=f"atreides-acceptance:{acceptance_id}")
        if disposition is Disposition.PASS
        else Absent(
            kind=AbsenceKind.NOTHING_RECORDED,
            reason=";".join(reasons) or "ACCEPTANCE_NOT_RECORDED",
        )
    )
    return FrozenAcceptanceRecord(
        obligation_id=envelope.obligation_id,
        obligation_digest=digest(envelope),
        disposition=disposition,
        dsor_record=dsor,
        decided_by=decided_by,
        provenance=Provenance.POLICY_RESULT,
    )


def evaluate_candidate(
    envelope: SettlementObligationEnvelope,
    payload: bytes,
    *,
    acceptance_id: UUID,
    evaluated_at: datetime,
    decided_by: ActorRef,
    gate_decision: CatoCashDecision | None,
    halt: HaltContext | None,
) -> FrozenAcceptanceRecord:
    """Verify attested bytes, parse them internally, then apply every predicate."""
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if digest_bytes(payload) != envelope.payload_digest:
        return _frozen_record(
            envelope,
            disposition=Disposition.BLOCK,
            acceptance_id=acceptance_id,
            decided_by=decided_by,
            reasons=("PAYLOAD_DIGEST_MISMATCH",),
        )
    try:
        candidate = ObligationCandidate.model_validate_json(payload)
    except ValidationError:
        return _frozen_record(
            envelope,
            disposition=Disposition.BLOCK,
            acceptance_id=acceptance_id,
            decided_by=decided_by,
            reasons=("PAYLOAD_INVALID",),
        )
    envelope_digest = digest(envelope)
    predicates = (
        _required_fields(candidate),
        _unknown_enums(candidate),
        _leg_linkage(candidate),
        _halt(halt),
        _funding(envelope, candidate, envelope_digest, gate_decision),
    )
    disposition = next(
        severity for severity in _SEVERITY if any(p.disposition is severity for p in predicates)
    )
    reasons = tuple(code for predicate in predicates for code in predicate.reason_codes)
    return _frozen_record(
        envelope,
        disposition=disposition,
        acceptance_id=acceptance_id,
        decided_by=decided_by,
        reasons=reasons,
    )


class PreparationRefusedError(RuntimeError):
    """Raised instead of preparing an instruction without matching acceptance."""


def prepare_instruction(
    candidate: ObligationCandidate,
    acceptance: DraftAcceptanceRecord | None,
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
    *,
    halt: HaltContext | None = None,
) -> InstructionArtifact:
    """Legacy internal boundary; migrated to frozen inputs in WP-2."""
    if acceptance is None or not acceptance.accepted:
        raise PreparationRefusedError(
            "Obligation was not ACCEPTED; nothing is prepared (ATR-I-01)."
        )
    return emit_instruction_artifact(instruction, profile, halt=halt)
