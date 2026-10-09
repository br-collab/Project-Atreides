"""Evidence that books and records were posted.

Settlement matching is not a posting. A posting names the posted record, the
authority that posted it, the effective time, and the source event. Missing
or mismatched evidence does not pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self

from cannae_kernel._model import KernelModel, UtcDatetime
from cannae_kernel.actor import ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import EventId, LifecycleId
from cannae_kernel.provenance import Provenance
from pydantic import Field, ValidationError, model_validator

from atreides.dsor.lifecycle_records import _LifecycleRecord

__all__ = [
    "BooksPosting",
    "BooksPostingRecord",
    "PostingAssessment",
    "assess_posting",
    "read_posting",
]


class BooksPosting(KernelModel):
    """One posting observation. Matching a settlement does not create this."""

    posted_record_id: str = Field(min_length=1, description="Identity of the posted record.")
    posting_authority: ActorRef = Field(description="Who posted the record.")
    effective_time: UtcDatetime = Field(description="When the posting took effect, in UTC.")
    source_event_id: EventId = Field(description="The source event this posting records.")
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC] = Field(
        description="A fact from outside, or from a synthetic emulator."
    )

    @model_validator(mode="after")
    def _record_id_is_an_identifier(self) -> Self:
        if self.posted_record_id != self.posted_record_id.strip():
            raise ValueError("posted record id must not have leading or trailing whitespace")
        return self


class PostingAssessment(KernelModel):
    """Whether a posting was observed. A match alone is not a posting."""

    disposition: Disposition = Field(description="PASS, HOLD, or INDETERMINATE.")
    reason: str = Field(min_length=1, description="Why the disposition was reached.")


class BooksPostingRecord(_LifecycleRecord):
    """A DSOR record of one posting. The embedded posting is the evidence."""

    kind: Literal["books_posting"] = "books_posting"
    doctrine_version: Literal["books-posting/0.1"] = "books-posting/0.1"
    lifecycle_id: LifecycleId
    posting: BooksPosting


def assess_posting(
    posting: BooksPosting | None,
    *,
    matched: bool = False,
    source_event_id: EventId | None = None,
) -> PostingAssessment:
    """Grade a posting. A match with no posting is unknown, not posted."""
    if posting is None:
        if matched:
            return PostingAssessment(
                disposition=Disposition.INDETERMINATE,
                reason="settlement matching does not establish a books and records posting",
            )
        return PostingAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="no books and records posting was observed",
        )
    if source_event_id is not None and posting.source_event_id != source_event_id:
        return PostingAssessment(
            disposition=Disposition.HOLD,
            reason="the posting names a different source event than the one under examination",
        )
    return PostingAssessment(
        disposition=Disposition.PASS,
        reason="a books and records posting identifies the posted record, its authority, "
        "its effective time, and its source event",
    )


def read_posting(payload: object) -> BooksPosting | PostingAssessment:
    """Read one posting, or return INDETERMINATE when the payload is not one."""
    try:
        if isinstance(payload, str | bytes):
            return BooksPosting.model_validate_json(payload)
        if isinstance(payload, Mapping):
            return BooksPosting.model_validate(dict(payload))
    except ValidationError:
        return PostingAssessment(
            disposition=Disposition.INDETERMINATE,
            reason="the payload is not a readable books and records posting",
        )
    return PostingAssessment(
        disposition=Disposition.INDETERMINATE,
        reason="the payload is not a readable books and records posting",
    )
