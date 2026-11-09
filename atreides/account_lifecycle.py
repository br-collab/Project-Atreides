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
from atreides.retail_identity import (
    CIPOutcome,
    CIPRecord,
    CustomerProfile,
    PrincipalAcceptanceRecord,
)


class RefusalReason(StrEnum):
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    KYC_MISSING = "KYC_MISSING"
    KYC_EXPIRED = "KYC_EXPIRED"
    UBO_UNRESOLVED = "UBO_UNRESOLVED"
    EDD_REQUIRED = "EDD_REQUIRED"
    PROHIBITED = "PROHIBITED"
    KYC_EVIDENCE_TAMPERED = "KYC_EVIDENCE_TAMPERED"
    KYC_EVIDENCE_STALE = "KYC_EVIDENCE_STALE"
    KYC_EVIDENCE_NOT_FOUND = "KYC_EVIDENCE_NOT_FOUND"
    KYC_ACCOUNT_MISMATCH = "KYC_ACCOUNT_MISMATCH"
    KYC_CHAIN_INVALID = "KYC_CHAIN_INVALID"
    ATREIDES_ELIGIBILITY_FAILED = "ATREIDES_ELIGIBILITY_FAILED"
    ELIGIBILITY_EVIDENCE_NOT_FOUND = "ELIGIBILITY_EVIDENCE_NOT_FOUND"
    ELIGIBILITY_ACCOUNT_MISMATCH = "ELIGIBILITY_ACCOUNT_MISMATCH"
    HUMAN_APPROVAL_MISSING = "HUMAN_APPROVAL_MISSING"
    HUMAN_APPROVER_REQUIRED = "HUMAN_APPROVER_REQUIRED"
    EVIDENCE_NOT_FRESH = "EVIDENCE_NOT_FRESH"
    TRANSFER_NOT_COMPLETED = "TRANSFER_NOT_COMPLETED"
    TRANSFER_EVIDENCE_NOT_FOUND = "TRANSFER_EVIDENCE_NOT_FOUND"
    TRANSFER_ACCOUNT_MISMATCH = "TRANSFER_ACCOUNT_MISMATCH"
    FIRST_TRADE_NOT_PERMITTED = "FIRST_TRADE_NOT_PERMITTED"
    FIRST_TRADE_EVIDENCE_NOT_FOUND = "FIRST_TRADE_EVIDENCE_NOT_FOUND"
    FIRST_TRADE_ACCOUNT_MISMATCH = "FIRST_TRADE_ACCOUNT_MISMATCH"
    FIRST_TRADE_EVIDENCE_TAMPERED = "FIRST_TRADE_EVIDENCE_TAMPERED"
    CIP_EVIDENCE_NOT_FOUND = "CIP_EVIDENCE_NOT_FOUND"
    CIP_ACCOUNT_MISMATCH = "CIP_ACCOUNT_MISMATCH"
    CIP_PERSON_MISMATCH = "CIP_PERSON_MISMATCH"
    CIP_PENDING = "CIP_PENDING"
    CIP_UNABLE_TO_VERIFY = "CIP_UNABLE_TO_VERIFY"
    CIP_LIST_MATCH_ESCALATE = "CIP_LIST_MATCH_ESCALATE"
    PROFILE_EVIDENCE_NOT_FOUND = "PROFILE_EVIDENCE_NOT_FOUND"
    PROFILE_ACCOUNT_MISMATCH = "PROFILE_ACCOUNT_MISMATCH"
    PROFILE_PERSON_MISMATCH = "PROFILE_PERSON_MISMATCH"
    PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
    PRINCIPAL_ACCEPTANCE_NOT_FOUND = "PRINCIPAL_ACCEPTANCE_NOT_FOUND"
    PRINCIPAL_ACCEPTANCE_MISMATCH = "PRINCIPAL_ACCEPTANCE_MISMATCH"
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


class KYCDecisionRecord(BaseModel):
    """Authoritative KYC ladder record resolved from the DSOR."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    path_id: str = Field(min_length=1)
    decided_at: datetime
    maximum_age_seconds: int = Field(gt=0)


class EligibilityResultRecord(BaseModel):
    """Stored output from one authoritative ``verify_eligibility`` run."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    verified_at: datetime
    result: EligibilityVerification


class TransferInRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    completed: bool
    completed_at: datetime


class FirstPermittedTradeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    permitted: bool
    traded_at: datetime


