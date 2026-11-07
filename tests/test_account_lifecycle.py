from datetime import UTC, datetime, timedelta

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest_bytes
from cannae_kernel.ids import ActorId

from atreides.account_lifecycle import (
    ALLOWED_TRANSITIONS,
    TRANSITION_RULES,
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    FirstPermittedTradeRecord,
    KYCDecisionReference,
    RefusalReason,
    TransferInRecord,
)
from atreides.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
)

NOW = datetime(2026, 11, 7, 16, tzinfo=UTC)


class TestApproverVerifier:
    def is_verified_human(self, candidate: ActorRef, approval_ref: str) -> bool:
        return bool(
            candidate.actor_kind is ActorKind.HUMAN
            and candidate.authenticated
            and approval_ref == "SYN-HUMAN-001"
        )


def actor(kind: ActorKind = ActorKind.HUMAN) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01K00000000000000000000000"),
        actor_kind=kind,
        role="synthetic-approver",
        entitlement_refs=("approve-account",),
        authenticated=True,
    )


def store() -> AccountLifecycleStore:
    return AccountLifecycleStore(TestApproverVerifier())


def kyc(path: str = "KYC_ELIGIBLE_CLEAR", *, at: datetime = NOW) -> KYCDecisionReference:
    payload = f'{{"path_id":"{path}"}}'
    return KYCDecisionReference(
        record_id="SYN-KYC-001",
        path_id=path,
        decided_at=at,
        maximum_age_seconds=300,
        payload=payload,
        payload_digest=digest_bytes(payload.encode()),
    )


def eligibility(*, at: datetime = NOW, passed: bool = True) -> EligibilityVerification:
    return EligibilityVerification(
        checks=tuple(
            EligibilityCheck(
                kind=kind,
                passed=passed,
                failure_reason=None if passed else "synthetic eligibility failure",
                verified_at=at,
            )
            for kind in EligibilityCheckKind
        )
    )


def approve(store: AccountLifecycleStore, account: str = "SYN-ACCOUNT-001") -> None:
    store.apply(account)
    store.transition(
        account,
        AccountStatus.APPROVED,
        actor=actor(),
        timestamp=NOW,
        reason="synthetic approval",
        evidence_refs=("SYN-KYC-001", "SYN-ELIGIBILITY-001", "SYN-HUMAN-001"),
        kyc_evidence=kyc(),
        eligibility=eligibility(),
        human_approval_ref="SYN-HUMAN-001",
    )


@pytest.mark.parametrize(
    ("outcome", "eligible", "approval", "reason"),
    [
        ("KYC_MISSING_HALT", True, "SYN-HUMAN-001", RefusalReason.KYC_MISSING),
        ("KYC_ELIGIBLE_CLEAR", False, "SYN-HUMAN-001", RefusalReason.ATREIDES_ELIGIBILITY_FAILED),
        ("KYC_ELIGIBLE_CLEAR", True, None, RefusalReason.HUMAN_APPROVAL_MISSING),
    ],
)
def test_approval_refusals(outcome, eligible, approval, reason) -> None:
    lifecycle = store()
    with pytest.raises(AccountTransitionRefusedError) as caught:
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic approval",
            evidence_refs=("SYN-EVIDENCE-001",),
            kyc_evidence=kyc(outcome),
            eligibility=eligibility(passed=eligible),
            human_approval_ref=approval,
        )
    assert caught.value.reason is reason


def test_end_to_end_lifecycle_and_append_only_events() -> None:
    lifecycle = store()
    approve(lifecycle)
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.FUNDED,
        actor=actor(),
        timestamp=NOW,
        reason="clean synthetic ACATS transfer",
        evidence_refs=("SYN-ACATS-001",),
        transfer=TransferInRecord(record_id="SYN-ACATS-001", completed=True, completed_at=NOW),
    )
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.ACTIVE,
        actor=actor(),
        timestamp=NOW,
        reason="first permitted synthetic trade",
        evidence_refs=("SYN-ORDER-001",),
        first_trade=FirstPermittedTradeRecord(
            record_id="SYN-ORDER-001", permitted=True, traded_at=NOW
        ),
    )
    assert lifecycle.status("SYN-ACCOUNT-001") is AccountStatus.ACTIVE
    assert [event.payload.status for event in lifecycle.events] == [
        AccountStatus.APPROVED,
        AccountStatus.FUNDED,
        AccountStatus.ACTIVE,
    ]
    assert b"cannae.attested_account_status/1" in lifecycle.publish_status(
        as_of=NOW, maximum_age_seconds=300
    )


def test_illegal_transition_and_transfer_refusal() -> None:
    lifecycle = store()
    with pytest.raises(AccountTransitionRefusedError, match="ILLEGAL_TRANSITION"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.ACTIVE,
            actor=actor(),
            timestamp=NOW,
            reason="skip",
            evidence_refs=("SYN-ORDER-001",),
            first_trade=FirstPermittedTradeRecord(
                record_id="SYN-ORDER-001", permitted=True, traded_at=NOW
            ),
        )
    approve(lifecycle)
    with pytest.raises(AccountTransitionRefusedError, match="TRANSFER_NOT_COMPLETED"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.FUNDED,
            actor=actor(),
            timestamp=NOW,
            reason="rejected",
            evidence_refs=("SYN-ACATS-REJECT",),
            transfer=TransferInRecord(
                record_id="SYN-ACATS-REJECT", completed=False, completed_at=NOW
            ),
        )


