from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId
from cannae_kernel.journal import ChainReport

from atreides.account_lifecycle import (
    AccountApplication,
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    AccountType,
    ActorRegistryApproverVerifier,
    AuthoritativeEvidenceResolver,
    EligibilityResultRecord,
    KYCDecisionRecord,
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from atreides.retail_identity import (
    ACCOUNT_RECORD_POLICIES,
    PRINCIPAL_APPROVER_POLICY,
    PROFILE_COMPLETENESS_FIELDS,
    REGULATORY_ANCHORS,
    CIPOutcome,
    CustomerProfile,
    PrincipalAcceptanceRecord,
    PrincipalApproverPolicyRow,
    RetailEvidenceStore,
    SyntheticIdentity,
    VerificationMethod,
    build_account_record,
    build_cip_record,
)

NOW = datetime(2026, 11, 9, 10, tzinfo=UTC)
ACCOUNT = "SYN-ACCOUNT-RETAIL1"
PERSON = "SYN-PERSON-RETAIL1"
KYC_ID = "SYN-KYC-RETAIL1"
ELIGIBILITY_ID = "SYN-ELIGIBILITY-RETAIL1"
CIP_ID = "SYN-CIP-RETAIL1"
PROFILE_ID = "SYN-PROFILE-RETAIL1"
PRINCIPAL_ID = "SYN-PRINCIPAL-RETAIL1"
APPLICATION_ID = "SYN-APPLICATION-RETAIL1"


def test_profile_completeness_contract_checksum() -> None:
    assert sha256(",".join(PROFILE_COMPLETENESS_FIELDS).encode()).hexdigest() == (
        "c51ad6bae415031695470dec96af86bbd6e54f8c2d9b52ec67e150083d580744"
    )


def _actor(kind: ActorKind = ActorKind.HUMAN, *, number: str = "1") -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + number * 26),
        actor_kind=kind,
        role="synthetic-principal",
        entitlement_refs=("accept-retail-account",),
        authenticated=True,
    )


def _identity(*, person_id: str = PERSON) -> SyntheticIdentity:
    return SyntheticIdentity(
        person_id=person_id,
        name_token="SYN-NAME-RETAIL1",
        birth_date_token="SYN-DOB-RETAIL1",
        address_token="SYN-ADDRESS-RETAIL1",
        taxpayer_id_token="SYN-TIN-RETAIL1",
        identity_document_token="SYN-DOC-RETAIL1",
    )


def _profile(
    *, account_id: str = ACCOUNT, at: datetime = NOW, complete: bool = True
) -> CustomerProfile:
    return CustomerProfile(
        record_id=PROFILE_ID,
        account_id=account_id,
        person_id=PERSON,
        updated_at=at,
        employment_status="SYNTHETIC_EMPLOYED" if complete else None,
        annual_income_band="SYNTHETIC_BAND_A",
        net_worth_band="SYNTHETIC_BAND_B",
        liquid_net_worth_band="SYNTHETIC_BAND_C",
        tax_status="SYNTHETIC_STATUS",
        investment_objectives=("SYNTHETIC_GROWTH",),
        risk_tolerance="SYNTHETIC_MODERATE",
        time_horizon="SYNTHETIC_LONG",
        liquidity_needs="SYNTHETIC_LOW",
        investment_experience=("SYNTHETIC_EQUITIES",),
    )


def _eligibility(at: datetime) -> EligibilityResultRecord:
    result = verify_eligibility(
        EligibilityInputs(
            check_time=at,
            kyc=KYCEvidence(
                beneficial_owner_id=PERSON,
                kyc_reference_id=KYC_ID,
                verified_at=at,
                expires_at=at + timedelta(days=30),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id=PERSON,
                    screening_id="SYN-OFAC-RETAIL1",
                    matched=False,
                    screened_at=at,
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id=PERSON,
                    screening_id="SYN-SANCTIONS-RETAIL1",
                    matched=False,
                    screened_at=at,
                ),
            ),
        )
    )
    return EligibilityResultRecord(
        record_id=ELIGIBILITY_ID,
        account_id=ACCOUNT,
        verified_at=at,
        result=result,
    )