class AttestedFirstPermittedTradeRecord(BaseModel):
    """Exact L.C. payload plus its digest, following the account-status pattern."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload: str = Field(min_length=1)


class AccountType(StrEnum):
    INSTITUTIONAL = "INSTITUTIONAL"
    NATURAL_PERSON = "NATURAL_PERSON"


class AccountApplication(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    account_id: str = Field(min_length=1)
    account_type: AccountType
    person_id: str | None = None


class EvidenceResolver(Protocol):
    """Resolve references only across authoritative producer boundaries."""

    def resolve_kyc(self, record_id: str) -> KYCDecisionRecord: ...

    def resolve_eligibility(self, record_id: str) -> EligibilityResultRecord: ...

    def resolve_transfer_in(self, record_id: str) -> TransferInRecord: ...

    def resolve_first_trade(self, record_id: str) -> FirstPermittedTradeRecord: ...

    def resolve_cip(self, record_id: str) -> CIPRecord: ...

    def resolve_profile(self, record_id: str) -> CustomerProfile: ...

    def resolve_principal_acceptance(self, record_id: str) -> PrincipalAcceptanceRecord: ...


class AuthoritativeEvidenceResolver:
    """Read-only resolver over DSOR, eligibility, ACATS, and L.C. producer stores."""

    def __init__(
        self,
        *,
        kyc_dsor_records: Mapping[str, KYCDecisionRecord],
        kyc_chain_reports: Mapping[str, ChainReport],
        eligibility_records: Mapping[str, EligibilityResultRecord],
        transfer_records: Mapping[str, TransferInRecord],
        first_trade_attestations: Mapping[str, bytes],
        cip_records: Mapping[str, CIPRecord] | None = None,
        profile_records: Mapping[str, CustomerProfile] | None = None,
        principal_acceptance_records: Mapping[str, PrincipalAcceptanceRecord] | None = None,
    ) -> None:
        self._kyc_dsor_records = kyc_dsor_records
        self._kyc_chain_reports = kyc_chain_reports
        self._eligibility_records = eligibility_records
        self._transfer_records = transfer_records
        self._first_trade_attestations = first_trade_attestations
        self._cip_records = {} if cip_records is None else cip_records
        self._profile_records = {} if profile_records is None else profile_records
        self._principal_acceptance_records = (
            {} if principal_acceptance_records is None else principal_acceptance_records
        )

    def resolve_kyc(self, record_id: str) -> KYCDecisionRecord:
        record = self._kyc_dsor_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.KYC_EVIDENCE_NOT_FOUND)
        report = self._kyc_chain_reports.get(record_id)
        if report is None or not report.ok:
            raise AccountTransitionRefusedError(RefusalReason.KYC_CHAIN_INVALID)
        return record

    def resolve_eligibility(self, record_id: str) -> EligibilityResultRecord:
        record = self._eligibility_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.ELIGIBILITY_EVIDENCE_NOT_FOUND)
        return record

    def resolve_transfer_in(self, record_id: str) -> TransferInRecord:
        record = self._transfer_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.TRANSFER_EVIDENCE_NOT_FOUND)
        return record

    def resolve_first_trade(self, record_id: str) -> FirstPermittedTradeRecord:
        wire = self._first_trade_attestations.get(record_id)
        if wire is None:
            raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_EVIDENCE_NOT_FOUND)
        try:
            attestation = AttestedFirstPermittedTradeRecord.model_validate_json(wire)
        except ValueError as exc:
            raise AccountTransitionRefusedError(
                RefusalReason.FIRST_TRADE_EVIDENCE_TAMPERED
            ) from exc
        payload = attestation.payload.encode()
        if digest_bytes(payload) != attestation.payload_digest:
            raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_EVIDENCE_TAMPERED)
        try:
            record = FirstPermittedTradeRecord.model_validate_json(payload)
        except ValueError as exc:
            raise AccountTransitionRefusedError(
                RefusalReason.FIRST_TRADE_EVIDENCE_TAMPERED
            ) from exc
        if record.record_id != record_id:
            raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_EVIDENCE_TAMPERED)
        return record

    def resolve_cip(self, record_id: str) -> CIPRecord:
        record = self._cip_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.CIP_EVIDENCE_NOT_FOUND)
        return record

    def resolve_profile(self, record_id: str) -> CustomerProfile:
        record = self._profile_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.PROFILE_EVIDENCE_NOT_FOUND)
        return record

    def resolve_principal_acceptance(self, record_id: str) -> PrincipalAcceptanceRecord:
        record = self._principal_acceptance_records.get(record_id)
        if record is None:
            raise AccountTransitionRefusedError(RefusalReason.PRINCIPAL_ACCEPTANCE_NOT_FOUND)
        return record


def attest_first_permitted_trade(record: FirstPermittedTradeRecord) -> bytes:
    """Produce the L.C. attestation accepted by the authoritative resolver."""

    payload = canonical_bytes(record)
    return (
        AttestedFirstPermittedTradeRecord(
            payload_digest=digest_bytes(payload), payload=payload.decode()
        )
        .model_dump_json()
        .encode()
    )


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
    def __init__(
        self, approver_verifier: ApproverVerifier, evidence_resolver: EvidenceResolver
    ) -> None:
        self._approver_verifier = approver_verifier
        self._evidence_resolver = evidence_resolver
        self._events: list[EventEnvelope[AccountEvent]] = []
        self._lifecycle_ids: dict[str, LifecycleId] = {}
        self._checkpoints: dict[str, JournalCheckpoint] = {}
        self._applications: dict[str, AccountApplication] = {}

    @property
    def events(self) -> tuple[EventEnvelope[AccountEvent], ...]:
        return tuple(self._events)

    def apply(
        self,
        account_id: str,
        *,
        account_type: AccountType = AccountType.INSTITUTIONAL,
        person_id: str | None = None,
    ) -> None:
        if account_type is AccountType.NATURAL_PERSON and person_id is None:
            raise ValueError("natural-person application requires a synthetic person ID")
        application = AccountApplication(
            account_id=account_id, account_type=account_type, person_id=person_id
        )
        existing = self._applications.get(account_id)
        if existing is not None and existing != application:
            raise ValueError("account application identity cannot change")
        self._applications.setdefault(account_id, application)
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
    def _verify_kyc(
        evidence: KYCDecisionRecord, account_id: str, timestamp: datetime
    ) -> None:
        if evidence.account_id != account_id:
            raise AccountTransitionRefusedError(RefusalReason.KYC_ACCOUNT_MISMATCH)
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

    def transition(  # noqa: PLR0915 - ordered fail-closed evidence ladder
        self,
        account_id: str,
        target: AccountStatus,
        *,
        actor: ActorRef,
        timestamp: datetime,
        reason: str,
        evidence_refs: tuple[str, ...],
        kyc_record_id: str | None = None,
        eligibility_record_id: str | None = None,
        human_approval_ref: str | None = None,
        transfer_record_id: str | None = None,
        first_trade_record_id: str | None = None,
        cip_record_id: str | None = None,
        profile_record_id: str | None = None,
        principal_acceptance_record_id: str | None = None,
    ) -> EventEnvelope[AccountEvent]:
        prior = self.status(account_id)
        rule = TRANSITION_RULES.get((prior, target))
        if rule is None:
            raise AccountTransitionRefusedError(RefusalReason.ILLEGAL_TRANSITION)
        requirements = set(rule.requirements)
        application = self._applications.get(
            account_id,
            AccountApplication(
                account_id=account_id,
                account_type=AccountType.INSTITUTIONAL,
            ),
        )
        if Requirement.REASON in requirements and not reason.strip():
            raise AccountTransitionRefusedError(RefusalReason.REASON_REQUIRED)
        if Requirement.AUTHENTICATED_ACTOR in requirements and not actor.authenticated:
            raise AccountTransitionRefusedError(RefusalReason.HUMAN_APPROVER_REQUIRED)
        if Requirement.VERIFIED_HUMAN in requirements:
            self._verify_human(actor, human_approval_ref)
        if Requirement.VERIFIED_KYC in requirements:
            if kyc_record_id is None:
                raise AccountTransitionRefusedError(RefusalReason.KYC_MISSING)
            kyc_evidence = self._evidence_resolver.resolve_kyc(kyc_record_id)
            try:
                self._verify_kyc(kyc_evidence, account_id, timestamp)
            except AccountTransitionRefusedError as exc:
                if exc.reason is RefusalReason.PROHIBITED:
                    self._append_event(
                        account_id,
                        AccountStatus.CLOSED,
                        actor=actor,
                        timestamp=timestamp,
                        reason="prohibited KYC ladder outcome",
                        evidence_refs=tuple(dict.fromkeys((*evidence_refs, kyc_record_id))),
                    )
                raise
        if Requirement.VERIFIED_ELIGIBILITY in requirements:
            if eligibility_record_id is None:
                raise AccountTransitionRefusedError(
                    RefusalReason.ELIGIBILITY_EVIDENCE_NOT_FOUND
                )
            eligibility = self._evidence_resolver.resolve_eligibility(
                eligibility_record_id
            )
            if eligibility.account_id != account_id:
                raise AccountTransitionRefusedError(
                    RefusalReason.ELIGIBILITY_ACCOUNT_MISMATCH
                )
            if not eligibility.result.all_passed:
                raise AccountTransitionRefusedError(RefusalReason.ATREIDES_ELIGIBILITY_FAILED)
        cip_evidence: CIPRecord | None = None
        profile_evidence: CustomerProfile | None = None
        if (
            target is AccountStatus.APPROVED
            and application.account_type is AccountType.NATURAL_PERSON
        ):
            if cip_record_id is None:
                raise AccountTransitionRefusedError(RefusalReason.CIP_EVIDENCE_NOT_FOUND)
            cip_evidence = self._evidence_resolver.resolve_cip(cip_record_id)
            if cip_evidence.account_id != account_id:
                raise AccountTransitionRefusedError(RefusalReason.CIP_ACCOUNT_MISMATCH)
            if cip_evidence.identity.person_id != application.person_id:
                raise AccountTransitionRefusedError(RefusalReason.CIP_PERSON_MISMATCH)
            cip_refusals = {
                CIPOutcome.PENDING: RefusalReason.CIP_PENDING,
                CIPOutcome.UNABLE_TO_VERIFY: RefusalReason.CIP_UNABLE_TO_VERIFY,
                CIPOutcome.LIST_MATCH_ESCALATE: RefusalReason.CIP_LIST_MATCH_ESCALATE,
            }
            if cip_evidence.outcome in cip_refusals:
                raise AccountTransitionRefusedError(cip_refusals[cip_evidence.outcome])
            if profile_record_id is None:
                raise AccountTransitionRefusedError(RefusalReason.PROFILE_EVIDENCE_NOT_FOUND)
            profile_evidence = self._evidence_resolver.resolve_profile(profile_record_id)
            if profile_evidence.account_id != account_id:
                raise AccountTransitionRefusedError(RefusalReason.PROFILE_ACCOUNT_MISMATCH)
            if profile_evidence.person_id != application.person_id:
                raise AccountTransitionRefusedError(RefusalReason.PROFILE_PERSON_MISMATCH)
            if not profile_evidence.complete:
                raise AccountTransitionRefusedError(RefusalReason.PROFILE_INCOMPLETE)
            if principal_acceptance_record_id is None:
                raise AccountTransitionRefusedError(
                    RefusalReason.PRINCIPAL_ACCEPTANCE_NOT_FOUND
                )
            principal = self._evidence_resolver.resolve_principal_acceptance(
                principal_acceptance_record_id
            )
            if (
                principal.account_id != account_id
                or principal.person_id != application.person_id
                or principal.profile_record_id != profile_evidence.record_id
            ):
                raise AccountTransitionRefusedError(
                    RefusalReason.PRINCIPAL_ACCEPTANCE_MISMATCH
                )
            self._verify_human(principal.actor, principal.approval_ref)
        if Requirement.FRESH_AFTER_RESTRICTION in requirements:
            restriction_time = self._account_events(account_id)[-1].times.processing_time
            if (
                kyc_evidence.decided_at <= restriction_time
                or eligibility.verified_at <= restriction_time
                or (
                    application.account_type is AccountType.NATURAL_PERSON
                    and (
                        cip_evidence is None
                        or profile_evidence is None
                        or cip_evidence.verified_at <= restriction_time
                        or profile_evidence.updated_at <= restriction_time
                    )
                )
            ):
                raise AccountTransitionRefusedError(RefusalReason.EVIDENCE_NOT_FRESH)
        if Requirement.COMPLETED_TRANSFER in requirements:
            if transfer_record_id is None:
                raise AccountTransitionRefusedError(
                    RefusalReason.TRANSFER_EVIDENCE_NOT_FOUND
                )
            transfer = self._evidence_resolver.resolve_transfer_in(transfer_record_id)
            if transfer.account_id != account_id:
                raise AccountTransitionRefusedError(RefusalReason.TRANSFER_ACCOUNT_MISMATCH)
            if not transfer.completed:
                raise AccountTransitionRefusedError(RefusalReason.TRANSFER_NOT_COMPLETED)
        if Requirement.PERMITTED_TRADE in requirements:
            if first_trade_record_id is None:
                raise AccountTransitionRefusedError(
                    RefusalReason.FIRST_TRADE_EVIDENCE_NOT_FOUND
                )
            first_trade = self._evidence_resolver.resolve_first_trade(first_trade_record_id)
            if first_trade.account_id != account_id:
                raise AccountTransitionRefusedError(
                    RefusalReason.FIRST_TRADE_ACCOUNT_MISMATCH
                )
            if not first_trade.permitted:
                raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_NOT_PERMITTED)
        resolved_refs = tuple(
            value
            for value in (
                kyc_record_id,
                eligibility_record_id,
                transfer_record_id,
                first_trade_record_id,
                cip_record_id,
                profile_record_id,
                principal_acceptance_record_id,
            )
            if value is not None
        )
        return self._append_event(
            account_id,
            target,
            actor=actor,
            timestamp=timestamp,
            reason=reason,
            evidence_refs=tuple(dict.fromkeys((*evidence_refs, *resolved_refs))),
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
        if account_id not in self._lifecycle_ids:
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
