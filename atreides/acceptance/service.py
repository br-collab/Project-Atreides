"""Frozen settlement-obligation acceptance boundary and instruction gate."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from xml.etree import ElementTree

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import digest, digest_bytes
from cannae_kernel.delivery import DeliveryPattern
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.envelopes import FirmSecuritiesDirection, SettlementObligationEnvelope
from cannae_kernel.envelopes import ObligationAcceptanceRecord as FrozenAcceptanceRecord
from cannae_kernel.finality import FinalityType
from cannae_kernel.halt import HaltContext, gate_under_halt
from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.acceptance.candidate import SELLER_CAPACITIES, ObligationCandidate
from atreides.acceptance.record import PredicateResult
from atreides.acceptance.registry import ParticipantRegistry
from atreides.customer_protection.control import ControlResult
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
    cash = candidate.cash_leg
    if cash is None or cash.total is None or cash.currency is None:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "Cash leg is absent.",
            "CASH_GATE_CASH_LEG_MISSING",
        )
    if decision.evaluated_notional != cash.total:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "Cash notional differs.",
            "CASH_GATE_NOTIONAL_MISMATCH",
        )
    if decision.evaluated_currency != cash.currency:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "Cash currency differs.",
            "CASH_GATE_CURRENCY_MISMATCH",
        )
    snapshot = dict(decision.funding_state_snapshot)
    try:
        net_obligation = Decimal(snapshot["net_obligation"])
    except (KeyError, ValueError):
        return _result(
            name,
            Disposition.INDETERMINATE,
            "Net obligation absent.",
            "CASH_GATE_NET_OBLIGATION_MISSING",
        )
    # Netting against other obligations remains possible; the snapshot need
    # only cover this obligation's total, not equal it.
    if net_obligation < cash.total:
        return _result(
            name,
            Disposition.HOLD,
            "Net obligation does not cover cash total.",
            "CASH_GATE_NET_OBLIGATION_INSUFFICIENT",
        )
    return _passed(name, "Cato Cash PROCEED is bound to this frozen envelope.")


def _customer_sell_control(
    envelope: SettlementObligationEnvelope,
    candidate: ObligationCandidate,
    control: ControlResult | None,
) -> PredicateResult:
    """Rule 15c3-3(b)(1): customer securities delivered on a sale must be in possession or control.

    INST-1 Amendment 3 (WP2b). The seller's capacity is read from the digest-bound payload,
    never from a caller. A control result counts only if it names this obligation's issue,
    is as of its settlement date, passes, and holds at least the delivery quantity in
    control locations. Anything else HOLDs with a named code.
    """
    name = "customer_sell_possession_or_control"
    if envelope.firm_securities_direction is not FirmSecuritiesDirection.DELIVER:
        return _passed(name, "The firm receives securities; customer-sell control does not apply.")
    capacity = candidate.seller_capacity
    if capacity is None:
        return _result(
            name,
            Disposition.HOLD,
            "The payload does not state the delivering account's capacity.",
            "CUSTOMER_SELL_CLASSIFICATION_MISSING",
        )
    if capacity not in SELLER_CAPACITIES:
        return _result(
            name,
            Disposition.INDETERMINATE,
            "The payload states an unknown seller capacity.",
            "SELLER_CAPACITY_UNKNOWN",
        )
    if capacity != "CUSTOMER":
        return _passed(name, f"The delivering account's capacity is {capacity}.")
    if control is None:
        return _result(
            name,
            Disposition.HOLD,
            "No possession-or-control result supplied.",
            "CUSTOMER_CONTROL_EVIDENCE_MISSING",
        )
    securities = candidate.securities_leg
    cash = candidate.cash_leg
    issue = securities.instrument_id if securities is not None else None
    quantity = securities.quantity if securities is not None else None
    settles = cash.value_date if cash is not None else None
    checked = next((item for item in control.issues if item.issue == issue), None)
    if (
        issue is None
        or quantity is None
        or settles is None
        or control.as_of.isoformat() != settles
        or checked is None
    ):
        return _result(
            name,
            Disposition.HOLD,
            "The control result does not name this obligation's issue and settlement date.",
            "CUSTOMER_CONTROL_UNBOUND",
        )
    if control.disposition is not Disposition.PASS:
        return _result(
            name,
            Disposition.HOLD,
            "Customer securities are not established in possession or control.",
            "CUSTOMER_CONTROL_NOT_ESTABLISHED",
        )
    if checked.in_control < quantity:
        return _result(
            name,
            Disposition.HOLD,
            "Fewer securities are in control than the delivery requires.",
            "CUSTOMER_CONTROL_INSUFFICIENT",
        )
    return _passed(name, "Customer securities are established in possession or control.")


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
    customer_control: ControlResult | None = None,
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
        _customer_sell_control(envelope, candidate, customer_control),
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
    envelope: SettlementObligationEnvelope,
    payload: bytes,
    acceptance: FrozenAcceptanceRecord | None,
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
    *,
    halt: HaltContext | None = None,
    participant_registry: ParticipantRegistry | None = None,
) -> InstructionArtifact:
    """Prepare only from payload bytes attested and accepted by frozen records."""
    if digest_bytes(payload) != envelope.payload_digest:
        raise PreparationRefusedError(
            "Payload does not match the frozen envelope (PAYLOAD_DIGEST_MISMATCH)."
        )
    if acceptance is None:
        raise PreparationRefusedError("No acceptance record; nothing is prepared (ATR-I-01).")
    if acceptance.disposition is not Disposition.PASS:
        raise PreparationRefusedError(
            f"Acceptance disposition is {acceptance.disposition.value}, not PASS; "
            "nothing is prepared (ATR-I-01)."
        )
    if acceptance.obligation_id != envelope.obligation_id:
        raise PreparationRefusedError(
            "Acceptance record names another obligation; nothing is prepared (ATR-I-01)."
        )
    if acceptance.obligation_digest != digest(envelope):
        raise PreparationRefusedError(
            "Acceptance record does not reference this envelope digest; "
            "nothing is prepared (ATR-I-01)."
        )
    candidate = ObligationCandidate.model_validate_json(payload)
    cash = candidate.cash_leg
    if cash is None or cash.total is None or cash.currency is None:
        raise PreparationRefusedError("INSTRUCTION_UNBOUND: cash leg is absent.")
    if instruction.amount != cash.total:
        raise PreparationRefusedError("INSTRUCTION_AMOUNT_MISMATCH")
    if instruction.currency != cash.currency:
        raise PreparationRefusedError("INSTRUCTION_CURRENCY_MISMATCH")
    if participant_registry is None:
        raise PreparationRefusedError("INSTRUCTION_UNBOUND: participant registry is absent.")
    if candidate.participant_registry_digest is None:
        raise PreparationRefusedError(
            "INSTRUCTION_UNBOUND: the obligation does not name a participant registry."
        )
    if participant_registry.digest != candidate.participant_registry_digest:
        raise PreparationRefusedError(
            "PARTICIPANT_REGISTRY_MISMATCH: the registry is not the version the obligation names."
        )
    payer = participant_registry.institution(cash.paying_account_id)
    receiver = participant_registry.institution(cash.receiving_account_id)
    if payer is None or receiver is None:
        raise PreparationRefusedError("INSTRUCTION_UNBOUND: account-to-BIC mapping is absent.")
    if instruction.debtor != payer or instruction.creditor != receiver:
        raise PreparationRefusedError("INSTRUCTION_PARTY_MISMATCH")
    if instruction.debtor.bicfi == instruction.creditor.bicfi:
        raise PreparationRefusedError("INSTRUCTION_PARTY_MISMATCH: debtor equals creditor.")
    artifact = emit_instruction_artifact(instruction, profile, halt=halt)
    try:
        ElementTree.fromstring(artifact.header_xml)
        ElementTree.fromstring(artifact.document_xml)
    except ElementTree.ParseError as exc:
        raise PreparationRefusedError("INSTRUCTION_XML_INVALID") from exc
    return artifact
