"""Declared-synthetic SIM-1 retail onboarding scenarios."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId
from cannae_kernel.journal import ChainReport
from pydantic import BaseModel, ConfigDict

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
    CIPOutcome,
    CustomerProfile,
    PrincipalAcceptanceRecord,
    RetailEvidenceStore,
    SyntheticIdentity,
    VerificationMethod,
    build_cip_record,
)

START = datetime(2026, 11, 9, 14, tzinfo=UTC)


class RetailOnboardingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    scenario: Literal["CLEAN", "UNABLE_TO_VERIFY", "LIST_MATCH_ESCALATION", "PROFILE_INCOMPLETE"]
    synthetic: Literal[True] = True
    applied_at: datetime
    approved_at: datetime | None
    application_to_approval_seconds: int | None
    refusal: str | None
    exception_age_seconds: int | None


def _actor() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + "1" * 26),
        actor_kind=ActorKind.HUMAN,
        role="synthetic-retail-principal",
        entitlement_refs=("accept-retail-account",),
        authenticated=True,
    )


def _principal() -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + "2" * 26),
        actor_kind=ActorKind.HUMAN,
        role="synthetic-retail-principal",
        entitlement_refs=("accept-retail-account",),
        authenticated=True,
    )


def _run_one(
    scenario: Literal["CLEAN", "UNABLE_TO_VERIFY", "LIST_MATCH_ESCALATION", "PROFILE_INCOMPLETE"],
) -> RetailOnboardingResult:
    suffix = scenario.replace("_", "")
    account_id = f"SYN-ACCOUNT-{suffix}"
    application_id = f"SYN-APPLICATION-{suffix}"
    person_id = f"SYN-PERSON-{suffix}"
    kyc_id = f"SYN-KYC-{suffix}"
    eligibility_id = f"SYN-ELIGIBILITY-{suffix}"
    cip_id = f"SYN-CIP-{suffix}"
    profile_id = f"SYN-PROFILE-{suffix}"
    principal_id = f"SYN-PRINCIPAL-{suffix}"
    outcome = {
        "CLEAN": CIPOutcome.VERIFIED,
        "UNABLE_TO_VERIFY": CIPOutcome.UNABLE_TO_VERIFY,
        "LIST_MATCH_ESCALATION": CIPOutcome.LIST_MATCH_ESCALATE,
        "PROFILE_INCOMPLETE": CIPOutcome.VERIFIED,
    }[scenario]
    identity = SyntheticIdentity(
        person_id=person_id,
        name_token=f"SYN-NAME-{suffix}",
        birth_date_token=f"SYN-DOB-{suffix}",
        address_token=f"SYN-ADDRESS-{suffix}",
        taxpayer_id_token=f"SYN-TIN-{suffix}",
        identity_document_token=f"SYN-DOC-{suffix}",
    )
    cip = build_cip_record(
        record_id=cip_id,
        account_id=account_id,
        identity=identity,
        verification_method=VerificationMethod.DOCUMENTARY_SYNTHETIC,
        outcome=outcome,
        checked_at=START + timedelta(seconds=10),
        exception_owner=(
            "SYNTHETIC_CIP_OPERATIONS" if outcome is not CIPOutcome.VERIFIED else None
        ),
    )
    profile = CustomerProfile(
        record_id=profile_id,
        account_id=account_id,
        person_id=person_id,
        updated_at=START + timedelta(seconds=20),
        employment_status=None if scenario == "PROFILE_INCOMPLETE" else "SYNTHETIC_EMPLOYED",
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
    accepting_principal = _actor()
    retail = RetailEvidenceStore()
    retail.append_cip(cip)
    retail.append_profile(profile)
    retail.append_principal_acceptance(
        PrincipalAcceptanceRecord(
            record_id=principal_id,
            account_id=account_id,
            person_id=person_id,
            profile_record_id=profile_id,
            accepted_at=START + timedelta(seconds=25),
            actor=accepting_principal,
            approval_ref=f"SYN-APPROVAL-{suffix}",
        )
    )
    eligibility = verify_eligibility(
        EligibilityInputs(
            check_time=START + timedelta(seconds=20),
            kyc=KYCEvidence(
                beneficial_owner_id=person_id,
                kyc_reference_id=kyc_id,
                verified_at=START + timedelta(seconds=10),
                expires_at=START + timedelta(days=30),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id=person_id,
                    screening_id=f"SYN-OFAC-{suffix}",
                    matched=False,
                    screened_at=START + timedelta(seconds=10),
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id=person_id,
                    screening_id=f"SYN-SANCTIONS-{suffix}",
                    matched=False,
                    screened_at=START + timedelta(seconds=10),
                ),
            ),
        )
    )
    resolver = AuthoritativeEvidenceResolver(
        application_records={
            application_id: AccountApplication(
                record_id=application_id,
                account_id=account_id,
                account_type=AccountType.NATURAL_PERSON,
                person_id=person_id,
                applied_at=START,
            )
        },
        kyc_dsor_records={
            kyc_id: KYCDecisionRecord(
                record_id=kyc_id,
                account_id=account_id,
                path_id="KYC_ELIGIBLE_CLEAR",
                decided_at=START + timedelta(seconds=10),
                maximum_age_seconds=3600,
                account_type=AccountType.NATURAL_PERSON,
                person_id=person_id,
            )
        },
        kyc_chain_reports={
            kyc_id: ChainReport(
                ok=True,
                event_count=1,
                head_digest="sha256:" + "22" * 32,
                issues=(),
            )
        },
        eligibility_records={
            eligibility_id: EligibilityResultRecord(
                record_id=eligibility_id,
                account_id=account_id,
                verified_at=START + timedelta(seconds=20),
                result=eligibility,
            )
        },
        transfer_records={},
        first_trade_attestations={},
        cip_records=retail.cip_records,
        profile_records=retail.profiles,
        principal_acceptance_records=retail.principal_acceptances,
    )
    principal = _principal()
    lifecycle = AccountLifecycleStore(
        ActorRegistryApproverVerifier(
            {
                str(accepting_principal.actor_id): accepting_principal,
                str(principal.actor_id): principal,
            }
        ),
        resolver,
    )
    lifecycle.apply(application_id)
    approval_time = START + timedelta(seconds=30)
    approved_at: datetime | None = approval_time
    refusal: str | None = None
    try:
        lifecycle.transition(
            account_id,
            AccountStatus.APPROVED,
            actor=principal,
            timestamp=approval_time,
            reason="synthetic retail onboarding",
            evidence_refs=(),
            kyc_record_id=kyc_id,
            eligibility_record_id=eligibility_id,
            human_approval_ref=f"SYN-APPROVAL-{suffix}",
            cip_record_id=cip_id,
            profile_record_id=profile_id,
            principal_acceptance_record_id=principal_id,
        )
    except AccountTransitionRefusedError as exc:
        refusal = exc.reason.value
        approved_at = None
    return RetailOnboardingResult(
        scenario=scenario,
        applied_at=START,
        approved_at=approved_at,
        application_to_approval_seconds=(
            int((approved_at - START).total_seconds()) if approved_at is not None else None
        ),
        refusal=refusal,
        exception_age_seconds=cip.exception_age_seconds(START + timedelta(seconds=30)),
    )


def run_retail_onboarding() -> tuple[RetailOnboardingResult, ...]:
    return tuple(
        _run_one(scenario)
        for scenario in (
            "CLEAN",
            "UNABLE_TO_VERIFY",
            "LIST_MATCH_ESCALATION",
            "PROFILE_INCOMPLETE",
        )
    )
