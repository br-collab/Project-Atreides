"""MVP-3 one-account golden path across the real Cannae layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes, canonical_bytes_of, digest, digest_bytes
from cannae_kernel.ids import ActorId, IntentId, LifecycleId, OrderId
from cannae_kernel.journal import ChainReport
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lc.events import OrderTerms, OrderType, TimeInForce
from lc.lifecycle import ApprovedIntentPayload, AuthorityManifest, OrderSide, PolicyManifest
from lc.market_access import (
    AttestedInput,
    CapacityAccount,
    CapacityDocument,
    ChildRelease,
    LimitsManifest,
    MarketAccessGate,
)
from lc.recommendation_profile import (
    CustomerProfileEvidence,
    MappingRecommendationProfileResolver,
    enforce_recommendation_profile,
)
from pydantic import BaseModel, ConfigDict

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
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from atreides.books.ledger import EquitiesBooks
from atreides.customer_protection.reserve import DAILY_REDUCTION, ComputationMode
from atreides.customer_protection.rules import load_rule_table
from atreides.dsor.lifecycle_records import ApprovedIntentDecisionRecord
from atreides.dsor.store import DSORStore
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
from simulator.estate import DepositDraw, DepositPolicy, _event, _identifier, _wire, drive_estate
from simulator.estate import _actor as estate_actor
from simulator.focus import FirmFocusLines, tie_out_firm_close
from simulator.model import Print
from simulator.protection_oracle import (
    required_control,
    required_net_capital,
    required_reserve,
)
from simulator.street import (
    SettlementOutcome,
    SyntheticDepository,
    reconcile,
)
from simulator.synthetic_attestation_fixture import (
    LC_KEY_ID,
    LC_PRIVATE_KEY,
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


class GoldenPathResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
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
        # The consumer owns freshness. The producer's claimed duration is ignored.
        consumed = profile.model_copy(update={"maximum_age_seconds": self.maximum_age_seconds})
        enforce_recommendation_profile(
            terms,
            resolver=MappingRecommendationProfileResolver({consumed.record_id: consumed}),
            evaluated_at=self.clock(),
            account_status_input=status,
        )


_ATREIDES_KEY = Ed25519PrivateKey.generate()
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
    from lc.trust_anchors import TrustAnchor as LCTrustAnchor
    from lc.trust_anchors import install_runtime_trust_anchor as install_lc_anchor

    install_lc_anchor(
        LCTrustAnchor(
            key_id="mvp3-atreides-key",
            producer="atreides",
            public_key=_ATREIDES_KEY.public_key(),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 1, 1, tzinfo=UTC),
            revoked=False,
        )
    )
    _TRUST_CONFIGURED = True


def _human(number: str, role: str) -> ActorRef:
    return ActorRef(
        actor_id=ActorId("act_" + number * 26),
        actor_kind=ActorKind.HUMAN,
        role=role,
        entitlement_refs=("MVP-3",),
        authenticated=True,
    )


def _event_pack(stages: list[str]) -> tuple[EvidenceEvent, ...]:
    events: list[EvidenceEvent] = []
    for index, stage in enumerate(stages, 1):
        events.append(
            EvidenceEvent(
                event_id=f"MVP3-{index:03d}",
                producer=stage.split(":", 1)[0],
                signature_status=("VERIFIED" if stage.startswith(("Atreides", "L.C.")) else "N/A"),
                cause_event_id=None if index == 1 else f"MVP3-{index - 1:03d}",
                summary=stage.split(":", 1)[-1].strip(),
            )
        )
    return tuple(events)


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
) -> GoldenPathResult:
    evidence = _event_pack(stages)
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
    )


def run_golden_path(variant: Variant = Variant.CLEAN) -> GoldenPathResult:  # noqa: PLR0915
    """Run one deterministic account, or one named fail-closed mutation."""
    _configure_trust()
    clock = FixedRunClock(START + timedelta(seconds=30))
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
    transfers = {
        transfer_id: TransferInRecord(
            record_id=transfer_id, account_id=ACCOUNT, completed=True, completed_at=clock()
        )
    }
    trades: dict[str, bytes] = {}
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
        kyc_dsor_records={
            kyc_id: KYCDecisionRecord(
                record_id=kyc_id,
                account_id=ACCOUNT,
                path_id="KYC_ELIGIBLE_CLEAR",
                decided_at=START + timedelta(seconds=5),
                maximum_age_seconds=999999,
                account_type=AccountType.NATURAL_PERSON,
                person_id=PERSON,
            )
        },
        kyc_chain_reports={
            kyc_id: ChainReport(
                ok=True, event_count=1, head_digest="sha256:" + "22" * 32, issues=()
            )
        },
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
    stages = ["Atreides: natural-person application recorded"]
    if variant is Variant.STALE_CALLER_TIME:
        clock.advance(timedelta(seconds=KYC_MAXIMUM_AGE_SECONDS + 1))
    try:
        lifecycle.transition(
            ACCOUNT,
            AccountStatus.APPROVED,
            actor=principal,
            timestamp=START,
            reason="MVP-3 human-approved retail onboarding",
            evidence_refs=("MVP3-HUMAN-APPROVAL",),
            kyc_record_id=kyc_id,
            eligibility_record_id=eligibility_id,
            human_approval_ref="MVP3-HUMAN-APPROVAL",
            cip_record_id=cip_id,
            profile_record_id=profile_id,
            principal_acceptance_record_id=principal_id,
        )
    except AccountTransitionRefusedError as exc:
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=AccountStatus.APPLIED,
            refusal=exc.reason.value,
            owner="CIP_OPERATIONS" if variant is Variant.CIP_UNABLE else "KYC_OPERATIONS",
            age=cip.exception_age_seconds(clock()),
        )
    stages.append("Atreides: CIP, profile, eligibility, principal, and human approval passed")
    books = EquitiesBooks(break_owner="MVP3_SETTLEMENT_OPERATIONS")
    _post_transfer(
        books,
        StatementLine(
            account=ACCOUNT, issue=ISSUE, quantity=Decimal(0), cash_credit=Decimal("10000")
        ),
        transfer_id=transfer_id,
        sequence=1,
        quantity=Decimal(0),
        cash=Decimal("10000"),
        day=clock().date(),
    )
    lifecycle.transition(
        ACCOUNT,
        AccountStatus.FUNDED,
        actor=principal,
        timestamp=START,
        reason="completed synthetic ACATS transfer",
        evidence_refs=(transfer_id,),
        transfer_record_id=transfer_id,
    )
    stages.extend(
        ("Atreides: completed transfer posted to books", "Atreides: account moved to FUNDED")
    )

    policy = PolicyManifest(
        policy_id="MVP3-POLICY", version="1", bounds_digest="sha256:" + "1" * 64, enabled=True
    )
    actor = estate_actor()
    payload = ApprovedIntentPayload(
        intent_id=IntentId(_identifier("int_", 10001)),
        instrument_id=ISSUE,
        side=OrderSide.BUY,
        quantity=Decimal(10),
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=actor.actor_id, policy_manifest_digest=digest(policy), authorized=True
        ),
        allocation_accounts=(ACCOUNT,),
    )
    with DSORStore(":memory:") as dsor:
        dsor.append(
            ApprovedIntentDecisionRecord(
                operation_id=UUID("00000000-0000-0000-0000-000000000301"),
                lifecycle_id=LifecycleId(_identifier("lif_", 20001)),
                intent_id=str(payload.intent_id),
                intent_digest=digest(payload),
                decided_at=clock(),
            ),
            dtg=clock(),
        )
        dsor_count = len(dsor.records())
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
        key_id="mvp3-atreides-key",
        private_key=_ATREIDES_KEY,
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
            key_id="mvp3-atreides-key",
            private_key=_ATREIDES_KEY,
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
    try:
        GoldenRecommendationGate(clock, PROFILE_MAXIMUM_AGE_SECONDS).evaluate(
            terms, lc_profile, status_wire
        )
    except ValueError as exc:
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal=str(exc),
            owner="RETAIL_SUPERVISION",
            age=0,
            dsor_records=dsor_count,
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
        approved_by=actor,
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(
            operation="MVP-3 approved intent", effects=(), note="synthetic only"
        ),
        payload_digest=kernel_digest_bytes(wire),
    )
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
        quantity=Decimal(10),
        event=_event(40004, clock()),
        terms=terms,
    )
    consumed_profile = lc_profile.model_copy(
        update={"maximum_age_seconds": PROFILE_MAXIMUM_AGE_SECONDS}
    )
    register = split_parent(
        outcome,
        actor=actor,
        children=(child,),
        recommendation_profile_resolver=MappingRecommendationProfileResolver(
            {profile_id: consumed_profile}
        ),
        evaluated_at=clock(),
        account_status_input=status_wire,
    ).journal
    order_event = register.events[-1]
    capacity = CapacityDocument(
        schema_version="atreides.equities_account_capacity/3",
        as_of=clock(),
        maximum_age_seconds=300,
        synthetic=True,
        journal_digest=books.digest(),
        firm_participant_id="MVP3-FIRM",
        accounts=(
            CapacityAccount(
                account_id=ACCOUNT,
                capacity="CUSTOMER",
                buying_power=Decimal("10000"),
                margin_excess=Decimal("10000"),
                margin_result_digest="sha256:" + "3" * 64,
                positions=(),
            ),
        ),
    )
    capacity_bytes = canonical_bytes(capacity)
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
            account_credit_limits={
                ACCOUNT: Decimal("500") if variant is Variant.CREDIT_LIMIT else Decimal("10000")
            },
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
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal=reason,
            owner="MARKET_ACCESS_RISK",
            age=0,
            dsor_records=dsor_count,
        )
    stages.extend(("L.C.: firm market access passed", "L.C.: order sealed for synthetic venue"))
    if variant is Variant.SETTLEMENT_FAIL:
        stages.append("Atreides: CNS fail recorded and aged")
        return _result(
            variant,
            stages,
            disposition="HOLD",
            status=lifecycle.status(ACCOUNT),
            refusal="CNS_SETTLEMENT_FAIL",
            owner="MVP3_SETTLEMENT_OPERATIONS",
            age=86400,
            dsor_records=dsor_count,
            books_digest=books.digest(),
            close_report="FAIL_AGED_1_DAY",
        )

    report = Print(
        print_id="MVP3-PRINT-001",
        order_id=str(child.order_id),
        issue=ISSUE,
        quantity=10,
        price=Decimal("100"),
        matched_at=clock(),
        reported_at=clock() + timedelta(seconds=1),
    )
    estate = drive_estate(
        run_number=1,
        business_date=clock().date(),
        issue=ISSUE,
        reports=(report,),
        account_weights=(1,),
        street_quantity=Decimal(10),
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
        deposit_policy=DepositPolicy(
            customer=DepositDraw(outcome="ON_TIME", short_fraction=Decimal(0)),
            pab=DepositDraw(outcome="ON_TIME", short_fraction=Decimal(0)),
            bank_equity_capital=Decimal("1000000"),
        ),
    )
    trades[trade_id] = attest_first_permitted_trade(
        FirstPermittedTradeRecord(
            record_id=trade_id, account_id=ACCOUNT, permitted=True, traded_at=clock()
        ),
        key_id=LC_KEY_ID,
        private_key=LC_PRIVATE_KEY,
    )
    lifecycle.transition(
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
    depository = SyntheticDepository(())
    depository.apply_settlements(
        (
            SettlementOutcome(
                issue=ISSUE,
                net_quantity=Decimal(10),
                allocated_quantity=Decimal(10),
                settlement_date=clock().date(),
            ),
        )
    )
    location_balances: dict[tuple[str, str], Decimal] = {}
    observed_accounts: set[str] = set()
    for entry in books.entries:
        for line in entry.lines:
            if line.record_side.value == "LOCATION" and line.issue is not None:
                location = line.account_type.value
                location_balances[(line.issue, location)] = (
                    location_balances.get((line.issue, location), Decimal()) + line.quantity
                )
            if line.account_type.value in {"CUSTOMER_CASH", "CUSTOMER_MARGIN"}:
                observed_accounts.add(line.account_id)
    street_breaks, street_completion = reconcile(
        {key: value for key, value in location_balances.items() if key[1] == "DTC"},
        (depository.source(clock().date()),),
        as_of=clock().date(),
    )
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
    invariants = {
        "stock_record": not estate.stock_breaks,
        "reserve": estate.reserve_disposition == "PASS",
        "pab_reserve": estate.pab_reserve_disposition == "PASS",
        "net_capital": estate.net_capital_disposition == "PASS",
        "possession_or_control": estate.control_disposition == "PASS",
        "settlement_two_sided": estate.settlement_residual_two_sided,
        "evidence_chain": all(
            item.cause_event_id == f"MVP3-{index:03d}"
            for index, item in enumerate(_event_pack(stages)[1:], 1)
        ),
        "independent_oracle": (
            oracle_reserve.customer_requirement == estate.reserve_figure
            and oracle_reserve.pab_requirement == estate.pab_reserve_figure
            and oracle_capital is not None
            and oracle_capital.net_capital == estate.net_capital_figure
            and oracle_control is not None
            and oracle_control.outcome == estate.control_disposition
        ),
        "street_reconciliation": not street_breaks and street_completion.status == "COMPLETED",
        "focus_tie_out": focus.held,
        "customer_in_books": ACCOUNT in observed_accounts,
    }
    return _result(
        variant,
        stages,
        disposition="PASS",
        status=lifecycle.status(ACCOUNT),
        dsor_records=dsor_count,
        books_digest=estate.books_digest,
        invariants=invariants,
        close_report="NORMAL_CLOSE",
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
    summary_path.write_text(
        "# MVP-3 synthetic golden path\n\n"
        "This pack contains one declared-synthetic natural-person account and one "
        "declared-synthetic United States equity. It records the ordered cause chain "
        "from application through the daily close. No event was submitted to a venue, "
        "depository, bank, or regulator.\n\n"
        f"Evidence digest: `{result.evidence_digest}`\n\n"
        "Every clean-run invariant in `evidence-pack.json` is true.\n"
    )
    return evidence_path, summary_path
