"""Synthetic retail identity, profile, and account-record evidence.

No value in this module is sent outside the process. Regulatory anchors are
data awaiting primary-text verification, not claims that the code is compliant.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self, TypeVar

from cannae_kernel.actor import ActorRef
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE_COMPLETENESS_FIELDS = (
    "employment_status",
    "annual_income_band",
    "net_worth_band",
    "liquid_net_worth_band",
    "tax_status",
    "investment_objectives",
    "risk_tolerance",
    "time_horizon",
    "liquidity_needs",
    "investment_experience",
)

VerificationStatus = Literal["TO_VERIFY_AGAINST_PRIMARY_TEXT"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


_RecordT = TypeVar("_RecordT", bound=_Record)


class RegulatoryAnchor(_Record):
    area: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    modeled_requirement: str = Field(min_length=1)
    verification_status: VerificationStatus = "TO_VERIFY_AGAINST_PRIMARY_TEXT"


REGULATORY_ANCHORS = (
    RegulatoryAnchor(
        area="Customer Identification Program",
        citation="31 CFR 1023.220",
        modeled_requirement=(
            "minimum identifying information, verification, designated-list check, "
            "notice, and retention after closure"
        ),
    ),
    RegulatoryAnchor(
        area="Natural-person account record",
        citation="SEC Rule 17a-3(a)(17)",
        modeled_requirement="account record, customer furnishing, and recorded changes",
    ),
    RegulatoryAnchor(
        area="Customer account information",
        citation="FINRA Rule 4512",
        modeled_requirement="required account information and principal acceptance",
    ),
    RegulatoryAnchor(
        area="Know your customer",
        citation="FINRA Rule 2090",
        modeled_requirement="essential facts about the customer",
    ),
    RegulatoryAnchor(
        area="Retail recommendations",
        citation="17 CFR 240.15l-1",
        modeled_requirement="retail customer investment profile input",
    ),
    RegulatoryAnchor(
        area="Non-retail suitability",
        citation="FINRA Rule 2111",
        modeled_requirement="customer investment profile where Reg BI does not apply",
    ),
)


class AccountRecordPolicyRow(_Record):
    event: Literal["FURNISH", "UPDATE_CADENCE", "CIP_RETENTION"]
    citation: str = Field(min_length=1)
    cadence_days: int | None = Field(default=None, gt=0)
    retention_days: int | None = Field(default=None, gt=0)
    verification_status: VerificationStatus = "TO_VERIFY_AGAINST_PRIMARY_TEXT"


ACCOUNT_RECORD_POLICIES = (
    AccountRecordPolicyRow(event="FURNISH", citation="SEC Rule 17a-3(a)(17)"),
    AccountRecordPolicyRow(
        event="UPDATE_CADENCE",
        citation="SEC Rule 17a-3(a)(17)",
        cadence_days=1095,
    ),
    AccountRecordPolicyRow(
        event="CIP_RETENTION",
        citation="31 CFR 1023.220",
        retention_days=1825,
    ),
)


class PrincipalApproverPolicyRow(_Record):
    citation: Literal["FINRA Rule 4512"] = "FINRA Rule 4512"
    allow_same_person: bool
    verification_status: VerificationStatus = "TO_VERIFY_AGAINST_PRIMARY_TEXT"


PRINCIPAL_APPROVER_POLICY = PrincipalApproverPolicyRow(allow_same_person=False)


class CIPOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"
    LIST_MATCH_ESCALATE = "LIST_MATCH_ESCALATE"
    PENDING = "PENDING"


class VerificationMethod(StrEnum):
    DOCUMENTARY_SYNTHETIC = "DOCUMENTARY_SYNTHETIC"
    NON_DOCUMENTARY_SYNTHETIC = "NON_DOCUMENTARY_SYNTHETIC"


class SyntheticIdentity(_Record):
    person_id: str = Field(pattern=r"^SYN-PERSON-[A-Z0-9]+$")
    name_token: str = Field(pattern=r"^SYN-NAME-[A-Z0-9]+$")
    birth_date_token: str = Field(pattern=r"^SYN-DOB-[A-Z0-9]+$")
    address_token: str = Field(pattern=r"^SYN-ADDRESS-[A-Z0-9]+$")
    taxpayer_id_token: str = Field(pattern=r"^SYN-TIN-[A-Z0-9]+$")
    identity_document_token: str = Field(pattern=r"^SYN-DOC-[A-Z0-9]+$")


class CIPRecord(_Record):
    record_id: str = Field(pattern=r"^SYN-CIP-[A-Z0-9]+$")
    account_id: str = Field(pattern=r"^SYN-ACCOUNT-[A-Z0-9]+$")
    identity: SyntheticIdentity
    verification_method: VerificationMethod
    verification_source: Literal["SYNTHETIC_STAND_IN"] = "SYNTHETIC_STAND_IN"
    outcome: CIPOutcome
    government_list_checked: bool
    government_list_match: bool
    notice_given: bool
    notice_given_at: datetime
    verified_at: datetime
    exception_owner: str | None = None
    exception_opened_at: datetime | None = None
    account_closed_at: datetime | None = None
    retention_until: datetime | None = None

    @model_validator(mode="after")
    def _outcome_and_retention_are_coherent(self) -> Self:
        exception_fields = (self.exception_owner, self.exception_opened_at)
        if self.outcome is CIPOutcome.VERIFIED and any(
            value is not None for value in exception_fields
        ):
            raise ValueError("verified CIP must not carry an exception")
        if self.outcome is not CIPOutcome.VERIFIED and any(
            value is None for value in exception_fields
        ):
            raise ValueError("non-verified CIP requires an owned exception and opened time")
        if self.government_list_match != (self.outcome is CIPOutcome.LIST_MATCH_ESCALATE):
            raise ValueError("list-match outcome must agree with the government-list result")
        if (self.account_closed_at is None) != (self.retention_until is None):
            raise ValueError("closure and retention dates must be present together")
        return self

    def exception_age_seconds(self, as_of: datetime) -> int | None:
        if self.exception_opened_at is None:
            return None
        return int((as_of - self.exception_opened_at).total_seconds())


def build_cip_record(
    *,
    record_id: str,
    account_id: str,
    identity: SyntheticIdentity,
    verification_method: VerificationMethod,
    outcome: CIPOutcome,
    checked_at: datetime,
    exception_owner: str | None = None,
    account_closed_at: datetime | None = None,
) -> CIPRecord:
    policy = next(row for row in ACCOUNT_RECORD_POLICIES if row.event == "CIP_RETENTION")
    retention_until = (
        account_closed_at + timedelta(days=policy.retention_days)
        if account_closed_at is not None and policy.retention_days is not None
        else None
    )
    return CIPRecord(
        record_id=record_id,
        account_id=account_id,
        identity=identity,
        verification_method=verification_method,
        outcome=outcome,
        government_list_checked=True,
        government_list_match=outcome is CIPOutcome.LIST_MATCH_ESCALATE,
        notice_given=True,
        notice_given_at=checked_at,
        verified_at=checked_at,
        exception_owner=exception_owner,
        exception_opened_at=checked_at if outcome is not CIPOutcome.VERIFIED else None,
        account_closed_at=account_closed_at,
        retention_until=retention_until,
    )


class CustomerProfile(_Record):
    record_id: str = Field(pattern=r"^SYN-PROFILE-[A-Z0-9]+$")
    account_id: str = Field(pattern=r"^SYN-ACCOUNT-[A-Z0-9]+$")
    person_id: str = Field(pattern=r"^SYN-PERSON-[A-Z0-9]+$")
    updated_at: datetime
    employment_status: str | None = None
    annual_income_band: str | None = None
    net_worth_band: str | None = None
    liquid_net_worth_band: str | None = None
    tax_status: str | None = None
    investment_objectives: tuple[str, ...] | None = None
    risk_tolerance: str | None = None
    time_horizon: str | None = None
    liquidity_needs: str | None = None
    investment_experience: tuple[str, ...] | None = None
    reg_bi_fields: tuple[str, ...] = (
        "annual_income_band",
        "net_worth_band",
        "liquid_net_worth_band",
        "tax_status",
        "investment_objectives",
        "risk_tolerance",
        "time_horizon",
        "liquidity_needs",
        "investment_experience",
    )
    rule_2111_fields: tuple[str, ...] = (
        "annual_income_band",
        "net_worth_band",
        "tax_status",
        "investment_objectives",
        "risk_tolerance",
        "time_horizon",
        "liquidity_needs",
        "investment_experience",
    )

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        return tuple(name for name in PROFILE_COMPLETENESS_FIELDS if not getattr(self, name))

    @property
    def complete(self) -> bool:
        return not self.missing_required_fields


class AccountRecordChange(_Record):
    changed_at: datetime
    profile_record_id: str = Field(pattern=r"^SYN-PROFILE-[A-Z0-9]+$")
    changed_fields: tuple[str, ...] = Field(min_length=1)


class FurnishedToCustomerEvent(_Record):
    event_id: str = Field(pattern=r"^SYN-FURNISH-[A-Z0-9]+$")
    furnished_at: datetime
    delivery_channel: Literal["SYNTHETIC_DELIVERY"] = "SYNTHETIC_DELIVERY"
    policy: AccountRecordPolicyRow


class CustomerAccountRecord(_Record):
    record_id: str = Field(pattern=r"^SYN-ACCOUNT-RECORD-[A-Z0-9]+$")
    account_id: str = Field(pattern=r"^SYN-ACCOUNT-[A-Z0-9]+$")
    person_id: str = Field(pattern=r"^SYN-PERSON-[A-Z0-9]+$")
    profile_record_id: str = Field(pattern=r"^SYN-PROFILE-[A-Z0-9]+$")
    furnished_events: tuple[FurnishedToCustomerEvent, ...]
    changes: tuple[AccountRecordChange, ...]
    update_policy: AccountRecordPolicyRow


def build_account_record(
    *,
    record_id: str,
    profile: CustomerProfile,
    furnish_event_id: str,
    furnished_at: datetime,
    changes: tuple[AccountRecordChange, ...] = (),
) -> CustomerAccountRecord:
    furnish_policy = next(row for row in ACCOUNT_RECORD_POLICIES if row.event == "FURNISH")
    update_policy = next(row for row in ACCOUNT_RECORD_POLICIES if row.event == "UPDATE_CADENCE")
    return CustomerAccountRecord(
        record_id=record_id,
        account_id=profile.account_id,
        person_id=profile.person_id,
        profile_record_id=profile.record_id,
        furnished_events=(
            FurnishedToCustomerEvent(
                event_id=furnish_event_id,
                furnished_at=furnished_at,
                policy=furnish_policy,
            ),
        ),
        changes=changes,
        update_policy=update_policy,
    )


class PrincipalAcceptanceRecord(_Record):
    record_id: str = Field(pattern=r"^SYN-PRINCIPAL-[A-Z0-9]+$")
    account_id: str = Field(pattern=r"^SYN-ACCOUNT-[A-Z0-9]+$")
    person_id: str = Field(pattern=r"^SYN-PERSON-[A-Z0-9]+$")
    profile_record_id: str = Field(pattern=r"^SYN-PROFILE-[A-Z0-9]+$")
    accepted_at: datetime
    actor: ActorRef
    approval_ref: str = Field(min_length=1)
    citation: Literal["FINRA Rule 4512"] = "FINRA Rule 4512"
    verification_status: VerificationStatus = "TO_VERIFY_AGAINST_PRIMARY_TEXT"


class RetailEvidenceStore:
    """Append-only in-process store for synthetic producer records."""

    def __init__(self) -> None:
        self._cip: dict[str, CIPRecord] = {}
        self._profiles: dict[str, CustomerProfile] = {}
        self._principal: dict[str, PrincipalAcceptanceRecord] = {}
        self._account_records: dict[str, CustomerAccountRecord] = {}

    @staticmethod
    def _append(target: dict[str, _RecordT], key: str, record: _RecordT) -> None:
        if key in target:
            raise ValueError(f"append-only record already exists: {key}")
        target[key] = record

    def append_cip(self, record: CIPRecord) -> None:
        self._append(self._cip, record.record_id, record)

    def append_profile(self, record: CustomerProfile) -> None:
        self._append(self._profiles, record.record_id, record)

    def append_principal_acceptance(self, record: PrincipalAcceptanceRecord) -> None:
        self._append(self._principal, record.record_id, record)

    def append_account_record(self, record: CustomerAccountRecord) -> None:
        self._append(self._account_records, record.record_id, record)

    @property
    def cip_records(self) -> Mapping[str, CIPRecord]:
        return MappingProxyType(self._cip.copy())

    @property
    def profiles(self) -> Mapping[str, CustomerProfile]:
        return MappingProxyType(self._profiles.copy())

    @property
    def principal_acceptances(self) -> Mapping[str, PrincipalAcceptanceRecord]:
        return MappingProxyType(self._principal.copy())

    @property
    def account_records(self) -> Mapping[str, CustomerAccountRecord]:
        return MappingProxyType(self._account_records.copy())
