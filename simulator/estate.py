"""SIM-1B adapter: supply generated facts to the real L.C. and Atreides APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes_of, digest, digest_bytes
from cannae_kernel.clocks import EventTimes
from cannae_kernel.effects import OperationEffects
from cannae_kernel.envelopes import ApprovedIntentEnvelope, ExecutionEvent
from cannae_kernel.ids import ActorId, AllocationId, EventId, IntentId, LifecycleId, OrderId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext
from lc.events import LifecycleState
from lc.lifecycle import (
    ApprovedIntentPayload,
    AuthorityManifest,
    ChildOrder,
    EventInput,
    OrderSide,
    PolicyManifest,
    accept_intent,
    activate_parent,
    authorize_strategy,
    split_parent,
    transition,
)
from lc.policy import ExecutionReport, apply_execution
from lc.trade import AllocationPlan, AllocationRule, AllocationTarget, allocate, capture

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
    StockRecordBreak,
)
from atreides.books.projections import project_customer_protection, project_margin_accounts
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    ComputationMode,
    LineBalance,
    ReserveInputs,
    compute_reserve,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from atreides.margin.engine import compute_margin
from atreides.rails.cns import (
    CloseOutRegime,
    MarketProfile,
    net_positions,
    settle_net_position,
)
from simulator.model import Print


@dataclass(frozen=True, slots=True)
class EstateResult:
    captured_quantity: Decimal
    captured_money: Decimal
    allocated_quantity: Decimal
    allocated_money: Decimal
    books_quantity: Decimal
    books_money: Decimal
    stock_breaks: tuple[StockRecordBreak, ...]
    reserve_disposition: str
    net_capital_disposition: str
    control_disposition: str
    reserve_figure: Decimal | None
    net_capital_figure: Decimal | None
    control_figure: Decimal | None
    protection_reasons: dict[str, tuple[str, ...]]
    books_digest: str
    settled_quantity: Decimal
    settlement_residual_two_sided: bool
    customer_total_credits: Decimal
    pab_total_credits: Decimal


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
    payload = ApprovedIntentPayload(
        intent_id=IntentId(_identifier("int_", 10_000 + run_number)),
        instrument_id=issue,
        side=OrderSide.BUY,
        quantity=total_quantity,
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=actor.actor_id,
            policy_manifest_digest=digest(policy),
            authorized=True,
        ),
        allocation_accounts=tuple(f"ACCOUNT-{i + 1}" for i in range(len(account_weights))),
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
        approved_by=actor,
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(
            operation="simulate approved intent",
            effects=(),
            note="synthetic input only; no submission capability",
        ),
        payload_digest=digest_bytes(wire),
    )
    parent_id = OrderId(_identifier("ord_", 30_000 + run_number * 2))
    child_id = OrderId(_identifier("ord_", 30_001 + run_number * 2))
    outcome = accept_intent(
        envelope,
        wire,
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
            ),
        ),
    ).journal
    register = transition(
        register,
        order_id=child_id,
        target=LifecycleState.MARKET_ACCESS_PASSED,
        reason="SIM-1B generated release passed its exercised controls",
        actor=actor,
        event=_event(40_004 + run_number * 20, base),
    )
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
            account=f"ACCOUNT-{index + 1}",
            target_quantity=Decimal(weight) * total_quantity,
        )
        for index, weight in enumerate(account_weights)
    )
    _, allocation = allocate(
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
    books = EquitiesBooks(break_owner="SIM_SETTLEMENT_OPS")
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    net_position = net_positions(
        ((issue, total_quantity),),
        market_id="NSCC_SYNTHETIC",
        settlement_date_offset_days=1,
    )[0]
    signed_cash = (total_quantity * prior_close).quantize(Decimal("0.01"))
    allocated_cash = (street_quantity * prior_close).quantize(Decimal("0.01"))
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
        settlement_date=business_date,
        as_of_date=business_date,
        calendar=calendar,
    )
    lines: list[LedgerLine] = []
    for entry in allocation.entries:
        lines.extend(
            (
                LedgerLine(
                    account_id=entry.account,
                    account_type=AccountType.CUSTOMER_MARGIN,
                    record_side=RecordSide.OWNERSHIP,
                    issue=issue,
                    quantity=entry.quantity,
                ),
                LedgerLine(
                    account_id=entry.account,
                    account_type=AccountType.CUSTOMER_MARGIN,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-entry.consideration,
                ),
                LedgerLine(
                    account_id=entry.account,
                    account_type=AccountType.CUSTOMER_CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=entry.consideration,
                ),
                LedgerLine(
                    account_id="SYNTHETIC_FUNDING",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-entry.consideration,
                ),
            )
        )
    lines.extend(
        (
            LedgerLine(
                account_id="DTC",
                account_type=AccountType.DTC,
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
    source_event_id = _identifier("evt_", 60_000 + run_number)
    books.post(
        JournalEntry(
            entry_id=f"SIM-1B-{run_number}",
            source_event_id=source_event_id,
            source=PostingSource.CNS_SETTLEMENT,
            effective_date=business_date,
            effective_date_basis="SETTLEMENT_DATE",
            authority="NSCC_SYNTHETIC",
            lines=tuple(lines),
            posting=BooksPosting(
                posted_record_id=f"SIM-1B-{run_number}",
                posting_authority=actor,
                effective_time=base,
                source_event_id=EventId(source_event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
        )
    )
    credit_event_id = _identifier("evt_", 70_000 + run_number)
    books.post(
        JournalEntry(
            entry_id=f"SIM-1D-CREDIT-{run_number}",
            source_event_id=credit_event_id,
            source=PostingSource.CASH_MOVEMENT,
            effective_date=business_date,
            effective_date_basis="VALUE_DATE",
            authority="SIM-1D_SYNTHETIC_CUSTOMER_ACTIVITY",
            lines=(
                LedgerLine(
                    account_id="CUSTOMER-GENERATED-CREDIT",
                    account_type=AccountType.CUSTOMER_CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=customer_credit_balance,
                ),
                LedgerLine(
                    account_id="SYNTHETIC_CUSTOMER_CREDIT_FUNDING",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=-customer_credit_balance,
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
        net_capital_inputs = net_capital_inputs.model_copy(update={"net_worth": None})
        control_inputs = control_inputs.model_copy(
            update={
                "issues": tuple(
                    item.model_copy(update={"fully_paid": None})
                    for item in control_inputs.issues
                )
            }
        )
    rules = load_rule_table()
    reserve = compute_reserve(reserve_inputs, rules)
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
            if line.account_type is AccountType.CUSTOMER_MARGIN and line.currency == "USD"
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
    return EstateResult(
        captured_quantity=captured.quantity,
        captured_money=captured.quantity * captured.price,
        allocated_quantity=sum((item.quantity for item in allocation.entries), Decimal()),
        allocated_money=sum((item.consideration for item in allocation.entries), Decimal()),
        books_quantity=books_quantity,
        books_money=trade_books_money + financing_booked,
        stock_breaks=stock_breaks,
        reserve_disposition=reserve.disposition.value,
        net_capital_disposition=capital.disposition.value,
        control_disposition=control.disposition.value,
        reserve_figure=reserve.requirement,
        net_capital_figure=capital.net_capital,
        control_figure=control_figure,
        protection_reasons={
            "reserve": reserve.reasons + reserve.missing_inputs + reserve.breaches,
            "net_capital": capital.reasons + capital.missing_inputs + capital.breaches,
            "possession_or_control": control.reasons + control.missing_inputs + control.breaches,
        },
        books_digest=books.digest(),
        settled_quantity=settlement.allocated_quantity,
        settlement_residual_two_sided=(
            settlement.residual is None
            or (
                settlement.residual.quantity is not None
                and settlement.residual.cash is not None
            )
        ),
        customer_total_credits=customer_total_credits,
        pab_total_credits=pab_total_credits,
    )
