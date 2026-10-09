"""Join a prepared artifact, an external action, a venue readback, and finality.

EXPERIMENTAL. The join consumes the receipt type and the readback type in one
execution. It does not translate either into a shape invented for a test, and
it does not submit, authorize, or instruct.

Instructed, matched, accepted, settled, and final stay distinct. Asset-final
and cash-final evidence are published only when a passing settlement
instruction receipt, the exact artifact digest, and an authoritative settled
readback all join. Anything short of that is HOLD or INDETERMINATE.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from xml.etree import ElementTree

from cannae_kernel._model import KernelModel
from cannae_kernel.actor import ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.finality import (
    ConditionalityStatus,
    FinalityAssertion,
    FinalityType,
    RevocabilityStatus,
)
from cannae_kernel.ids import EventId
from cannae_kernel.provenance import Provenance
from pydantic import Field, model_validator

from atreides.messaging.canonical import CashLegInstruction
from atreides.messaging.emit import InstructionArtifact, instruction_artifact_digest
from atreides.messaging.finality_evidence import (
    EvidenceState,
    FinalityEvidence,
    finality_from_readback,
)
from atreides.messaging.readback import ReadbackMatch, StatusEntry
from atreides.messaging.receipt import (
    ExternalAction,
    ExternalActionReceipt,
    ReceiptAssessment,
    assess_receipts,
)

__all__ = [
    "JoinedStage",
    "SettlementJoin",
    "join_settlement_evidence",
]

_Leg = Literal["asset", "cash"]
_NOT_JOINED = "the evidence does not join, so no finality assertion is published"


class JoinedStage(StrEnum):
    """How far the four pieces of evidence join. Final is the only pass."""

    UNREAD = "UNREAD"
    """Nothing usable was joined. Absence lands here."""

    INSTRUCTED = "INSTRUCTED"
    """An entitled member instructed settlement. Instructed is not a venue status."""

    MATCHED = "MATCHED"
    """The venue received the instruction. Matched is not accepted or final."""

    ACCEPTED = "ACCEPTED"
    """The venue accepted the instruction. Accepted is not settled or final."""

    REFUSED = "REFUSED"
    """The venue rejected or cancelled the instruction. Refusal is not finality."""

    SETTLED = "SETTLED"
    """The venue said settled. Settled is not yet a published finality assertion."""

    FINAL = "FINAL"
    """Artifact, entitled member action, readback, and a kernel finality assertion join."""


class SettlementJoin(KernelModel):
    """One join. PASS exists only beside a published final assertion."""

    stage: JoinedStage = Field(description="How far the evidence joins.")
    disposition: Disposition = Field(
        description="PASS only beside a joined final assertion. Otherwise HOLD or INDETERMINATE."
    )
    reason: str = Field(min_length=1, description="Why the disposition was reached.")
    leg: _Leg = Field(description="Which leg the caller asked to join, asset or cash.")
    artifact_digest: str = Field(
        description="Digest of the prepared artifact header then document."
    )
    receipt_disposition: Disposition = Field(description="Grade of the external action receipts.")
    venue_state: EvidenceState = Field(description="How far the readback adapter could read.")
    venue_disposition: Disposition = Field(description="Grade returned by the finality adapter.")
    assertion: FinalityAssertion | None = Field(
        default=None,
        description="The kernel assertion. Present only when the stage is FINAL.",
    )

    @model_validator(mode="after")
    def _only_a_joined_final_assertion_passes(self) -> Self:
        final = self.stage is JoinedStage.FINAL
        passed = self.disposition is Disposition.PASS
        has_assertion = self.assertion is not None
        if final != passed or final != has_assertion:
            raise ValueError("only a joined final assertion passes, and only a pass carries one")
        if self.assertion is None:
            return self
        expected = FinalityType.ASSET_FINAL if self.leg == "asset" else FinalityType.CASH_FINAL
        if self.assertion.finality_type is not expected:
            raise ValueError("the assertion type does not match the leg")
        if self.assertion.confidence is not None:
            raise ValueError("a finality fact from this join carries no confidence")
        return self


def _local_texts(xml: bytes) -> dict[str, list[str]] | None:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    found: dict[str, list[str]] = {}
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        if element.text:
            found.setdefault(name, []).append(element.text)
    return found


def _artifact_problem(
    artifact: InstructionArtifact,
    instruction: CashLegInstruction,
) -> tuple[Disposition, str] | None:
    header = _local_texts(artifact.header_xml)
    document = _local_texts(artifact.document_xml)
    if header is None or document is None:
        return (
            Disposition.INDETERMINATE,
            "the prepared artifact could not be read, so the join cannot be verified",
        )
    message_ok = (
        instruction.message_id in header.get("BizMsgIdr", [])
        and instruction.message_id in document.get("MsgId", [])
    )
    end_to_end_ok = instruction.end_to_end_id in document.get("EndToEndId", [])
    if message_ok and end_to_end_ok:
        return None
    return (
        Disposition.HOLD,
        "the prepared artifact does not carry the instruction identity",
    )


def _receipt_identity(
    receipts: Sequence[ExternalActionReceipt],
    instruction: CashLegInstruction,
) -> tuple[Disposition, str] | None:
    for receipt in receipts:
        if (
            receipt.message_id != instruction.message_id
            or receipt.end_to_end_id != instruction.end_to_end_id
        ):
            return (
                Disposition.HOLD,
                "a receipt names a different instruction than the prepared artifact",
            )
    return None


def _readback_identity(
    match: ReadbackMatch,
    entry: StatusEntry | None,
    instruction: CashLegInstruction,
) -> tuple[Disposition, str] | None:
    original = match.report.original_message_id
    if original is not None and original != instruction.message_id:
        return (
            Disposition.HOLD,
            "the readback names a different message than the prepared artifact",
        )
    if (
        entry is not None
        and entry.end_to_end_id is not None
        and entry.end_to_end_id != instruction.end_to_end_id
    ):
        return (
            Disposition.HOLD,
            "the readback entry names a different end-to-end identity than the prepared artifact",
        )
    return None


def _instructed(
    receipts: Sequence[ExternalActionReceipt],
    instruction: CashLegInstruction,
    digest: str,
) -> bool:
    settlement = [
        receipt for receipt in receipts if receipt.action is ExternalAction.SETTLEMENT_INSTRUCTION
    ]
    if not settlement:
        return False
    grade = assess_receipts(
        settlement,
        prepared_artifact_digest=digest,
        prepared_at=instruction.created_at,
    )
    return grade.disposition is Disposition.PASS


def _stage(venue: FinalityEvidence, instructed: bool, publish: bool) -> JoinedStage:
    if publish:
        return JoinedStage.FINAL
    if venue.state is EvidenceState.UNREAD:
        return JoinedStage.INSTRUCTED if instructed else JoinedStage.UNREAD
    if venue.state is EvidenceState.MATCHED:
        return JoinedStage.MATCHED
    if venue.state is EvidenceState.ACCEPTED:
        return JoinedStage.ACCEPTED
    if venue.state is EvidenceState.REFUSED:
        return JoinedStage.REFUSED
    return JoinedStage.SETTLED


def _disposition(
    *,
    publish: bool,
    problems: list[tuple[Disposition, str]],
    receipt: ReceiptAssessment,
    venue: FinalityEvidence,
) -> tuple[Disposition, str]:
    if publish:
        return (
            Disposition.PASS,
            "the prepared artifact, the entitled member action, the venue readback, "
            "and a kernel finality assertion join",
        )
    holds = [reason for disposition, reason in problems if disposition is Disposition.HOLD]
    if receipt.disposition is Disposition.HOLD:
        holds.append(receipt.reason)
    if venue.disposition is Disposition.HOLD:
        holds.append(venue.reason)
    if holds:
        return Disposition.HOLD, holds[0]
    unknowns = [
        reason for disposition, reason in problems if disposition is not Disposition.PASS
    ]
    if receipt.disposition is not Disposition.PASS:
        unknowns.append(receipt.reason)
    if venue.disposition is not Disposition.PASS:
        unknowns.append(venue.reason)
    if unknowns:
        return Disposition.INDETERMINATE, unknowns[0]
    if venue.state is EvidenceState.FINAL:
        return Disposition.INDETERMINATE, _NOT_JOINED
    return Disposition.HOLD, venue.reason


def join_settlement_evidence(
    artifact: InstructionArtifact,
    instruction: CashLegInstruction,
    receipts: Sequence[ExternalActionReceipt],
    match: ReadbackMatch,
    entry: StatusEntry | None,
    *,
    leg: _Leg,
    governing_rule_set: str,
    authoritative_actor: ActorRef,
    authoritative_event_id: EventId,
    effective_time: datetime,
    observation_time: datetime,
    evidence_reference: str,
    conditionality_status: ConditionalityStatus,
    revocability_status: RevocabilityStatus,
    provenance: Provenance,
) -> SettlementJoin:
    """Join the real artifact, receipts, readback, and finality adapter.

    The returned assertion is the adapter's assertion. It is published only
    when the receipt and the identities join as well. A settled readback
    with no usable receipt does not pass.
    """
    digest = instruction_artifact_digest(artifact)
    problems: list[tuple[Disposition, str]] = []
    artifact_problem = _artifact_problem(artifact, instruction)
    if artifact_problem is not None:
        problems.append(artifact_problem)
    identity_problem = _receipt_identity(receipts, instruction)
    if identity_problem is not None:
        problems.append(identity_problem)
    readback_problem = _readback_identity(match, entry, instruction)
    if readback_problem is not None:
        problems.append(readback_problem)
    receipt_grade = assess_receipts(
        receipts,
        prepared_artifact_digest=digest,
        prepared_at=instruction.created_at,
    )
    venue = finality_from_readback(
        match,
        entry,
        leg=leg,
        governing_rule_set=governing_rule_set,
        authoritative_actor=authoritative_actor,
        authoritative_event_id=authoritative_event_id,
        effective_time=effective_time,
        observation_time=observation_time,
        evidence_reference=evidence_reference,
        conditionality_status=conditionality_status,
        revocability_status=revocability_status,
        provenance=provenance,
    )
    instructed = (
        artifact_problem is None
        and identity_problem is None
        and _instructed(receipts, instruction, digest)
    )
    if venue.state is EvidenceState.FINAL and not instructed:
        if not any(receipt.action is ExternalAction.SETTLEMENT_INSTRUCTION for receipt in receipts):
            problems.append(
                (
                    Disposition.INDETERMINATE,
                    "no settlement instruction receipt was supplied, so finality is not joined",
                )
            )
    publish = (
        instructed
        and not problems
        and receipt_grade.disposition is Disposition.PASS
        and venue.state is EvidenceState.FINAL
        and venue.assertion is not None
    )
    stage = _stage(venue, instructed, publish)
    disposition, reason = _disposition(
        publish=publish,
        problems=problems,
        receipt=receipt_grade,
        venue=venue,
    )
    return SettlementJoin(
        stage=stage,
        disposition=disposition,
        reason=reason,
        leg=leg,
        artifact_digest=digest,
        receipt_disposition=receipt_grade.disposition,
        venue_state=venue.state,
        venue_disposition=venue.disposition,
        assertion=venue.assertion if publish else None,
    )
