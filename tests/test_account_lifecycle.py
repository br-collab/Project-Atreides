from datetime import UTC, datetime

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId

from atreides.account_lifecycle import (
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    RefusalReason,
)

NOW = datetime(2026, 11, 7, 16, tzinfo=UTC)


def actor(kind: ActorKind = ActorKind.HUMAN) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01K00000000000000000000000"),
        actor_kind=kind,
        role="synthetic-approver",
        entitlement_refs=("approve-account",),
        authenticated=True,
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
        kyc_ladder_outcome="KYC_ELIGIBLE_CLEAR",
        eligibility_passed=True,
        human_approval_ref="SYN-HUMAN-001",
    )


@pytest.mark.parametrize(
    ("outcome", "eligible", "approval", "reason"),
    [
        ("KYC_MISSING", True, "SYN-HUMAN-001", RefusalReason.KYC_LADDER_NOT_CLEAR),
        ("KYC_ELIGIBLE_CLEAR", False, "SYN-HUMAN-001", RefusalReason.ATREIDES_ELIGIBILITY_FAILED),
        ("KYC_ELIGIBLE_CLEAR", True, None, RefusalReason.HUMAN_APPROVAL_MISSING),
    ],
)
def test_approval_refusals(outcome, eligible, approval, reason) -> None:
    store = AccountLifecycleStore()
    with pytest.raises(AccountTransitionRefusedError) as caught:
        store.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic approval",
            evidence_refs=("SYN-EVIDENCE-001",),
            kyc_ladder_outcome=outcome,
            eligibility_passed=eligible,
            human_approval_ref=approval,
        )
    assert caught.value.reason is reason


def test_end_to_end_lifecycle_and_append_only_events() -> None:
    store = AccountLifecycleStore()
    approve(store)
    store.transition(
        "SYN-ACCOUNT-001", AccountStatus.FUNDED, actor=actor(), timestamp=NOW,
        reason="clean synthetic ACATS transfer", evidence_refs=("SYN-ACATS-001",),
        transfer_clean=True,
    )
    store.transition(
        "SYN-ACCOUNT-001", AccountStatus.ACTIVE, actor=actor(), timestamp=NOW,
        reason="first permitted synthetic trade", evidence_refs=("SYN-ORDER-001",),
        first_trade_permitted=True,
    )
    assert store.status("SYN-ACCOUNT-001") is AccountStatus.ACTIVE
    assert [event.status for event in store.events] == [
        AccountStatus.APPROVED, AccountStatus.FUNDED, AccountStatus.ACTIVE
    ]
    assert b"cannae.attested_account_status/1" in store.publish_status(
        as_of=NOW, maximum_age_seconds=300
    )


def test_illegal_transition_and_transfer_refusal() -> None:
    store = AccountLifecycleStore()
    with pytest.raises(AccountTransitionRefusedError, match="ILLEGAL_TRANSITION"):
        store.transition(
            "SYN-ACCOUNT-001", AccountStatus.ACTIVE, actor=actor(), timestamp=NOW,
            reason="skip", evidence_refs=("SYN-ORDER-001",), first_trade_permitted=True,
        )
    approve(store)
    with pytest.raises(AccountTransitionRefusedError, match="TRANSFER_NOT_CLEAN"):
        store.transition(
            "SYN-ACCOUNT-001", AccountStatus.FUNDED, actor=actor(), timestamp=NOW,
            reason="rejected", evidence_refs=("SYN-ACATS-REJECT",), transfer_clean=False,
        )
