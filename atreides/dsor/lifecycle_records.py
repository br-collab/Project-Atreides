"""Settlement-lifecycle record kinds for the DSOR (ATR-I-12, slice-minimal).

DRAFT, ``0.1-draft`` (JUM-D-26). One record kind per lifecycle fact the first
settlement slice needs to journal. The obligation acceptance record
(:mod:`atreides.acceptance.record`) and the cash-gate decision record
(:mod:`atreides.rails.cato_f_record`) live beside the code that produces them;
the kinds below have no other home yet.

Store subject: the DSOR store allows one original record per ``operation_id``,
so ``operation_id`` on every record here is the record's own identifier, supplied
by the application service that writes it. What a record is *about* is carried
in ``lifecycle_id`` and, where there is one, ``obligation_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from cannae_kernel.canonical import Digest
from cannae_kernel.finality import FinalityAssertion
from cannae_kernel.halt import HaltContext
from cannae_kernel.ids import LifecycleId, ObligationId
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atreides.messaging.readback import SettlementStatus

__all__ = [
    "FinalityAssertedRecord",
    "HaltRecord",
    "InstructionPreparedRecord",
    "RailStatusObservedRecord",
    "ReconciliationResultRecord",
]


class _LifecycleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.1-draft"] = "0.1-draft"
    #: The record's own id; the DSOR store's record subject.
    operation_id: UUID
    lifecycle_id: LifecycleId | None


class HaltRecord(_LifecycleRecord):
    """A halt context as declared or cleared. ``lifecycle_id`` is ``None`` for a halt
    that is not about one lifecycle."""

    kind: Literal["halt_context"] = "halt_context"
    halt: HaltContext

    @property
    def event(self) -> Literal["declared", "cleared"]:
        return "declared" if self.halt.active else "cleared"


class InstructionPreparedRecord(_LifecycleRecord):
    """``INSTRUCTION_PREPARED``: an instruction artifact exists for an accepted obligation.

    Prepared, never submitted. The artifact itself is referenced by digest.
    """

    kind: Literal["instruction_prepared"] = "instruction_prepared"
    obligation_id: ObligationId
    obligation_digest: Digest
    #: ``sha256:`` of the acceptance record that authorized preparation.
    acceptance_record_digest: Digest
    message_definition: str = Field(min_length=1)
    end_to_end_id: str = Field(min_length=1)
    #: ``sha256:`` over the header bytes followed by the document bytes.
    artifact_digest: Digest
    prepared_at: datetime
    is_submission: Literal[False] = False

    @model_validator(mode="after")
    def _never_a_submission(self) -> Self:
        if self.is_submission is not False:  # pragma: no cover - Literal already refuses
            raise ValueError("a prepared instruction is never a submission")
        return self


class RailStatusObservedRecord(_LifecycleRecord):
    """A status the rail reported, as observed in a reconciled readback."""

    kind: Literal["rail_status_observed"] = "rail_status_observed"
    obligation_id: ObligationId | None = None
    end_to_end_id: str = Field(min_length=1)
    status: SettlementStatus
    status_code: str = Field(min_length=1)
    status_report_message_id: str = Field(min_length=1)
    observed_at: datetime
    #: A rail status is a fact reported from outside: external, or from an emulator.
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC]


class FinalityAssertedRecord(_LifecycleRecord):
    """One element of the finality vector (charter §19.5), as asserted."""

    kind: Literal["finality_asserted"] = "finality_asserted"
    obligation_id: ObligationId | None = None
    assertion: FinalityAssertion


class ReconciliationResultRecord(_LifecycleRecord):
    """The outcome of reconciling a readback against what was prepared."""

    kind: Literal["reconciliation_result"] = "reconciliation_result"
    obligation_id: ObligationId | None = None
    status_report_message_id: str | None
    matched: bool
    break_codes: tuple[str, ...]
    reconciled_at: datetime

    @model_validator(mode="after")
    def _matched_means_no_breaks(self) -> Self:
        if self.matched == bool(self.break_codes):
            raise ValueError("a matched reconciliation has no breaks; an unmatched one names them")
        return self
