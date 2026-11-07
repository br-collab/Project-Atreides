"""Append-only synthetic account lifecycle owned by Atreides."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from cannae_kernel.account import (
    AccountStatus,
    AccountStatusDocument,
    AccountStatusEntry,
    AttestedAccountStatusDocument,
)
from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import canonical_bytes, digest_bytes
from cannae_kernel.clocks import EventTimes
from cannae_kernel.domains import Domain
from cannae_kernel.events import EventEnvelope, seal
from cannae_kernel.ids import CheckpointId, EventId, LifecycleId
from cannae_kernel.journal import ChainReport, JournalCheckpoint, verify_chain
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

from atreides.agents.tier2.outputs import EligibilityVerification


class RefusalReason(StrEnum):
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    KYC_MISSING = "KYC_MISSING"
    KYC_EXPIRED = "KYC_EXPIRED"
    UBO_UNRESOLVED = "UBO_UNRESOLVED"
    EDD_REQUIRED = "EDD_REQUIRED"
    PROHIBITED = "PROHIBITED"
    KYC_EVIDENCE_TAMPERED = "KYC_EVIDENCE_TAMPERED"
    KYC_EVIDENCE_STALE = "KYC_EVIDENCE_STALE"
    ATREIDES_ELIGIBILITY_FAILED = "ATREIDES_ELIGIBILITY_FAILED"
    HUMAN_APPROVAL_MISSING = "HUMAN_APPROVAL_MISSING"
    HUMAN_APPROVER_REQUIRED = "HUMAN_APPROVER_REQUIRED"
    EVIDENCE_NOT_FRESH = "EVIDENCE_NOT_FRESH"
    TRANSFER_NOT_COMPLETED = "TRANSFER_NOT_COMPLETED"
    FIRST_TRADE_NOT_PERMITTED = "FIRST_TRADE_NOT_PERMITTED"
    REASON_REQUIRED = "REASON_REQUIRED"
    CHAIN_INVALID = "CHAIN_INVALID"


class AccountTransitionRefusedError(ValueError):
    def __init__(self, reason: RefusalReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class AccountEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    account_id: str = Field(min_length=1)
    prior_status: AccountStatus
    status: AccountStatus
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class KYCDecisionReference(BaseModel):
    """Attested Decision System of Record reference from the KYC ladder."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    path_id: str = Field(min_length=1)
    decided_at: datetime
    maximum_age_seconds: int = Field(gt=0)
    payload: str = Field(min_length=1)
    payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class TransferInRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    completed: bool
    completed_at: datetime


class FirstPermittedTradeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    permitted: bool
    traded_at: datetime


class ApproverVerifier(Protocol):
    def is_verified_human(self, actor: ActorRef, approval_ref: str) -> bool: ...


class ActorRegistryApproverVerifier:
    """Resolve identity from the Cannae C2 actor registry snapshot."""

    def __init__(self, registry: Mapping[str, ActorRef]) -> None:
        self._registry = registry

    def is_verified_human(self, actor: ActorRef, approval_ref: str) -> bool:
        registered = self._registry.get(str(actor.actor_id))
        return bool(
            approval_ref
            and registered == actor
            and registered.authenticated
            and registered.actor_kind.value == "HUMAN"
        )


class Requirement(StrEnum):
    AUTHENTICATED_ACTOR = "AUTHENTICATED_ACTOR"
    REASON = "REASON"
    VERIFIED_HUMAN = "VERIFIED_HUMAN"
    VERIFIED_KYC = "VERIFIED_KYC"
    VERIFIED_ELIGIBILITY = "VERIFIED_ELIGIBILITY"
    FRESH_AFTER_RESTRICTION = "FRESH_AFTER_RESTRICTION"
    COMPLETED_TRANSFER = "COMPLETED_TRANSFER"
    PERMITTED_TRADE = "PERMITTED_TRADE"


class TransitionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    requirements: tuple[Requirement, ...]