def _store(
    *,
    outcome: CIPOutcome = CIPOutcome.VERIFIED,
    cip_account: str = ACCOUNT,
    cip_person: str = PERSON,
    profile: CustomerProfile | None = None,
    cip_at: datetime = NOW,
    profile_at: datetime = NOW,
    principal_kind: ActorKind = ActorKind.HUMAN,
    application_type: AccountType = AccountType.NATURAL_PERSON,
    kyc_type: AccountType = AccountType.NATURAL_PERSON,
    allow_same_person: bool = False,
    same_person: bool = False,
    apply_record: bool = True,
    cip_list_checked: bool = True,
    cip_notice_given: bool = True,
    legal_entity_record_id: str | None = None,
    kyb_result_record_id: str | None = None,
) -> AccountLifecycleStore:
    human = _actor()
    principal = human if same_person else _actor(principal_kind, number="2")
    registry = {str(human.actor_id): human, str(principal.actor_id): principal}
    retail = RetailEvidenceStore()
    cip = build_cip_record(
        record_id=CIP_ID,
        account_id=cip_account,
        identity=_identity(person_id=cip_person),
        verification_method=VerificationMethod.DOCUMENTARY_SYNTHETIC,
        outcome=outcome,
        checked_at=cip_at,
        exception_owner=(
            "SYNTHETIC_CIP_OPERATIONS" if outcome is not CIPOutcome.VERIFIED else None
        ),
    ).model_copy(
        update={
            "government_list_checked": cip_list_checked,
            "notice_given": cip_notice_given,
        }
    )
    retail.append_cip(cip)
    profile = profile or _profile(at=profile_at)
    retail.append_profile(profile)
    retail.append_principal_acceptance(
        PrincipalAcceptanceRecord(
            record_id=PRINCIPAL_ID,
            account_id=ACCOUNT,
            person_id=PERSON,
            profile_record_id=PROFILE_ID,
            accepted_at=profile_at,
            actor=principal,
            approval_ref="SYN-PRINCIPAL-APPROVAL-RETAIL1",
        )
    )
    resolver = AuthoritativeEvidenceResolver(
        kyc_dsor_records={
            KYC_ID: KYCDecisionRecord(
                record_id=KYC_ID,
                account_id=ACCOUNT,
                account_type=kyc_type,
                person_id=PERSON if kyc_type is AccountType.NATURAL_PERSON else None,
                path_id="KYC_ELIGIBLE_CLEAR",
                decided_at=cip_at,
                maximum_age_seconds=86400,
                legal_entity_record_id=legal_entity_record_id,
                kyb_result_record_id=kyb_result_record_id,
            )
        },
        kyc_chain_reports={
            KYC_ID: ChainReport(
                ok=True,
                event_count=1,
                head_digest="sha256:" + "11" * 32,
                issues=(),
            )
        },
        eligibility_records={ELIGIBILITY_ID: _eligibility(profile_at)},
        transfer_records={},
        first_trade_attestations={},
        cip_records=retail.cip_records,
        profile_records=retail.profiles,
        principal_acceptance_records=retail.principal_acceptances,
        application_records={
            APPLICATION_ID: AccountApplication(
                record_id=APPLICATION_ID,
                account_id=ACCOUNT,
                account_type=application_type,
                person_id=(PERSON if application_type is AccountType.NATURAL_PERSON else None),
                applied_at=NOW,
                legal_entity_record_id=legal_entity_record_id,
                kyb_result_record_id=kyb_result_record_id,
            )
        },
    )
    lifecycle = AccountLifecycleStore(
        ActorRegistryApproverVerifier(registry),
        resolver,
        PrincipalApproverPolicyRow(allow_same_person=allow_same_person),
    )
    if apply_record:
        lifecycle.apply(APPLICATION_ID)
    return lifecycle


