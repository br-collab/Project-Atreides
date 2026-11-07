"""Append-only synthetic account lifecycle owned by Atreides."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from cannae_kernel.account import (
    AccountStatus,
    AccountStatusDocument,
    AccountStatusEntry,
    AttestedAccountStatusDocument,
)
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes, digest_bytes
from pydantic import BaseModel, ConfigDict, Field


class RefusalReason(StrEnum):
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    KYC_LADDER_NOT_CLEAR = "KYC_LADDER_NOT_CLEAR"
    ATREIDES_ELIGIBILITY_FAILED = "ATREIDES_ELIGIBILITY_FAILED"
    HUMAN_APPROVAL_MISSING = "HUMAN_APPROVAL_MISSING"
    HUMAN_APPROVER_REQUIRED = "HUMAN_APPROVER_REQUIRED"
    TRANSFER_NOT_CLEAN = "TRANSFER_NOT_CLEAN"
    FIRST_TRADE_NOT_PERMITTED = "FIRST_TRADE_NOT_PERMITTED"


class AccountTransitionRefusedError(ValueError):
    def __init__(self, reason: RefusalReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class AccountEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    event_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    prior_status: AccountStatus
    status: AccountStatus
    actor: ActorRef
    timestamp: datetime
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


ALLOWED_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.APPLIED: frozenset({AccountStatus.APPROVED, AccountStatus.CLOSED}),
    AccountStatus.APPROVED: frozenset({AccountStatus.RESTRICTED, AccountStatus.FUNDED}),
    AccountStatus.RESTRICTED: frozenset({AccountStatus.APPROVED, AccountStatus.CLOSED}),
    AccountStatus.FUNDED: frozenset({AccountStatus.RESTRICTED, AccountStatus.ACTIVE}),
    AccountStatus.ACTIVE: frozenset({AccountStatus.RESTRICTED, AccountStatus.CLOSED}),
    AccountStatus.CLOSED: frozenset(),
}


class AccountLifecycleStore:
    def __init__(self) -> None:
        self._status: dict[str, AccountStatus] = {}
        self.events: list[AccountEvent] = []

    def apply(self, account_id: str) -> None:
        self._status.setdefault(account_id, AccountStatus.APPLIED)

    def status(self, account_id: str) -> AccountStatus:
        return self._status.get(account_id, AccountStatus.APPLIED)

    def transition(
        self,
        account_id: str,
        target: AccountStatus,
        *,
        actor: ActorRef,
        timestamp: datetime,
        reason: str,
        evidence_refs: tuple[str, ...],
        kyc_ladder_outcome: str | None = None,
        eligibility_passed: bool | None = None,
        human_approval_ref: str | None = None,
        transfer_clean: bool | None = None,
        first_trade_permitted: bool | None = None,
    ) -> AccountEvent:
        prior = self.status(account_id)
        if target not in ALLOWED_TRANSITIONS[prior]:
            raise AccountTransitionRefusedError(RefusalReason.ILLEGAL_TRANSITION)
        if prior is AccountStatus.APPLIED and target is AccountStatus.APPROVED:
            if kyc_ladder_outcome != "KYC_ELIGIBLE_CLEAR":
                raise AccountTransitionRefusedError(RefusalReason.KYC_LADDER_NOT_CLEAR)
            if eligibility_passed is not True:
                raise AccountTransitionRefusedError(RefusalReason.ATREIDES_ELIGIBILITY_FAILED)
            if not human_approval_ref:
                raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVAL_MISSING)
            if actor.actor_kind is not ActorKind.HUMAN or not actor.authenticated:
                raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVER_REQUIRED)
        if prior is AccountStatus.APPROVED and target is AccountStatus.FUNDED:
            if transfer_clean is not True:
                raise AccountTransitionRefusedError(RefusalReason.TRANSFER_NOT_CLEAN)
        if prior is AccountStatus.FUNDED and target is AccountStatus.ACTIVE:
            if first_trade_permitted is not True:
                raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_NOT_PERMITTED)
        event = AccountEvent(
            event_id=f"SYN-ACCOUNT-EVENT-{len(self.events) + 1:06d}",
            account_id=account_id,
            prior_status=prior,
            status=target,
            actor=actor,
            timestamp=timestamp,
            reason=reason,
            evidence_refs=evidence_refs,
        )
        self.events.append(event)
        self._status[account_id] = target
        return event

    def publish_status(self, *, as_of: datetime, maximum_age_seconds: int) -> bytes:
        document = AccountStatusDocument(
            as_of=as_of,
            maximum_age_seconds=maximum_age_seconds,
            accounts=tuple(
                AccountStatusEntry(
                    account_id=account_id,
                    status=status,
                    last_event_id=next(
                        event.event_id
                        for event in reversed(self.events)
                        if event.account_id == account_id
                    ),
                )
                for account_id, status in sorted(self._status.items())
                if any(event.account_id == account_id for event in self.events)
            ),
        )
        payload = canonical_bytes(document)
        return AttestedAccountStatusDocument(
            payload_digest=digest_bytes(payload), payload=payload.decode()
        ).model_dump_json().encode()
