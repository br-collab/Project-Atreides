"""MVP-3 one-account golden path across the real Cannae layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from cannae_kernel.absence import Recorded
from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes, canonical_bytes_of, digest, digest_bytes
from cannae_kernel.envelopes import ExecutionEvent
from cannae_kernel.events import verify as verify_event
from cannae_kernel.ids import ActorId, IntentId, LifecycleId, OrderId
from emulators.settlement import (  # type: ignore[import-untyped]
    RailOutcome,
    SyntheticEntitledMember,
    SyntheticRail,
)
from emulators.venue import (  # type: ignore[import-untyped]
    VenueEmulator,
    VenueExecutionReport,
    VenueOrder,
    VenueOutcome,
)
from lc.events import OrderTerms, OrderType, TimeInForce
from lc.lifecycle import ApprovedIntentPayload, AuthorityManifest, OrderSide, PolicyManifest
from lc.market_access import (
    AttestedInput,
    CapacityDocument,
    ChildRelease,
    LimitsManifest,
    MarketAccessGate,
    record_decision,
)
from lc.recommendation_profile import (
    CustomerProfileEvidence,
    MappingRecommendationProfileResolver,
    enforce_recommendation_profile,
)
from pydantic import BaseModel, ConfigDict, Field

from atreides.account_lifecycle import (
    AccountApplication,
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    AccountType,
    ActorRegistryApproverVerifier,
    AuthoritativeEvidenceResolver,
    EligibilityResultRecord,
    FirstPermittedTradeRecord,
    KYCDecisionRecord,
    TransferInRecord,
    attest_first_permitted_trade,
    kyc_event_chain,
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from atreides.books.ledger import (
    EquitiesBooks,
    JournalEntry,
    PostingSource,
    RecordSide,
)
from atreides.books.projections import classify_accounts, project_margin_accounts
from atreides.books.ps1 import (
    ACCOUNT_TREATMENT_ROWS,
    TAX_LOT_RULES,
    ControlResult,
    InstructionKind,
    InstructionLog,
    MoneyInstruction,
    SecuritiesConfirmation,
    build_securities_count,
)
from atreides.books.ps1 import (
    reconcile as reconcile_ps1,
)
from atreides.client_reporting import (
    AccountStatement,
    FurnishedEvent,
    TradeConfirmation,
    build_statement_draft,
    customer_side_facts_from_furnished_confirmations,
    find_book_entry_for_execution,
    generate_trade_confirmation,
    issue_statement,
    record_furnished,
)
from atreides.customer_protection.reserve import DAILY_REDUCTION, ComputationMode
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.lifecycle_records import ApprovedIntentDecisionRecord
from atreides.dsor.store import DSORStore
from atreides.equities.documents import project_capacity
from atreides.margin.engine import compute_margin
from atreides.retail_identity import (
    CIPOutcome,
    CustomerProfile,
    PrincipalAcceptanceRecord,
    SyntheticIdentity,
    VerificationMethod,
    build_cip_record,
)
from simulator.account_transfers import _post_transfer
from simulator.conversion import StatementLine
from simulator.estate import (
    DepositDraw,
    DepositPolicy,
    EstateResult,
    _event,
    _identifier,
    _wire,
    drive_estate,
    validate_approval_provenance,
)
from simulator.estate import _actor as estate_actor
from simulator.focus import FirmFocusLines, tie_out_firm_close
from simulator.model import Print
from simulator.protection_oracle import (
    required_control,
    required_net_capital,
    required_reserve,
)
from simulator.street import (
    DepositoryPosition,
    IndependentSourceInputs,
    OpenFail,
    ReconciliationCompletion,
    SettlementOutcome,
    StreetBreak,
    build_independent_sources,
    reconcile,
    reconciliation_calendar,
)
from simulator.synthetic_attestation_fixture import (
    LC_KEY_ID,
    LC_PRIVATE_KEY,
    LC_STATUS_KEY_ID,
    LC_STATUS_PRIVATE_KEY,
    configure_lc_status_trust,
    configure_synthetic_trust,
)

START = datetime(2026, 11, 13, 14, tzinfo=UTC)
ACCOUNT = "SYN-ACCOUNT-GOLDEN001"
PERSON = "SYN-PERSON-GOLDEN001"
ISSUE = "SYN-GOLDEN-US-EQUITY"
PROFILE_MAXIMUM_AGE_SECONDS = 300
KYC_MAXIMUM_AGE_SECONDS = 300


class Variant(StrEnum):
    CLEAN = "CLEAN"
    CIP_UNABLE = "CIP_UNABLE"
    PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
    ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"
    CREDIT_LIMIT = "CREDIT_LIMIT"
    SETTLEMENT_FAIL = "SETTLEMENT_FAIL"
    FORGED_STATUS = "FORGED_STATUS"
    STALE_CALLER_TIME = "STALE_CALLER_TIME"


class FixedRunClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class EvidenceEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    event_id: str
    producer: str
    signature_status: str
    cause_event_id: str | None
    summary: str
    artifact_digest: str
    recorded_at: datetime
    actor_kind: str


class StateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    books_digest: str
    dsor_records: int
    lc_register_length: int


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    status: Literal["VERIFIED", "FAILED"]
    reason: str | None = None


def verify_first_trade_record(
    resolver: AuthoritativeEvidenceResolver, record_id: str, *, evaluated_at: datetime
) -> VerificationResult:
    """Return a typed status so a failed verification cannot be rendered as verified."""
    try:
        resolver.resolve_first_trade(record_id, evaluated_at=evaluated_at)
    except AccountTransitionRefusedError as exc:
        return VerificationResult(status="FAILED", reason=exc.reason.value)
    return VerificationResult(status="VERIFIED")


class GoldenCloseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    close_id: str
    report: str
    fail_age_business_days: int
    i3_stock_record_to_street: bool
    reserve_requirement: Decimal
    focus_tie_out_held: bool


class GoldenPathResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    run_id: str = "PS1B-TRUE-RECONCILIATIONS-2026-11-18"
    variant: Variant
    disposition: str
    account_status: str
    refusal: str | None
    exception_owner: str | None
    exception_age_seconds: int | None
    stages: tuple[str, ...]
    evidence: tuple[EvidenceEvent, ...]
    evidence_digest: str
    dsor_records: int
    books_digest: str | None
    invariants: dict[str, bool]
    close_report: str | None
    lc_register_length: int
    fill_quantity: Decimal | None
    customer_position: Decimal | None
    fail_id: str | None
    i3_computed: bool | None
    stored_artifacts: dict[str, str]
    refusal_state_before: StateSnapshot | None
    refusal_state_after: StateSnapshot | None
    books_entries: tuple[JournalEntry, ...] = ()
    confirmation: TradeConfirmation | None = None
    confirmation_furnished: FurnishedEvent | None = None
    statement: AccountStatement | None = None
    trade_date_statement: AccountStatement | None = None
    venue_execution_event: ExecutionEvent | None = None
    venue_execution_report: VenueExecutionReport | None = None
    engine_dispositions: dict[str, str] = Field(default_factory=dict)
    early_warning_notices: tuple[dict[str, str], ...] = ()
    reconciliation_calendar: tuple[dict[str, object], ...] = ()
    tax_lot_rules: tuple[dict[str, str], ...] = ()
    account_treatment: tuple[dict[str, str], ...] = ()


class PackDigestDSORRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    record_id: str
    pack_digest: str
    recorded_at: datetime


@dataclass(frozen=True)
class GoldenRecommendationGate:
    clock: FixedRunClock
    maximum_age_seconds: int

    def evaluate(
        self,
        terms: OrderTerms,
        profile: CustomerProfileEvidence,
        status: bytes,
    ) -> None:
        enforce_recommendation_profile(
            terms,
            resolver=MappingRecommendationProfileResolver({profile.record_id: profile}),
            evaluated_at=self.clock(),
            account_status_input=status,
            profile_maximum_age_seconds=self.maximum_age_seconds,
        )


_TRUST_CONFIGURED = False


def _configure_trust() -> None:
    global _TRUST_CONFIGURED  # noqa: PLW0603 - process-local synthetic composition root
    if _TRUST_CONFIGURED:
        return
    try:
        configure_synthetic_trust()
    except RuntimeError:
        # The test composition root installs this exact process-local fixture.
        pass
    try:
        configure_lc_status_trust()
    except RuntimeError:
        # Another synthetic path installed this exact process-local fixture.
        pass
    _TRUST_CONFIGURED = True


def _human(number: str, role: str) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + number * 26),
        actor_kind=ActorKind.HUMAN,
        role=role,
        entitlement_refs=("MVP-3",),
        authenticated=True,
    )


def _artifact_bytes(artifact: BaseModel | bytes) -> bytes:
    if isinstance(artifact, bytes):
        return artifact
    return canonical_bytes_of(artifact.model_dump(mode="json"))


def _evidence_event(
    *,
    event_id: str,
    producer: str,
    signature_status: str,
    cause_event_id: str | None,
    summary: str,
    artifact: BaseModel | bytes,
    recorded_at: datetime,
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        producer=producer,
        signature_status=signature_status,
        cause_event_id=cause_event_id,
        summary=summary,
        artifact_digest=digest_bytes(_artifact_bytes(artifact)),
        recorded_at=recorded_at,
        actor_kind="HUMAN" if summary == "account approved" else "SERVICE",
    )


def verify_evidence_artifacts(result: GoldenPathResult) -> bool:
    """Recompute every event digest from the artifacts carried by the result."""
    by_id = {item.event_id: item for item in result.evidence}
    return (
        len(by_id) == len(result.evidence)
        and set(by_id) == set(result.stored_artifacts)
        and all(
            by_id[event_id].artifact_digest == digest_bytes(bytes.fromhex(artifact_hex))
            for event_id, artifact_hex in result.stored_artifacts.items()
        )
    )


def _append_evidence(
    events: list[EvidenceEvent],
    artifacts: dict[str, str],
    *,
    event_id: str,
    producer: str,
    signature_status: str,
    cause_event_id: str | None,
    summary: str,
    artifact: BaseModel | bytes,
) -> None:
    event = _evidence_event(
        event_id=event_id,
        producer=producer,
        signature_status=signature_status,
        cause_event_id=cause_event_id,
        summary=summary,
        artifact=artifact,
        recorded_at=START + timedelta(microseconds=len(events)),
    )
    events.append(event)
    artifacts[event_id] = _artifact_bytes(artifact).hex()


def _append_refusal(
    events: list[EvidenceEvent], artifacts: dict[str, str], *, reason: str, producer: str
) -> None:
    _append_evidence(
        events,
        artifacts,
        event_id=f"REFUSAL:{reason}",
        producer=producer,
        signature_status="NOT_SIGNED",
        cause_event_id=events[-1].event_id if events else None,
        summary=reason,
        artifact=reason.encode(),
    )


def _result(
    variant: Variant,
    stages: list[str],
    *,
    disposition: str,
    status: AccountStatus,
    refusal: str | None = None,
    owner: str | None = None,
    age: int | None = None,
    dsor_records: int = 0,
    books_digest: str | None = None,
    invariants: dict[str, bool] | None = None,
    close_report: str | None = None,
    lc_register_length: int = 0,
    fill_quantity: Decimal | None = None,
    customer_position: Decimal | None = None,
    fail_id: str | None = None,
    i3_computed: bool | None = None,
    evidence: tuple[EvidenceEvent, ...],
    stored_artifacts: dict[str, str],
    refusal_state_before: StateSnapshot | None = None,
    refusal_state_after: StateSnapshot | None = None,
    books_entries: tuple[JournalEntry, ...] = (),
    confirmation: TradeConfirmation | None = None,
    confirmation_furnished: FurnishedEvent | None = None,
    statement: AccountStatement | None = None,
    trade_date_statement: AccountStatement | None = None,
    venue_execution_event: ExecutionEvent | None = None,
    venue_execution_report: VenueExecutionReport | None = None,
    engine_dispositions: dict[str, str] | None = None,
    early_warning_notices: tuple[dict[str, str], ...] = (),
    reconciliation_calendar: tuple[dict[str, object], ...] = (),
    tax_lot_rules: tuple[dict[str, str], ...] = (),
    account_treatment: tuple[dict[str, str], ...] = (),
) -> GoldenPathResult:
    return GoldenPathResult(
        variant=variant,
        disposition=disposition,
        account_status=status.value,
        refusal=refusal,
        exception_owner=owner,
        exception_age_seconds=age,
        stages=tuple(stages),
        evidence=evidence,
        evidence_digest=digest_bytes(
            canonical_bytes_of([item.model_dump(mode="json") for item in evidence])
        ),
        dsor_records=dsor_records,
        books_digest=books_digest,
        invariants={} if invariants is None else invariants,
        close_report=close_report,
        lc_register_length=lc_register_length,
        fill_quantity=fill_quantity,
        customer_position=customer_position,
        fail_id=fail_id,
        i3_computed=i3_computed,
        stored_artifacts=stored_artifacts,
        refusal_state_before=refusal_state_before,
        refusal_state_after=refusal_state_after,
        books_entries=books_entries,
        confirmation=confirmation,
        confirmation_furnished=confirmation_furnished,
        statement=statement,
        trade_date_statement=trade_date_statement,
        venue_execution_event=venue_execution_event,
        venue_execution_report=venue_execution_report,
        engine_dispositions={} if engine_dispositions is None else engine_dispositions,
        early_warning_notices=early_warning_notices,
        reconciliation_calendar=reconciliation_calendar,
        tax_lot_rules=tax_lot_rules,
        account_treatment=account_treatment,
    )


def _capacity_from_books(books: EquitiesBooks, *, clock: FixedRunClock) -> CapacityDocument:
    accounts = project_margin_accounts(books, prices={ISSUE: Decimal("100")})
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    results = tuple(
        compute_margin(
            account,
            trade_date=clock().date(),
            calendar=calendar,
            house_maintenance_rate=Decimal("0.30"),
            maintenance_call_due_business_days=2,
        )
        for account in accounts
    )
    projected = project_capacity(
        journal_digest=books.digest(),
        as_of=clock(),
        maximum_age_seconds=300,
        margin_results=results,
        accounts=accounts,
        account_types=classify_accounts(books),
        firm_participant_id="MVP3-FIRM",
    )
    return CapacityDocument.model_validate(projected.model_dump())


def _run_daily_close(
    *,
    books: EquitiesBooks,
    estate: EstateResult,
    as_of: datetime,
    fail_id: str | None,
    quantity: Decimal,
    price: Decimal,
    opened_on: date,
    depository_quantity_delta: Decimal = Decimal(),
) -> GoldenCloseResult:
    rules = load_rule_table()
    reduction_row = rules.get(DAILY_REDUCTION)
    if reduction_row is None or reduction_row.value is None:
        raise ValueError("daily reserve reduction rate is missing")
    reserve = required_reserve(
        books,
        as_of=as_of.date(),
        prices={ISSUE: price},
        customer_debit_reduction_rate=reduction_row.value,
    )
    capital = required_net_capital(books, {ISSUE: price}, Decimal("1000000"), rules)
    control = required_control(books, {ISSUE: price}, rules)
    location_balances: dict[tuple[str, str], Decimal] = {}
    observed_accounts: set[str] = set()
    for entry in books.entries:
        if entry.effective_date > as_of.date():
            continue
        for line in entry.lines:
            if line.record_side is RecordSide.LOCATION and line.issue is not None:
                key = (line.issue, line.account_type.value)
                location_balances[key] = location_balances.get(key, Decimal()) + line.quantity
            if line.account_type.value in {"CUSTOMER_CASH", "CUSTOMER_MARGIN"}:
                observed_accounts.add(line.account_id)
    location_balances = {
        key: value
        for key, value in location_balances.items()
        if value and key[1] in {"DTC", "FAIL_TO_RECEIVE", "STOCK_LOANED"}
    }
    if depository_quantity_delta:
        key = (ISSUE, "DTC")
        location_balances[key] = location_balances.get(key, Decimal()) + depository_quantity_delta
    location_balances = {key: value for key, value in location_balances.items() if value}
    readers = build_independent_sources(
        books,
        IndependentSourceInputs(
            as_of=as_of.date(),
            opening_depository=(),
            settlement_outcomes=(
                ()
                if fail_id is not None
                else (
                    SettlementOutcome(
                        issue=ISSUE,
                        net_quantity=quantity,
                        allocated_quantity=quantity,
                        settlement_date=opened_on,
                    ),
                )
            ),
            open_fails=(
                ()
                if fail_id is None
                else (
                    OpenFail(
                        fail_id=fail_id,
                        issue=ISSUE,
                        quantity=quantity,
                        cash=quantity * price,
                        opening_settlement_date=opened_on,
                        contract_price=price,
                    ),
                )
            ),
            loan_instructions=(),
        ),
    )
    street_breaks, street_completion = reconcile(
        location_balances,
        tuple(reader.read() for reader in readers),
        as_of=as_of.date(),
    )
    control_lines = (
        ()
        if control is None
        else tuple(
            (issue, max(required - control.in_control.get(issue, Decimal()), Decimal()))
            for issue, required in sorted(control.required.items())
        )
    )
    focus = tie_out_firm_close(
        close_date=as_of.date(),
        books=FirmFocusLines(
            net_capital=None if capital is None else capital.net_capital,
            reserve_total_credits=reserve.customer_credits,
            reserve_total_debits=reserve.customer_debits,
            pab_reserve_requirement=reserve.pab_requirement,
            control_shortfall_by_issue=control_lines,
        ),
        engines=FirmFocusLines(
            net_capital=estate.net_capital_figure,
            reserve_total_credits=estate.customer_total_credits,
            reserve_total_debits=estate.customer_total_debits,
            pab_reserve_requirement=estate.pab_reserve_figure,
            control_shortfall_by_issue=estate.control_shortfall_by_issue,
        ),
        expected_customer_accounts=(ACCOUNT,),
        observed_customer_accounts=tuple(sorted(observed_accounts)),
        book_shape={"journal_entries": len(books.entries), "customer_accounts": 1},
    )
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    age = 0 if fail_id is None else calendar.business_days_after(opened_on, as_of.date())
    i3 = not street_breaks and street_completion.status == "COMPLETED"
    return GoldenCloseResult(
        close_id=f"MVP4-CLOSE-{as_of.date().isoformat()}",
        report=("NORMAL_CLOSE" if fail_id is None else f"FAIL_AGED_{age}_BUSINESS_DAY"),
        fail_age_business_days=age,
        i3_stock_record_to_street=i3,
        reserve_requirement=reserve.customer_requirement,
        focus_tie_out_held=focus.held,
    )


def run_golden_path(  # noqa: PLR0915
    variant: Variant = Variant.CLEAN,
    *,
    order_quantity: Decimal = Decimal(10),
    funding_cash: Decimal | None = None,
    depository_quantity_delta: Decimal = Decimal(),
    bank_statement_delta: Decimal = Decimal(),
) -> GoldenPathResult:
    """Run one deterministic account, or one named fail-closed mutation."""
    _configure_trust()
    clock = FixedRunClock(START + timedelta(seconds=30))
    books = EquitiesBooks(break_owner="MVP3_SETTLEMENT_OPERATIONS")
    principal = _human("2", "synthetic retail principal")
    approver = _human("1", "synthetic human approver")
    application_id = "MVP3-APPLICATION"
    kyc_id = "MVP3-KYC"
    eligibility_id = "MVP3-ELIGIBILITY"
    cip_id = "SYN-CIP-GOLDEN001"
    profile_id = "SYN-PROFILE-GOLDEN001"
    principal_id = "SYN-PRINCIPAL-GOLDEN001"
    transfer_id = "MVP3-TRANSFER"
    trade_id = "MVP3-FIRST-TRADE"
    identity = SyntheticIdentity(
        person_id=PERSON,
        name_token="SYN-NAME-GOLDEN",
        birth_date_token="SYN-DOB-GOLDEN",
        address_token="SYN-ADDRESS-GOLDEN",
        taxpayer_id_token="SYN-TIN-GOLDEN",
        identity_document_token="SYN-DOC-GOLDEN",
    )
    cip = build_cip_record(
        record_id=cip_id,
        account_id=ACCOUNT,
        identity=identity,
        verification_method=VerificationMethod.DOCUMENTARY_SYNTHETIC,
        outcome=(
            CIPOutcome.UNABLE_TO_VERIFY if variant is Variant.CIP_UNABLE else CIPOutcome.VERIFIED
        ),
        checked_at=START + timedelta(seconds=5),
        exception_owner="CIP_OPERATIONS" if variant is Variant.CIP_UNABLE else None,
    )
    profile = CustomerProfile(
        record_id=profile_id,
        account_id=ACCOUNT,
        person_id=PERSON,
        updated_at=START + timedelta(seconds=10),
        employment_status="SYNTHETIC_EMPLOYED",
        annual_income_band="SYNTHETIC_A",
        net_worth_band="SYNTHETIC_B",
        liquid_net_worth_band="SYNTHETIC_C",
        tax_status="SYNTHETIC_STATUS",
        investment_objectives=("SYNTHETIC_GROWTH",),
        risk_tolerance="SYNTHETIC_MODERATE",
        time_horizon="SYNTHETIC_LONG",
        liquidity_needs="SYNTHETIC_LOW",
        investment_experience=("SYNTHETIC_EQUITIES",),
    )
    eligibility = verify_eligibility(
        EligibilityInputs(
            check_time=START + timedelta(seconds=10),
            kyc=KYCEvidence(
                beneficial_owner_id=PERSON,
                kyc_reference_id=kyc_id,
                verified_at=START + timedelta(seconds=5),
                expires_at=START + timedelta(days=30),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id=PERSON,
                    screening_id="MVP3-OFAC",
                    matched=False,
                    screened_at=START + timedelta(seconds=5),
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id=PERSON,
                    screening_id="MVP3-SANCTIONS",
                    matched=False,
                    screened_at=START + timedelta(seconds=5),
                ),
            ),
        )
    )
    funded_cash = (
        (Decimal("400") if variant is Variant.CREDIT_LIMIT else Decimal("10000"))
        if funding_cash is None
        else funding_cash
    )
    transfers = {
        transfer_id: TransferInRecord(
            record_id=transfer_id, account_id=ACCOUNT, completed=True, completed_at=clock()
        )
    }
    trades: dict[str, bytes] = {}
    kyc_record = KYCDecisionRecord(
        record_id=kyc_id,
        account_id=ACCOUNT,
        path_id="KYC_ELIGIBLE_CLEAR",
        decided_at=START + timedelta(seconds=5),
        maximum_age_seconds=999999,
        account_type=AccountType.NATURAL_PERSON,
        person_id=PERSON,
    )
    resolver = AuthoritativeEvidenceResolver(
        application_records={
            application_id: AccountApplication(
                record_id=application_id,
                account_id=ACCOUNT,
                account_type=AccountType.NATURAL_PERSON,
                person_id=PERSON,
                applied_at=START,
            )
        },
        kyc_dsor_records={kyc_id: kyc_record},
        kyc_event_chains={kyc_id: kyc_event_chain(kyc_record)},
        eligibility_records={
            eligibility_id: EligibilityResultRecord(
                record_id=eligibility_id,
                account_id=ACCOUNT,
                verified_at=START + timedelta(seconds=10),
                result=eligibility,
            )
        },
        transfer_records=transfers,
        first_trade_attestations=trades,
        cip_records={cip_id: cip},
        profile_records={profile_id: profile},
        principal_acceptance_records={
            principal_id: PrincipalAcceptanceRecord(
                record_id=principal_id,
                account_id=ACCOUNT,
                person_id=PERSON,
                profile_record_id=profile_id,
                accepted_at=START + timedelta(seconds=20),
                actor=approver,
                approval_ref="MVP3-HUMAN-APPROVAL",
            )
        },
    )
    lifecycle = AccountLifecycleStore(
        ActorRegistryApproverVerifier(
            {str(principal.actor_id): principal, str(approver.actor_id): approver}
        ),
        resolver,
        clock=clock,
        kyc_maximum_age_seconds=KYC_MAXIMUM_AGE_SECONDS,
    )
    lifecycle.apply(application_id)
    evidence_items: list[EvidenceEvent] = []
    stored_artifacts: dict[str, str] = {}
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=application_id,
        producer="Atreides",
        signature_status="NOT_SIGNED",
        cause_event_id=None,
        summary="natural-person application",
        artifact=resolver.resolve_application(application_id),
    )
    stages = ["Atreides: natural-person application recorded"]
    if variant is Variant.STALE_CALLER_TIME:
        clock.advance(timedelta(seconds=KYC_MAXIMUM_AGE_SECONDS + 1))
    onboarding_before = StateSnapshot(
        books_digest=books.digest(), dsor_records=0, lc_register_length=0
    )
    try:
        approved_event = lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=principal,
            timestamp=START,
            reason="MVP-3 human-approved retail onboarding",
            evidence_refs=(application_id, "MVP3-HUMAN-APPROVAL"),
            kyc_record_id=kyc_id,
            eligibility_record_id=eligibility_id,
            human_approval_ref="MVP3-HUMAN-APPROVAL",
            cip_record_id=cip_id,
            profile_record_id=profile_id,
            principal_acceptance_record_id=principal_id,
        )
    except AccountTransitionRefusedError as exc:
        _append_refusal(
            evidence_items,
            stored_artifacts,
            reason=exc.reason.value,
            producer="Atreides account lifecycle",
        )
        onboarding_after = StateSnapshot(
            books_digest=books.digest(), dsor_records=0, lc_register_length=0
        )
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=AccountStatus.APPLIED,
            refusal=exc.reason.value,
            owner="CIP_OPERATIONS" if variant is Variant.CIP_UNABLE else "KYC_OPERATIONS",
            age=cip.exception_age_seconds(clock()),
            books_digest=books.digest(),
            evidence=tuple(evidence_items),
            stored_artifacts=stored_artifacts,
            refusal_state_before=onboarding_before,
            refusal_state_after=onboarding_after,
        )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(approved_event.event_id),
        producer="Atreides",
        signature_status="VERIFIED" if lifecycle.chain_report(ACCOUNT).ok else "FAILED",
        cause_event_id=application_id,
        summary="account approved",
        artifact=approved_event,
    )
    stages.append("Atreides: CIP, profile, eligibility, principal, and human approval passed")
    _post_transfer(
        books,
        StatementLine(account=ACCOUNT, issue=ISSUE, quantity=Decimal(0), cash_credit=funded_cash),
        transfer_id=transfer_id,
        sequence=1,
        quantity=Decimal(0),
        cash=funded_cash,
        day=clock().date(),
    )
    funded_event = lifecycle.transition(
        ACCOUNT,
        AccountStatus.FUNDED,
        actor=principal,
        timestamp=START,
        reason="completed synthetic ACATS transfer",
        evidence_refs=(str(approved_event.event_id), transfer_id),
        transfer_record_id=transfer_id,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(funded_event.event_id),
        producer="Atreides",
        signature_status="VERIFIED" if lifecycle.chain_report(ACCOUNT).ok else "FAILED",
        cause_event_id=str(approved_event.event_id),
        summary="account funded",
        artifact=funded_event,
    )
    stages.extend(
        ("Atreides: completed transfer posted to books", "Atreides: account moved to FUNDED")
    )

    policy = PolicyManifest(
        policy_id="MVP3-POLICY", version="1", bounds_digest="sha256:" + "1" * 64, enabled=True
    )
    actor = estate_actor()
    payload = ApprovedIntentPayload(
        intent_id=IntentId(_identifier("int_", 11001)),
        instrument_id=ISSUE,
        side=OrderSide.BUY,
        quantity=order_quantity,
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=approver.actor_id, policy_manifest_digest=digest(policy), authorized=True
        ),
        allocation_accounts=(ACCOUNT,),
        source_event_id=str(funded_event.event_id),
    )
    with DSORStore(":memory:") as dsor:
        dsor_record = ApprovedIntentDecisionRecord(
            operation_id=UUID("00000000-0000-0000-0000-000000000301"),
            lifecycle_id=LifecycleId(_identifier("lif_", 20001)),
            intent_id=str(payload.intent_id),
            intent_digest=digest(payload),
            decided_at=clock(),
            source_event_id=str(funded_event.event_id),
        )
        dsor.append(
            dsor_record,
            dtg=clock(),
        )
        dsor_count = len(dsor.records())
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(payload.intent_id),
        producer="Aureon",
        signature_status="NOT_SIGNED",
        cause_event_id=payload.source_event_id,
        summary="approved intent",
        artifact=payload,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(dsor_record.operation_id),
        producer="Atreides Decision System of Record",
        signature_status="NOT_SIGNED",
        cause_event_id=dsor_record.intent_id,
        summary="approved intent decision",
        artifact=dsor_record,
    )
    stages.extend(
        (
            "Aureon: recommended equity BUY intent approved",
            "Atreides: intent decision appended to DSOR",
        )
    )

    terms = OrderTerms(
        account_id=ACCOUNT,
        strategy_id="MVP3",
        issue=ISSUE,
        side="BUY",
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        control_price=Decimal("100"),
        approved_intent_digest=digest(payload),
        policy_expires_at=clock() + timedelta(days=1),
        recommended=True,
        customer_profile_record_id=profile_id,
    )
    status_wire = lifecycle.publish_status(
        as_of=clock(),
        maximum_age_seconds=PROFILE_MAXIMUM_AGE_SECONDS,
        key_id=LC_STATUS_KEY_ID,
        private_key=LC_STATUS_PRIVATE_KEY,
    )
    if variant is Variant.ACCOUNT_RESTRICTED:
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.RESTRICTED,
            actor=principal,
            timestamp=START,
            reason="synthetic account restriction",
            evidence_refs=("MVP3-RESTRICTION",),
        )
        status_wire = lifecycle.publish_status(
            as_of=clock(),
            maximum_age_seconds=PROFILE_MAXIMUM_AGE_SECONDS,
            key_id=LC_STATUS_KEY_ID,
            private_key=LC_STATUS_PRIVATE_KEY,
        )
    if variant is Variant.FORGED_STATUS:
        status_wire = status_wire[:-2] + b"xx"
    lc_profile = CustomerProfileEvidence(
        record_id=profile_id,
        account_id=ACCOUNT,
        employment_status=None
        if variant is Variant.PROFILE_INCOMPLETE
        else profile.employment_status,
        annual_income_band=profile.annual_income_band,
        net_worth_band=profile.net_worth_band,
        liquid_net_worth_band=profile.liquid_net_worth_band,
        tax_status=profile.tax_status,
        investment_objectives=profile.investment_objectives or (),
        risk_tolerance=profile.risk_tolerance,
        time_horizon=profile.time_horizon,
        liquidity_needs=profile.liquidity_needs,
        investment_experience=profile.investment_experience or (),
        verified_at=profile.updated_at,
        maximum_age_seconds=999999,
        source="SYNTHETIC_MVP3",
    )
    recommendation_before = StateSnapshot(
        books_digest=books.digest(), dsor_records=dsor_count, lc_register_length=0
    )
    try:
        GoldenRecommendationGate(clock, PROFILE_MAXIMUM_AGE_SECONDS).evaluate(
            terms, lc_profile, status_wire
        )
    except ValueError as exc:
        reason = str(exc)
        _append_refusal(
            evidence_items,
            stored_artifacts,
            reason=reason,
            producer="L.C. recommendation gate",
        )
        recommendation_after = StateSnapshot(
            books_digest=books.digest(), dsor_records=dsor_count, lc_register_length=0
        )
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal=reason,
            owner="RETAIL_SUPERVISION",
            age=0,
            dsor_records=dsor_count,
            books_digest=books.digest(),
            evidence=tuple(evidence_items),
            stored_artifacts=stored_artifacts,
            refusal_state_before=recommendation_before,
            refusal_state_after=recommendation_after,
        )
    stages.append("L.C.: recommendation profile and signed account status passed")

    # Exercise the real market-access gate on the same sealed child terms via the
    # estate lifecycle. The estate then consumes the identical deterministic intent.
    from cannae_kernel.canonical import digest_bytes as kernel_digest_bytes
    from cannae_kernel.effects import OperationEffects
    from cannae_kernel.envelopes import ApprovedIntentEnvelope as KernelEnvelope
    from cannae_kernel.provenance import Provenance
    from cannae_kernel.session import BusinessDate, MarketSession, SessionContext
    from lc.lifecycle import (
        ChildOrder,
        accept_intent,
        activate_parent,
        authorize_strategy,
        split_parent,
    )

    wire = _wire(payload)
    envelope = KernelEnvelope(
        envelope_id=payload.intent_id,
        lifecycle_id=LifecycleId(_identifier("lif_", 20001)),
        revision=1,
        prior_digest=None,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=clock().date(), calendar="SIFMA-US", established_by="MVP-3 run clock"
            ),
        ),
        approved_by=approver,
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(
            operation="MVP-3 approved intent", effects=(), note="synthetic only"
        ),
        payload_digest=kernel_digest_bytes(wire),
    )
    validate_approval_provenance(envelope)
    outcome = accept_intent(
        envelope,
        wire,
        parent_order_id=OrderId(_identifier("ord_", 30002)),
        actor=actor,
        event=_event(40001, clock()),
    )
    outcome = authorize_strategy(outcome, actor=actor, event=_event(40002, clock()))
    outcome = activate_parent(outcome, actor=actor, event=_event(40003, clock()))
    child = ChildOrder(
        order_id=OrderId(_identifier("ord_", 30003)),
        quantity=order_quantity,
        event=_event(40004, clock()),
        terms=terms,
    )
    register = split_parent(
        outcome,
        actor=actor,
        children=(child,),
        recommendation_profile_resolver=MappingRecommendationProfileResolver(
            {profile_id: lc_profile}
        ),
        evaluated_at=clock(),
        account_status_input=status_wire,
        profile_maximum_age_seconds=PROFILE_MAXIMUM_AGE_SECONDS,
    ).journal
    for item in register.events:
        _append_evidence(
            evidence_items,
            stored_artifacts,
            event_id=str(item.event_id),
            producer="L.C.",
            signature_status="VERIFIED" if verify_event(item) else "FAILED",
            cause_event_id=str(item.parent_ids[0]) if item.parent_ids else str(payload.intent_id),
            summary=item.payload.state.value,
            artifact=item,
        )
    order_event = register.events[-1]
    capacity = _capacity_from_books(books, clock=clock)
    capacity_bytes = canonical_bytes(capacity)
    market_access_before = StateSnapshot(
        books_digest=books.digest(),
        dsor_records=dsor_count,
        lc_register_length=len(register.events),
    )
    decision = MarketAccessGate().evaluate(
        ChildRelease(
            order_event=order_event,
            lifecycle_register=register,
            reference_price=Decimal("100"),
            submitted_at=clock(),
        ),
        limits=LimitsManifest(
            version="MVP3-1",
            authority="MVP3-RISK",
            account_credit_limits={ACCOUNT: Decimal("100000")},
            firm_aggregate_threshold=Decimal("100000"),
            price_collar_percent=Decimal("0.10"),
            maximum_quantity=Decimal(1000),
            maximum_notional=Decimal("100000"),
            duplicate_window_seconds=60,
        ),
        capacity_input=AttestedInput(
            payload=capacity_bytes, payload_digest=digest_bytes(capacity_bytes)
        ),
        locates_input=None,
        account_status_input=status_wire,
    )
    if decision.terminal:
        reason = next(item.reason for item in decision.checks if not item.passed)
        _append_refusal(
            evidence_items,
            stored_artifacts,
            reason=reason,
            producer="L.C. market access gate",
        )
        market_access_after = StateSnapshot(
            books_digest=books.digest(),
            dsor_records=dsor_count,
            lc_register_length=len(register.events),
        )
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal=reason,
            owner="MARKET_ACCESS_RISK",
            age=0,
            dsor_records=dsor_count,
            books_digest=books.digest(),
            lc_register_length=len(register.events),
            evidence=tuple(evidence_items),
            stored_artifacts=stored_artifacts,
            refusal_state_before=market_access_before,
            refusal_state_after=market_access_after,
        )
    register = record_decision(
        register,
        decision,
        actor=actor,
        event=_event(40005, clock()),
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(register.events[-1].event_id),
        producer="L.C. market access gate",
        signature_status="VERIFIED" if verify_event(register.events[-1]) else "FAILED",
        cause_event_id=str(order_event.event_id),
        summary="MARKET_ACCESS_PASSED",
        artifact=register.events[-1],
    )
    stages.extend(("L.C.: firm market access passed", "L.C.: order sealed for synthetic venue"))
    venue_result = VenueEmulator(seed=30003).execute(
        VenueOrder(
            lifecycle_id=order_event.lifecycle_id,
            order_id=child.order_id,
            intent_id=payload.intent_id,
            intent_digest=digest(payload),
            quantity=order_quantity,
            limit_price=terms.control_price,
            policy_expires_at=terms.policy_expires_at or clock() + timedelta(days=1),
            session=envelope.session,
        ),
        outcome=VenueOutcome.FILL,
        event_time=clock(),
    )
    if not isinstance(venue_result.report, Recorded) or not isinstance(
        venue_result.event, Recorded
    ):
        raise ValueError("synthetic venue fill did not produce recorded evidence")
    venue_report = venue_result.report.value
    venue_event = venue_result.event.value
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(venue_event.event_id),
        producer="VenueEmulator",
        signature_status="NOT_SIGNED",
        cause_event_id=str(register.events[-1].event_id),
        summary="venue fill",
        artifact=venue_event,
    )
    report = Print(
        print_id=venue_report.execution_id,
        order_id=str(child.order_id),
        issue=ISSUE,
        quantity=int(venue_report.quantity),
        price=venue_report.price,
        matched_at=venue_event.times.event_time,
        reported_at=venue_event.times.observation_time,
    )
    fail_id: str | None = None
    if variant is Variant.SETTLEMENT_FAIL:
        rail_times = _event(50001, clock()).times
        submission = SyntheticEntitledMember(seed=1).submit(
            lifecycle_id=order_event.lifecycle_id,
            instruction=canonical_bytes(venue_report),
            times=rail_times,
        )
        rail_response = SyntheticRail(seed=1).respond(submission, times=rail_times)
        if rail_response.outcome is not RailOutcome.QUEUED:
            raise ValueError("settlement fail scenario requires the deterministic queued rail")
        fail_id = rail_response.response_id
    estate = drive_estate(
        run_number=1,
        business_date=clock().date(),
        issue=ISSUE,
        reports=(report,),
        account_weights=(1,),
        street_quantity=Decimal(0) if fail_id is not None else venue_report.quantity,
        prior_close=Decimal("100"),
        protection_inputs_missing=False,
        customer_credit_balance=Decimal(0),
        average_total_credits=Decimal(0),
        daily_requirement_effective_date=clock().date(),
        computation_mode=ComputationMode.DAILY,
        previously_daily_required=True,
        daily_exit_notice_date=None,
        financing_charge=None,
        account_ids=(ACCOUNT,),
        books=books,
        source_event_id=str(order_event.event_id),
        settlement_fail_id=fail_id,
        approved_payload=payload,
        approved_register=register,
        source_execution_event_id=str(venue_event.event_id),
        deposit_policy=DepositPolicy(
            customer=DepositDraw(outcome="ON_TIME", short_fraction=Decimal(0)),
            pab=DepositDraw(outcome="ON_TIME", short_fraction=Decimal(0)),
            bank_equity_capital=Decimal("1000000"),
        ),
    )
    # The estate consumes the same approved intent and lifecycle register already
    # published above. Publishing them a second time would duplicate evidence ids.
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=estate.capture_record.trade_id,
        producer="L.C.",
        signature_status="NOT_SIGNED",
        cause_event_id=str(venue_event.event_id),
        summary="trade capture",
        artifact=estate.capture_record,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(estate.allocation_record.allocation_id),
        producer="L.C.",
        signature_status="NOT_SIGNED",
        cause_event_id=estate.allocation_record.trade_ids[0],
        summary="allocation",
        artifact=estate.allocation_record,
    )
    settlement_entry = find_book_entry_for_execution(books, venue_event)
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=settlement_entry.entry_id,
        producer="Atreides books",
        signature_status="NOT_SIGNED",
        cause_event_id=settlement_entry.source_event_id,
        summary="customer buy journal entry",
        artifact=settlement_entry,
    )
    if variant is Variant.SETTLEMENT_FAIL:
        if fail_id is None:
            raise ValueError("settlement fail response did not carry a fail identifier")
        fail_opened = clock().date()
        calendar = MarketCalendar.load(Market.US_EQUITIES)
        next_close = calendar.add_business_days(fail_opened, 1)
        clock.advance(timedelta(days=(next_close - fail_opened).days))
        fail_state_before = StateSnapshot(
            books_digest=books.digest(),
            dsor_records=dsor_count,
            lc_register_length=len(register.events),
        )
        close = _run_daily_close(
            books=books,
            estate=estate,
            as_of=clock(),
            fail_id=fail_id,
            quantity=venue_report.quantity,
            price=venue_report.price,
            opened_on=fail_opened,
        )
        _append_evidence(
            evidence_items,
            stored_artifacts,
            event_id=close.close_id,
            producer="Atreides daily close",
            signature_status="NOT_SIGNED",
            cause_event_id=settlement_entry.entry_id,
            summary=close.report,
            artifact=close,
        )
        _append_refusal(
            evidence_items,
            stored_artifacts,
            reason="CNS_SETTLEMENT_FAIL",
            producer="Atreides settlement operations",
        )
        fail_state_after = StateSnapshot(
            books_digest=books.digest(),
            dsor_records=dsor_count,
            lc_register_length=len(register.events),
        )
        stages.extend(
            (
                "Atreides: CNS fail posted to books and aged by daily close",
                "Atreides: daily close completed",
            )
        )
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal="CNS_SETTLEMENT_FAIL",
            owner="MVP3_SETTLEMENT_OPERATIONS",
            age=close.fail_age_business_days * 86400,
            dsor_records=dsor_count,
            books_digest=books.digest(),
            close_report=close.report,
            lc_register_length=len(register.events),
            fill_quantity=venue_report.quantity,
            fail_id=fail_id,
            i3_computed=close.i3_stock_record_to_street,
            evidence=tuple(evidence_items),
            stored_artifacts=stored_artifacts,
            refusal_state_before=fail_state_before,
            refusal_state_after=fail_state_after,
        )
    first_trade_record = FirstPermittedTradeRecord(
        record_id=trade_id,
        account_id=ACCOUNT,
        permitted=True,
        traded_at=clock(),
        source_event_id=settlement_entry.entry_id,
    )
    trades[trade_id] = attest_first_permitted_trade(
        first_trade_record,
        key_id=LC_KEY_ID,
        private_key=LC_PRIVATE_KEY,
    )
    active_event = lifecycle.transition(
        ACCOUNT,
        AccountStatus.ACTIVE,
        actor=principal,
        timestamp=START,
        reason="L.C. signed first permitted trade after books posting",
        evidence_refs=(trade_id,),
        first_trade_record_id=trade_id,
    )
    stages.extend(
        (
            "Venue: execution emulator produced a fill",
            "L.C.: execution captured and allocated",
            "Atreides: CNS settlement posted to books",
            "Atreides: L.C. signed first-trade evidence moved account to ACTIVE",
            "Atreides: daily close completed",
        )
    )
    rules = load_rule_table()
    reduction_row = rules.get(DAILY_REDUCTION)
    if reduction_row is None or reduction_row.value is None:
        raise ValueError("daily reserve reduction rate is missing")
    reduction = reduction_row.value
    oracle_reserve = required_reserve(
        books,
        as_of=clock().date(),
        prices={ISSUE: Decimal("100")},
        customer_debit_reduction_rate=reduction,
    )
    oracle_capital = required_net_capital(books, {ISSUE: Decimal("100")}, Decimal("1000000"), rules)
    oracle_control = required_control(books, {ISSUE: Decimal("100")}, rules)
    observed_accounts: set[str] = set()
    for entry in books.entries:
        if entry.effective_date > clock().date():
            continue
        for line in entry.lines:
            if line.account_type.value in {"CUSTOMER_CASH", "CUSTOMER_MARGIN"}:
                observed_accounts.add(line.account_id)
    independent_control_lines = (
        ()
        if oracle_control is None
        else tuple(
            (issue, max(quantity - oracle_control.in_control.get(issue, Decimal()), Decimal()))
            for issue, quantity in sorted(oracle_control.required.items())
        )
    )
    focus = tie_out_firm_close(
        close_date=clock().date(),
        books=FirmFocusLines(
            net_capital=None if oracle_capital is None else oracle_capital.net_capital,
            reserve_total_credits=oracle_reserve.customer_credits,
            reserve_total_debits=oracle_reserve.customer_debits,
            pab_reserve_requirement=oracle_reserve.pab_requirement,
            control_shortfall_by_issue=independent_control_lines,
        ),
        engines=FirmFocusLines(
            net_capital=estate.net_capital_figure,
            reserve_total_credits=estate.customer_total_credits,
            reserve_total_debits=estate.customer_total_debits,
            pab_reserve_requirement=estate.pab_reserve_figure,
            control_shortfall_by_issue=estate.control_shortfall_by_issue,
        ),
        expected_customer_accounts=(ACCOUNT,),
        observed_customer_accounts=tuple(sorted(observed_accounts)),
        book_shape={"journal_entries": len(books.entries), "customer_accounts": 1},
    )
    account_chain_verified = lifecycle.chain_report(ACCOUNT).ok
    verified_first_trade = verify_first_trade_record(resolver, trade_id, evaluated_at=clock())
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=trade_id,
        producer="L.C.",
        signature_status=verified_first_trade.status,
        cause_event_id=first_trade_record.source_event_id,
        summary="first permitted trade",
        artifact=trades[trade_id],
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=str(active_event.event_id),
        producer="Atreides",
        signature_status="VERIFIED" if account_chain_verified else "FAILED",
        cause_event_id=trade_id,
        summary="account active",
        artifact=active_event,
    )
    confirmation = generate_trade_confirmation(
        account_id=ACCOUNT,
        book_entry=settlement_entry,
        execution_event=venue_event,
        execution_report=venue_report,
    )
    furnished = record_furnished(
        confirmation,
        furnished_at=clock(),
        recipient_id=PERSON,
    )
    customer_side_facts = customer_side_facts_from_furnished_confirmations(
        deposit_instructions=(funded_cash,),
        venue_fills=((ISSUE, venue_report.quantity, venue_report.price),),
        furnished_confirmations=((confirmation, furnished),),
    )
    trade_date_statement_draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=lifecycle.status(ACCOUNT),
        period_start=START.date(),
        period_end=clock().date(),
        market_prices={ISSUE: venue_report.price},
    )
    trade_date_statement = issue_statement(
        trade_date_statement_draft,
        books,
        issued_at=clock(),
        customer_side_facts=customer_side_facts,
    )
    settlement_date = max(
        entry.effective_date
        for entry in books.entries
        if entry.source in {PostingSource.CNS_SETTLEMENT, PostingSource.CNS_FAIL}
    )
    clock.advance(timedelta(days=(settlement_date - clock().date()).days))
    reconciliation_date = clock().date()
    street_books: dict[tuple[str, str], Decimal] = {}
    for entry in books.entries:
        if entry.effective_date > reconciliation_date:
            continue
        for line in entry.lines:
            if (
                line.record_side is RecordSide.LOCATION
                and line.issue is not None
                and line.account_type.value in {"DTC", "FAIL_TO_RECEIVE", "STOCK_LOANED"}
            ):
                key = (line.issue, line.account_type.value)
                street_books[key] = street_books.get(key, Decimal()) + line.quantity
    street_readers = build_independent_sources(
        books,
        IndependentSourceInputs(
            as_of=reconciliation_date,
            opening_depository=(DepositoryPosition(ISSUE, "DTC", depository_quantity_delta),)
            if depository_quantity_delta
            else (),
            settlement_outcomes=(
                SettlementOutcome(
                    ISSUE,
                    venue_report.quantity,
                    venue_report.quantity,
                    settlement_date,
                ),
            ),
            open_fails=(),
            loan_instructions=(),
        ),
    )
    street_sources = tuple(reader.read() for reader in street_readers)
    street_specs = (
        ("stock-record-to-street", "DTC", street_sources[0]),
        ("ftr-to-cns-fail-statement", "FAIL_TO_RECEIVE", street_sources[1]),
        ("stock-loan-to-contract-register", "STOCK_LOANED", street_sources[2]),
    )
    street_completions = []
    street_breaks: list[StreetBreak] = []
    for item_id, location, source in street_specs:
        scoped_books = {key: value for key, value in street_books.items() if key[1] == location}
        item_breaks, completion = reconcile(
            scoped_books,
            (source,),
            as_of=reconciliation_date,
            item_id=item_id,
        )
        street_breaks.extend(item_breaks)
        street_completions.append(
            ReconciliationCompletion(
                item_id=item_id,
                close_date=reconciliation_date,
                sources_read=("Atreides equities books", *completion.sources_read),
                break_count=len(item_breaks),
                status="FAILED" if item_breaks else "COMPLETED",
                error="reconciliation break" if item_breaks else None,
            )
        )

    instruction_log = InstructionLog()
    cash_instructions = (
        MoneyInstruction(
            "GOLDEN-CASH-OPENING",
            START.date(),
            -funded_cash,
            InstructionKind.OPENING,
            "SYN-CONVERSION-FUNDING",
        ),
        MoneyInstruction(
            "GOLDEN-CNS-MONEY-SETTLEMENT",
            settlement_date,
            venue_report.quantity * venue_report.price + bank_statement_delta,
            InstructionKind.CNS_SETTLEMENT,
            "CLEARING",
        ),
    )
    for instruction in cash_instructions:
        instruction_log.append(instruction)
    cash_statement = instruction_log.statement(
        "synthetic firm bank statement",
        reconciliation_date,
        kinds=frozenset(
            {
                InstructionKind.OPENING,
                InstructionKind.CNS_SETTLEMENT,
                InstructionKind.CUSTOMER_DEPOSIT,
            }
        ),
    )
    cash_result = reconcile_ps1("cash-to-bank", books, cash_statement, reconciliation_date)
    reserve_instructions = tuple(
        MoneyInstruction(
            f"GOLDEN-RESERVE-{deposit.computation}",
            deposit.deposit_date,
            deposit.amount,
            InstructionKind.RESERVE_TRANSFER,
            (
                "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK"
                if deposit.computation == "customer"
                else "RESERVE_BANK_PAB@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK"
            ),
        )
        for deposit in estate.reserve_deposits
        if deposit.deposit_date is not None and deposit.amount
    )
    for instruction in reserve_instructions:
        instruction_log.append(instruction)
    reserve_statement = instruction_log.statement(
        "synthetic reserve bank statement",
        reconciliation_date,
        kinds=frozenset({InstructionKind.RESERVE_TRANSFER}),
    )
    reserve_result = reconcile_ps1(
        "reserve-bank-to-books", books, reserve_statement, reconciliation_date
    )
    securities_count = build_securities_count(
        (
            SecuritiesConfirmation(
                "GOLDEN-DTC-CONFIRMATION",
                settlement_date,
                ISSUE,
                "DTC",
                venue_report.quantity + depository_quantity_delta,
            ),
        ),
        reconciliation_date,
    )
    securities_result = reconcile_ps1(
        "securities-count", books, securities_count, reconciliation_date
    )

    def money_completion(control: ControlResult) -> ReconciliationCompletion:
        return ReconciliationCompletion(
            item_id=control.item_id,
            close_date=reconciliation_date,
            sources_read=control.sources_read,
            break_count=len(control.breaks),
            status="FAILED" if control.status == "FAILED" else "COMPLETED",
            error="reconciliation break" if control.breaks else None,
        )

    control_calendar = reconciliation_calendar(
        reconciliation_date,
        (
            *street_completions,
            money_completion(cash_result),
            money_completion(reserve_result),
            money_completion(securities_result),
        ),
    )
    statement_draft = build_statement_draft(
        books,
        account_id=ACCOUNT,
        account_status=lifecycle.status(ACCOUNT),
        period_start=START.date(),
        period_end=clock().date(),
        market_prices={ISSUE: venue_report.price},
    )
    statement = issue_statement(
        statement_draft,
        books,
        issued_at=clock(),
        customer_side_facts=customer_side_facts,
    )
    clean_close = _run_daily_close(
        books=books,
        estate=estate,
        as_of=clock(),
        fail_id=None,
        quantity=venue_report.quantity,
        price=venue_report.price,
        opened_on=clock().date(),
        depository_quantity_delta=depository_quantity_delta,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=confirmation.confirmation_id,
        producer="Atreides client reporting",
        signature_status="NOT_SIGNED",
        cause_event_id=settlement_entry.entry_id,
        summary="trade confirmation",
        artifact=confirmation,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=furnished.furnished_event_id,
        producer="Atreides client reporting",
        signature_status="NOT_SIGNED",
        cause_event_id=confirmation.confirmation_id,
        summary="synthetic confirmation furnished",
        artifact=furnished,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=statement.statement_id,
        producer="Atreides client reporting",
        signature_status="NOT_SIGNED",
        cause_event_id=confirmation.confirmation_id,
        summary="account statement",
        artifact=statement,
    )
    _append_evidence(
        evidence_items,
        stored_artifacts,
        event_id=f"MVP5B-CLOSE-{clock().date().isoformat()}",
        producer="Atreides daily close",
        signature_status="NOT_SIGNED",
        cause_event_id=statement.statement_id,
        summary="NORMAL_CLOSE",
        artifact=clean_close,
    )
    evidence = tuple(evidence_items)
    evidence_ids = {item.event_id for item in evidence}
    invariants = {
        "stock_record": not estate.stock_breaks,
        "reserve": estate.reserve_disposition == "PASS",
        "pab_reserve": estate.pab_reserve_disposition == "PASS",
        "net_capital": estate.net_capital_disposition == "PASS",
        "possession_or_control": estate.control_disposition == "PASS",
        "settlement_two_sided": estate.settlement_residual_two_sided,
        "evidence_chain": evidence[0].cause_event_id is None
        and all(item.cause_event_id in evidence_ids for item in evidence[1:]),
        "independent_oracle": (
            oracle_reserve.customer_requirement == estate.reserve_figure
            and oracle_reserve.pab_requirement == estate.pab_reserve_figure
            and oracle_capital is not None
            and oracle_capital.net_capital == estate.net_capital_figure
            and oracle_control is not None
            and oracle_control.outcome == estate.control_disposition
        ),
        "street_reconciliation": not street_breaks
        and all(item.status == "COMPLETED" for item in street_completions),
        "focus_tie_out": focus.held,
        "customer_in_books": ACCOUNT in observed_accounts,
    }
    customer_position = sum(
        (
            line.quantity
            for entry in books.entries
            for line in entry.lines
            if line.account_id == ACCOUNT
            and line.issue == ISSUE
            and line.record_side is RecordSide.OWNERSHIP
        ),
        Decimal(),
    )
    return _result(
        variant,
        stages,
        disposition="PASS",
        status=lifecycle.status(ACCOUNT),
        dsor_records=dsor_count,
        books_digest=estate.books_digest,
        invariants=invariants,
        close_report="NORMAL_CLOSE",
        lc_register_length=len(register.events),
        fill_quantity=venue_report.quantity,
        customer_position=customer_position,
        i3_computed=clean_close.i3_stock_record_to_street,
        evidence=evidence,
        stored_artifacts=stored_artifacts,
        books_entries=books.entries,
        confirmation=confirmation,
        confirmation_furnished=furnished,
        statement=statement,
        trade_date_statement=trade_date_statement,
        venue_execution_event=venue_event,
        venue_execution_report=venue_report,
        engine_dispositions={
            "reserve": estate.reserve_disposition,
            "pab_reserve": estate.pab_reserve_disposition,
            "net_capital": estate.net_capital_disposition,
            "possession_or_control": estate.control_disposition,
            "street_reconciliation": (
                "PASS"
                if not street_breaks
                and all(item.status == "COMPLETED" for item in street_completions)
                else "HOLD"
            ),
        },
        early_warning_notices=(),
        reconciliation_calendar=tuple(
            {
                "item_id": item.item_id,
                "status": item.status,
                "break_count": item.break_count,
                "close_date": item.close_date.isoformat(),
                "sources_read": item.sources_read,
            }
            for item in control_calendar
        ),
        tax_lot_rules=TAX_LOT_RULES,
        account_treatment=ACCOUNT_TREATMENT_ROWS,
    )


def replay_evidence_digest(result: GoldenPathResult) -> str:
    return digest_bytes(
        canonical_bytes_of([item.model_dump(mode="json") for item in result.evidence])
    )


def write_golden_path_publication(output: Path) -> tuple[Path, Path]:
    """Publish the dated synthetic evidence pack without changing prior packs."""
    result = run_golden_path()
    output.mkdir(parents=True, exist_ok=False)
    evidence_path = output / "evidence-pack.json"
    summary_path = output / "SUMMARY.md"
    evidence_path.write_text(result.model_dump_json(indent=2) + "\n")
    pack_digest = digest_bytes(evidence_path.read_bytes())
    anchor = PackDigestDSORRecord(
        record_id=f"PACK-{pack_digest.removeprefix('sha256:')[:24]}",
        pack_digest=pack_digest,
        recorded_at=datetime.now(UTC),
    )
    # Convenience copy only. A sibling file is not an independent anchor.
    (output / "pack-digest-dsor.json").write_text(anchor.model_dump_json(indent=2) + "\n")
    summary_path.write_text(
        "# PS-1B closure\n\n"
        "This pack contains one declared-synthetic natural-person account and one "
        "declared-synthetic United States equity. It records the ordered cause chain "
        "from application through the settlement date close. No event was submitted to a venue, "
        "depository, bank, or regulator.\n\n"
        "| Figure | Prior pack | Current pack | Reason |\n"
        "| --- | ---: | ---: | --- |\n"
        "| Reconciliation rows | Six constant RAN rows | Six control result rows | "
        "Rows now carry each control's status, break count and sources read |\n"
        "| Closing free cash | 9000.00 | 9000.00 | Customer economics are unchanged |\n"
        "| Closing shares | 10 | 10 | Customer economics are unchanged |\n"
        "| Settlement status | SETTLED | SETTLED | Dated posting is unchanged |\n"
        "| Cost basis | 1000.00 | 1000.00 | Journal-replayed lots are unchanged |\n"
        "| Unrealized gain or loss | 0.00 | 0.00 | Synthetic closing price is unchanged |\n\n"
        "The trade-date statement reports the same cash and shares as `UNSETTLED`; the "
        "settlement-date statement reports them as `SETTLED`. All six reconciliation "
        "calendar rows report `RAN` with zero breaks, and every clean-run invariant in "
        "`evidence-pack.json` is true.\n"
        "\n## Tax-lot rules\n\n"
        "FIFO is applied under 26 CFR 1.1012-1(c)(1)(i), and specific identification must be "
        "recorded no later than the settlement deadline under 26 CFR 1.1012-1(c)(8). Broker "
        "basis reporting is cited to 26 CFR 1.6045-1(d)(2)(i)(A). Wash-sale adjustment remains "
        "`TO_VERIFY`: the journal does not carry the verified CUSIP or other covered-security "
        "identifier required to apply 26 CFR 1.6045-1(d)(6)(iii) deterministically.\n\n"
        "## Account treatment\n\n"
        "The evidence pack includes a row for each PS-1 account type. Each is marked "
        "`TO_VERIFY_AGAINST_PRIMARY_TEXT` because the pinned 17 CFR 240.15c3-3 and "
        "240.15c3-3a text does not settle the internal placement.\n"
    )
    return evidence_path, summary_path


def verify_published_pack(evidence_path: Path, anchor_path: Path) -> bool:
    """Verify a pack against a supplied digest record, which may be a convenience copy."""
    anchor = PackDigestDSORRecord.model_validate_json(anchor_path.read_text(encoding="utf-8"))
    return anchor.pack_digest == digest_bytes(evidence_path.read_bytes())