def _approve(lifecycle: AccountLifecycleStore, at: datetime = NOW) -> None:
    lifecycle.transition(
        ACCOUNT,
        AccountStatus.APPROVED,
        actor=_actor(),
        timestamp=at,
        reason="synthetic retail approval",
        evidence_refs=(),
        kyc_record_id=KYC_ID,
        eligibility_record_id=ELIGIBILITY_ID,
        human_approval_ref="SYN-HUMAN-APPROVAL-RETAIL1",
        cip_record_id=CIP_ID,
        profile_record_id=PROFILE_ID,
        principal_acceptance_record_id=PRINCIPAL_ID,
    )


@pytest.mark.parametrize(
    ("outcome", "refusal"),
    [
        (CIPOutcome.PENDING, "CIP_PENDING"),
        (CIPOutcome.UNABLE_TO_VERIFY, "CIP_UNABLE_TO_VERIFY"),
        (CIPOutcome.LIST_MATCH_ESCALATE, "CIP_LIST_MATCH_ESCALATE"),
    ],
)
def test_non_verified_cip_has_named_refusal(outcome: CIPOutcome, refusal: str) -> None:
    with pytest.raises(AccountTransitionRefusedError, match=refusal):
        _approve(_store(outcome=outcome))


@pytest.mark.parametrize(
    ("list_checked", "notice_given", "refusal"),
    [
        (False, True, "CIP_LIST_CHECK_REQUIRED"),
        (True, False, "CIP_NOTICE_REQUIRED"),
    ],
)
def test_verified_cip_requires_list_check_and_notice(
    list_checked: bool, notice_given: bool, refusal: str
) -> None:
    with pytest.raises(AccountTransitionRefusedError, match=refusal):
        _approve(_store(cip_list_checked=list_checked, cip_notice_given=notice_given))


def test_natural_person_cannot_carry_legal_entity_evidence() -> None:
    lifecycle = _store(
        legal_entity_record_id="SYN-LEGAL-FORBIDDEN",
        kyb_result_record_id="SYN-KYB-FORBIDDEN",
    )
    with pytest.raises(AccountTransitionRefusedError, match="LEGAL_ENTITY_FORBIDDEN"):
        _approve(lifecycle)


@pytest.mark.parametrize(
    ("account", "person", "refusal"),
    [
        ("SYN-ACCOUNT-OTHER", PERSON, "CIP_ACCOUNT_MISMATCH"),
        (ACCOUNT, "SYN-PERSON-OTHER", "CIP_PERSON_MISMATCH"),
    ],
)
def test_cip_bound_to_account_and_person(account: str, person: str, refusal: str) -> None:
    with pytest.raises(AccountTransitionRefusedError, match=refusal):
        _approve(_store(cip_account=account, cip_person=person))


def test_incomplete_profile_is_refused() -> None:
    with pytest.raises(AccountTransitionRefusedError, match="PROFILE_INCOMPLETE"):
        _approve(_store(profile=_profile(complete=False)))


def test_principal_acceptance_by_service_actor_is_refused() -> None:
    with pytest.raises(AccountTransitionRefusedError, match="HUMAN_APPROVER_REQUIRED"):
        _approve(_store(principal_kind=ActorKind.DETERMINISTIC_SERVICE))


@pytest.mark.parametrize("allow_same_person", [False, True])
def test_principal_and_approver_role_policy_is_data(allow_same_person: bool) -> None:
    lifecycle = _store(allow_same_person=allow_same_person, same_person=True)
    if allow_same_person:
        _approve(lifecycle)
        assert lifecycle.status(ACCOUNT) is AccountStatus.APPROVED
    else:
        with pytest.raises(AccountTransitionRefusedError, match="PRINCIPAL_ROLE_CONFLICT"):
            _approve(lifecycle)


def test_natural_person_cannot_use_institutional_path() -> None:
    lifecycle = _store()
    with pytest.raises(AccountTransitionRefusedError, match="CIP_EVIDENCE_NOT_FOUND"):
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=_actor(),
            timestamp=NOW,
            reason="attempted institutional path",
            evidence_refs=(),
            kyc_record_id=KYC_ID,
            eligibility_record_id=ELIGIBILITY_ID,
            human_approval_ref="SYN-HUMAN-APPROVAL-RETAIL1",
        )


