"""Fail-closed assessment across independently evidenced lifecycle stages.

Each input is the production evidence type owned by its stage.  Reaching one
stage never supplies evidence for the next: secured funding is not finality,
finality is not a books posting, posting is not output production, and output
production is not delivery.  Exception resolution is reported separately and
never closes the settlement lifecycle.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from cannae_kernel._model import KernelModel
from cannae_kernel.disposition import Disposition
from cannae_kernel.envelopes import ExecutionEvent
from cannae_kernel.finality import FinalityAssertion, FinalityType
from pydantic import Field, model_validator

from atreides.cockpit.breaks import BreakRecord, BreakState
from atreides.dsor.books import BooksPosting
from atreides.dsor.client_output import ClientOutputEvidence
from atreides.messaging.settlement_join import JoinedStage, SettlementJoin
from atreides.rails.secured_funding import SecuredFunding

__all__ = [
    "CrossStageAssessment",
    "EvidenceStage",
    "assess_lifecycle_evidence",
]


class EvidenceStage(StrEnum):
    """Furthest contiguous settlement stage supported by direct evidence."""

    UNREAD = "UNREAD"
    EXECUTION_RECEIVED = "EXECUTION_RECEIVED"
    FUNDING_SECURED = "FUNDING_SECURED"
    SETTLEMENT_FINAL = "SETTLEMENT_FINAL"
    BOOKS_POSTED = "BOOKS_POSTED"
    OUTPUT_PRODUCED = "OUTPUT_PRODUCED"
    OUTPUT_DELIVERED = "OUTPUT_DELIVERED"


class CrossStageAssessment(KernelModel):
    """One assessment; exception closure remains a separate dimension."""

    stage: EvidenceStage = Field(description="Furthest contiguous evidenced stage.")
    disposition: Disposition = Field(description="Grade of that cross-stage assessment.")
    reason: str = Field(min_length=1, description="Why the grade was reached.")
    finality_assertion: FinalityAssertion | None = Field(
        default=None,
        description="The delivered kernel assertion, present from settlement final onward.",
    )
    output_delivered: bool = Field(
        default=False,
        description="True only when separate delivery evidence is present.",
    )
    exception_closure: Disposition = Field(
        description="Grade of exception closure, independent of the settlement stage."
    )
    exception_reason: str = Field(
        min_length=1,
        description="Why exception closure did or did not pass.",
    )

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        final_or_later = self.stage in {
            EvidenceStage.SETTLEMENT_FINAL,
            EvidenceStage.BOOKS_POSTED,
            EvidenceStage.OUTPUT_PRODUCED,
            EvidenceStage.OUTPUT_DELIVERED,
        }
        if final_or_later != (self.finality_assertion is not None):
            raise ValueError("settlement-final and later stages preserve the kernel assertion")
        if self.output_delivered != (self.stage is EvidenceStage.OUTPUT_DELIVERED):
            raise ValueError("only separate delivery evidence marks output delivered")
        return self


def _exception_grade(record: BreakRecord | None) -> tuple[Disposition, str]:
    if record is None:
        return Disposition.INDETERMINATE, "no exception record was supplied"
    if record.state is BreakState.RESOLVED and record.resolution_evidence is not None:
        return Disposition.PASS, "the exception has attributable resolution evidence"
    return Disposition.HOLD, "the exception is not evidence-backed as resolved"


def _assessment(
    stage: EvidenceStage,
    disposition: Disposition,
    reason: str,
    *,
    assertion: FinalityAssertion | None,
    exception: BreakRecord | None,
    output_delivered: bool = False,
) -> CrossStageAssessment:
    exception_disposition, exception_reason = _exception_grade(exception)
    return CrossStageAssessment(
        stage=stage,
        disposition=disposition,
        reason=reason,
        finality_assertion=assertion,
        output_delivered=output_delivered,
        exception_closure=exception_disposition,
        exception_reason=exception_reason,
    )


def assess_lifecycle_evidence(
    *,
    execution: ExecutionEvent | None,
    funding: SecuredFunding | None,
    settlement: SettlementJoin | None,
    posting: BooksPosting | None,
    output: ClientOutputEvidence | None,
    exception: BreakRecord | None = None,
) -> CrossStageAssessment:
    """Assess the real stage evidence without inferring across a missing boundary."""
    if execution is None:
        return _assessment(
            EvidenceStage.UNREAD,
            Disposition.INDETERMINATE,
            "no execution event was received",
            assertion=None,
            exception=exception,
        )
    if funding is None:
        return _assessment(
            EvidenceStage.EXECUTION_RECEIVED,
            Disposition.INDETERMINATE,
            "execution was received, and secured funding was not observed",
            assertion=None,
            exception=exception,
        )
    if settlement is None:
        return _assessment(
            EvidenceStage.FUNDING_SECURED,
            Disposition.INDETERMINATE,
            "funding was observed, and settlement finality was not read",
            assertion=None,
            exception=exception,
        )
    if (
        settlement.stage is not JoinedStage.FINAL
        or settlement.disposition is not Disposition.PASS
        or settlement.assertion is None
        or settlement.assertion.finality_type
        not in {FinalityType.ASSET_FINAL, FinalityType.CASH_FINAL}
    ):
        disposition = (
            Disposition.HOLD
            if settlement.disposition is Disposition.HOLD
            else Disposition.INDETERMINATE
        )
        return _assessment(
            EvidenceStage.FUNDING_SECURED,
            disposition,
            "secured funding does not establish settlement finality",
            assertion=None,
            exception=exception,
        )
    assertion = settlement.assertion
    if posting is None:
        return _assessment(
            EvidenceStage.SETTLEMENT_FINAL,
            Disposition.INDETERMINATE,
            "settlement finality does not establish a books and records posting",
            assertion=assertion,
            exception=exception,
        )
    if posting.source_event_id != execution.event_id:
        return _assessment(
            EvidenceStage.SETTLEMENT_FINAL,
            Disposition.HOLD,
            "the posting names a different source event than the received execution",
            assertion=assertion,
            exception=exception,
        )
    if output is None:
        return _assessment(
            EvidenceStage.BOOKS_POSTED,
            Disposition.INDETERMINATE,
            "a books and records posting does not establish client output production",
            assertion=assertion,
            exception=exception,
        )
    if output.source_event_id != execution.event_id:
        return _assessment(
            EvidenceStage.BOOKS_POSTED,
            Disposition.HOLD,
            "the client output names a different source event than the received execution",
            assertion=assertion,
            exception=exception,
        )
    if output.delivery is None:
        return _assessment(
            EvidenceStage.OUTPUT_PRODUCED,
            Disposition.PASS,
            "client output was produced, and delivery was not observed",
            assertion=assertion,
            exception=exception,
        )
    return _assessment(
        EvidenceStage.OUTPUT_DELIVERED,
        Disposition.PASS,
        "client output was produced and separate delivery evidence was recorded",
        assertion=assertion,
        exception=exception,
        output_delivered=True,
    )
