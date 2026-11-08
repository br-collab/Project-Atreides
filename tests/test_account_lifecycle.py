from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest_bytes
from cannae_kernel.ids import ActorId
from cannae_kernel.journal import ChainReport

from atreides.account_lifecycle import (
    ALLOWED_TRANSITIONS,
    TRANSITION_RULES,
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    ActorRegistryApproverVerifier,
    AuthoritativeEvidenceResolver,
    EligibilityResultRecord,
    FirstPermittedTradeRecord,
    KYCDecisionRecord,
    RefusalReason,
    TransferInRecord,
    attest_first_permitted_trade,
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from atreides.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
)

NOW = datetime(2026, 11, 8, 9, tzinfo=UTC)
ACCOUNT = "SYN-ACCOUNT-001"
OTHER_ACCOUNT = "SYN-ACCOUNT-OTHER"
KYC_ID = "SYN-KYC-001"
ELIGIBILITY_ID = "SYN-ELIGIBILITY-001"
TRANSFER_ID = "SYN-ACATS-001"
TRADE_ID = "SYN-ORDER-001"
APPROVAL_ID = "SYN-HUMAN-001"


def actor(kind: ActorKind = ActorKind.HUMAN) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_01K00000000000000000000000"),
        actor_kind=kind,
        role="synthetic-approver",
        entitlement_refs=("approve-account",),
        authenticated=True,
    )


def eligibility(*, at: datetime = NOW, passed: bool = True) -> EligibilityVerification:
    if not passed:
        return EligibilityVerification(
            checks=tuple(
                EligibilityCheck(
                    kind=kind,
                    passed=False,
                    failure_reason="synthetic eligibility failure",
                    verified_at=at,
                )
                for kind in EligibilityCheckKind
            )
        )
    return verify_eligibility(
        EligibilityInputs(
            check_time=at,
            kyc=KYCEvidence(
                beneficial_owner_id="SYN-OWNER-001",
                kyc_reference_id=KYC_ID,
                verified_at=at - timedelta(days=1),
                expires_at=at + timedelta(days=30),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id="SYN-OWNER-001",
                    screening_id="SYN-OFAC-001",
                    matched=False,
                    screened_at=at,
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id="SYN-OWNER-001",
                    screening_id="SYN-SANCTIONS-001",
                    matched=False,
                    screened_at=at,
                ),
            ),
        )
    )


def resolver(
    *,
    account: str = ACCOUNT,
    kyc_path: str = "KYC_ELIGIBLE_CLEAR",
    kyc_at: datetime = NOW,
    kyc_chain_valid: bool = True,
    eligibility_id: str = ELIGIBILITY_ID,
    eligibility_at: datetime = NOW,
    eligible: bool = True,
    transfer_id: str = TRANSFER_ID,
    transfer_completed: bool = True,
    trade_wire: bytes | None = None,
) -> AuthoritativeEvidenceResolver:
    trade = FirstPermittedTradeRecord(
        record_id=TRADE_ID,
        account_id=account,
        permitted=True,
        traded_at=NOW,
    )
    return AuthoritativeEvidenceResolver(
        kyc_dsor_records={
            KYC_ID: KYCDecisionRecord(
                record_id=KYC_ID,
                account_id=account,
                path_id=kyc_path,
                decided_at=kyc_at,
                maximum_age_seconds=300,
            )
        },
        kyc_chain_reports={
            KYC_ID: ChainReport(
                ok=kyc_chain_valid,
                event_count=1,
                head_digest="sha256:" + "11" * 32,
                issues=(),
            )
        },
        eligibility_records={
            eligibility_id: EligibilityResultRecord(
                record_id=eligibility_id,
                account_id=account,
                verified_at=eligibility_at,
                result=eligibility(at=eligibility_at, passed=eligible),
            )
        },
        transfer_records={
            transfer_id: TransferInRecord(
                record_id=transfer_id,
                account_id=account,
                completed=transfer_completed,
                completed_at=NOW,
            )
        },
        first_trade_attestations={
            TRADE_ID: trade_wire
            if trade_wire is not None
            else attest_first_permitted_trade(trade)
        },
    )


def store(
    evidence: AuthoritativeEvidenceResolver | None = None,
    *,
    registered: ActorRef | None = None,
) -> AccountLifecycleStore:
    registered = registered or actor()
    verifier = ActorRegistryApproverVerifier({str(registered.actor_id): registered})
    return AccountLifecycleStore(verifier, evidence or resolver())


def approve(store: AccountLifecycleStore, account: str = ACCOUNT) -> None:
    store.apply(account)
    store.transition(
        account,
        AccountStatus.APPROVED,
        actor=actor(),
        timestamp=NOW,
        reason="synthetic approval",
        evidence_refs=(APPROVAL_ID,),
        kyc_record_id=KYC_ID,
        eligibility_record_id=ELIGIBILITY_ID,
        human_approval_ref=APPROVAL_ID,
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
    lifecycle = store(resolver(kyc_path=outcome, eligible=eligible))
    with pytest.raises(AccountTransitionRefusedError) as caught:
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic approval",
            evidence_refs=("SYN-EVIDENCE-001",),
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
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
        evidence_refs=(),
        transfer_record_id=TRANSFER_ID,
    )
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.ACTIVE,
        actor=actor(),
        timestamp=NOW,
        reason="first permitted synthetic trade",
        evidence_refs=(),
        first_trade_record_id=TRADE_ID,
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