def test_natural_person_applied_as_institutional_is_refused_by_type_origin() -> None:
    lifecycle = _store(application_type=AccountType.INSTITUTIONAL)
    with pytest.raises(AccountTransitionRefusedError, match="ACCOUNT_TYPE_MISMATCH"):
        _approve(lifecycle)


def test_account_never_applied_is_refused_by_name() -> None:
    lifecycle = _store(apply_record=False)
    with pytest.raises(AccountTransitionRefusedError, match="ACCOUNT_APPLICATION_NOT_FOUND"):
        _approve(lifecycle)


def test_application_and_kyc_type_mismatch_is_refused_by_name() -> None:
    lifecycle = _store(kyc_type=AccountType.INSTITUTIONAL)
    with pytest.raises(AccountTransitionRefusedError, match="ACCOUNT_TYPE_MISMATCH"):
        _approve(lifecycle)


def test_reapproval_requires_fresh_cip_and_profile_after_restriction() -> None:
    lifecycle = _store()
    _approve(lifecycle)
    lifecycle.transition(
        ACCOUNT,
        AccountStatus.RESTRICTED,
        actor=_actor(),
        timestamp=NOW + timedelta(seconds=1),
        reason="synthetic restriction",
        evidence_refs=("SYN-RESTRICTION-RETAIL1",),
    )
    with pytest.raises(AccountTransitionRefusedError, match="EVIDENCE_NOT_FRESH"):
        _approve(lifecycle, NOW + timedelta(seconds=2))


def test_clean_natural_person_approval_resolves_all_three_retail_records() -> None:
    lifecycle = _store()
    _approve(lifecycle)
    assert lifecycle.status(ACCOUNT) is AccountStatus.APPROVED
    refs = lifecycle.events[-1].payload.evidence_refs
    assert (CIP_ID, PROFILE_ID, PRINCIPAL_ID) == refs[-3:]


def test_regulatory_rows_keep_citation_and_unverified_status() -> None:
    rows = (*REGULATORY_ANCHORS, *ACCOUNT_RECORD_POLICIES, PRINCIPAL_APPROVER_POLICY)
    assert len(REGULATORY_ANCHORS) == 6
    assert all(row.citation for row in rows)
    assert all(row.verification_status == "TO_VERIFY_AGAINST_PRIMARY_TEXT" for row in rows)


def test_account_record_is_built_from_profile_with_furnishing_and_change_history() -> None:
    profile = _profile()
    record = build_account_record(
        record_id="SYN-ACCOUNT-RECORD-RETAIL1",
        profile=profile,
        furnish_event_id="SYN-FURNISH-RETAIL1",
        furnished_at=NOW,
    )
    assert record.profile_record_id == profile.record_id
    assert record.furnished_events[0].policy.verification_status == (
        "TO_VERIFY_AGAINST_PRIMARY_TEXT"
    )
    assert record.update_policy.verification_status == "TO_VERIFY_AGAINST_PRIMARY_TEXT"


def test_cip_store_is_append_only_and_retention_is_derived_from_policy_row() -> None:
    closed_at = NOW + timedelta(days=1)
    record = build_cip_record(
        record_id=CIP_ID,
        account_id=ACCOUNT,
        identity=_identity(),
        verification_method=VerificationMethod.NON_DOCUMENTARY_SYNTHETIC,
        outcome=CIPOutcome.VERIFIED,
        checked_at=NOW,
        account_closed_at=closed_at,
    )
    store = RetailEvidenceStore()
    store.append_cip(record)
    with pytest.raises(ValueError, match="append-only"):
        store.append_cip(record)
    retention = next(row for row in ACCOUNT_RECORD_POLICIES if row.event == "CIP_RETENTION")
    assert retention.retention_days is not None
    assert record.retention_until == closed_at + timedelta(days=retention.retention_days)
