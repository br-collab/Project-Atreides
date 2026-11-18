"""SIM-1B adapter: supply generated facts to the real L.C. and Atreides APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes, canonical_bytes_of, digest, digest_bytes
from cannae_kernel.clocks import EventTimes
from cannae_kernel.effects import OperationEffects
from cannae_kernel.envelopes import ApprovedIntentEnvelope, ExecutionEvent
from cannae_kernel.ids import ActorId, AllocationId, EventId, IntentId, LifecycleId, OrderId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext
from cannae_kernel.signed_attestation import sign_attestation
from lc.events import OrderEvent, OrderTerms, OrderType, TimeInForce
from lc.lifecycle import (
    ApprovedIntentPayload,
    AuthorityManifest,
    ChildOrder,
    EventInput,
    LifecycleRegister,
    OrderSide,
    PolicyManifest,
    accept_intent,
    activate_parent,
    authorize_strategy,
    split_parent,
)
from lc.market_access import (
    AttestedInput,
    CapacityAccount,
    CapacityDocument,
    ChildRelease,
    LimitsManifest,
    MarketAccessGate,
    record_decision,
)
from lc.policy import ExecutionReport, apply_execution
from lc.trade import (
    AllocationPlan,
    AllocationRecord,
    AllocationRule,
    AllocationTarget,
    CaptureRecord,
    allocate,
    capture,
)

from atreides.account_lifecycle import (
    AccountType as LifecycleAccountType,
)
from atreides.account_lifecycle import (
    AccountTypeStatusDocument,
    AccountTypeStatusEntry,
)
from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
    ReserveActivity,
    ReserveSourceFact,
    StockRecordBreak,
)
from atreides.books.projections import (
    project_customer_protection,
    project_margin_accounts,
    reserve_bank_balances,
)
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    BankCashDeposit,
    ComputationMode,
    LineBalance,
    ReserveInputs,
    ReserveResult,
    compute_reserve,
    with_customer_excess_debits,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.customer_protection.rules.model import RuleTable
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from atreides.margin.engine import compute_margin
from atreides.rails.cns import (
    CloseOutRegime,
    MarketProfile,
    net_positions,
    settle_net_position,
)
from simulator.calibration import CalibrationPack
from simulator.market import allocate_largest_remainder
from simulator.model import Print
from simulator.synthetic_attestation_fixture import (
    LC_STATUS_KEY_ID,
    LC_STATUS_PRIVATE_KEY,
    configure_lc_status_trust,
)

#: SIM-1G deposit outcomes that leave the computation short at its deadline.
DEPOSIT_BREACH_OUTCOMES = frozenset({"SHORT", "LATE", "NOT_DECLARED_IN_PACK"})

_STATUS_TRUST_INSTALLED = False


@dataclass(frozen=True, slots=True)
class DepositDraw:
    """One computation's drawn deposit behaviour under the pack's SYNTHETIC policy.

    ``outcome`` is ON_TIME, SHORT or LATE. ``short_fraction`` is the share of the
    needed deposit left unpaid on a SHORT draw.
    """

    outcome: str
    short_fraction: Decimal


@dataclass(frozen=True, slots=True)
class DepositPolicy:
    """SIM-1G synthetic deposit policy for both reserve computations of one day."""

    customer: DepositDraw
    pab: DepositDraw
    #: Equity capital of the one synthetic non-affiliated reserve bank (Rule 15c3-3(e)(5) cap).
    bank_equity_capital: Decimal


@dataclass(frozen=True, slots=True)
class ReserveDeposit:
    """What the simulator did for one reserve computation, read back from the books."""

    computation: str
    opening_balance: Decimal
    requirement: Decimal | None
    needed: Decimal | None
    drawn_outcome: str
    outcome: str
    amount: Decimal
    deposit_date: date | None
    deadline: date
    balance_at_deadline: Decimal
    closing_balance: Decimal


@dataclass(frozen=True, slots=True)
class EstateResult:
    approved_intent: ApprovedIntentPayload
    lifecycle_events: tuple[OrderEvent, ...]
    capture_record: CaptureRecord
    allocation_record: AllocationRecord
    journal_entries: tuple[JournalEntry, ...]
    lifecycle_event_ids: tuple[str, ...]
    capture_id: str
    allocation_id: str
    journal_entry_ids: tuple[str, ...]
    captured_quantity: Decimal
    captured_money: Decimal
    allocated_quantity: Decimal
    allocated_money: Decimal
    books_quantity: Decimal
    books_money: Decimal
    stock_breaks: tuple[StockRecordBreak, ...]
    reserve_disposition: str
    pab_reserve_disposition: str
    net_capital_disposition: str
    control_disposition: str
    reserve_figure: Decimal | None
    pab_reserve_figure: Decimal | None
    net_capital_figure: Decimal | None
    control_figure: Decimal | None
    protection_reasons: dict[str, tuple[str, ...]]
    reserve_deposits: tuple[ReserveDeposit, ...]
    books_digest: str
    settled_quantity: Decimal
    settlement_residual_two_sided: bool
    customer_total_credits: Decimal
    customer_total_debits: Decimal
    pab_total_credits: Decimal
    pab_total_debits: Decimal
    control_shortfall_by_issue: tuple[tuple[str, Decimal | None], ...]


def _complete_reserve_inputs(
    projected: ReserveInputs,
    *,
    average_total_credits: Decimal | None,
    daily_requirement_effective_date: date | None,
    computation_mode: ComputationMode,
    previously_daily_required: bool,
    daily_exit_notice_date: date | None,
) -> ReserveInputs:
    """Turn complete activity and simulated filing-history evidence into reserve facts.

    17 CFR 240.15c3-3(e)(3)(i)(B)(1), pinned in the rule table:
    "For purposes of this paragraph (e)(3), average total credits means the arithmetic
    mean of the sum of Total Credits in the Customer Reserve Bank Account computation
    and the PAB Reserve Bank Account computation reported in the 12 most recently filed
    month-end Forms X-17A-5." This simulator's month-end book projections are explicitly
    a synthetic stand-in for those filed figures; they are not represented as filings.
    The same paragraph requires daily computations no later than six months after average
    total credits first equal or exceed $500 million.
    """
    reserve_lines = tuple(
        LineBalance(rule_id=line.rule_id, amount=line.amount or Decimal())
        for line in projected.lines
    )
    return projected.model_copy(
        update={
            "lines": reserve_lines,
            "average_total_credits": average_total_credits,
            "daily_requirement_effective_date": daily_requirement_effective_date,
            "previously_daily_required": previously_daily_required,
            "daily_exit_notice_date": daily_exit_notice_date,
            "mode": computation_mode,
            "qualified_securities_deposit": Decimal(),
        }
    )


def _identifier(prefix: str, value: int) -> str:
    return prefix + f"{value:026d}"


def _actor() -> ActorRef:
    return ActorRef(
        actor_id=ActorId(_identifier("act_", 71)),
        actor_kind=ActorKind.DETERMINISTIC_SERVICE,
        role="sim-1b-estate-adapter",
        entitlement_refs=("SIM-1B",),
        authenticated=True,
    )


def _approver() -> ActorRef:
    return ActorRef(
        actor_id=ActorId(_identifier("act_", 72)),
        actor_kind=ActorKind.HUMAN,
        role="sim-1b-synthetic-human-approver",
        entitlement_refs=("SIM-1B_APPROVER",),
        authenticated=True,
    )


def simulated_filed_credit_total(as_of: date, customer_credit: Decimal) -> tuple[Decimal, Decimal]:
    """Project a pre-run synthetic month-end through the real books seam.

    SIM-1E scope: this is a simulated stand-in for a month-end FOCUS figure,
    not a filed report. The returned values are the customer and PAB Exhibit A
    total credits produced by ``project_customer_protection``.
    """
    actor = _actor()
    base = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
    books = EquitiesBooks(break_owner="SIM_SETTLEMENT_OPS")
    source_event_id = _identifier("evt_", 90_000 + as_of.toordinal())
    books.post(
        JournalEntry(
            entry_id=f"SIM-1E-PREHISTORY-{as_of.isoformat()}",
            source_event_id=source_event_id,
            source=PostingSource.CASH_MOVEMENT,
            effective_date=as_of,
            effective_date_basis="VALUE_DATE",
            authority="SIM-1E_SYNTHETIC_FOCUS_STAND_IN",
            lines=(
                LedgerLine(
                    account_id="CUSTOMER-PREHISTORY-CREDIT",
                    account_type=AccountType.CUSTOMER_CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=customer_credit,
                ),
                LedgerLine(
                    account_id="PREHISTORY-FUNDING",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-customer_credit,
                ),
            ),
            posting=BooksPosting(
                posted_record_id=f"SIM-1E-PREHISTORY-{as_of.isoformat()}",
                posting_authority=actor,
                effective_time=base,
                source_event_id=EventId(source_event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )
    projected = project_customer_protection(
        books,
        as_of=as_of,
        prices={},
        net_worth=Decimal("1000000"),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=(),
    )

    def total(inputs: ReserveInputs) -> Decimal:
        return sum(
            (
                line.amount or Decimal()
                for line in inputs.lines
                if line.rule_id in EXHIBIT_A_CREDITS
            ),
            Decimal(),
        )

    return total(projected.reserve), total(projected.pab_reserve)


def _event(number: int, at: datetime) -> EventInput:
    when = at + timedelta(microseconds=number)
    return EventInput(
        event_id=EventId(_identifier("evt_", number)),
        times=EventTimes(
            event_time=when,
            observation_time=when,
            processing_time=when,
            decision_time=when,
        ),
        idempotency_key=f"sim-1b-{number}",
    )


def _wire(payload: ApprovedIntentPayload) -> bytes:
    return canonical_bytes_of(
        {
            "schema_version": "aureon.approved_intent/0.1-draft",
            "intent": {
                "instrument_id": payload.instrument_id,
                "side": payload.side,
                "quantity": {"basis": "QUANTITY", "quantity": str(payload.quantity)},
            },
            "policy_manifest": {
                "disposition": "PASS",
                "policy_record_id": payload.policy_manifest.policy_id,
                "rule_set_version": payload.policy_manifest.version,
                "rules_digest": payload.policy_manifest.bounds_digest,
            },
            "authority_manifest": {
                "quorum_met": payload.authority_manifest.authorized,
                "authority_id": payload.authority_manifest.authority_id,
            },
            "allocation_accounts": payload.allocation_accounts,
        }
    )


def validate_approval_provenance(envelope: ApprovedIntentEnvelope) -> None:
    """Refuse human-judgment provenance unless the approver is a verified human."""
    if envelope.provenance is Provenance.HUMAN_JUDGMENT and (
        envelope.approved_by.actor_kind is not ActorKind.HUMAN
        or not envelope.approved_by.authenticated
    ):
        raise ValueError("HUMAN_JUDGMENT requires an authenticated HUMAN approved_by actor")


def seed_customer_cash(
    books: EquitiesBooks,
    *,
    run_number: int,
    business_date: date,
    accounts: tuple[str, ...],
    account_weights: tuple[int, ...],
    balance: Decimal,
) -> None:
    """Post the declared synthetic customer cash that the market-access gate reads."""
    if not balance:
        return
    actor = _actor()
    base = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    credit_event_id = _identifier("evt_", 70_000 + run_number)
    credit_cents = int((balance * Decimal(100)).to_integral_exact())
    allocations = allocate_largest_remainder(abs(credit_cents), account_weights)
    sign = Decimal(1 if credit_cents >= 0 else -1)
    customer_lines = tuple(
        LedgerLine(
            account_id=account,
            account_type=AccountType.CUSTOMER_CASH,
            record_side=RecordSide.MONEY,
            currency="USD",
            money=sign * Decimal(cents) / Decimal(100),
        )
        for account, cents in zip(accounts, allocations, strict=True)
    )
    books.post(
        JournalEntry(
            entry_id=f"SIM-1D-CREDIT-{run_number}",
            source_event_id=credit_event_id,
            source=PostingSource.CASH_MOVEMENT,
            effective_date=business_date,
            effective_date_basis="VALUE_DATE",
            authority="SIM-1D_SYNTHETIC_CUSTOMER_ACTIVITY",
            lines=(
                *customer_lines,
                LedgerLine(
                    account_id="SYNTHETIC_CUSTOMER_CREDIT_FUNDING",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-balance,
                ),
            ),
            posting=BooksPosting(
                posted_record_id=f"SIM-1D-CREDIT-{run_number}",
                posting_authority=actor,
                effective_time=base,
                source_event_id=EventId(credit_event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )


def _customer_cash_capacity(books: EquitiesBooks, account: str) -> Decimal:
    return sum(
        (
            line.money
            for entry in books.entries
            for line in entry.lines
            if line.account_id == account
            and line.account_type is AccountType.CUSTOMER_CASH
            and line.record_side is RecordSide.MONEY
            and line.money is not None
        ),
        Decimal(),
    )


def cash_account_purchase_lines(
    *, account_id: str, issue: str, quantity: Decimal, consideration: Decimal
) -> tuple[LedgerLine, LedgerLine]:
    """Post a cash-account buy: securities in and free cash down by consideration."""
    return (
        LedgerLine(
            account_id=account_id,
            account_type=AccountType.CUSTOMER_CASH,
            record_side=RecordSide.OWNERSHIP,
            issue=issue,
            quantity=quantity,
        ),
        LedgerLine(
            account_id=account_id,
            account_type=AccountType.CUSTOMER_CASH,
            record_side=RecordSide.MONEY,
            currency="USD",
            money=-consideration,
        ),
    )


def exercise_simulator_market_access(
    *,
    run_number: int,
    business_date: date,
    issue: str,
    reports: tuple[Print, ...],
    account_weights: tuple[int, ...],
    prior_close: Decimal,
    pack: CalibrationPack,
    books: EquitiesBooks,
) -> tuple[ApprovedIntentPayload, LifecycleRegister]:
    """Build the SIM-1B register and record its real market-access decision."""
    global _STATUS_TRUST_INSTALLED  # noqa: PLW0603 - process-local composition root
    actor = _actor()
    base = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    total_quantity = sum((Decimal(item.quantity) for item in reports), Decimal())
    accounts = tuple(f"ACCOUNT-{index + 1}" for index in range(len(account_weights)))
    policy = PolicyManifest(
        policy_id="sim-1b-generated-day",
        version="1",
        bounds_digest="sha256:" + "1" * 64,
        enabled=True,
    )
    payload = ApprovedIntentPayload(
        intent_id=IntentId(_identifier("int_", 10_000 + run_number)),
        instrument_id=issue,
        side=OrderSide.BUY,
        quantity=total_quantity,
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=_approver().actor_id,
            policy_manifest_digest=digest(policy),
            authorized=True,
        ),
        allocation_accounts=accounts,
    )
    envelope = ApprovedIntentEnvelope(
        envelope_id=payload.intent_id,
        lifecycle_id=LifecycleId(_identifier("lif_", 20_000 + run_number)),
        revision=1,
        prior_digest=None,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=business_date,
                calendar="SIFMA-US",
                established_by="SIM-1B generated day",
            ),
        ),
        approved_by=_approver(),
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(
            operation="simulate approved intent",
            effects=(),
            note="synthetic input only; no submission capability",
        ),
        payload_digest=digest_bytes(_wire(payload)),
    )
    validate_approval_provenance(envelope)
    parent_id = OrderId(_identifier("ord_", 30_000 + run_number * 2))
    child_id = OrderId(_identifier("ord_", 30_001 + run_number * 2))
    outcome = accept_intent(
        envelope,
        _wire(payload),
        parent_order_id=parent_id,
        actor=actor,
        event=_event(40_000 + run_number * 20, base),
    )
    outcome = authorize_strategy(outcome, actor=actor, event=_event(40_001 + run_number * 20, base))
    outcome = activate_parent(outcome, actor=actor, event=_event(40_002 + run_number * 20, base))
    register = split_parent(
        outcome,
        actor=actor,
        children=(
            ChildOrder(
                order_id=child_id,
                quantity=total_quantity,
                event=_event(40_003 + run_number * 20, base),
                terms=OrderTerms(
                    account_id=accounts[0],
                    strategy_id="SIM-1B",
                    issue=issue,
                    side=payload.side.value,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    control_price=prior_close,
                    approved_intent_digest=digest(payload),
                    policy_expires_at=base + timedelta(days=1),
                    recommended=False,
                ),
            ),
        ),
    ).journal
    if not _STATUS_TRUST_INSTALLED:
        try:
            configure_lc_status_trust()
        except RuntimeError:
            # Another synthetic path installed this exact process-local fixture.
            pass
        _STATUS_TRUST_INSTALLED = True
    status = AccountTypeStatusDocument(
        as_of=base,
        maximum_age_seconds=300,
        accounts=tuple(
            AccountTypeStatusEntry(
                account_id=account,
                account_type=LifecycleAccountType.NATURAL_PERSON,
                status=AccountStatus.ACTIVE,
                last_event_id=str(register.events[-1].event_id),
            )
            for account in accounts
        ),
    )
    status_wire = sign_attestation(
        canonical_bytes(status),
        producer="atreides",
        key_id=LC_STATUS_KEY_ID,
        private_key=LC_STATUS_PRIVATE_KEY,
    )
    capacity = CapacityDocument(
        schema_version="atreides.equities_account_capacity/3",
        as_of=base,
        maximum_age_seconds=300,
        synthetic=True,
        journal_digest=books.digest(),
        firm_participant_id="SIM-1B-FIRM",
        accounts=tuple(
            CapacityAccount(
                account_id=account,
                capacity="CUSTOMER",
                buying_power=_customer_cash_capacity(books, account),
                margin_excess=_customer_cash_capacity(books, account),
                margin_result_digest=books.digest(),
                positions=(),
            )
            for account in accounts
        ),
    )
    capacity_wire = canonical_bytes(capacity)
    maximum_quantity = Decimal(str(pack.value("generator", "quantity_max"))) + Decimal(2) * Decimal(
        str(pack.value("generator", "auction_quantity_each"))
    )
    maximum_notional = maximum_quantity * Decimal(str(pack.value("market", "cns_prior_close")))
    account_credit_limit = Decimal(str(pack.value("generator", "customer_credit_max")))
    decision = MarketAccessGate().evaluate(
        ChildRelease(
            order_event=register.events[-1],
            lifecycle_register=register,
            reference_price=prior_close,
            submitted_at=base,
        ),
        limits=LimitsManifest(
            version="SIM-1B-1",
            authority="SIM-1B-RISK",
            account_credit_limits={account: account_credit_limit for account in accounts},
            firm_aggregate_threshold=account_credit_limit,
            price_collar_percent=Decimal("0.10"),
            maximum_quantity=maximum_quantity,
            maximum_notional=maximum_notional,
            duplicate_window_seconds=60,
        ),
        capacity_input=AttestedInput(
            payload=capacity_wire,
            payload_digest=digest_bytes(capacity_wire),
        ),
        locates_input=None,
        account_status_input=status_wire,
    )
    if decision.terminal:
        reason = next(item.reason for item in decision.checks if not item.passed)
        raise ValueError(f"SIM-1B market access refused: {reason}")
    return payload, record_decision(
        register,
        decision,
        actor=actor,
        event=_event(40_004 + run_number * 20, base),
    )


def drive_estate(  # noqa: PLR0915 - intentionally drives the end-to-end estate path
    *,
    run_number: int,
    business_date: date,
    issue: str,
    reports: tuple[Print, ...],
    account_weights: tuple[int, ...],
    street_quantity: Decimal,
    prior_close: Decimal,
    protection_inputs_missing: bool,
    customer_credit_balance: Decimal,
    average_total_credits: Decimal | None,
    daily_requirement_effective_date: date | None,
    computation_mode: ComputationMode,
    previously_daily_required: bool,
    daily_exit_notice_date: date | None,
    financing_charge: Decimal | None,
    post_financing: bool = True,
    pab_fail_to_receive: tuple[Decimal, Decimal] | None = None,
    reserve_bank_opening: tuple[Decimal, Decimal] = (Decimal(0), Decimal(0)),
    deposit_policy: DepositPolicy | None = None,
    account_ids: tuple[str, ...] | None = None,
    books: EquitiesBooks | None = None,
    source_event_id: str | None = None,
    settlement_fail_id: str | None = None,
    approved_payload: ApprovedIntentPayload | None = None,
    approved_register: LifecycleRegister | None = None,
    source_execution_event_id: str | None = None,
) -> EstateResult:
    """Drive L.C. then Atreides; checks elsewhere only compare their outputs.

    SIM-1 v0.2: "Simulated venue reports pass through the real L.C. capture and
    allocation and the real Atreides ... stock record, reserve and gate code."
    """
    actor = _actor()
    base = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    total_quantity = sum((Decimal(item.quantity) for item in reports), Decimal())
    policy = PolicyManifest(
        policy_id="sim-1b-generated-day",
        version="1",
        bounds_digest="sha256:" + "1" * 64,
        enabled=True,
    )
    allocation_accounts = account_ids or tuple(
        f"ACCOUNT-{i + 1}" for i in range(len(account_weights))
    )
    if len(allocation_accounts) != len(account_weights):
        raise ValueError("account_ids and account_weights must have equal length")
    payload = approved_payload or ApprovedIntentPayload(
        intent_id=IntentId(_identifier("int_", 10_000 + run_number)),
        instrument_id=issue,
        side=OrderSide.BUY,
        quantity=total_quantity,
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=_approver().actor_id,
            policy_manifest_digest=digest(policy),
            authorized=True,
        ),
        allocation_accounts=allocation_accounts,
        source_event_id=source_event_id,
    )
    wire = _wire(payload)
    lifecycle_id = LifecycleId(_identifier("lif_", 20_000 + run_number))
    envelope = ApprovedIntentEnvelope(
        envelope_id=payload.intent_id,
        lifecycle_id=lifecycle_id,
        revision=1,
        prior_digest=None,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=business_date,
                calendar="SIFMA-US",
                established_by="SIM-1B generated day",
            ),
        ),
        approved_by=_approver(),
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(
            operation="simulate approved intent",
            effects=(),
            note="synthetic input only; no submission capability",
        ),
        payload_digest=digest_bytes(wire),
    )
    validate_approval_provenance(envelope)
    if approved_register is None:
        raise ValueError("customer booking requires the register accepted by MarketAccessGate")
    register = approved_register
    child_id = OrderId(_identifier("ord_", 30_001 + run_number * 2))
    lc_reports = tuple(
        ExecutionReport(
            execution_id=f"{run_number}-{index}-{item.print_id}",
            order_id=child_id,
            intent_id=payload.intent_id,
            venue="VENUE-SYNTHETIC",
            quantity=Decimal(item.quantity),
            price=item.price,
            outcome="FILL" if index == len(reports) - 1 else "PARTIAL_FILL",
        )
        for index, item in enumerate(reports)
    )
    for index, report in enumerate(lc_reports):
        event_time = reports[index].matched_at
        execution = ExecutionEvent(
            event_id=EventId(_identifier("evt_", 70_000 + run_number * 20 + index)),
            lifecycle_id=lifecycle_id,
            intent_id=payload.intent_id,
            intent_digest=digest(payload),
            times=EventTimes(
                event_time=event_time,
                observation_time=reports[index].reported_at,
                processing_time=reports[index].reported_at,
                decision_time=None,
            ),
            session=envelope.session,
            provenance=Provenance.FACT_SYNTHETIC,
            payload_digest=digest(report),
        )
        applied = apply_execution(
            register,
            execution,
            report,
            actor=actor,
            event=_event(40_005 + run_number * 20 + index, base),
        )
        register = applied.journal
    register, captured = capture(
        register,
        lc_reports,
        payload,
        actor=actor,
        event=_event(40_012 + run_number * 20, base),
    )
    targets = tuple(
        AllocationTarget(
            account=allocation_accounts[index],
            target_quantity=Decimal(weight) * total_quantity,
        )
        for index, weight in enumerate(account_weights)
    )
    register, allocation = allocate(
        register,
        captured,
        payload,
        allocation_id=AllocationId(_identifier("alc_", 50_000 + run_number)),
        actor=actor,
        event=_event(40_013 + run_number * 20, base),
        plan=AllocationPlan(
            targets=targets,
            rule=AllocationRule.PRO_RATA,
            rounding_method="LARGEST_REMAINDER",
        ),
    )
    if books is None:
        books = EquitiesBooks(break_owner="SIM_SETTLEMENT_OPS")
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    net_position = net_positions(
        ((issue, total_quantity),),
        market_id="NSCC_SYNTHETIC",
        settlement_date_offset_days=1,
    )[0]
    signed_cash = (total_quantity * prior_close).quantize(Decimal("0.01"))
    allocated_cash = (street_quantity * prior_close).quantize(Decimal("0.01"))
    settlement_date = calendar.add_business_days(
        business_date, net_position.settlement_date_offset_days
    )
    settlement = settle_net_position(
        net_position,
        MarketProfile(
            market_id="NSCC_SYNTHETIC",
            settlement_cycle_days=1,
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            close_out_deadline_days=3,
            allocation_rule_published=True,
            provenance="SIM-1B synthetic market profile",
        ),
        allocated_quantity=street_quantity,
        signed_cash=signed_cash,
        allocated_cash=allocated_cash,
        settlement_date=settlement_date,
        as_of_date=business_date,
        calendar=calendar,
    )
    trade_lines: list[LedgerLine] = []
    for entry in allocation.entries:
        trade_lines.extend(
            cash_account_purchase_lines(
                account_id=entry.account,
                issue=issue,
                quantity=entry.quantity,
                consideration=entry.consideration,
            )
        )
    trade_lines.extend(
        (
            LedgerLine(
                account_id="PENDING_SETTLEMENT",
                account_type=AccountType.PENDING_SETTLEMENT,
                record_side=RecordSide.LOCATION,
                issue=issue,
                quantity=-allocation.executed_quantity,
            ),
            LedgerLine(
                account_id="CLEARING_PAYABLE",
                account_type=AccountType.CLEARING_PAYABLE,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=allocation.executed_consideration,
            ),
        )
    )
    location_account_type = (
        AccountType.FAIL_TO_RECEIVE if settlement_fail_id is not None else AccountType.DTC
    )
    location_account_id = "NSCC_FAIL_TO_RECEIVE" if settlement_fail_id is not None else "DTC"
    settlement_lines = [
        LedgerLine(
            account_id="PENDING_SETTLEMENT",
            account_type=AccountType.PENDING_SETTLEMENT,
            record_side=RecordSide.LOCATION,
            issue=issue,
            quantity=allocation.executed_quantity,
        ),
        LedgerLine(
            account_id="CLEARING_PAYABLE",
            account_type=AccountType.CLEARING_PAYABLE,
            record_side=RecordSide.MONEY,
            currency="USD",
            money=-allocation.executed_consideration,
        ),
    ]
    settlement_lines.extend(
        (
            LedgerLine(
                account_id=location_account_id,
                account_type=location_account_type,
                record_side=RecordSide.LOCATION,
                issue=issue,
                quantity=-allocation.executed_quantity,
            ),
            LedgerLine(
                account_id="CLEARING",
                account_type=AccountType.CASH,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=allocation.executed_consideration,
            ),
        )
    )
    settlement_source_event_id = source_execution_event_id or str(register.events[-1].event_id)
    reserve_source_facts: tuple[ReserveSourceFact, ...] = ()
    if settlement_fail_id is not None:
        reserve_source_facts = (
            ReserveSourceFact(
                account_type=AccountType.FAIL_TO_RECEIVE,
                issue=issue,
                activity=ReserveActivity.CUSTOMER,
                settlement_date=settlement_date,
                contract_price=prior_close,
                fail_id=settlement_fail_id,
            ),
        )
    books.post(
        JournalEntry(
            entry_id=f"SIM-1B-{run_number}",
            source_event_id=settlement_source_event_id,
            source=PostingSource.ALLOCATION,
            effective_date=business_date,
            effective_date_basis="TRADE_DATE",
            authority="NSCC_SYNTHETIC",
            lines=tuple(trade_lines),
            posting=BooksPosting(
                posted_record_id=f"SIM-1B-{run_number}",
                posting_authority=actor,
                effective_time=base,
                source_event_id=EventId(settlement_source_event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
        )
    )
    settlement_event_id = _identifier("evt_", 90_000_000 + run_number)
    books.post(
        JournalEntry(
            entry_id=f"SIM-1B-SETTLEMENT-{run_number}",
            source_event_id=settlement_event_id,
            source=(
                PostingSource.CNS_FAIL
                if settlement_fail_id is not None
                else PostingSource.CNS_SETTLEMENT
            ),
            effective_date=settlement_date,
            effective_date_basis="SETTLEMENT_DATE",
            authority="NSCC_SYNTHETIC",
            lines=tuple(settlement_lines),
            reserve_source_facts=reserve_source_facts,
            posting=BooksPosting(
                posted_record_id=f"SIM-1B-SETTLEMENT-{run_number}",
                posting_authority=actor,
                effective_time=datetime.combine(settlement_date, datetime.min.time(), tzinfo=UTC),
                source_event_id=EventId(settlement_event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
        )
    )
    seed_customer_cash(
        books,
        run_number=run_number,
        business_date=business_date,
        accounts=allocation_accounts,
        account_weights=account_weights,
        balance=customer_credit_balance,
    )
    if financing_charge not in {None, Decimal()} and post_financing:
        financing_event_id = _identifier("evt_", 80_000 + run_number)
        books.post(
            JournalEntry(
                entry_id=f"SIM-1D-FINANCING-{run_number}",
                source_event_id=financing_event_id,
                source=PostingSource.MARGIN_INTEREST,
                effective_date=business_date,
                effective_date_basis="VALUE_DATE",
                authority="SIM-1D_SYNTHETIC_FINANCING",
                lines=(
                    LedgerLine(
                        account_id="SYNTHETIC_FINANCING_EXPENSE",
                        account_type=AccountType.FIRM_PROPRIETARY,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=financing_charge,
                    ),
                    LedgerLine(
                        account_id="SYNTHETIC_FINANCING_CASH",
                        account_type=AccountType.CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=-financing_charge,
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id=f"SIM-1D-FINANCING-{run_number}",
                    posting_authority=actor,
                    effective_time=base,
                    source_event_id=EventId(financing_event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )
    if pab_fail_to_receive is not None:
        # CLOSE-1 WP5: a synthetic correspondent broker-dealer (PAB account) purchase
        # that fails to receive. Exhibit A item 4 is a credit in the PAB computation
        # when the source activity is PAB; the real projection routes it
        # (atreides/books/projections.py). Posted on its own synthetic issue as a
        # location-only pair, so the trade issue's stock record is untouched.
        pab_quantity, pab_price = pab_fail_to_receive
        pab_issue = f"SYN-PAB-{run_number}"
        pab_event_id = _identifier("evt_", 300_000_000 + run_number)
        books.post(
            JournalEntry(
                entry_id=f"CLOSE-1-PAB-FTR-{run_number}",
                source_event_id=pab_event_id,
                source=PostingSource.CNS_FAIL,
                effective_date=business_date,
                effective_date_basis="SETTLEMENT_DATE",
                authority="CLOSE-1_SYNTHETIC_PAB_CORRESPONDENT",
                lines=(
                    LedgerLine(
                        account_id="PAB-CORRESPONDENT-FAIL_TO_RECEIVE",
                        account_type=AccountType.FAIL_TO_RECEIVE,
                        record_side=RecordSide.LOCATION,
                        issue=pab_issue,
                        quantity=pab_quantity,
                    ),
                    LedgerLine(
                        account_id="DTC",
                        account_type=AccountType.DTC,
                        record_side=RecordSide.LOCATION,
                        issue=pab_issue,
                        quantity=-pab_quantity,
                    ),
                ),
                reserve_source_facts=(
                    ReserveSourceFact(
                        account_type=AccountType.FAIL_TO_RECEIVE,
                        issue=pab_issue,
                        activity=ReserveActivity.PAB,
                        settlement_date=business_date,
                        contract_price=pab_price,
                        fail_id=f"CLOSE-1-PAB-FTR-{run_number}",
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id=f"CLOSE-1-PAB-FTR-{run_number}",
                    posting_authority=actor,
                    effective_time=base,
                    source_event_id=EventId(pab_event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )
    stock_breaks = books.verify_stock_record(
        observed_locations={issue: settlement.allocated_quantity}
    )
    margin_results = tuple(
        compute_margin(
            account,
            trade_date=business_date,
            calendar=calendar,
            house_maintenance_rate=Decimal("0.30"),
            maintenance_call_due_business_days=2,
        )
        for account in project_margin_accounts(books, prices={issue: prior_close})
    )
    projected = project_customer_protection(
        books,
        as_of=business_date,
        prices={issue: prior_close},
        net_worth=Decimal("1000000"),
        calendar=calendar,
        margin_results=margin_results,
    )
    pab_reserve_inputs = _complete_reserve_inputs(
        projected.pab_reserve,
        average_total_credits=average_total_credits,
        daily_requirement_effective_date=daily_requirement_effective_date,
        computation_mode=computation_mode,
        previously_daily_required=previously_daily_required,
        daily_exit_notice_date=daily_exit_notice_date,
    )
    # A generated normal day describes the complete synthetic activity set. Lines
    # absent from that set are observed zeroes, not invented regulatory defaults.
    reserve_inputs = _complete_reserve_inputs(
        projected.reserve,
        average_total_credits=average_total_credits,
        daily_requirement_effective_date=daily_requirement_effective_date,
        computation_mode=computation_mode,
        previously_daily_required=previously_daily_required,
        daily_exit_notice_date=daily_exit_notice_date,
    )
    net_capital_inputs = projected.net_capital.model_copy(
        update={
            "reports_lending_activity_monthly": False,
            "securities_loaned_and_repo_payable": Decimal(),
            "securities_borrowed_and_reverse_repo_value": Decimal(),
        }
    )
    control_inputs = projected.control
    if protection_inputs_missing:
        reserve_inputs = reserve_inputs.model_copy(
            update={
                "lines": (
                    reserve_inputs.lines[0].model_copy(update={"amount": None}),
                    *reserve_inputs.lines[1:],
                )
            }
        )
        pab_reserve_inputs = pab_reserve_inputs.model_copy(
            update={
                "lines": (
                    pab_reserve_inputs.lines[0].model_copy(update={"amount": None}),
                    *pab_reserve_inputs.lines[1:],
                )
            }
        )
        net_capital_inputs = net_capital_inputs.model_copy(update={"net_worth": None})
        control_inputs = control_inputs.model_copy(
            update={
                "issues": tuple(
                    item.model_copy(update={"fully_paid": None}) for item in control_inputs.issues
                )
            }
        )
    rules = load_rule_table()
    reserve = compute_reserve(reserve_inputs, rules)
    # Rule 15c3-3(e)(4): the PAB computation is run with the same-date customer
    # computation's excess debits attached (with_customer_excess_debits).
    pab_reserve = compute_reserve(with_customer_excess_debits(pab_reserve_inputs, reserve), rules)
    reserve, pab_reserve, reserve_deposits = _post_reserve_deposits(
        books=books,
        run_number=run_number,
        business_date=business_date,
        calendar=calendar,
        actor=actor,
        rules=rules,
        reserve_inputs=reserve_inputs,
        pab_reserve_inputs=pab_reserve_inputs,
        sized_from=(reserve, pab_reserve),
        opening=reserve_bank_opening,
        policy=deposit_policy,
    )
    capital = compute_net_capital(net_capital_inputs, rules)
    control = check_possession_or_control(control_inputs, rules)
    control_figure = (
        None
        if any(item.shortfall is None for item in control.issues)
        else sum(
            (item.shortfall for item in control.issues if item.shortfall is not None),
            Decimal(),
        )
    )
    quantities = books.quantities()[issue]
    books_quantity = quantities[RecordSide.OWNERSHIP]
    trade_books_money = -sum(
        (
            line.money
            for item in books.entries
            for line in item.lines
            if item.source
            in {PostingSource.ALLOCATION, PostingSource.CNS_SETTLEMENT, PostingSource.CNS_FAIL}
            and line.account_type is AccountType.CUSTOMER_CASH
            and line.currency == "USD"
        ),
        Decimal(),
    )
    financing_booked = sum(
        (
            line.money
            for item in books.entries
            if item.source is PostingSource.MARGIN_INTEREST
            for line in item.lines
            if line.account_type is AccountType.FIRM_PROPRIETARY and line.currency == "USD"
        ),
        Decimal(),
    )
    customer_total_credits = sum(
        (
            line.amount or Decimal()
            for line in projected.reserve.lines
            if line.rule_id in EXHIBIT_A_CREDITS
        ),
        Decimal(),
    )
    pab_total_credits = sum(
        (
            line.amount or Decimal()
            for line in projected.pab_reserve.lines
            if line.rule_id in EXHIBIT_A_CREDITS
        ),
        Decimal(),
    )
    customer_total_debits = sum(
        (
            line.amount or Decimal()
            for line in projected.reserve.lines
            if line.rule_id in EXHIBIT_A_DEBITS
        ),
        Decimal(),
    )
    pab_total_debits = sum(
        (
            line.amount or Decimal()
            for line in projected.pab_reserve.lines
            if line.rule_id in EXHIBIT_A_DEBITS
        ),
        Decimal(),
    )
    return EstateResult(
        approved_intent=payload,
        lifecycle_events=register.events,
        capture_record=captured,
        allocation_record=allocation,
        journal_entries=books.entries,
        lifecycle_event_ids=tuple(str(item.event_id) for item in register.events),
        capture_id=captured.trade_id,
        allocation_id=str(allocation.allocation_id),
        journal_entry_ids=tuple(item.entry_id for item in books.entries),
        captured_quantity=captured.quantity,
        captured_money=captured.quantity * captured.price,
        allocated_quantity=sum((item.quantity for item in allocation.entries), Decimal()),
        allocated_money=sum((item.consideration for item in allocation.entries), Decimal()),
        books_quantity=books_quantity,
        books_money=trade_books_money + financing_booked,
        stock_breaks=stock_breaks,
        reserve_disposition=reserve.disposition.value,
        pab_reserve_disposition=pab_reserve.disposition.value,
        net_capital_disposition=capital.disposition.value,
        control_disposition=control.disposition.value,
        reserve_figure=reserve.requirement,
        pab_reserve_figure=pab_reserve.requirement,
        net_capital_figure=capital.net_capital,
        control_figure=control_figure,
        protection_reasons={
            "reserve": reserve.reasons + reserve.missing_inputs + reserve.breaches,
            "pab_reserve": pab_reserve.reasons + pab_reserve.missing_inputs + pab_reserve.breaches,
            "net_capital": capital.reasons + capital.missing_inputs + capital.breaches,
            "possession_or_control": control.reasons + control.missing_inputs + control.breaches,
        },
        reserve_deposits=reserve_deposits,
        books_digest=books.digest(),
        settled_quantity=settlement.allocated_quantity,
        settlement_residual_two_sided=(
            settlement.residual is None
            or (settlement.residual.quantity is not None and settlement.residual.cash is not None)
        ),
        customer_total_credits=customer_total_credits,
        customer_total_debits=customer_total_debits,
        pab_total_credits=pab_total_credits,
        pab_total_debits=pab_total_debits,
        control_shortfall_by_issue=tuple((item.issue, item.shortfall) for item in control.issues),
    )


_RESERVE_BANK = "SYNTHETIC-NON-AFFILIATED-RESERVE-BANK"
#: Deposits and withdrawals move whole cents; the requirement itself is not rounded.
CENT = Decimal("0.01")


def _deposit_entry(
    *,
    entry_id: str,
    event_number: int,
    account_type: AccountType,
    amount: Decimal,
    effective: date,
    authority: str,
    actor: ActorRef,
) -> JournalEntry:
    """A balanced cash movement between firm cash and one reserve bank account."""
    event_id = _identifier("evt_", event_number)
    return JournalEntry(
        entry_id=entry_id,
        source_event_id=event_id,
        source=PostingSource.CASH_MOVEMENT,
        effective_date=effective,
        effective_date_basis="VALUE_DATE",
        authority=authority,
        lines=(
            LedgerLine(
                account_id=f"{account_type.value}@{_RESERVE_BANK}",
                account_type=account_type,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=amount,
            ),
            LedgerLine(
                account_id="FIRM-OPERATING-CASH",
                account_type=AccountType.CASH,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=-amount,
            ),
        ),
        posting=BooksPosting(
            posted_record_id=entry_id,
            posting_authority=actor,
            effective_time=datetime.combine(effective, datetime.min.time(), tzinfo=UTC),
            source_event_id=EventId(event_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=True,
    )


def _post_reserve_deposits(
    *,
    books: EquitiesBooks,
    run_number: int,
    business_date: date,
    calendar: MarketCalendar,
    actor: ActorRef,
    rules: RuleTable,
    reserve_inputs: ReserveInputs,
    pab_reserve_inputs: ReserveInputs,
    sized_from: tuple[ReserveResult, ReserveResult],
    opening: tuple[Decimal, Decimal],
    policy: DepositPolicy | None,
    opening_already_posted: bool = False,
) -> tuple[ReserveResult, ReserveResult, tuple[ReserveDeposit, ...]]:
    """SIM-1G: post each computation's Reserve Bank Account deposit, then recompute.

    17 CFR 240.15c3-3(e)(3)(i)(A), pinned source sha256 c7d7067f...: computations
    "must be made weekly, as of the close of the last business day of the week, and
    the deposit so computed must be made no later than one hour after the opening of
    banking business on the second following business day." Paragraph (e)(3)(i)(B)(1)
    (daily computations) and paragraph (e)(3)(iv) (additional computations on any
    business day) set the same deadline. The simulator computes every business day,
    so each computation's deadline is the second following business day.

    17 CFR 240.15c3-3(g): withdrawals are permitted "if and to the extent that at the
    time of the withdrawal the amount remaining ... is not less than the amount then
    required". An over-funded account is therefore drawn down to the requirement.

    Declared simplifications (SYNTHETIC policy, not firm practice): business days come
    from the loaded US equities calendar, not a bank holiday calendar; the intraday
    "one hour after the opening" is not modelled, so an ON_TIME deposit is effective on
    the deadline date and a LATE one on the next business day; the account is held at
    one non-affiliated bank with declared equity capital; no qualified securities.
    Cash moves in whole cents: a full deposit rounds up, a SHORT deposit rounds down,
    and a withdrawal rounds toward zero, so rounding never creates or hides a breach.
    """
    deadline = calendar.add_business_days(business_date, 2)
    accounts = (
        ("customer", AccountType.RESERVE_BANK_CUSTOMER),
        ("pab", AccountType.RESERVE_BANK_PAB),
    )
    draws = (None, None) if policy is None else (policy.customer, policy.pab)
    plans: list[
        tuple[str, Decimal, Decimal | None, Decimal | None, str, str, Decimal, date | None]
    ] = []
    for index, ((name, account_type), result, balance, draw) in enumerate(
        zip(accounts, sized_from, opening, draws, strict=True)
    ):
        base_event = 400_000_000 + run_number * 10 + index * 3
        if balance != 0 and not opening_already_posted:
            books.post(
                _deposit_entry(
                    entry_id=f"SIM-1G-{name.upper()}-BROUGHT-FORWARD-{run_number}",
                    event_number=base_event,
                    account_type=account_type,
                    amount=balance,
                    effective=business_date,
                    authority="SIM-1G_SYNTHETIC_BALANCE_BROUGHT_FORWARD",
                    actor=actor,
                )
            )
        requirement = result.requirement_after_customer_excess_debits
        needed = None if requirement is None else requirement - balance
        drawn = "NOT_DECLARED_IN_PACK" if draw is None else draw.outcome
        amount = Decimal(0)
        deposit_date: date | None = None
        if needed is None:
            outcome = "NOT_COMPUTED"
        elif draw is None:
            outcome = "NOT_DECLARED_IN_PACK" if needed > 0 else "NO_DEPOSIT_NEEDED"
        elif needed < 0:
            # Toward zero, so the account never falls below the requirement (Rule 15c3-3(g)).
            amount = needed.quantize(CENT, rounding=ROUND_CEILING)
            outcome, deposit_date = "WITHDRAWAL_TO_REQUIREMENT", deadline
            if amount == 0:
                outcome, deposit_date = "NO_DEPOSIT_NEEDED", None
        elif needed == 0:
            outcome = "NO_DEPOSIT_NEEDED"
        elif draw.outcome == "SHORT":
            amount = (needed * (1 - draw.short_fraction)).quantize(CENT, rounding=ROUND_FLOOR)
            outcome, deposit_date = "SHORT", deadline
        elif draw.outcome == "LATE":
            outcome, amount = "LATE", needed.quantize(CENT, rounding=ROUND_CEILING)
            deposit_date = calendar.add_business_days(deadline, 1)
        else:
            amount = needed.quantize(CENT, rounding=ROUND_CEILING)
            outcome, deposit_date = "ON_TIME", deadline
        if amount != 0 and deposit_date is not None:
            books.post(
                _deposit_entry(
                    entry_id=f"SIM-1G-{name.upper()}-{outcome}-{run_number}",
                    event_number=base_event + 1,
                    account_type=account_type,
                    amount=amount,
                    effective=deposit_date,
                    authority="SIM-1G_SYNTHETIC_RESERVE_DEPOSIT_POLICY",
                    actor=actor,
                )
            )
        plans.append((name, balance, requirement, needed, drawn, outcome, amount, deposit_date))
    at_deadline = reserve_bank_balances(books, through=deadline)
    closing = reserve_bank_balances(books, through=date.max)
    equity = None if policy is None else policy.bank_equity_capital

    def counted(inputs: ReserveInputs, account_type: AccountType) -> ReserveInputs:
        cash = at_deadline[account_type]
        if cash == 0:
            return inputs
        return inputs.model_copy(
            update={
                "cash_deposits": (
                    BankCashDeposit(
                        bank=_RESERVE_BANK,
                        amount=cash,
                        affiliated=False,
                        bank_equity_capital=equity,
                    ),
                )
            }
        )

    reserve = compute_reserve(counted(reserve_inputs, AccountType.RESERVE_BANK_CUSTOMER), rules)
    pab_reserve = compute_reserve(
        with_customer_excess_debits(
            counted(pab_reserve_inputs, AccountType.RESERVE_BANK_PAB), reserve
        ),
        rules,
    )
    deposits = tuple(
        ReserveDeposit(
            computation=name,
            opening_balance=balance,
            requirement=requirement,
            needed=needed,
            drawn_outcome=drawn,
            outcome=outcome,
            amount=amount,
            deposit_date=deposit_date,
            deadline=deadline,
            balance_at_deadline=at_deadline[account_type],
            closing_balance=closing[account_type],
        )
        for (name, balance, requirement, needed, drawn, outcome, amount, deposit_date), (
            _,
            account_type,
        ) in zip(plans, accounts, strict=True)
    )
    return reserve, pab_reserve, deposits
