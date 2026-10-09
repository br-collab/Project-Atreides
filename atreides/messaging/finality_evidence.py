"""Bind an authoritative settled readback to a kernel finality assertion.

EXPERIMENTAL. The adapter reads a reconciled status report and constructs a
cannae-kernel ``FinalityAssertion`` only when that readback is authoritative
and settled. Received, accepted, refused, settled, and final stay distinct.
No earlier state emits ``ASSET_FINAL`` or ``CASH_FINAL``.

Instructed is not a state here. An instruction to settle is an external
action receipt, joined later, not a status the venue reported.

A fact is not a forecast. A provenance other than ``FACT_EXTERNAL`` or
``FACT_SYNTHETIC`` is refused before an assertion is constructed, because
the kernel would accept a forecast that carries a confidence. This module
never sets a confidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self, assert_never

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
from pydantic import Field, ValidationError, model_validator

from atreides.messaging.readback import ReadbackMatch, SettlementStatus, StatusEntry

__all__ = [
    "EvidenceState",
    "FinalityEvidence",
    "finality_from_readback",
]

_Leg = Literal["asset", "cash"]
_FACTS = frozenset({Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC})


class EvidenceState(StrEnum):
    """How far a readback can be read. Final is the only state that asserts."""

    UNREAD = "UNREAD"
    """Nothing usable was read. Absence and an unrecognised code land here."""

    MATCHED = "MATCHED"
    """The venue has the instruction. Received is not accepted and not final."""

    ACCEPTED = "ACCEPTED"
    """The venue accepted the instruction. Accepted is not settled and not final."""

    REFUSED = "REFUSED"
    """The venue rejected or cancelled the instruction. Refusal is not finality."""

    SETTLED = "SETTLED"
    """The venue said settled. Settled is not yet a finality assertion."""

    FINAL = "FINAL"
    """An authoritative settled readback emitted a kernel finality assertion."""


class FinalityEvidence(KernelModel):
    """One reading of a readback. PASS exists only beside a final assertion."""

    state: EvidenceState = Field(description="How far this readback can be read.")
    disposition: Disposition = Field(
        description="PASS only beside a final assertion. Otherwise HOLD or INDETERMINATE."
    )
    reason: str = Field(min_length=1, description="Why the disposition was reached.")
    leg: _Leg = Field(description="Which leg the caller asked to read, asset or cash.")
    assertion: FinalityAssertion | None = Field(
        default=None,
        description="The kernel assertion. Present only when the state is FINAL.",
    )

    @model_validator(mode="after")
    def _final_is_exactly_one_assertion(self) -> Self:
        final = self.state is EvidenceState.FINAL
        has_assertion = self.assertion is not None
        passed = self.disposition is Disposition.PASS
        if final != has_assertion or final != passed:
            raise ValueError("only a final assertion passes, and only a pass carries one")
        if self.assertion is None:
            return self
        expected = FinalityType.ASSET_FINAL if self.leg == "asset" else FinalityType.CASH_FINAL
        if self.assertion.finality_type is not expected:
            raise ValueError("the assertion type does not match the leg")
        if self.assertion.confidence is not None:
            raise ValueError("a finality fact from this adapter carries no confidence")
        return self


def _open(
    state: EvidenceState,
    disposition: Disposition,
    reason: str,
    leg: _Leg,
) -> FinalityEvidence:
    return FinalityEvidence(
        state=state,
        disposition=disposition,
        reason=reason,
        leg=leg,
        assertion=None,
    )


def _earlier(status: SettlementStatus, leg: _Leg) -> FinalityEvidence | None:
    """The states before settled. None means the venue said settled."""
    if status is SettlementStatus.RECEIVED:
        return _open(
            EvidenceState.MATCHED,
            Disposition.HOLD,
            "received is not accepted, settled, or final",
            leg,
        )
    if status is SettlementStatus.IN_PROGRESS:
        return _open(
            EvidenceState.ACCEPTED,
            Disposition.HOLD,
            "acceptance in progress is not settled or final",
            leg,
        )
    if status is SettlementStatus.ACCEPTED_NOT_POSTED:
        return _open(
            EvidenceState.ACCEPTED,
            Disposition.HOLD,
            "accepted and not posted is not settled or final",
            leg,
        )
    if status is SettlementStatus.ACCEPTED_WITH_CHANGE:
        return _open(
            EvidenceState.ACCEPTED,
            Disposition.HOLD,
            "accepted on other terms is not settled or final",
            leg,
        )
    if status is SettlementStatus.REJECTED:
        return _open(
            EvidenceState.REFUSED,
            Disposition.HOLD,
            "the venue refused the instruction, and refusal is not finality",
            leg,
        )
    if status is SettlementStatus.CANCELLED:
        return _open(
            EvidenceState.REFUSED,
            Disposition.HOLD,
            "the venue cancelled the instruction, and cancellation is not finality",
            leg,
        )
    if status is SettlementStatus.UNRECOGNIZED:
        return _open(
            EvidenceState.UNREAD,
            Disposition.INDETERMINATE,
            "the status code is not recognised, so finality cannot be judged",
            leg,
        )
    if status is SettlementStatus.SETTLED:
        return None
    assert_never(status)


def _settled_fields_are_legal(
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
) -> FinalityEvidence | FinalityAssertion:
    """Return an assertion, or a non-passing reading when the fields are not legal."""
    if provenance not in _FACTS:
        return _open(
            EvidenceState.SETTLED,
            Disposition.INDETERMINATE,
            "the provenance is not an external or synthetic fact, so no finality "
            "assertion is emitted",
            leg,
        )
    if (
        not isinstance(effective_time, datetime)
        or not isinstance(observation_time, datetime)
        or effective_time.utcoffset() != timedelta(0)
        or observation_time.utcoffset() != timedelta(0)
    ):
        return _open(
            EvidenceState.SETTLED,
            Disposition.INDETERMINATE,
            "the effective time or the observation time is not UTC, so finality cannot be judged",
            leg,
        )
    if observation_time < effective_time:
        return _open(
            EvidenceState.SETTLED,
            Disposition.HOLD,
            "the observation is before the effective time, so a fact cannot be asserted",
            leg,
        )
    if not isinstance(governing_rule_set, str) or governing_rule_set == "":
        return _open(
            EvidenceState.SETTLED,
            Disposition.INDETERMINATE,
            "the governing rule is missing, so the assertion cannot be verified",
            leg,
        )
    if not isinstance(evidence_reference, str) or evidence_reference == "":
        return _open(
            EvidenceState.SETTLED,
            Disposition.INDETERMINATE,
            "the evidence reference is missing, so the assertion cannot be verified",
            leg,
        )
    finality_type = FinalityType.ASSET_FINAL if leg == "asset" else FinalityType.CASH_FINAL
    try:
        return FinalityAssertion(
            finality_type=finality_type,
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
    except ValidationError:
        return _open(
            EvidenceState.SETTLED,
            Disposition.INDETERMINATE,
            "the supplied fields are not a legal kernel finality assertion",
            leg,
        )


def finality_from_readback(
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
) -> FinalityEvidence:
    """Read one entry of a reconciled readback.

    Authoritative and settled means all of the following. The readback is
    not absent. The entry is in that readback. The match names the same
    status as the entry. No break attaches to that end-to-end identity.
    The provenance is an external or synthetic fact. Every kernel field is
    present and legal. Anything short of that does not emit ``ASSET_FINAL``
    or ``CASH_FINAL``.
    """
    if match.is_absent:
        return _open(
            EvidenceState.UNREAD,
            Disposition.INDETERMINATE,
            "the readback is absent, so nothing is final",
            leg,
        )
    if entry is None or entry not in match.report.entries:
        return _open(
            EvidenceState.UNREAD,
            Disposition.INDETERMINATE,
            "the entry is not in this readback, so nothing is final",
            leg,
        )
    end_to_end_id = entry.end_to_end_id
    if end_to_end_id is None or end_to_end_id not in match.matched:
        return _open(
            EvidenceState.UNREAD,
            Disposition.INDETERMINATE,
            "the entry has no matched end-to-end identity, so the status cannot be verified",
            leg,
        )
    if match.matched[end_to_end_id] is not entry.status:
        return _open(
            EvidenceState.UNREAD,
            Disposition.INDETERMINATE,
            "the match and the entry do not name the same status, so the status cannot be verified",
            leg,
        )
    earlier = _earlier(entry.status, leg)
    if earlier is not None:
        return earlier
    if any(item.end_to_end_id == end_to_end_id for item in match.breaks):
        return _open(
            EvidenceState.SETTLED,
            Disposition.HOLD,
            "a break attaches to this settled entry, so it is not final",
            leg,
        )
    built = _settled_fields_are_legal(
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
    if isinstance(built, FinalityEvidence):
        return built
    return FinalityEvidence(
        state=EvidenceState.FINAL,
        disposition=Disposition.PASS,
        reason="an authoritative settled readback emitted a kernel finality assertion",
        leg=leg,
        assertion=built,
    )