ALLOWED_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.APPLIED: frozenset(
        {AccountStatus.APPROVED, AccountStatus.RESTRICTED, AccountStatus.CLOSED}
    ),
    AccountStatus.APPROVED: frozenset(
        {AccountStatus.RESTRICTED, AccountStatus.FUNDED, AccountStatus.CLOSED}
    ),
    AccountStatus.RESTRICTED: frozenset({AccountStatus.APPROVED, AccountStatus.CLOSED}),
    AccountStatus.FUNDED: frozenset(
        {AccountStatus.RESTRICTED, AccountStatus.ACTIVE, AccountStatus.CLOSED}
    ),
    AccountStatus.ACTIVE: frozenset({AccountStatus.RESTRICTED, AccountStatus.CLOSED}),
    AccountStatus.CLOSED: frozenset(),
}

_APPROVAL = (
    Requirement.VERIFIED_HUMAN,
    Requirement.VERIFIED_KYC,
    Requirement.VERIFIED_ELIGIBILITY,
)
TRANSITION_RULES: dict[tuple[AccountStatus, AccountStatus], TransitionRule] = {
    (AccountStatus.APPLIED, AccountStatus.APPROVED): TransitionRule(requirements=_APPROVAL),
    (AccountStatus.RESTRICTED, AccountStatus.APPROVED): TransitionRule(
        requirements=(*_APPROVAL, Requirement.FRESH_AFTER_RESTRICTION)
    ),
    (AccountStatus.APPROVED, AccountStatus.FUNDED): TransitionRule(
        requirements=(Requirement.COMPLETED_TRANSFER,)
    ),
    (AccountStatus.FUNDED, AccountStatus.ACTIVE): TransitionRule(
        requirements=(Requirement.PERMITTED_TRADE,)
    ),
    **{
        (source, AccountStatus.RESTRICTED): TransitionRule(
            requirements=(Requirement.AUTHENTICATED_ACTOR, Requirement.REASON)
        )
        for source in (
            AccountStatus.APPLIED,
            AccountStatus.APPROVED,
            AccountStatus.FUNDED,
            AccountStatus.ACTIVE,
        )
    },
    **{
        (source, AccountStatus.CLOSED): TransitionRule(
            requirements=(Requirement.VERIFIED_HUMAN, Requirement.REASON)
        )
        for source in (
            AccountStatus.APPLIED,
            AccountStatus.APPROVED,
            AccountStatus.RESTRICTED,
            AccountStatus.FUNDED,
            AccountStatus.ACTIVE,
        )
    },
}


