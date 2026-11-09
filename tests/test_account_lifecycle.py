import json
from datetime import UTC, date, datetime, timedelta
from inspect import signature

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import digest_bytes
from cannae_kernel.ids import ActorId
from cannae_kernel.journal import ChainReport
from cannae_kernel.signed_attestation import (
    PublicKeyRecord,
    PublicKeyRegistry,
    pinned_public_key_registry,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atreides.account_lifecycle import (
    ALLOWED_TRANSITIONS,
    TRANSITION_RULES,
    AccountApplication,
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    AccountType,
    ActorRegistryApproverVerifier,
    AuthoritativeEvidenceResolver,
    EligibilityResultRecord,
    FirstPermittedTradeRecord,
    KYBClearResultRecord,
    KYCDecisionRecord,
    LegalEntityEvidenceRecord,
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
from atreides.reference_data import LegalEntityRecord

NOW = datetime(2026, 11, 8, 9, tzinfo=UTC)
ACCOUNT = "SYN-ACCOUNT-001"
OTHER_ACCOUNT = "SYN-ACCOUNT-OTHER"
KYC_ID = "SYN-KYC-001"
ELIGIBILITY_ID = "SYN-ELIGIBILITY-001"
TRANSFER_ID = "SYN-ACATS-001"
TRADE_ID = "SYN-ORDER-001"
APPROVAL_ID = "SYN-HUMAN-001"
APPLICATION_ID = "SYN-APPLICATION-001"
LEGAL_ENTITY_ID = "SYN-LEGAL-001"
KYB_ID = "SYN-KYB-001"
SIGNING_KEY_ID = "synthetic-lc-key-1"
SIGNING_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
SIGNING_KEYS = pinned_public_key_registry(
    {SIGNING_KEY_ID: PublicKeyRecord("legiones-cannenses", SIGNING_KEY.public_key())}
)


def actor(kind: ActorKind = ActorKind.HUMAN, number: int = 0) -> ActorRef:
    return ActorRef(
        actor_id=ActorId(f"act_{number:026d}"),
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
    application_account: str = ACCOUNT,
    kyc_path: str = "KYC_ELIGIBLE_CLEAR",
    kyc_at: datetime = NOW,
    kyc_chain_valid: bool = True,
    eligibility_id: str = ELIGIBILITY_ID,
    eligibility_at: datetime = NOW,
    eligible: bool = True,
    transfer_id: str = TRANSFER_ID,
    transfer_completed: bool = True,
    trade_wire: bytes | None = None,
    trade_key_registry: PublicKeyRegistry = SIGNING_KEYS,
    legal_entity_record_id: str | None = LEGAL_ENTITY_ID,
    kyb_result_record_id: str | None = KYB_ID,
    kyb_clear: bool = True,
    legal_entity_account: str | None = None,
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
                account_type=AccountType.INSTITUTIONAL,
                path_id=kyc_path,
                decided_at=kyc_at,
                maximum_age_seconds=300,
                legal_entity_record_id=legal_entity_record_id,
                kyb_result_record_id=kyb_result_record_id,
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
            else attest_first_permitted_trade(trade, key_id=SIGNING_KEY_ID, private_key=SIGNING_KEY)
        },
        first_trade_key_registry=trade_key_registry,
        application_records={
            APPLICATION_ID: AccountApplication(
                record_id=APPLICATION_ID,
                account_id=application_account,
                account_type=AccountType.INSTITUTIONAL,
                applied_at=NOW,
                legal_entity_record_id=legal_entity_record_id,
                kyb_result_record_id=kyb_result_record_id,
            )
        },
        legal_entity_records={
            LEGAL_ENTITY_ID: LegalEntityEvidenceRecord(
                record_id=LEGAL_ENTITY_ID,
                account_id=legal_entity_account or application_account,
                legal_entity=LegalEntityRecord(
                    provenance="synthetic fixture",
                    effective_date=date(2026, 11, 8),
                    lei="SYNTHETICLEI00000001",
                    entity_id="SYN-ENTITY-001",
                ),
            )
        },
        kyb_records={
            KYB_ID: KYBClearResultRecord(
                record_id=KYB_ID,
                account_id=application_account,
                entity_id="SYN-ENTITY-001",
                clear=kyb_clear,
                verified_at=NOW,
            )
        },
    )


def store(
    evidence: AuthoritativeEvidenceResolver | None = None,
    *,
    registered: ActorRef | None = None,
) -> AccountLifecycleStore:
    registered = registered or actor()
    human = actor()
    verifier = ActorRegistryApproverVerifier(
        {str(human.actor_id): human, str(registered.actor_id): registered}
    )
    lifecycle = AccountLifecycleStore(verifier, evidence or resolver())
    lifecycle.apply(APPLICATION_ID)
    return lifecycle


def approve(store: AccountLifecycleStore, account: str = ACCOUNT) -> None:
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
def test_approval_refusals(
    outcome: str,
    eligible: bool,
    approval: str | None,
    reason: RefusalReason,
) -> None:
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
    assert b"cannae.signed_attestation/1" in lifecycle.publish_status(
        as_of=NOW,
        maximum_age_seconds=300,
        key_id=SIGNING_KEY_ID,
        private_key=SIGNING_KEY,
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
    service = actor(ActorKind.DETERMINISTIC_SERVICE, number=1)
    lifecycle = store(registered=service)
    approve(lifecycle)
    lifecycle.transition(
        "SYN-ACCOUNT-001",
        AccountStatus.RESTRICTED,
        actor=service,
        timestamp=NOW + timedelta(seconds=1),
        reason="risk restriction",
        evidence_refs=("SYN-RESTRICT-001",),
    )
    with pytest.raises(AccountTransitionRefusedError, match="HUMAN_APPROVER_REQUIRED"):
        lifecycle.transition(
            "SYN-ACCOUNT-001",
            AccountStatus.APPROVED,
            actor=service,
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
    with pytest.raises(AccountTransitionRefusedError, match="ELIGIBILITY_EVIDENCE_NOT_FOUND"):
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
    valid_wire = attest_first_permitted_trade(
        valid_trade, key_id=SIGNING_KEY_ID, private_key=SIGNING_KEY
    )
    envelope = json.loads(valid_wire)
    envelope["payload_b64"] = "dGFtcGVyZWQ="
    tampered = json.dumps(envelope).encode()
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
    with pytest.raises(AccountTransitionRefusedError, match="FIRST_TRADE_SIGNATURE_INVALID"):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.ACTIVE,
            actor=actor(),
            timestamp=NOW,
            reason="tampered trade",
            evidence_refs=(),
            first_trade_record_id=TRADE_ID,
        )


@pytest.mark.parametrize(
    ("registry", "reason"),
    [
        (pinned_public_key_registry({}), RefusalReason.FIRST_TRADE_SIGNING_KEY_UNKNOWN),
        (
            pinned_public_key_registry(
                {SIGNING_KEY_ID: PublicKeyRecord("atreides", SIGNING_KEY.public_key())}
            ),
            RefusalReason.FIRST_TRADE_PRODUCER_MISMATCH,
        ),
    ],
)
def test_first_trade_signer_identity_is_pinned(
    registry: PublicKeyRegistry, reason: RefusalReason
) -> None:
    lifecycle = store(resolver(trade_key_registry=registry))
    approve(lifecycle)
    lifecycle.transition(
        ACCOUNT,
        AccountStatus.FUNDED,
        actor=actor(),
        timestamp=NOW,
        reason="synthetic funding",
        evidence_refs=(),
        transfer_record_id=TRANSFER_ID,
    )
    with pytest.raises(AccountTransitionRefusedError) as caught:
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.ACTIVE,
            actor=actor(),
            timestamp=NOW,
            reason="synthetic activation",
            evidence_refs=(),
            first_trade_record_id=TRADE_ID,
        )
    assert caught.value.reason is reason


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (resolver(legal_entity_record_id=None), RefusalReason.LEGAL_ENTITY_REQUIRED),
        (
            resolver(legal_entity_account=OTHER_ACCOUNT),
            RefusalReason.LEGAL_ENTITY_ACCOUNT_MISMATCH,
        ),
        (resolver(kyb_clear=False), RefusalReason.KYB_NOT_CLEAR),
    ],
)
def test_institutional_approval_requires_authoritative_entity_and_kyb(
    evidence: AuthoritativeEvidenceResolver, reason: RefusalReason
) -> None:
    lifecycle = store(evidence)
    with pytest.raises(AccountTransitionRefusedError) as caught:
        approve(lifecycle)
    assert caught.value.reason is reason


def test_unregistered_actor_cannot_restrict() -> None:
    lifecycle = store()
    approve(lifecycle)
    with pytest.raises(AccountTransitionRefusedError, match="ACTOR_NOT_REGISTERED"):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.RESTRICTED,
            actor=actor(ActorKind.DETERMINISTIC_SERVICE, number=2),
            timestamp=NOW + timedelta(seconds=1),
            reason="synthetic restriction",
            evidence_refs=("SYN-RESTRICT-UNKNOWN",),
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
def test_ladder_outcomes_have_distinct_refusals(path: str, refusal: RefusalReason) -> None:
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