def test_transfer_record_must_be_referenced_by_id() -> None:
    lifecycle = store()
    approve(lifecycle)
    with pytest.raises(AccountTransitionRefusedError, match="TRANSFER_NOT_COMPLETED"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.FUNDED,
            actor=actor(),
            timestamp=NOW,
            reason="completed transfer",
            evidence_refs=("SYN-ACATS-OTHER",),
            transfer=TransferInRecord(
                record_id="SYN-ACATS-001", completed=True, completed_at=NOW
            ),
        )


def test_every_allowed_edge_has_a_declared_rule() -> None:
    allowed = {
        (source, target) for source, targets in ALLOWED_TRANSITIONS.items() for target in targets
    }
    assert set(TRANSITION_RULES) == allowed


def test_service_actor_cannot_reopen_restricted_account() -> None:
    lifecycle = store()
    approve(lifecycle)
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.RESTRICTED,
        actor=actor(ActorKind.DETERMINISTIC_SERVICE),
        timestamp=NOW + timedelta(seconds=1),
        reason="risk restriction",
        evidence_refs=("SYN-RESTRICT-001",),
    )
    with pytest.raises(AccountTransitionRefusedError, match="HUMAN_APPROVER_REQUIRED"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(ActorKind.DETERMINISTIC_SERVICE),
            timestamp=NOW + timedelta(seconds=3),
            reason="claimed reopening",
            evidence_refs=("SYN-ATTACK",),
            kyc_evidence=kyc(at=NOW + timedelta(seconds=2)),
            eligibility=eligibility(at=NOW + timedelta(seconds=2)),
            human_approval_ref="SELF-DECLARED",
        )


@pytest.mark.parametrize(
    ("path", "refusal"),
    [
        ("KYC_MISSING_HALT", RefusalReason.KYC_MISSING),
        ("KYC_EXPIRED_HALT", RefusalReason.KYC_EXPIRED),
        ("KYB_UBO_UNRESOLVED_HALT", RefusalReason.UBO_UNRESOLVED),
        ("AML_EDD_REQUIRED_HALT", RefusalReason.EDD_REQUIRED),
        ("AML_PROHIBITED_BLOCK", RefusalReason.PROHIBITED),
    ],
)
def test_ladder_outcomes_have_distinct_refusals(path, refusal) -> None:
    lifecycle = store()
    with pytest.raises(AccountTransitionRefusedError) as caught:
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic approval",
            evidence_refs=("SYN-KYC-001",),
            kyc_evidence=kyc(path),
            eligibility=eligibility(),
            human_approval_ref="SYN-HUMAN-001",
        )
    assert caught.value.reason is refusal
    expected = (
        AccountStatus.CLOSED if refusal is RefusalReason.PROHIBITED else AccountStatus.APPLIED
    )
    assert lifecycle.status("SYN-ACCOUNT-001") is expected


def test_restricted_reapproval_requires_fresh_evidence() -> None:
    lifecycle = store()
    approve(lifecycle)
    restriction_time = NOW + timedelta(seconds=1)
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.RESTRICTED,
        actor=actor(),
        timestamp=restriction_time,
        reason="risk restriction",
        evidence_refs=("SYN-RESTRICT-001",),
    )
    with pytest.raises(AccountTransitionRefusedError, match="EVIDENCE_NOT_FRESH"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW + timedelta(seconds=2),
            reason="stale reopening",
            evidence_refs=("SYN-KYC-001",),
            kyc_evidence=kyc(),
            eligibility=eligibility(),
            human_approval_ref="SYN-HUMAN-001",
        )


def test_chain_detects_removal_reordering_and_editing() -> None:
    lifecycle = store()
    approve(lifecycle)
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.FUNDED,
        actor=actor(),
        timestamp=NOW + timedelta(seconds=1),
        reason="funded",
        evidence_refs=("SYN-ACATS-001",),
        transfer=TransferInRecord(record_id="SYN-ACATS-001", completed=True, completed_at=NOW),
    )
    original = list(lifecycle._events)
    lifecycle._events = original[:1]
    assert not lifecycle.chain_report("SYN-ACCOUNT-001").ok
    lifecycle._events = list(reversed(original))
    assert not lifecycle.chain_report("SYN-ACCOUNT-001").ok
    lifecycle._events = [
        original[0].model_copy(
            update={"payload": original[0].payload.model_copy(update={"reason": "edited"})}
        ),
        original[1],
    ]
    assert not lifecycle.chain_report("SYN-ACCOUNT-001").ok
    lifecycle._events = original
    assert lifecycle.status("SYN-ACCOUNT-001") is AccountStatus.FUNDED