class AccountLifecycleStore:
    def __init__(self, approver_verifier: ApproverVerifier) -> None:
        self._approver_verifier = approver_verifier
        self._events: list[EventEnvelope[AccountEvent]] = []
        self._lifecycle_ids: dict[str, LifecycleId] = {}
        self._checkpoints: dict[str, JournalCheckpoint] = {}

    @property
    def events(self) -> tuple[EventEnvelope[AccountEvent], ...]:
        return tuple(self._events)

    def apply(self, account_id: str) -> None:
        self._lifecycle_ids.setdefault(
            account_id, LifecycleId(f"lif_{len(self._lifecycle_ids) + 1:026d}")
        )

    def _account_events(self, account_id: str) -> tuple[EventEnvelope[AccountEvent], ...]:
        return tuple(event for event in self._events if event.payload.account_id == account_id)

    def chain_report(self, account_id: str) -> ChainReport:
        return verify_chain(
            self._account_events(account_id), expected_head=self._checkpoints.get(account_id)
        )

    def status(self, account_id: str) -> AccountStatus:
        events = self._account_events(account_id)
        if not events:
            return AccountStatus.APPLIED
        if not self.chain_report(account_id).ok:
            raise AccountTransitionRefusedError(RefusalReason.CHAIN_INVALID)
        return events[-1].payload.status

    def _verify_human(self, actor: ActorRef, approval_ref: str | None) -> None:
        if not approval_ref:
            raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVAL_MISSING)
        if not self._approver_verifier.is_verified_human(actor, approval_ref):
            raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVER_REQUIRED)

    @staticmethod
    def _verify_kyc(evidence: KYCDecisionReference | None, timestamp: datetime) -> None:
        if evidence is None:
            raise AccountTransitionRefusedError(RefusalReason.KYC_MISSING)
        if digest_bytes(evidence.payload.encode()) != evidence.payload_digest:
            raise AccountTransitionRefusedError(RefusalReason.KYC_EVIDENCE_TAMPERED)
        if (timestamp - evidence.decided_at).total_seconds() > evidence.maximum_age_seconds:
            raise AccountTransitionRefusedError(RefusalReason.KYC_EVIDENCE_STALE)
        refusals = {
            "KYC_MISSING_HALT": RefusalReason.KYC_MISSING,
            "KYC_EXPIRED_HALT": RefusalReason.KYC_EXPIRED,
            "KYB_UBO_UNRESOLVED_HALT": RefusalReason.UBO_UNRESOLVED,
            "AML_EDD_REQUIRED_HALT": RefusalReason.EDD_REQUIRED,
            "AML_PROHIBITED_BLOCK": RefusalReason.PROHIBITED,
        }
        if evidence.path_id in refusals:
            raise AccountTransitionRefusedError(refusals[evidence.path_id])
        if evidence.path_id != "KYC_ELIGIBLE_CLEAR":
            raise AccountTransitionRefusedError(RefusalReason.KYC_MISSING)

    def transition(
        self,
        account_id: str,
        target: AccountStatus,
        *,
        actor: ActorRef,
        timestamp: datetime,
        reason: str,
        evidence_refs: tuple[str, ...],
        kyc_evidence: KYCDecisionReference | None = None,
        eligibility: EligibilityVerification | None = None,
        human_approval_ref: str | None = None,
        transfer: TransferInRecord | None = None,
        first_trade: FirstPermittedTradeRecord | None = None,
    ) -> EventEnvelope[AccountEvent]:
        prior = self.status(account_id)
        rule = TRANSITION_RULES.get((prior, target))
        if rule is None:
            raise AccountTransitionRefusedError(RefusalReason.ILLEGAL_TRANSITION)
        requirements = set(rule.requirements)
        if Requirement.REASON in requirements and not reason.strip():
            raise AccountTransitionRefusedError(RefusalReason.REASON_REQUIRED)
        if Requirement.AUTHENTICATED_ACTOR in requirements and not actor.authenticated:
            raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVER_REQUIRED)
        if Requirement.VERIFIED_HUMAN in requirements:
            self._verify_human(actor, human_approval_ref)
        if Requirement.VERIFIED_KYC in requirements:
            try:
                self._verify_kyc(kyc_evidence, timestamp)
            except AccountTransitionRefusedError as exc:
                if exc.reason is RefusalReason.PROHIBITED:
                    self._append_event(
                        account_id,
                        AccountStatus.CLOSED,
                        actor=actor,
                        timestamp=timestamp,
                        reason="prohibited KYC ladder outcome",
                        evidence_refs=evidence_refs,
                    )
                raise
        if Requirement.VERIFIED_ELIGIBILITY in requirements:
            if eligibility is None or not eligibility.all_passed:
                raise AccountTransitionRefusedError(RefusalReason.ATREIDES_ELIGIBILITY_FAILED)
        if Requirement.FRESH_AFTER_RESTRICTION in requirements:
            restriction_time = self._account_events(account_id)[-1].times.processing_time
            eligibility_times = (
                ()
                if eligibility is None
                else tuple(check.verified_at for check in eligibility.checks)
            )
            if (
                kyc_evidence is None
                or kyc_evidence.decided_at <= restriction_time
                or not eligibility_times
                or min(eligibility_times) <= restriction_time
            ):
                raise AccountTransitionRefusedError(RefusalReason.EVIDENCE_NOT_FRESH)
        if Requirement.COMPLETED_TRANSFER in requirements:
            if (
                transfer is None
                or not transfer.completed
                or transfer.record_id not in evidence_refs
            ):
                raise AccountTransitionRefusedError(RefusalReason.TRANSFER_NOT_COMPLETED)
        if Requirement.PERMITTED_TRADE in requirements:
            if (
                first_trade is None
                or not first_trade.permitted
                or first_trade.record_id not in evidence_refs
            ):
                raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_NOT_PERMITTED)
        return self._append_event(
            account_id,
            target,
            actor=actor,
            timestamp=timestamp,
            reason=reason,
            evidence_refs=evidence_refs,
        )

    def _append_event(
        self,
        account_id: str,
        target: AccountStatus,
        *,
        actor: ActorRef,
        timestamp: datetime,
        reason: str,
        evidence_refs: tuple[str, ...],
    ) -> EventEnvelope[AccountEvent]:
        self.apply(account_id)
        prior_events = self._account_events(account_id)
        prior = prior_events[-1].payload.status if prior_events else AccountStatus.APPLIED
        number = len(self._events) + 1
        envelope = seal(
            event_id=EventId(f"evt_{number:026d}"),
            lifecycle_id=self._lifecycle_ids[account_id],
            parent_ids=() if not prior_events else (prior_events[-1].event_id,),
            producer_domain=Domain.ATREIDES,
            event_type="AccountStatusChanged",
            schema_version="atreides.account_status_changed/1",
            rule_version="account-lifecycle/2",
            times=EventTimes(
                event_time=timestamp,
                observation_time=timestamp,
                processing_time=timestamp,
                decision_time=timestamp,
            ),
            provenance=Provenance.HUMAN_JUDGMENT,
            actor=actor,
            idempotency_key=f"account-{account_id}-{number}",
            payload=AccountEvent(
                account_id=account_id,
                prior_status=prior,
                status=target,
                reason=reason,
                evidence_refs=evidence_refs,
            ),
            prior_event_digest=prior_events[-1].envelope_digest if prior_events else None,
        )
        self._events.append(envelope)
        account_events = self._account_events(account_id)
        self._checkpoints[account_id] = JournalCheckpoint(
            checkpoint_id=CheckpointId(f"ckp_{number:026d}"),
            lifecycle_id=envelope.lifecycle_id,
            domain=Domain.ATREIDES,
            head_event_id=envelope.event_id,
            head_digest=envelope.envelope_digest,
            event_count=len(account_events),
            taken_at=timestamp,
            recorded_by=actor,
        )
        return envelope

    def publish_status(self, *, as_of: datetime, maximum_age_seconds: int) -> bytes:
        document = AccountStatusDocument(
            as_of=as_of,
            maximum_age_seconds=maximum_age_seconds,
            accounts=tuple(
                AccountStatusEntry(
                    account_id=account_id,
                    status=self.status(account_id),
                    last_event_id=next(
                        str(event.event_id)
                        for event in reversed(self._events)
                        if event.payload.account_id == account_id
                    ),
                )
                for account_id in sorted(self._lifecycle_ids)
                if any(event.payload.account_id == account_id for event in self._events)
            ),
        )
        payload = canonical_bytes(document)
        return (
            AttestedAccountStatusDocument(
                payload_digest=digest_bytes(payload), payload=payload.decode()
            )
            .model_dump_json()
            .encode()
        )

    def approval_to_first_funded_trade_seconds(self) -> tuple[int, ...]:
        durations: list[int] = []
        for account_id in self._lifecycle_ids:
            events = self._account_events(account_id)
            approved = next(
                (event for event in events if event.payload.status is AccountStatus.APPROVED), None
            )
            active = next(
                (event for event in events if event.payload.status is AccountStatus.ACTIVE), None
            )
            if approved is not None and active is not None:
                durations.append(
                    int(
                        (
                            active.times.processing_time - approved.times.processing_time
                        ).total_seconds()
                    )
                )
        return tuple(durations)