def test_illegal_transition_is_refused() -> None:
    lifecycle = store()
    with pytest.raises(AccountTransitionRefusedError, match="ILLEGAL_TRANSITION"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.ACTIVE,
            actor=actor(),
            timestamp=NOW,
            reason="skip",
            evidence_refs=("SYN-ORDER-001",),
            first_trade_record_id=TRADE_ID,
        )


def test_incomplete_transfer_record_is_refused() -> None:
    lifecycle = store(resolver(transfer_id="SYN-ACATS-REJECT", transfer_completed=False))
    approve(lifecycle)
    with pytest.raises(AccountTransitionRefusedError, match="TRANSFER_NOT_COMPLETED"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.FUNDED,
            actor=actor(),
            timestamp=NOW,
            reason="rejected",
            evidence_refs=("SYN-ACATS-REJECT",),
            transfer_record_id="SYN-ACATS-REJECT",
        )


def test_transfer_record_id_that_does_not_exist_is_refused() -> None:
    lifecycle = store()
    approve(lifecycle)
    with pytest.raises(AccountTransitionRefusedError, match="TRANSFER_EVIDENCE_NOT_FOUND"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.FUNDED,
            actor=actor(),
            timestamp=NOW,
            reason="completed transfer",
            evidence_refs=(),
            transfer_record_id="SYN-ACATS-OTHER",
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
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
            human_approval_ref="SELF-DECLARED",
        )


def test_hand_built_kyc_with_self_computed_digest_is_not_authoritative() -> None:
    forged_payload = '{"account_id":"SYN-ACCOUNT-001","path_id":"KYC_ELIGIBLE_CLEAR"}'
    forged = {
        "record_id": "FORGED-KYC",
        "path_id": "KYC_ELIGIBLE_CLEAR",
        "payload": forged_payload,
        "payload_digest": digest_bytes(forged_payload.encode()),
    }
    lifecycle = store()
    with pytest.raises(AccountTransitionRefusedError, match="KYC_EVIDENCE_NOT_FOUND"):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="forged KYC",
            evidence_refs=(),
            kyc_record_id=forged["record_id"],
            eligibility_record_id=ELIGIBILITY_ID,
            human_approval_ref=APPROVAL_ID,
        )


def test_kyc_record_for_another_account_is_refused() -> None:
    lifecycle = store(resolver(account=OTHER_ACCOUNT))
    with pytest.raises(AccountTransitionRefusedError, match="KYC_ACCOUNT_MISMATCH"):
        approve(lifecycle)


def test_kyc_record_with_invalid_chain_is_refused() -> None:
    lifecycle = store(resolver(kyc_chain_valid=False))
    with pytest.raises(AccountTransitionRefusedError, match="KYC_CHAIN_INVALID"):
        approve(lifecycle)


def test_hand_built_eligibility_cannot_enter_transition() -> None:
    forged = EligibilityVerification(
        checks=tuple(
            EligibilityCheck(kind=kind, passed=True, verified_at=NOW)
            for kind in EligibilityCheckKind
        )
    )
    assert forged.all_passed
    assert "eligibility" not in signature(AccountLifecycleStore.transition).parameters
    lifecycle = store()
    with pytest.raises(
        AccountTransitionRefusedError, match="ELIGIBILITY_EVIDENCE_NOT_FOUND"
    ):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="forged eligibility",
            evidence_refs=(),
            kyc_record_id=KYC_ID,
            eligibility_record_id="FORGED-ELIGIBILITY",
            human_approval_ref=APPROVAL_ID,
        )


def test_first_trade_with_tampered_attestation_is_refused() -> None:
    valid_trade = FirstPermittedTradeRecord(
        record_id=TRADE_ID,
        account_id=ACCOUNT,
        permitted=True,
        traded_at=NOW,
    )
    tampered = attest_first_permitted_trade(valid_trade).replace(
        b'\\"permitted\\":true', b'\\"permitted\\":false'
    )
    assert tampered != attest_first_permitted_trade(valid_trade)
    lifecycle = store(resolver(trade_wire=tampered))
    approve(lifecycle)
    lifecycle.transition(
        ACCOUNT,
        AccountStatus.FUNDED,
        actor=actor(),
        timestamp=NOW,
        reason="funded",
        evidence_refs=(),
        transfer_record_id=TRANSFER_ID,
    )
    with pytest.raises(
        AccountTransitionRefusedError, match="FIRST_TRADE_EVIDENCE_TAMPERED"
    ):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.ACTIVE,
            actor=actor(),
            timestamp=NOW,
            reason="tampered trade",
            evidence_refs=(),
            first_trade_record_id=TRADE_ID,
        )


def test_registry_service_actor_is_not_a_human_approver() -> None:
    service = actor(ActorKind.DETERMINISTIC_SERVICE)
    lifecycle = store(registered=service)
    with pytest.raises(AccountTransitionRefusedError, match="HUMAN_APPROVER_REQUIRED"):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=service,
            timestamp=NOW,
            reason="service approval",
            evidence_refs=(),
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
            human_approval_ref=APPROVAL_ID,
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
    lifecycle = store(resolver(kyc_path=path))
    with pytest.raises(AccountTransitionRefusedError) as caught:
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic approval",
            evidence_refs=("SYN-KYC-001",),
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
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
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
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
        evidence_refs=(),
        transfer_record_id=TRANSFER_ID,
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
