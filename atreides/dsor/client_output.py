"""Evidence that a client output was produced.

Production is not delivery. A books and records posting is not production.
Delivery is a separate observation. Without it, the output stays produced.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Self

from cannae_kernel._model import KernelModel, UtcDatetime
from cannae_kernel.canonical import Digest
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import EventId, LifecycleId
from cannae_kernel.provenance import Provenance
from pydantic import Field, ValidationError, model_validator

from atreides.dsor.lifecycle_records import _LifecycleRecord

__all__ = [
    "ClientOutputEvidence",
    "ClientOutputRecord",
    "DeliveryObservation",
    "OutputReading",
    "OutputStage",
    "assess_client_output",
    "read_client_output",
]


class OutputStage(StrEnum):
    """How far client output evidence goes. Produced is not delivered."""

    UNREAD = "UNREAD"
    """No client output was read."""

    PRODUCED = "PRODUCED"
    """An output artifact was produced. Produced is not delivered."""

    DELIVERED = "DELIVERED"
    """Separate delivery evidence says the output was delivered."""


class DeliveryObservation(KernelModel):
    """A separate fact that an output was delivered. Production does not imply it."""

    observation_time: UtcDatetime = Field(description="When delivery was observed, in UTC.")
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC] = Field(
        description="A fact from outside, or from a synthetic emulator."
    )
    recipient_ref: str = Field(min_length=1, description="Who the delivery observation names.")

    @model_validator(mode="after")
    def _recipient_is_an_identifier(self) -> Self:
        if self.recipient_ref != self.recipient_ref.strip():
            raise ValueError("recipient ref must not have leading or trailing whitespace")
        return self


class ClientOutputEvidence(KernelModel):
    """One produced output. Delivery is present only when it was observed."""

    artifact_digest: Digest = Field(description="Digest of the produced output artifact.")
    recipient_class: str = Field(min_length=1, description="The intended recipient class.")
    source_event_id: EventId = Field(description="The source event this output was produced from.")
    generation_time: UtcDatetime = Field(description="When the output was generated, in UTC.")
    provenance: Literal[Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC] = Field(
        description="A fact from outside, or from a synthetic emulator."
    )
    delivery: DeliveryObservation | None = Field(
        default=None,
        description="Delivery evidence. Absent means the output was not observed as delivered.",
    )

    @model_validator(mode="after")
    def _recipient_class_is_an_identifier(self) -> Self:
        if self.recipient_class != self.recipient_class.strip():
            raise ValueError("recipient class must not have leading or trailing whitespace")
        return self


class OutputReading(KernelModel):
    """One reading of client output. Delivery is its own stage."""

    stage: OutputStage = Field(description="Unread, produced, or delivered.")
    disposition: Disposition = Field(description="PASS, HOLD, or INDETERMINATE.")
    reason: str = Field(min_length=1, description="Why the disposition was reached.")
    delivered: bool = Field(description="True only when delivery evidence joined and passed.")

    @model_validator(mode="after")
    def _delivery_is_its_own_pass(self) -> Self:
        if self.delivered != (self.stage is OutputStage.DELIVERED):
            raise ValueError("only a delivered stage says the output was delivered")
        if self.stage is OutputStage.DELIVERED and self.disposition is not Disposition.PASS:
            raise ValueError("delivery is recorded only when the output evidence passes")
        if self.stage is OutputStage.UNREAD and self.disposition is Disposition.PASS:
            raise ValueError("an unread output cannot pass")
        return self


class ClientOutputRecord(_LifecycleRecord):
    """A DSOR record of one client output. The embedded evidence is the output."""

    kind: Literal["client_output"] = "client_output"
    doctrine_version: Literal["client-output/0.1"] = "client-output/0.1"
    lifecycle_id: LifecycleId
    client_output: ClientOutputEvidence


def assess_client_output(
    evidence: ClientOutputEvidence | None,
    *,
    posted: bool = False,
    source_event_id: EventId | None = None,
) -> OutputReading:
    """Grade output evidence. A posting does not produce it, and production does not deliver it."""
    if evidence is None:
        if posted:
            return OutputReading(
                stage=OutputStage.UNREAD,
                disposition=Disposition.INDETERMINATE,
                reason="a books and records posting does not produce client output",
                delivered=False,
            )
        return OutputReading(
            stage=OutputStage.UNREAD,
            disposition=Disposition.INDETERMINATE,
            reason="no client output was observed",
            delivered=False,
        )
    if source_event_id is not None and evidence.source_event_id != source_event_id:
        return OutputReading(
            stage=OutputStage.PRODUCED,
            disposition=Disposition.HOLD,
            reason=(
                "the client output names a different source event than the one under examination"
            ),
            delivered=False,
        )
    if evidence.delivery is None:
        return OutputReading(
            stage=OutputStage.PRODUCED,
            disposition=Disposition.PASS,
            reason="client output was produced, and delivery was not observed",
            delivered=False,
        )
    return OutputReading(
        stage=OutputStage.DELIVERED,
        disposition=Disposition.PASS,
        reason="client output was produced and a separate delivery observation was recorded",
        delivered=True,
    )


def read_client_output(payload: object) -> ClientOutputEvidence | OutputReading:
    """Read one output, or return INDETERMINATE when the payload is not one."""
    unread = OutputReading(
        stage=OutputStage.UNREAD,
        disposition=Disposition.INDETERMINATE,
        reason="the payload is not a readable client output",
        delivered=False,
    )
    try:
        if isinstance(payload, str | bytes):
            return ClientOutputEvidence.model_validate_json(payload)
        if isinstance(payload, Mapping):
            return ClientOutputEvidence.model_validate(dict(payload))
    except ValidationError:
        return unread
    return unread
