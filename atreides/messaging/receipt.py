"""Evidence that an entitled member performed an action outside Atreides.

EXPERIMENTAL. Atreides records the action. It does not perform it, authorize
it, or instruct anyone to perform it. A receipt is usable only when its
digest is the exact digest of the prepared artifact and the action was not
observed before that artifact existed. Anything else is HOLD or
INDETERMINATE, never a clean pass.

The digest this module checks is ``instruction_artifact_digest``: the
``sha256:`` digest of the header bytes followed by the document bytes, which
is the digest ``InstructionPreparedRecord.artifact_digest`` names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from cannae_kernel._model import KernelModel, UtcDatetime
from cannae_kernel.canonical import Digest
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import EventId
from cannae_kernel.provenance import Provenance
from pydantic import Field, TypeAdapter, ValidationError, model_validator

__all__ = [
    "ExternalAction",
    "ExternalActionReceipt",
    "ReceiptAssessment",
    "assess_receipt",
    "assess_receipts",
    "read_receipt",
]

_MAX_IDENTIFIER = 35
_UNREADABLE = "the payload is not a readable external action receipt"
_DIGEST = TypeAdapter(Digest)


class ExternalAction(StrEnum):
    """An action an entitled member performed outside Atreides.

    Naming the action records what was observed. It does not ask anyone to
    perform it.
    """

    CLEARING_SUBMISSION = "CLEARING_SUBMISSION"
    """The entitled member submitted the artifact to clearing."""

    SETTLEMENT_INSTRUCTION = "SETTLEMENT_INSTRUCTION"
    """The entitled member instructed settlement of the artifact."""


class ExternalActionReceipt(KernelModel):
    """One observed external action, tied to one prepared artifact.

    ``authorizes_action`` and ``is_submission`` are false and cannot be made
    true. The receipt is evidence. It is not an instruction.
    """

    entitled_member_id: str = Field(min_length=1, description="Who performed the action.")
    event_id: EventId = Field(
        description="Event identifier carried on the evidence. Not minted here."
    )
    action: ExternalAction = Field(description="Which external action was observed.")
    artifact_digest: Digest = Field(
        description="Exact sha256 digest of the prepared artifact header bytes then document bytes."
    )
    observation_time: UtcDatetime = Field(description="When the action was observed, in UTC.")
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC] = Field(
        description="A fact from outside, or from a synthetic emulator. Never a forecast."
    )
    message_id: str = Field(
        min_length=1,
        max_length=_MAX_IDENTIFIER,
        description="Message identifier of the prepared instruction this action used.",
    )
    end_to_end_id: str = Field(
        min_length=1,
        max_length=_MAX_IDENTIFIER,
        description="End-to-end identifier of the prepared instruction this action used.",
    )
    authorizes_action: Literal[False] = Field(
        default=False,
        description="Always false. A receipt does not authorize the action it records.",
    )
    is_submission: Literal[False] = Field(
        default=False,
        description="Always false. Atreides does not submit, and a receipt is not a submission.",
    )

    @model_validator(mode="after")
    def _member_is_an_identifier(self) -> Self:
        if self.entitled_member_id != self.entitled_member_id.strip():
            raise ValueError("entitled member id must not have leading or trailing whitespace")
        return self


class ReceiptAssessment(KernelModel):
    """Whether a receipt is usable evidence. PASS is never finality."""

    disposition: Disposition = Field(description="PASS, HOLD, or INDETERMINATE.")
    reason: str = Field(min_length=1, description="Why the disposition was reached.")


def _unreadable() -> ReceiptAssessment:
    return ReceiptAssessment(disposition=Disposition.INDETERMINATE, reason=_UNREADABLE)


def read_receipt(payload: object) -> ExternalActionReceipt | ReceiptAssessment:
    """Read one receipt, or return INDETERMINATE when the payload is not one.

    A failed read has no receipt. Callers cannot treat it as an action that
    happened.
    """
    if isinstance(payload, str | bytes):
        try:
            return ExternalActionReceipt.model_validate_json(payload)
        except ValidationError:
            return _unreadable()
    if isinstance(payload, Mapping):
        try:
            return ExternalActionReceipt.model_validate(dict(payload))
        except ValidationError:
            return _unreadable()
    return _unreadable()


def _valid_digest(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        _DIGEST.validate_python(value)
    except ValidationError:
        return False
    return True


def assess_receipt(
    receipt: ExternalActionReceipt,
    *,
    prepared_artifact_digest: str | None,
    prepared_at: datetime | None,
) -> ReceiptAssessment:
    """Grade one receipt against the artifact it claims to evidence.

    A missing or malformed digest, or a preparation time that is not UTC, is
    unverifiable (INDETERMINATE). A different digest, or an observation
    before the artifact existed, is a contradiction or stale (HOLD).
    """
    if not _valid_digest(prepared_artifact_digest):
        return ReceiptAssessment(
            disposition=Disposition.INDETERMINATE,
            reason=(
                "no usable prepared artifact digest was supplied, so the receipt cannot be verified"
            ),
        )
    if not isinstance(prepared_at, datetime) or prepared_at.utcoffset() != timedelta(0):
        return ReceiptAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="the preparation time is missing or not UTC, so staleness cannot be judged",
        )
    if receipt.artifact_digest != prepared_artifact_digest:
        return ReceiptAssessment(
            disposition=Disposition.HOLD,
            reason="the receipt digest does not match the prepared artifact",
        )
    if receipt.observation_time < prepared_at:
        return ReceiptAssessment(
            disposition=Disposition.HOLD,
            reason="the action was observed before the artifact was prepared",
        )
    return ReceiptAssessment(
        disposition=Disposition.PASS,
        reason="the receipt matches the prepared artifact and was not observed before it existed",
    )


def _disagree(group: Sequence[ExternalActionReceipt]) -> bool:
    first = group[0]
    return any(
        receipt.action is not first.action
        or receipt.artifact_digest != first.artifact_digest
        or receipt.entitled_member_id != first.entitled_member_id
        or receipt.message_id != first.message_id
        or receipt.end_to_end_id != first.end_to_end_id
        for receipt in group[1:]
    )


def assess_receipts(
    receipts: Sequence[ExternalActionReceipt],
    *,
    prepared_artifact_digest: str | None,
    prepared_at: datetime | None,
) -> ReceiptAssessment:
    """Grade a set. No receipts is INDETERMINATE, not a clean pass.

    Receipts for one event that disagree on the action, the digest, the
    member, or the instruction identity are HOLD. Otherwise HOLD outranks
    INDETERMINATE, and INDETERMINATE outranks PASS.
    """
    if not receipts:
        return ReceiptAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="no external action receipt was supplied",
        )
    by_event: dict[str, list[ExternalActionReceipt]] = {}
    for receipt in receipts:
        by_event.setdefault(receipt.event_id, []).append(receipt)
    for event_id, group in by_event.items():
        if _disagree(group):
            return ReceiptAssessment(
                disposition=Disposition.HOLD,
                reason=f"receipts for event {event_id} disagree",
            )
    graded = [
        assess_receipt(
            receipt,
            prepared_artifact_digest=prepared_artifact_digest,
            prepared_at=prepared_at,
        )
        for receipt in receipts
    ]
    for item in graded:
        if item.disposition is Disposition.HOLD:
            return item
    for item in graded:
        if item.disposition is not Disposition.PASS:
            return item
    return ReceiptAssessment(
        disposition=Disposition.PASS,
        reason="every receipt matches the prepared artifact",
    )
