"""SCF-1 declared-synthetic self-clearing firm volume simulation.

The runner is source-only research infrastructure. It calls the installed L.C. capture and
allocation functions and the Atreides journal and CNS engines; it has no submission seam.
"""

from __future__ import annotations

import hashlib
import random
import resource
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes_of, digest, digest_bytes
from cannae_kernel.clocks import EventTimes
from cannae_kernel.effects import OperationEffects
from cannae_kernel.envelopes import ApprovedIntentEnvelope, ExecutionEvent
from cannae_kernel.ids import ActorId, AllocationId, EventId, IntentId, LifecycleId, OrderId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext
from lc.events import LifecycleState, OrderTerms, OrderType, TimeInForce
from lc.lifecycle import (
    ApprovedIntentPayload,
    AuthorityManifest,
    ChildOrder,
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
    ReserveActivity,
    ReserveSourceFact,
)
from atreides.books.projections import (
    project_customer_protection,
    project_margin_accounts,
    reserve_bank_balances,
)
from atreides.books.ps1 import (
    ControlStatus,
    InstructionKind,
    InstructionLog,
    MoneyInstruction,
    SecuritiesConfirmation,
    build_securities_count,
)
from atreides.books.ps1 import (
    reconcile as reconcile_ps1,
)
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
    DAILY_REDUCTION,
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    WEEKLY_REDUCTION,
    ComputationMode,
    compute_reserve,
    with_customer_excess_debits,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from atreides.margin.engine import compute_margin
from atreides.rails.cns import CloseOutRegime, MarketProfile, net_positions, settle_net_position
from simulator.calibration import CalibrationPack
from simulator.central_reconciliation import reconcile_observed_street
from simulator.early_warning import (
    EarlyWarningNotice,
    draft_notices,
    warning_workflow_held,
)
from simulator.estate import (
    DEPOSIT_BREACH_OUTCOMES,
    DepositDraw,
    DepositPolicy,
    ReserveDeposit,
    _complete_reserve_inputs,
    _deposit_entry,
    _post_reserve_deposits,
    _wire,
    simulated_filed_credit_total,
)
from simulator.focus import FirmFocusLines, FirmFocusTieOut, tie_out_firm_close
from simulator.protection_oracle import (
    EXCESS_MARGIN_THRESHOLD,
    ReserveRequirement,
    required_net_capital,
    required_reserve,
)
from simulator.protection_oracle import required_control as required_possession_or_control
from simulator.settlement import rule_204_deadline
from simulator.street import (
    CalendarRun,
    DepositoryPosition,
    IndependentSourceInputs,
    LoanInstruction,
    LoanRegister,
    ObservedSourceReader,
    OpenFail,
    PositionSource,
    ReconciliationCompletion,
    ReconciliationStatus,
    SettlementOutcome,
    StreetBreak,
    SyntheticDepository,
    build_independent_sources,
    reconciliation_calendar,
)

TierName = Literal["small", "medium", "large"]
#: FIX-11 honest stress inputs: a credit that creates a requirement, with a short deposit.
ReserveStress = Literal["customer", "pab"]
TIERS: tuple[TierName, ...] = ("small", "medium", "large")
DISCLAIMER = "SYNTHETIC LOAD LEVEL: no claim about any real firm"
NOT_CLAIMED = (
    "regulatory approval",
    "production readiness",
    "clearing-agency membership",
    "real customer assets",
    "real firm, account or security identifiers",
)


@dataclass(frozen=True, slots=True)
class FirmProfile:
    tier: TierName
    accounts: int
    issues: int
    executions_per_day: int
    margin_account_share: Decimal
    pab_activity_share: Decimal
    buy_share: Decimal
    sell_share: Decimal
    short_sale_share: Decimal
    order_size_min: int
    order_size_max: int
    price_min: Decimal
    price_max: Decimal
    fail_rate: Decimal
    refusal_rate: Decimal
    reserve_short_fraction: Decimal
    reserve_bank_equity_capital: Decimal
    filed_history_months: int
    filed_history_credit: Decimal
    error_account_shares_per_issue: Decimal
    firm_investment_shares_per_issue: Decimal
    seed_stream: str
    calibration_pack_id: str
    calibration_pack_version: str
    calibration_manifest_digest: str
    synthetic: bool = True
    #: Declared control loan: day, issue, and one quantity or a legacy day map.
    control_deficit: tuple[int, int, Decimal | dict[int, Decimal]] | None = None
    fail_lot_settlement_order: Literal["OLDEST_SETTLES_FIRST"] = "OLDEST_SETTLES_FIRST"


@dataclass(frozen=True, slots=True)
class FirmExecution:
    execution_id: str
    issue: str
    account: str
    side: str
    quantity: Decimal
    price: Decimal
    pab: bool
    refused: bool

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.side == "BUY" else -self.quantity

    @property
    def signed_money(self) -> Decimal:
        return -(self.signed_quantity * self.price).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class FirmDay:
    business_date: date
    executions: int
    invariants: dict[str, bool]
    fails_by_age: dict[str, int]
    breaks_by_owner: dict[str, int]
    street_breaks: tuple[StreetBreak, ...]
    reconciliation_completion: ReconciliationCompletion
    reconciliation_calendar: tuple[CalendarRun, ...]
    source_inputs: IndependentSourceInputs
    reconciled_sources: tuple[PositionSource, ...]
    protection_dispositions: dict[str, str]
    protection_required: dict[str, str]
    protection_reasons: dict[str, tuple[str, ...]]
    protection_figures: dict[str, Decimal | None]
    focus_tie_out: FirmFocusTieOut
    early_warning_notices: tuple[EarlyWarningNotice, ...]
    rule_204_close_outs: dict[str, date]
    economics_digest: str


@dataclass(frozen=True, slots=True)
class FirmRun:
    profile: FirmProfile
    seed: int
    days: tuple[FirmDay, ...]
    elapsed_seconds: float
    executions_per_second: float
    peak_memory_bytes: int | None
    publication_change_reasons: tuple[str, ...] = (
        "MVP-0 moves opening customer holdings out of the proprietary book",
        "MVP-0 declares a small synthetic proprietary book in calibration",
        "N2 restricts net capital haircut inputs to firm proprietary positions",
        "N3 includes PAB free credits in the PAB reserve computation",
        "N4 removes fails to deliver from the Rule 15c3-3(d)(2) control location",
        "N5 declares stock-loan holdings as loaned",
        "MVP-1 replaces the self-comparison with an independent street statement",
        "MVP-1 reports the declared reconciliation calendar at every close",
        "MVP-1 nets fail-to-receive and stock-loan lifecycle balances",
        "MVP-1B sources DTC, CNS fails and the stock-loan register independently",
        "MVP-1B preserves fail identity through posting, projection and aging",
        "MVP-1B records observed reconciliation completion and source failures",
        "MVP-1C fails I3 closed on failed or missing observed reconciliation",
        "MVP-1C carries CNS residuals as non-growing fail lots",
        "MVP-1C sizes recall from the independent loan register",
        "MVP-2 settles the oldest carried fail lot before newer lots",
        "MVP-2 reconciles the production run through independent source readers",
        "MVP-2 ties regulatory-report figures to every firm-at-volume close",
        "MVP-2 creates owned synthetic drafts for fired early-warning indicators",
        "MVP-2B derives reserve and PAB checks independently from journal lines",
        "MVP-2B uses one declared stock-loan input for every run length",
    )
    not_claimed: tuple[str, ...] = NOT_CLAIMED


MUTATIONS = (
    "UPSTREAM_ALLOCATION_QUANTITY",
    "UPSTREAM_FAIL_QUANTITY",
    "BOOKED_QUANTITY_STREET_LACKS",
    "STREET_MOVEMENT_BOOKS_MISSED",
    "WRONG_LOCATION_BOOKING",
    "DUPLICATE_BOOKING",
    "DROP_FILL_FROM_BOOKS",
    "DOUBLE_POST_NEW_EVENT",
    "OMIT_ISSUE_FROM_CNS",
    "WRONG_OPENING_POSITION",
    "FORCE_RESERVE_PASS_ON_SHORT_DAY",
    "AGE_FAIL_WITHOUT_CARRY",
    "FOCUS_WRONG_NET_CAPITAL",
    "FOCUS_WRONG_RESERVE_CREDIT",
    "FOCUS_WRONG_CONTROL_QUANTITY",
    "FOCUS_DROP_CUSTOMER_ACCOUNT",
    "PROJECTION_CUT_RESERVE_CREDIT",
    "UNSOURCED_BANK_CONTROL",
    "UNPOSTED_DEPOSIT_INSTRUCTION",
    "RESERVE_DEPOSIT_NOT_RECEIVED",
    "EARLY_WARNING_MISSING_DRAFT",
    "EARLY_WARNING_MISSING_OWNER",
    "DEPOSITORY_ONE_SHARE",
    "STREET_ONE_SHARE",
)


def roll_forward(
    opening_positions: dict[tuple[str, str], Decimal],
    opening_cash: dict[str, Decimal],
    position_activity: dict[tuple[str, str], Decimal],
    cash_activity: dict[str, Decimal],
) -> tuple[dict[tuple[str, str], Decimal], dict[str, Decimal]]:
    """Roll prior close plus independently sourced L.C. allocation activity."""
    positions = defaultdict(Decimal, opening_positions)
    cash = defaultdict(Decimal, opening_cash)
    for position_key, amount in position_activity.items():
        positions[position_key] += amount
    for account_id, amount in cash_activity.items():
        cash[account_id] += amount
    return dict(positions), dict(cash)


def _reconciliation_held(
    completions: tuple[ReconciliationCompletion, ...],
    required_item_ids: tuple[str, ...],
    breaks: tuple[StreetBreak, ...],
) -> bool:
    by_id = {item.item_id: item for item in completions}
    return not breaks and all(
        item_id in by_id and by_id[item_id].status == "COMPLETED" for item_id in required_item_ids
    )


def attack_firm_run(run: FirmRun) -> dict[str, tuple[str, ...]]:
    """Rerun the simulator with each ordered input, posting, or engine mutation."""
    if not run.days:
        raise ValueError("an adversarial pass requires at least one close")
    attacked: dict[str, tuple[str, ...]] = {}
    for mutation in MUTATIONS:
        mutated = run_firm(
            run.profile,
            seed=run.seed,
            days=3,
            start=run.days[0].business_date,
            mutation=mutation,
            verify_replay=False,
            early_warning_stress=mutation.startswith("EARLY_WARNING_"),
        )
        attacked[mutation] = tuple(
            sorted(
                {name for day in mutated.days for name, held in day.invariants.items() if not held}
            )
        )
    return attacked


def load_firm_profile(pack: CalibrationPack, tier: TierName) -> FirmProfile:
    """Load the one SCF-1 profile through the calibration-pack seam."""
    values = cast(dict[str, dict[str, object]], pack.value("firm_profile", "tiers"))
    selected = values[tier]
    return FirmProfile(
        tier=tier,
        accounts=cast(int, selected["accounts"]),
        issues=cast(int, selected["issues"]),
        executions_per_day=cast(int, selected["executions_per_day"]),
        margin_account_share=Decimal(str(pack.value("firm_profile", "margin_account_share"))),
        pab_activity_share=Decimal(str(pack.value("firm_profile", "pab_activity_share"))),
        buy_share=Decimal(str(pack.value("firm_profile", "buy_share"))),
        sell_share=Decimal(str(pack.value("firm_profile", "sell_share"))),
        short_sale_share=Decimal(str(pack.value("firm_profile", "short_sale_share"))),
        order_size_min=int(cast(int, pack.value("firm_profile", "order_size_min"))),
        order_size_max=int(cast(int, pack.value("firm_profile", "order_size_max"))),
        price_min=Decimal(str(pack.value("firm_profile", "price_min"))),
        price_max=Decimal(str(pack.value("firm_profile", "price_max"))),
        fail_rate=Decimal(str(pack.value("firm_profile", "fail_rate"))),
        refusal_rate=Decimal(str(pack.value("firm_profile", "refusal_rate"))),
        reserve_short_fraction=Decimal(str(pack.value("firm_profile", "reserve_short_fraction"))),
        reserve_bank_equity_capital=Decimal(
            str(pack.value("firm_profile", "reserve_bank_equity_capital"))
        ),
        filed_history_months=int(cast(int, pack.value("firm_profile", "filed_history_months"))),
        filed_history_credit=Decimal(str(pack.value("firm_profile", "filed_history_credit"))),
        error_account_shares_per_issue=Decimal(
            str(pack.value("firm_profile", "error_account_shares_per_issue"))
        ),
        firm_investment_shares_per_issue=Decimal(
            str(pack.value("firm_profile", "firm_investment_shares_per_issue"))
        ),
        seed_stream=str(pack.value("firm_profile", "seed_stream")),
        calibration_pack_id=pack.pack_id,
        calibration_pack_version=pack.version,
        calibration_manifest_digest=pack.manifest_digest,
        control_deficit=_control_deficit(pack),
        fail_lot_settlement_order=_fail_lot_settlement_order(pack),
    )


def _control_deficit(
    pack: CalibrationPack,
) -> tuple[int, int, Decimal | dict[int, Decimal]] | None:
    try:
        declared = cast(dict[str, object], pack.value("firm_profile", "control_deficit"))
    except (KeyError, ValueError):
        return None
    if "loan_shares" in declared:
        loan: Decimal | dict[int, Decimal] = Decimal(str(declared["loan_shares"]))
    elif "loan_shares_by_run_days" in declared:
        loan_shares = cast(dict[str, object], declared["loan_shares_by_run_days"])
        loan = {int(days): Decimal(str(quantity)) for days, quantity in loan_shares.items()}
    else:
        return None
    return (
        int(cast(int, declared["day_index"])),
        int(cast(int, declared["issue_index"])),
        loan,
    )


def _fail_lot_settlement_order(
    pack: CalibrationPack,
) -> Literal["OLDEST_SETTLES_FIRST"]:
    try:
        declared = cast(dict[str, object], pack.value("firm_profile", "fail_lot_policy"))
    except (KeyError, ValueError):
        return "OLDEST_SETTLES_FIRST"
    if declared.get("rule_anchor") != "TO_VERIFY_AGAINST_PRIMARY_TEXT":
        raise ValueError("fail-lot policy requires a TO_VERIFY_AGAINST_PRIMARY_TEXT anchor")
    if declared.get("order") == "OLDEST_FIRST":
        raise ValueError("FAIL_LOT_ORDER_OLDEST_FIRST_AMBIGUOUS: use firm-synthetic/5 or later")
    if declared.get("order") != "OLDEST_SETTLES_FIRST":
        raise ValueError("unsupported fail-lot order")
    return "OLDEST_SETTLES_FIRST"


def _id(prefix: str, number: int) -> str:
    return prefix + f"{number:026d}"


def _actor() -> ActorRef:
    return ActorRef(
        actor_id=ActorId(_id("act_", 91)),
        actor_kind=ActorKind.DETERMINISTIC_SERVICE,
        role="scf-1-volume-simulator",
        entitlement_refs=("SCF-1",),
        authenticated=True,
    )


def _event(number: int, at: datetime) -> Any:
    from lc.lifecycle import EventInput

    when = at + timedelta(microseconds=number % 1_000_000)
    return EventInput(
        event_id=EventId(_id("evt_", number)),
        times=EventTimes(
            event_time=when,
            observation_time=when,
            processing_time=when,
            decision_time=when,
        ),
        idempotency_key=f"scf-1-{number}",
    )


def _business_dates(start: date, days: int) -> tuple[date, ...]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    result: list[date] = []
    cursor = start
    while len(result) < days:
        if calendar.is_business_day(cursor):
            result.append(cursor)
        cursor += timedelta(days=1)
    return tuple(result)


def draw_executions(profile: FirmProfile, day: date, seed: int) -> tuple[FirmExecution, ...]:
    """Draw a day from the isolated, named SCF-1 stream."""
    rng = random.Random(f"{profile.seed_stream}:{seed}:{day.isoformat()}:{profile.tier}")
    cents_low = int(profile.price_min * 100)
    cents_high = int(profile.price_max * 100)
    result: list[FirmExecution] = []
    for index in range(profile.executions_per_day):
        side_draw = Decimal(str(rng.random()))
        side = (
            "BUY"
            if side_draw < profile.buy_share
            else ("SELL" if side_draw < profile.buy_share + profile.sell_share else "SHORT")
        )
        refused = Decimal(str(rng.random())) < profile.refusal_rate
        result.append(
            FirmExecution(
                execution_id=f"SCF1-{day:%Y%m%d}-{index:06d}",
                issue=f"SYN-SCF1-ISSUE-{rng.randrange(profile.issues):04d}",
                account=f"SYN-SCF1-ACCOUNT-{rng.randrange(profile.accounts):06d}",
                side=side,
                quantity=(
                    Decimal(profile.order_size_max + 1)
                    if refused
                    else Decimal(rng.randrange(profile.order_size_min, profile.order_size_max + 1))
                ),
                price=Decimal(rng.randrange(cents_low, cents_high + 1)) / 100,
                pab=Decimal(str(rng.random())) < profile.pab_activity_share,
                refused=refused,
            )
        )
    return tuple(result)


def _lc_allocate_batch(
    rows: tuple[FirmExecution, ...], business_date: date, sequence: int
) -> tuple[tuple[str, Decimal, Decimal], ...]:
    """Drive real L.C. lifecycle, capture and allocation for one issue/side batch."""
    actor = _actor()
    base = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    total = sum((row.quantity for row in rows), Decimal())
    policy = PolicyManifest(
        policy_id="scf-1-synthetic-volume",
        version="1",
        bounds_digest="sha256:" + "2" * 64,
        enabled=True,
    )
    payload = ApprovedIntentPayload(
        intent_id=IntentId(_id("int_", 1_000_000 + sequence)),
        instrument_id=rows[0].issue,
        side=OrderSide.BUY if rows[0].side == "BUY" else OrderSide.SELL,
        quantity=total,
        policy_manifest=policy,
        authority_manifest=AuthorityManifest(
            authority_id=actor.actor_id, policy_manifest_digest=digest(policy), authorized=True
        ),
        allocation_accounts=tuple(dict.fromkeys(row.account for row in rows)),
    )
    wire = _wire(payload)
    lifecycle_id = LifecycleId(_id("lif_", 2_000_000 + sequence))
    envelope = ApprovedIntentEnvelope(
        envelope_id=payload.intent_id,
        lifecycle_id=lifecycle_id,
        revision=1,
        prior_digest=None,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=business_date, calendar="SIFMA-US", established_by="SCF-1 synthetic day"
            ),
        ),
        approved_by=actor,
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(operation="simulate volume", effects=(), note=DISCLAIMER),
        payload_digest=digest_bytes(wire),
    )
    parent = OrderId(_id("ord_", 3_000_000 + sequence * 2))
    child = OrderId(_id("ord_", 3_000_001 + sequence * 2))
    outcome = accept_intent(
        envelope,
        wire,
        parent_order_id=parent,
        actor=actor,
        event=_event(4_000_000 + sequence * 10, base),
    )
    outcome = authorize_strategy(
        outcome, actor=actor, event=_event(4_000_001 + sequence * 10, base)
    )
    outcome = activate_parent(outcome, actor=actor, event=_event(4_000_002 + sequence * 10, base))
    register = split_parent(
        outcome,
        actor=actor,
        children=(
            ChildOrder(
                order_id=child,
                quantity=total,
                event=_event(4_000_003 + sequence * 10, base),
                terms=OrderTerms(
                    account_id=rows[0].account,
                    strategy_id="SCF-1",
                    issue=rows[0].issue,
                    side=payload.side.value,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    control_price=rows[0].price,
                    approved_intent_digest=digest(payload),
                    policy_expires_at=base + timedelta(days=1),
                    recommended=False,
                ),
            ),
        ),
    ).journal
    register = transition(
        register,
        order_id=child,
        target=LifecycleState.MARKET_ACCESS_PASSED,
        reason="SCF-1 synthetic release",
        actor=actor,
        event=_event(4_000_004 + sequence * 10, base),
    )
    reports = tuple(
        ExecutionReport(
            execution_id=row.execution_id,
            order_id=child,
            intent_id=payload.intent_id,
            venue="VENUE-SYNTHETIC",
            quantity=row.quantity,
            price=row.price,
            outcome="FILL" if index == len(rows) - 1 else "PARTIAL_FILL",
        )
        for index, row in enumerate(rows)
    )
    total_money = sum((report.quantity * report.price for report in reports), Decimal())
    aggregate = ExecutionReport(
        execution_id=f"SCF1-AGGREGATE-{sequence}",
        order_id=child,
        intent_id=payload.intent_id,
        venue="VENUE-SYNTHETIC",
        quantity=total,
        price=total_money / total,
        outcome="FILL",
    )
    execution = ExecutionEvent(
        event_id=EventId(_id("evt_", 20_000_000 + sequence * 1_000_000)),
        lifecycle_id=lifecycle_id,
        intent_id=payload.intent_id,
        intent_digest=digest(payload),
        times=EventTimes(
            event_time=base,
            observation_time=base,
            processing_time=base,
            decision_time=None,
        ),
        session=envelope.session,
        provenance=Provenance.FACT_SYNTHETIC,
        payload_digest=digest(aggregate),
    )
    register = apply_execution(
        register,
        execution,
        aggregate,
        actor=actor,
        event=_event(21_000_000 + sequence * 1_000_000, base),
    ).journal
    register, captured = capture(
        register,
        reports,
        payload,
        actor=actor,
        event=_event(22_000_000 + sequence * 1_000_000, base),
    )
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        totals[row.account] += row.quantity
    _, allocated = allocate(
        register,
        captured,
        payload,
        allocation_id=AllocationId(_id("alc_", 8_000_000 + sequence)),
        actor=actor,
        event=_event(23_000_000 + sequence * 1_000_000, base),
        plan=AllocationPlan(
            targets=tuple(
                AllocationTarget(account=account, target_quantity=quantity)
                for account, quantity in sorted(totals.items())
            ),
            rule=AllocationRule.PRO_RATA,
            rounding_method="LARGEST_REMAINDER",
        ),
    )
    return tuple(
        (entry.account, entry.quantity, entry.consideration) for entry in allocated.entries
    )


def _post_batch(
    books: EquitiesBooks,
    rows: tuple[FirmExecution, ...],
    allocations: tuple[tuple[str, Decimal, Decimal], ...],
    business_date: date,
    sequence: int,
    margin_account_share: Decimal,
) -> JournalEntry:
    sign = Decimal(1) if rows[0].side == "BUY" else Decimal(-1)
    issue = rows[0].issue
    pab_accounts = {row.account for row in rows if row.pab}
    lines: list[LedgerLine] = []
    total_quantity = Decimal()
    total_money = Decimal()
    for account, quantity, consideration in allocations:
        account_number = int(account.rsplit("-", 1)[1])
        account_type = (
            AccountType.PAB
            if account in pab_accounts
            else AccountType.CUSTOMER_MARGIN
            if Decimal(account_number % 100) / Decimal(100) < margin_account_share
            else AccountType.CUSTOMER_CASH
        )
        signed_quantity = sign * quantity
        signed_money = -sign * consideration
        total_quantity += signed_quantity
        total_money += signed_money
        lines.extend(
            (
                LedgerLine(
                    account_id=account,
                    account_type=account_type,
                    record_side=RecordSide.OWNERSHIP,
                    issue=issue,
                    quantity=signed_quantity,
                ),
                LedgerLine(
                    account_id=account,
                    account_type=account_type,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=signed_money,
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
                quantity=-total_quantity,
            ),
            LedgerLine(
                account_id="CLEARING",
                account_type=AccountType.CASH,
                record_side=RecordSide.MONEY,
                currency="USD",
                money=-total_money,
            ),
        )
    )
    event_id = _id("evt_", 10_000_000 + sequence)
    entry = JournalEntry(
        entry_id=f"SCF1-{sequence}",
        source_event_id=event_id,
        source=PostingSource.CNS_SETTLEMENT,
        effective_date=business_date,
        effective_date_basis="SETTLEMENT_DATE",
        authority="NSCC_SYNTHETIC",
        lines=tuple(lines),
        posting=BooksPosting(
            posted_record_id=f"SCF1-{sequence}",
            posting_authority=_actor(),
            effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
            source_event_id=EventId(event_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=True,
    )
    books.post(entry)
    return entry


def _balances(books: EquitiesBooks) -> tuple[dict[tuple[str, str], Decimal], dict[str, Decimal]]:
    positions: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    cash: dict[str, Decimal] = defaultdict(Decimal)
    for entry in books.entries:
        for line in entry.lines:
            if line.record_side is RecordSide.OWNERSHIP and line.issue:
                positions[(line.account_id, line.issue)] += line.quantity
            if (
                line.record_side is RecordSide.MONEY
                and line.currency == "USD"
                and line.account_type
                in {AccountType.CUSTOMER_CASH, AccountType.CUSTOMER_MARGIN, AccountType.PAB}
            ):
                cash[line.account_id] += line.money
    return dict(positions), dict(cash)


def _opening_street(profile: FirmProfile, days: int) -> tuple[DepositoryPosition, ...]:
    per_issue = Decimal(profile.executions_per_day * profile.order_size_max * days)
    total = (
        per_issue
        + profile.error_account_shares_per_issue
        + profile.firm_investment_shares_per_issue
    )
    return tuple(
        DepositoryPosition(issue=f"SYN-SCF1-ISSUE-{index:04d}", location="DTC", quantity=-total)
        for index in range(profile.issues)
    )


def _post_wrong_location(books: EquitiesBooks, business_date: date, issue: str) -> None:
    event_id = _id("evt_", 825_000_000)
    books.post(
        JournalEntry(
            entry_id="SCF1-WRONG-LOCATION",
            source_event_id=event_id,
            source=PostingSource.CNS_SETTLEMENT,
            effective_date=business_date,
            effective_date_basis="SETTLEMENT_DATE",
            authority="MVP1_ATTACK_WRONG_LOCATION",
            lines=(
                LedgerLine(
                    account_id="DTC",
                    account_type=AccountType.DTC,
                    record_side=RecordSide.LOCATION,
                    issue=issue,
                    quantity=Decimal(1),
                ),
                LedgerLine(
                    account_id="BANK_CONTROL",
                    account_type=AccountType.BANK_CONTROL,
                    record_side=RecordSide.LOCATION,
                    issue=issue,
                    quantity=Decimal(-1),
                ),
            ),
            posting=BooksPosting(
                posted_record_id="SCF1-WRONG-LOCATION",
                posting_authority=_actor(),
                effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
                source_event_id=EventId(event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )


def _post_unsourced_bank_control(books: EquitiesBooks, business_date: date, issue: str) -> None:
    event_id = _id("evt_", 825_000_001)
    books.post(
        JournalEntry(
            entry_id="SCF1-UNSOURCED-BANK-CONTROL",
            source_event_id=event_id,
            source=PostingSource.CNS_SETTLEMENT,
            effective_date=business_date,
            effective_date_basis="SETTLEMENT_DATE",
            authority="MVP2B_ATTACK_UNSOURCED_LOCATION",
            lines=(
                LedgerLine(
                    account_id="BANK_CONTROL",
                    account_type=AccountType.BANK_CONTROL,
                    record_side=RecordSide.LOCATION,
                    issue=issue,
                    quantity=Decimal(5),
                ),
                LedgerLine(
                    account_id="SYN-FIRM-PROPRIETARY",
                    account_type=AccountType.FIRM_PROPRIETARY,
                    record_side=RecordSide.OWNERSHIP,
                    issue=issue,
                    quantity=Decimal(-5),
                ),
            ),
            posting=BooksPosting(
                posted_record_id="SCF1-UNSOURCED-BANK-CONTROL",
                posting_authority=_actor(),
                effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
                source_event_id=EventId(event_id),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )


def _seed_inventory(books: EquitiesBooks, profile: FirmProfile, start: date, days: int) -> None:
    """Book customer opening holdings and the declared small proprietary book."""
    per_issue = Decimal(profile.executions_per_day * profile.order_size_max * days)
    per_customer = per_issue / profile.accounts
    for index in range(profile.issues):
        issue = f"SYN-SCF1-ISSUE-{index:04d}"
        event_id = _id("evt_", 900_000_000 + index)
        books.post(
            JournalEntry(
                entry_id=f"SCF1-OPENING-{index:04d}",
                source_event_id=event_id,
                source=PostingSource.CNS_SETTLEMENT,
                effective_date=start,
                effective_date_basis="SETTLEMENT_DATE",
                authority="SCF1_SYNTHETIC_OPENING_INVENTORY",
                lines=(
                    *(
                        LedgerLine(
                            account_id=f"SYN-SCF1-ACCOUNT-{account:06d}",
                            account_type=(
                                AccountType.CUSTOMER_MARGIN
                                if Decimal(account % 100) / Decimal(100)
                                < profile.margin_account_share
                                else AccountType.CUSTOMER_CASH
                            ),
                            record_side=RecordSide.OWNERSHIP,
                            issue=issue,
                            quantity=per_customer,
                        )
                        for account in range(profile.accounts)
                    ),
                    LedgerLine(
                        account_id="SYN-SCF1-ERROR-ACCOUNT",
                        account_type=AccountType.FIRM_PROPRIETARY,
                        record_side=RecordSide.OWNERSHIP,
                        issue=issue,
                        quantity=profile.error_account_shares_per_issue,
                    ),
                    LedgerLine(
                        account_id="SYN-SCF1-FIRM-INVESTMENTS",
                        account_type=AccountType.FIRM_PROPRIETARY,
                        record_side=RecordSide.OWNERSHIP,
                        issue=issue,
                        quantity=profile.firm_investment_shares_per_issue,
                    ),
                    LedgerLine(
                        account_id="DTC",
                        account_type=AccountType.DTC,
                        record_side=RecordSide.LOCATION,
                        issue=issue,
                        quantity=-(
                            per_issue
                            + profile.error_account_shares_per_issue
                            + profile.firm_investment_shares_per_issue
                        ),
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id=f"SCF1-OPENING-{index:04d}",
                    posting_authority=_actor(),
                    effective_time=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                    source_event_id=EventId(event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )


def synthetic_filed_history(profile: FirmProfile, start: date) -> tuple[Decimal, ...] | None:
    """Return the declared 12-month SIMULATED_FOCUS_STAND_IN, or honest absence."""
    if profile.filed_history_months == 0:
        return None
    return tuple(
        sum(
            simulated_filed_credit_total(
                start - timedelta(days=30 * month), profile.filed_history_credit
            ),
            Decimal(),
        )
        for month in range(1, profile.filed_history_months + 1)
    )


def _post_stock_borrows(
    books: EquitiesBooks,
    carried_fails: dict[str, tuple[OpenFail, ...]],
    business_date: date,
    prices: dict[str, Decimal],
    day_index: int,
) -> dict[tuple[str, str], Decimal]:
    """Post declared synthetic borrows that cover open CNS fails through the real books."""
    activity: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    lots = sorted(
        (fail for issue_lots in carried_fails.values() for fail in issue_lots),
        key=lambda fail: fail.fail_id,
    )
    for offset, fail in enumerate(lots):
        issue = fail.issue
        quantity, cash, settlement_date = (
            fail.quantity,
            fail.cash,
            fail.opening_settlement_date,
        )
        if quantity == 0:
            continue
        event_id = _id("evt_", 840_000_000 + day_index * 10_000 + offset)
        borrowed = abs(quantity)
        activity[("SYN-SCF2-STOCK-BORROWED", issue)] += borrowed
        activity[("SYN-SCF2-BORROW-LENDER", issue)] -= borrowed
        books.post(
            JournalEntry(
                entry_id=f"SCF2-BORROW-{day_index}-{offset}",
                source_event_id=event_id,
                source=PostingSource.CNS_FAIL,
                effective_date=business_date,
                effective_date_basis="SETTLEMENT_DATE",
                authority="SCF2_SYNTHETIC_BORROW_POLICY",
                lines=(
                    LedgerLine(
                        account_id="SYN-SCF2-STOCK-BORROWED",
                        account_type=AccountType.STOCK_BORROWED,
                        record_side=RecordSide.OWNERSHIP,
                        issue=issue,
                        quantity=borrowed,
                    ),
                    LedgerLine(
                        account_id="SYN-SCF2-BORROW-LENDER",
                        account_type=AccountType.STOCK_BORROW_COUNTERPARTY,
                        record_side=RecordSide.OWNERSHIP,
                        issue=issue,
                        quantity=-borrowed,
                    ),
                ),
                reserve_source_facts=(
                    ReserveSourceFact(
                        account_type=AccountType.STOCK_BORROWED,
                        issue=issue,
                        activity=ReserveActivity.CUSTOMER,
                        settlement_date=settlement_date,
                        contract_price=prices.get(issue, abs(cash / quantity)),
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id=f"SCF2-BORROW-{day_index}-{offset}",
                    posting_authority=_actor(),
                    effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
                    source_event_id=EventId(event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )
    return dict(activity)


def _post_fail_to_receive_movements(
    books: EquitiesBooks,
    carried: dict[str, tuple[OpenFail, ...]],
    closing: dict[str, tuple[OpenFail, ...]],
    business_date: date,
    day_index: int,
    mutation: str | None,
) -> None:
    """Post each fail lot's opening, partial closing, or full closing by fail ID."""
    prior_by_id = {fail.fail_id: fail for issue_lots in carried.values() for fail in issue_lots}
    current_by_id = {fail.fail_id: fail for issue_lots in closing.values() for fail in issue_lots}
    for offset, fail_id in enumerate(sorted(set(prior_by_id) | set(current_by_id))):
        prior = prior_by_id.get(fail_id)
        current = current_by_id.get(fail_id)
        fact = prior or current
        assert fact is not None
        issue = fact.issue
        delta = _fail_posting_delta(prior, current, business_date)
        if not delta:
            continue
        booked_delta = (
            delta + Decimal(1)
            if mutation == "UPSTREAM_FAIL_QUANTITY" and day_index == 1 and offset == 0
            else delta
        )
        event_id = _id("evt_", 845_000_000 + day_index * 10_000 + offset)
        entry_id = f"SCF2-FTR-{day_index}-{offset}"
        books.post(
            JournalEntry(
                entry_id=entry_id,
                source_event_id=event_id,
                source=PostingSource.CNS_FAIL,
                effective_date=business_date,
                effective_date_basis="SETTLEMENT_DATE",
                authority="SCF2_SYNTHETIC_FAIL_LIFECYCLE",
                lines=(
                    LedgerLine(
                        account_id="DTC",
                        account_type=AccountType.DTC,
                        record_side=RecordSide.LOCATION,
                        issue=issue,
                        quantity=booked_delta,
                    ),
                    LedgerLine(
                        account_id="SYN-SCF2-FAIL-TO-RECEIVE",
                        account_type=AccountType.FAIL_TO_RECEIVE,
                        record_side=RecordSide.LOCATION,
                        issue=issue,
                        quantity=-booked_delta,
                    ),
                ),
                reserve_source_facts=(
                    ReserveSourceFact(
                        account_type=AccountType.FAIL_TO_RECEIVE,
                        issue=issue,
                        activity=ReserveActivity.CUSTOMER,
                        settlement_date=fact.opening_settlement_date,
                        contract_price=fact.contract_price,
                        fail_id=fact.fail_id,
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id=entry_id,
                    posting_authority=_actor(),
                    effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
                    source_event_id=EventId(event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )


def _fail_posting_delta(
    prior: OpenFail | None, current: OpenFail | None, business_date: date
) -> Decimal:
    fact = prior or current
    if fact is None:
        return Decimal()
    ending = Decimal() if current is None else max(current.quantity, Decimal())
    opening = Decimal() if prior is None else max(prior.quantity, Decimal())
    target = ending if fact.opening_settlement_date <= business_date else Decimal()
    recorded = (
        opening
        if prior is not None and prior.opening_settlement_date < business_date
        else Decimal()
    )
    return target - recorded


def _same_direction(left: Decimal, right: Decimal) -> bool:
    return (left > 0 and right > 0) or (left < 0 and right < 0)


def _roll_fail_lots(
    issue: str,
    residual_quantity: Decimal,
    residual_cash: Decimal,
    carried: tuple[OpenFail, ...],
    opening_settlement_date: date,
    contract_price: Decimal,
) -> tuple[OpenFail, ...]:
    """Settle the oldest carried lot first without growing or flipping a fail ID.

    Oldest first is a declared firm policy pending confirmation against primary text.
    It is not represented as a regulatory rule.
    """
    if not residual_quantity:
        return ()
    remaining = abs(residual_quantity)
    direction = Decimal(1) if residual_quantity > 0 else Decimal(-1)
    result: list[OpenFail] = []
    # The residual is what remains open. Retain newest lots first so reductions
    # consume the oldest open lot before a newer one.
    for prior in sorted(
        carried,
        key=lambda item: (item.opening_settlement_date, item.fail_id),
        reverse=True,
    ):
        if not _same_direction(prior.quantity, residual_quantity) or not remaining:
            continue
        retained = min(abs(prior.quantity), remaining)
        ratio = retained / abs(prior.quantity)
        result.append(
            replace(
                prior,
                quantity=direction * retained,
                cash=(prior.cash * ratio).quantize(Decimal("0.01")),
            )
        )
        remaining -= retained
    if remaining:
        retained_cash = sum((item.cash for item in result), Decimal())
        result.append(
            OpenFail(
                fail_id=(
                    f"CNS-FAIL-{issue}-{opening_settlement_date.isoformat()}-{len(result) + 1}"
                ),
                issue=issue,
                quantity=direction * remaining,
                cash=residual_cash - retained_cash,
                opening_settlement_date=opening_settlement_date,
                contract_price=contract_price,
            )
        )
    return tuple(sorted(result, key=lambda item: (item.opening_settlement_date, item.fail_id)))


def _loan_entry(
    entry_id: str, event_number: int, issue: str, quantity: Decimal, business_date: date
) -> JournalEntry:
    event_id = _id("evt_", event_number)
    return JournalEntry(
        entry_id=entry_id,
        source_event_id=event_id,
        source=PostingSource.STOCK_LOAN,
        effective_date=business_date,
        effective_date_basis="SETTLEMENT_DATE",
        authority="FIX11_DECLARED_CONTROL_DEFICIT",
        lines=(
            LedgerLine(
                account_id="DTC",
                account_type=AccountType.DTC,
                record_side=RecordSide.LOCATION,
                issue=issue,
                quantity=quantity,
            ),
            LedgerLine(
                account_id="SYN-FIX11-STOCK-LOANED",
                account_type=AccountType.STOCK_LOANED,
                record_side=RecordSide.LOCATION,
                issue=issue,
                quantity=-quantity,
            ),
        ),
        posting=BooksPosting(
            posted_record_id=entry_id,
            posting_authority=_actor(),
            effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
            source_event_id=EventId(event_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=True,
    )


def _post_control_deficit(
    books: EquitiesBooks,
    loan_register: LoanRegister,
    profile: FirmProfile,
    business_date: date,
    prices: dict[str, Decimal],
    day_index: int,
    run_days: int,
) -> tuple[LoanInstruction, ...]:
    """Post the declared stock loan that leaves one issue short of control, then recall it.

    The loan moves firm inventory from DTC (a Rule 15c3-3(c) control location) to stock
    loaned (a (d)(1) noncontrol location). Ownership does not change, so the stock record
    still balances. The profile declares the loan instruction quantity for each supported
    run length, and the register declares the recall from its own open balance.
    """
    if profile.control_deficit is None:
        return ()
    deficit_day, issue_index, declared_loan = profile.control_deficit
    issue = f"SYN-SCF1-ISSUE-{issue_index:04d}"
    if day_index == deficit_day + 1:
        instruction = loan_register.declare_recall(
            issue,
            business_date,
            f"LOAN-RECALL-{day_index}",
        )
        if instruction is not None:
            books.post(
                _loan_entry(
                    f"FIX11-RECALL-{day_index}",
                    850_000_001,
                    issue,
                    instruction.quantity,
                    business_date,
                )
            )
            return (instruction,)
        return ()
    if day_index != deficit_day:
        return ()
    del prices
    loan = declared_loan.get(run_days) if isinstance(declared_loan, dict) else declared_loan
    if loan is None:
        raise ValueError(f"no declared control loan for {run_days} run days")
    if loan <= 0:
        raise ValueError(f"declared control loan must be positive for {issue}")
    instruction = LoanInstruction(f"LOAN-OPEN-{day_index}", issue, loan, business_date)
    loan_register.record(instruction)
    books.post(
        _loan_entry(
            f"FIX11-LOAN-{day_index}",
            850_000_000,
            issue,
            instruction.quantity,
            business_date,
        )
    )
    return (instruction,)


def _pab_fail_to_receive(business_date: date, prices: dict[str, Decimal]) -> JournalEntry:
    """FIX-11 honest PAB stress: a declared PAB fail to receive, an Exhibit A Item 4 credit."""
    issue = sorted(prices)[0]
    quantity = Decimal(1_000_000)
    event_id = _id("evt_", 860_000_000)
    return JournalEntry(
        entry_id="FIX11-PAB-FAIL-TO-RECEIVE",
        source_event_id=event_id,
        source=PostingSource.CNS_FAIL,
        effective_date=business_date,
        effective_date_basis="SETTLEMENT_DATE",
        authority="FIX11_DECLARED_PAB_STRESS",
        lines=(
            LedgerLine(
                account_id="SYN-FIX11-PAB-ACCOUNT",
                account_type=AccountType.PAB,
                record_side=RecordSide.OWNERSHIP,
                issue=issue,
                quantity=quantity,
            ),
            LedgerLine(
                account_id="SYN-FIX11-FAIL-TO-RECEIVE",
                account_type=AccountType.FAIL_TO_RECEIVE,
                record_side=RecordSide.LOCATION,
                issue=issue,
                quantity=-quantity,
            ),
        ),
        reserve_source_facts=(
            ReserveSourceFact(
                account_type=AccountType.FAIL_TO_RECEIVE,
                issue=issue,
                activity=ReserveActivity.PAB,
                settlement_date=business_date,
                contract_price=prices[issue],
                fail_id="FIX11-PAB-FAIL-TO-RECEIVE",
            ),
        ),
        posting=BooksPosting(
            posted_record_id="FIX11-PAB-FAIL-TO-RECEIVE",
            posting_authority=_actor(),
            effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
            source_event_id=EventId(event_id),
            provenance=Provenance.FACT_SYNTHETIC,
        ),
        synthetic=True,
    )


def _pab_requirement_from_book_lines(
    customer_credits: Decimal,
    customer_debits: Decimal,
    pab_credits: Decimal,
    pab_debits: Decimal,
    customer_debit_reduction_rate: Decimal,
) -> Decimal:
    """Conserve the PAB requirement through customer excess-debit application."""
    customer_excess_debits = max(
        customer_debits - customer_debit_reduction_rate * customer_debits - customer_credits,
        Decimal(),
    )
    raw_pab_requirement = max(pab_credits - pab_debits, Decimal())
    return raw_pab_requirement - min(raw_pab_requirement, customer_excess_debits)


def _focus_tie_out(
    *,
    books: EquitiesBooks,
    business_date: date,
    customer: Any,
    pab: Any,
    capital: Any,
    control: Any,
    required_capital: Any,
    required_control: Any,
    reserve_oracle: ReserveRequirement,
    expected_customer_accounts: set[str],
    mutation: str | None,
) -> FirmFocusTieOut:
    """Tie independently read journal lines to each engine result at the real firm close."""

    customer_credits = reserve_oracle.customer_credits
    customer_debits = reserve_oracle.customer_debits
    book_control = (
        ()
        if required_control is None
        else tuple(
            (issue, max(quantity - required_control.in_control.get(issue, Decimal()), Decimal()))
            for issue, quantity in sorted(required_control.required.items())
        )
    )
    engine_control = tuple(
        (item.issue, item.shortfall) for item in sorted(control.issues, key=lambda item: item.issue)
    )
    observed_accounts = {
        line.account_id
        for entry in books.entries
        for line in entry.lines
        if line.account_type in {AccountType.CUSTOMER_CASH, AccountType.CUSTOMER_MARGIN}
    }
    book_shape = {
        "journal_entries": len(books.entries),
        "customer_accounts": len(observed_accounts),
        "ownership_lines": sum(
            line.record_side is RecordSide.OWNERSHIP
            for entry in books.entries
            for line in entry.lines
        ),
        "fail_lines": sum(
            line.account_type in {AccountType.FAIL_TO_RECEIVE, AccountType.FAIL_TO_DELIVER}
            for entry in books.entries
            for line in entry.lines
        ),
        "stock_loan_lines": sum(
            line.account_type is AccountType.STOCK_LOANED
            for entry in books.entries
            for line in entry.lines
        ),
    }
    book_lines = FirmFocusLines(
        net_capital=(None if required_capital is None else required_capital.net_capital),
        reserve_total_credits=customer_credits,
        reserve_total_debits=customer_debits,
        pab_reserve_requirement=reserve_oracle.pab_requirement,
        control_shortfall_by_issue=book_control,
    )
    engine_lines = FirmFocusLines(
        net_capital=capital.net_capital,
        reserve_total_credits=customer.total_credits,
        reserve_total_debits=customer.total_debits,
        pab_reserve_requirement=pab.requirement_after_customer_excess_debits,
        control_shortfall_by_issue=engine_control,
    )
    if mutation == "FOCUS_WRONG_NET_CAPITAL" and engine_lines.net_capital is not None:
        engine_lines = replace(engine_lines, net_capital=engine_lines.net_capital + Decimal("0.01"))
    if mutation == "FOCUS_WRONG_RESERVE_CREDIT" and engine_lines.reserve_total_credits is not None:
        engine_lines = replace(
            engine_lines,
            reserve_total_credits=engine_lines.reserve_total_credits + Decimal("0.01"),
        )
    if mutation == "FOCUS_WRONG_CONTROL_QUANTITY" and engine_lines.control_shortfall_by_issue:
        first, *rest = engine_lines.control_shortfall_by_issue
        issue, quantity = first
        engine_lines = replace(
            engine_lines,
            control_shortfall_by_issue=((issue, None if quantity is None else quantity + 1), *rest),
        )
    if mutation == "FOCUS_DROP_CUSTOMER_ACCOUNT" and observed_accounts:
        observed_accounts.remove(sorted(observed_accounts)[0])
    return tie_out_firm_close(
        close_date=business_date,
        books=book_lines,
        engines=engine_lines,
        expected_customer_accounts=tuple(sorted(expected_customer_accounts)),
        observed_customer_accounts=tuple(sorted(observed_accounts)),
        book_shape=book_shape,
    )


def _protections(  # noqa: PLR0915 - one control close keeps gate inputs visible
    books: EquitiesBooks,
    business_date: date,
    prices: dict[str, Decimal],
    profile: FirmProfile,
    run_number: int,
    mutation: str | None,
    expected_customer_accounts: set[str],
    *,
    net_worth: Decimal = Decimal("1000000000"),
    reserve_stress: ReserveStress | None = None,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, tuple[str, ...]],
    dict[str, Decimal | None],
    FirmFocusTieOut,
    tuple[EarlyWarningNotice, ...],
    tuple[ReserveDeposit, ...],
    bool,
    bool,
]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    rules = load_rule_table()
    forced = mutation == "FORCE_RESERVE_PASS_ON_SHORT_DAY"
    stressed = "customer" if forced else reserve_stress
    if stressed == "pab" and run_number == 0:
        books.post(_pab_fail_to_receive(business_date, prices))
    if stressed == "customer" and run_number == 0:
        event_id = _id("evt_", 830_000_000)
        books.post(
            JournalEntry(
                entry_id="SCF1-MUTATION-RESERVE-CREDIT",
                source_event_id=event_id,
                source=PostingSource.CASH_MOVEMENT,
                effective_date=business_date,
                effective_date_basis="VALUE_DATE",
                authority="PHASE2_REAL_INPUT_MUTATION",
                lines=(
                    LedgerLine(
                        account_id="SYN-SCF1-ACCOUNT-000000",
                        account_type=AccountType.CUSTOMER_CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=Decimal("1000000000.00"),
                    ),
                    LedgerLine(
                        account_id="FIRM-OPERATING-CASH",
                        account_type=AccountType.CASH,
                        record_side=RecordSide.MONEY,
                        currency="USD",
                        money=Decimal("-1000000000.00"),
                    ),
                ),
                posting=BooksPosting(
                    posted_record_id="SCF1-MUTATION-RESERVE-CREDIT",
                    posting_authority=_actor(),
                    effective_time=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
                    source_event_id=EventId(event_id),
                    provenance=Provenance.FACT_SYNTHETIC,
                ),
                synthetic=True,
            )
        )
    margins = tuple(
        compute_margin(
            account,
            trade_date=business_date,
            calendar=calendar,
            house_maintenance_rate=Decimal("0.30"),
            maintenance_call_due_business_days=2,
        )
        for account in project_margin_accounts(books, prices=prices)
    )
    projected = project_customer_protection(
        books,
        as_of=business_date,
        prices=prices,
        net_worth=net_worth,
        calendar=calendar,
        margin_results=margins,
        excess_margin_threshold=_rule_value(rules, EXCESS_MARGIN_THRESHOLD),
    )
    history = synthetic_filed_history(profile, business_date)
    average_credits = None if history is None else sum(history, Decimal()) / len(history)
    daily_threshold_met = average_credits is not None and average_credits >= Decimal("500000000")
    customer_inputs = _complete_reserve_inputs(
        projected.reserve,
        average_total_credits=average_credits,
        daily_requirement_effective_date=business_date if daily_threshold_met else None,
        computation_mode=(ComputationMode.DAILY if daily_threshold_met else ComputationMode.WEEKLY),
        previously_daily_required=False,
        daily_exit_notice_date=None,
    )
    if mutation == "PROJECTION_CUT_RESERVE_CREDIT":
        customer_inputs = customer_inputs.model_copy(
            update={
                "lines": tuple(
                    line.model_copy(update={"amount": line.amount - Decimal("1000.00")})
                    if line.rule_id == "15c3-3a.item.01" and line.amount is not None
                    else line
                    for line in customer_inputs.lines
                )
            }
        )
    pab_inputs = _complete_reserve_inputs(
        projected.pab_reserve,
        average_total_credits=average_credits,
        daily_requirement_effective_date=business_date if daily_threshold_met else None,
        computation_mode=(ComputationMode.DAILY if daily_threshold_met else ComputationMode.WEEKLY),
        previously_daily_required=False,
        daily_exit_notice_date=None,
    )
    customer = compute_reserve(customer_inputs, rules)
    pab = compute_reserve(with_customer_excess_debits(pab_inputs, customer), rules)
    reduction_rule = (
        DAILY_REDUCTION if customer_inputs.mode is ComputationMode.DAILY else WEEKLY_REDUCTION
    )
    reduction_item = rules.get(reduction_rule)
    if reduction_item is None or reduction_item.value is None:
        raise ValueError("RESERVE_ORACLE_REDUCTION_RATE_MISSING")
    reserve_oracle = required_reserve(
        books,
        as_of=business_date,
        prices=prices,
        customer_debit_reduction_rate=reduction_item.value,
    )
    opening_balances = reserve_bank_balances(books, through=date.max)
    deposit_outcome = "SHORT" if stressed == "customer" else "ON_TIME"
    customer, pab, deposits = _post_reserve_deposits(
        books=books,
        run_number=70_000 + run_number,
        business_date=business_date,
        calendar=calendar,
        actor=_actor(),
        rules=rules,
        reserve_inputs=customer_inputs,
        pab_reserve_inputs=pab_inputs,
        sized_from=(customer, pab),
        opening=(
            opening_balances[AccountType.RESERVE_BANK_CUSTOMER],
            opening_balances[AccountType.RESERVE_BANK_PAB],
        ),
        policy=DepositPolicy(
            customer=DepositDraw(deposit_outcome, profile.reserve_short_fraction),
            pab=DepositDraw(
                "SHORT" if stressed == "pab" else "ON_TIME", profile.reserve_short_fraction
            ),
            bank_equity_capital=profile.reserve_bank_equity_capital,
        ),
        opening_already_posted=True,
    )
    if forced:
        customer = customer.model_copy(update={"disposition": "PASS", "breaches": ()})
    capital_inputs = projected.net_capital.model_copy(
        update={
            "reports_lending_activity_monthly": False,
            "securities_loaned_and_repo_payable": Decimal(),
            "securities_borrowed_and_reverse_repo_value": Decimal(),
        }
    )
    capital = compute_net_capital(capital_inputs, rules)
    control = check_possession_or_control(projected.control, rules)
    dispositions = {
        "reserve": str(customer.disposition),
        "pab_reserve": str(pab.disposition),
        "net_capital": str(capital.disposition),
        "possession_or_control": str(control.disposition),
    }
    reasons = {
        "reserve": customer.reasons + customer.missing_inputs + customer.breaches,
        "pab_reserve": pab.reasons + pab.missing_inputs + pab.breaches,
        "net_capital": capital.reasons + capital.missing_inputs + capital.breaches,
        "possession_or_control": control.reasons + control.missing_inputs + control.breaches,
    }
    # Every required outcome comes from declared inputs and the books, never from an
    # engine's own disposition, breaches, reasons or missing inputs (FIX-11 D1).
    reserve_holds = {item.computation: item.outcome in DEPOSIT_BREACH_OUTCOMES for item in deposits}
    required_capital = required_net_capital(books, prices, net_worth, rules)
    required_control = required_possession_or_control(books, prices, rules)

    def total(lines: tuple[Any, ...], rule_ids: tuple[str, ...]) -> Decimal | None:
        selected = [line.amount for line in lines if line.rule_id in rule_ids]
        return (
            None
            if any(value is None for value in selected)
            else sum((cast(Decimal, value) for value in selected), Decimal())
        )

    projected_customer_credits = total(customer_inputs.lines, EXHIBIT_A_CREDITS)
    projected_customer_debits = total(customer_inputs.lines, EXHIBIT_A_DEBITS)
    projected_pab_credits = total(pab_inputs.lines, EXHIBIT_A_CREDITS)
    projected_pab_debits = total(pab_inputs.lines, EXHIBIT_A_DEBITS)
    required = {
        "reserve": "HOLD"
        if reserve_holds["customer"]
        or customer.requirement != reserve_oracle.customer_requirement
        or projected_customer_credits != reserve_oracle.customer_credits
        or projected_customer_debits != reserve_oracle.customer_debits
        else "PASS",
        "pab_reserve": "HOLD"
        if reserve_holds["pab"]
        or pab.requirement_after_customer_excess_debits != reserve_oracle.pab_requirement
        or projected_pab_credits != reserve_oracle.pab_credits
        or projected_pab_debits != reserve_oracle.pab_debits
        else "PASS",
        "net_capital": ("UNDERIVABLE" if required_capital is None else required_capital.outcome),
        "possession_or_control": (
            "UNDERIVABLE" if required_control is None else required_control.outcome
        ),
    }

    figures = {
        "customer_credits": total(customer_inputs.lines, EXHIBIT_A_CREDITS),
        "customer_debits": total(customer_inputs.lines, EXHIBIT_A_DEBITS),
        "average_total_credits": average_credits,
        "reserve_requirement": customer.requirement,
        "pab_reserve_requirement": pab.requirement,
        "net_capital": capital.net_capital,
        "control_shortfall": sum(
            (item.shortfall for item in control.issues if item.shortfall is not None), Decimal()
        ),
        "firm_proprietary_market_value": sum(
            (
                position.long_market_value - position.short_market_value
                for position in capital_inputs.positions
            ),
            Decimal(),
        ),
    }
    if required_capital is not None:
        figures["independent_net_capital"] = required_capital.net_capital
    if required_control is not None:
        figures["independent_control_short_issues"] = Decimal(len(required_control.short_issues))
    focus_tie_out = _focus_tie_out(
        books=books,
        business_date=business_date,
        customer=customer,
        pab=pab,
        capital=capital,
        control=control,
        required_capital=required_capital,
        required_control=required_control,
        reserve_oracle=reserve_oracle,
        expected_customer_accounts=expected_customer_accounts,
        mutation=mutation,
    )
    notices = draft_notices(capital.early_warnings, business_date)
    if mutation == "EARLY_WARNING_MISSING_DRAFT" and notices:
        notices = notices[1:]
    if mutation == "EARLY_WARNING_MISSING_OWNER" and notices:
        notices = (replace(notices[0], owner_role=None), *notices[1:])
    return (
        dispositions,
        required,
        reasons,
        figures,
        focus_tie_out,
        notices,
        deposits,
        warning_workflow_held(capital.early_warnings, notices),
        all(dispositions[name] == expected for name, expected in required.items()),
    )


def _rule_value(table: Any, rule_id: str) -> Decimal | None:
    item = table.get(rule_id)
    return None if item is None else cast(Decimal | None, item.value)


def run_firm(  # noqa: PLR0915 - one run keeps the independent evidence sources visible
    profile: FirmProfile,
    *,
    seed: int = 20261024,
    days: int = 5,
    start: date = date(2027, 1, 4),
    mutation: str | None = None,
    verify_replay: bool = True,
    net_worth: Decimal = Decimal("1000000000"),
    reserve_stress: ReserveStress | None = None,
    early_warning_stress: bool = False,
) -> FirmRun:
    if mutation is not None and mutation not in MUTATIONS:
        raise ValueError(f"unknown firm mutation: {mutation}")
    books = EquitiesBooks(break_owner="SCF1_SETTLEMENT_CONTROL")
    _seed_inventory(books, profile, start, days)
    opening_depository = _opening_street(profile, days)
    street = SyntheticDepository(opening_depository)
    prior_breaks: tuple[StreetBreak, ...] = ()
    opening_positions, opening_cash = _balances(books)
    if mutation == "WRONG_OPENING_POSITION":
        opening_positions[next(iter(opening_positions))] += 1
    closes: list[FirmDay] = []
    carried_fails: dict[str, tuple[OpenFail, ...]] = {}
    loan_register = LoanRegister()
    all_settlement_outcomes: list[SettlementOutcome] = []
    instruction_log = InstructionLog()
    started = time.perf_counter()
    total_executions = 0
    expected_customer_accounts = {
        line.account_id
        for entry in books.entries
        for line in entry.lines
        if line.account_type in {AccountType.CUSTOMER_CASH, AccountType.CUSTOMER_MARGIN}
    }
    for day_index, business_date in enumerate(_business_dates(start, days)):
        executions = draw_executions(profile, business_date, seed)
        total_executions += len(executions)
        accepted = tuple(execution for execution in executions if not execution.refused)
        expected_customer_accounts.update(
            execution.account for execution in accepted if not execution.pab
        )
        groups: dict[tuple[str, str], list[FirmExecution]] = defaultdict(list)
        for execution in accepted:
            groups[(execution.issue, execution.side)].append(execution)
        activity_positions: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        activity_cash: dict[str, Decimal] = defaultdict(Decimal)
        carried_input = (
            {} if mutation == "AGE_FAIL_WITHOUT_CARRY" and day_index == 1 else carried_fails
        )
        cns_trades: list[tuple[str, Decimal]] = [
            (issue, sum((fail.quantity for fail in fails), Decimal()))
            for issue, fails in carried_input.items()
        ]
        posted: list[JournalEntry] = []
        for batch_index, (_, rows_list) in enumerate(sorted(groups.items())):
            rows = tuple(rows_list)
            sequence = day_index * 10_000 + batch_index
            allocations = _lc_allocate_batch(rows, business_date, sequence)
            if mutation == "UPSTREAM_ALLOCATION_QUANTITY" and day_index == 0 and batch_index == 0:
                first = allocations[0]
                allocations = (
                    (first[0], first[1] + Decimal(1), first[2]),
                    *allocations[1:],
                )
            entry = _post_batch(
                books,
                rows,
                allocations,
                business_date,
                sequence,
                profile.margin_account_share,
            )
            settlement_sign = Decimal(1) if rows[0].side == "BUY" else Decimal(-1)
            instruction_log.append(
                MoneyInstruction(
                    f"SCF1-CNS-MONEY-{sequence}",
                    business_date,
                    settlement_sign
                    * sum((consideration for _, _, consideration in allocations), Decimal()),
                    InstructionKind.CNS_SETTLEMENT,
                    "CLEARING",
                )
            )
            if (
                mutation in {"DROP_FILL_FROM_BOOKS", "STREET_MOVEMENT_BOOKS_MISSED"}
                and day_index == 0
                and batch_index == 0
            ):
                reversal_event = _id("evt_", 810_000_000)
                books.post(
                    entry.model_copy(
                        update={
                            "entry_id": entry.entry_id + "-DROP-REVERSAL",
                            "source_event_id": reversal_event,
                            "source": PostingSource.REVERSAL,
                            "lines": tuple(
                                line.model_copy(
                                    update={"quantity": -line.quantity, "money": -line.money}
                                )
                                for line in entry.lines
                            ),
                            "posting": entry.posting.model_copy(
                                update={
                                    "posted_record_id": entry.entry_id + "-DROP-REVERSAL",
                                    "source_event_id": EventId(reversal_event),
                                }
                            ),
                            "reverses_entry_id": entry.entry_id,
                        }
                    )
                )
            else:
                posted.append(entry)
            if (
                mutation in {"DOUBLE_POST_NEW_EVENT", "DUPLICATE_BOOKING"}
                and day_index == 0
                and batch_index == 0
            ):
                duplicate_event = _id("evt_", 820_000_000)
                books.post(
                    entry.model_copy(
                        update={
                            "entry_id": entry.entry_id + "-DOUBLE",
                            "source_event_id": duplicate_event,
                            "posting": entry.posting.model_copy(
                                update={
                                    "posted_record_id": entry.entry_id + "-DOUBLE",
                                    "source_event_id": EventId(duplicate_event),
                                }
                            ),
                        }
                    )
                )
            sign = Decimal(1) if rows[0].side == "BUY" else Decimal(-1)
            for account, quantity, consideration in allocations:
                activity_positions[(account, rows[0].issue)] += sign * quantity
                activity_cash[account] += -sign * consideration
            if mutation == "WRONG_LOCATION_BOOKING" and day_index == 0 and batch_index == 0:
                _post_wrong_location(books, business_date, rows[0].issue)
            cns_trades.extend((row.issue, row.signed_quantity) for row in rows)
        prices = {execution.issue: execution.price for execution in executions}
        borrow_activity = _post_stock_borrows(
            books, carried_input, business_date, prices, day_index
        )
        settlements = []
        profile_cns = MarketProfile(
            market_id="NSCC_SYNTHETIC",
            settlement_cycle_days=1,
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            close_out_deadline_days=3,
            allocation_rule_published=True,
            provenance="SCF-1 declared synthetic profile",
        )
        cns_positions = net_positions(
            tuple(cns_trades), market_id="NSCC_SYNTHETIC", settlement_date_offset_days=1
        )
        omitted_issue = cns_positions[0].security_id if cns_positions else None
        next_fails: dict[str, tuple[OpenFail, ...]] = {}
        settlement_outcomes: list[SettlementOutcome] = []
        for position in cns_positions:
            if (
                mutation == "OMIT_ISSUE_FROM_CNS"
                and day_index == 0
                and position.security_id == omitted_issue
            ):
                continue
            carried = carried_input.get(position.security_id, ())
            carried_quantity = sum((fail.quantity for fail in carried), Decimal())
            carried_cash = sum((fail.cash for fail in carried), Decimal())
            mark = prices.get(position.security_id)
            if mark is None and carried_quantity:
                mark = abs(carried_cash / carried_quantity)
                prices[position.security_id] = mark
            if mark is None:
                raise ValueError(f"missing synthetic mark for {position.security_id}")
            cash = (position.quantity * mark).quantize(Decimal("0.01"))
            allocated_quantity = (position.quantity * (Decimal(1) - profile.fail_rate)).quantize(
                Decimal("1")
            )
            allocated_cash = (cash * (Decimal(1) - profile.fail_rate)).quantize(Decimal("0.01"))
            calendar = MarketCalendar.load(Market.US_EQUITIES)
            new_settlement_date = calendar.add_business_days(
                business_date, position.settlement_date_offset_days
            )
            settlement_date = min(
                (fail.opening_settlement_date for fail in carried),
                default=new_settlement_date,
            )
            result = settle_net_position(
                position,
                profile_cns,
                allocated_quantity=allocated_quantity,
                signed_cash=cash,
                allocated_cash=allocated_cash,
                settlement_date=settlement_date,
                as_of_date=business_date,
                calendar=calendar,
            )
            settlements.append(result)
            if result.residual is not None:
                next_fails[position.security_id] = _roll_fail_lots(
                    position.security_id,
                    result.residual.quantity,
                    result.residual.cash,
                    carried,
                    new_settlement_date,
                    mark,
                )
            current_fails = next_fails.get(position.security_id, ())
            new_trade_quantity = position.quantity - carried_quantity
            fail_delta = sum(
                (
                    _fail_posting_delta(
                        {fail.fail_id: fail for fail in carried}.get(fail_id),
                        {fail.fail_id: fail for fail in current_fails}.get(fail_id),
                        business_date,
                    )
                    for fail_id in set(fail.fail_id for fail in carried)
                    | set(fail.fail_id for fail in current_fails)
                ),
                Decimal(),
            )
            settlement_outcomes.append(
                SettlementOutcome(
                    issue=position.security_id,
                    net_quantity=new_trade_quantity - fail_delta,
                    allocated_quantity=result.allocated_quantity,
                    settlement_date=settlement_date,
                )
            )
        _post_fail_to_receive_movements(
            books,
            carried_input,
            next_fails,
            business_date,
            day_index,
            mutation,
        )
        source_outcomes = tuple(settlement_outcomes)
        if mutation == "BOOKED_QUANTITY_STREET_LACKS" and day_index == 0:
            source_outcomes = source_outcomes[1:]
        street.apply_settlements(source_outcomes)
        all_settlement_outcomes.extend(source_outcomes)
        instructions = _post_control_deficit(
            books, loan_register, profile, business_date, prices, day_index, days
        )
        street.apply_instructions(instructions)
        closing_positions, closing_cash = _balances(books)
        full_position_activity = dict(activity_positions)
        for key, quantity in borrow_activity.items():
            full_position_activity[key] = full_position_activity.get(key, Decimal()) + quantity
        expected_positions, expected_cash = roll_forward(
            opening_positions, opening_cash, full_position_activity, dict(activity_cash)
        )
        i11 = expected_positions == closing_positions and expected_cash == closing_cash
        booked_position_activity: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        booked_cash_activity: dict[str, Decimal] = defaultdict(Decimal)
        for entry in books.entries:
            if (
                entry.source is not PostingSource.CNS_SETTLEMENT
                or entry.effective_date != business_date
                or entry.authority != "NSCC_SYNTHETIC"
            ):
                continue
            for line in entry.lines:
                if line.record_side is RecordSide.OWNERSHIP and line.issue is not None:
                    booked_position_activity[(line.account_id, line.issue)] += line.quantity
                elif (
                    line.record_side is RecordSide.MONEY
                    and line.account_type is not AccountType.CASH
                ):
                    booked_cash_activity[line.account_id] += line.money
        i1 = (
            dict(activity_positions) == dict(booked_position_activity)
            and dict(activity_cash) == dict(booked_cash_activity)
            and len(posted) == len(groups)
        )
        posted_sources = {
            entry.source_event_id
            for entry in posted
            if entry.source is PostingSource.CNS_SETTLEMENT
        }
        i2 = len(posted_sources) == len(posted) == len(groups)
        before = books.digest()
        duplicates_refused = all(not books.post(entry).posted for entry in posted)
        i12 = duplicates_refused and before == books.digest()
        replay_digest = books.digest()
        open_fails = tuple(fail for issue_lots in next_fails.values() for fail in issue_lots)
        source_opening = opening_depository
        if mutation == "DEPOSITORY_ONE_SHARE" and day_index == 0:
            first_position = source_opening[0]
            source_opening = (
                DepositoryPosition(
                    first_position.issue,
                    first_position.location,
                    first_position.quantity + Decimal(1),
                ),
                *source_opening[1:],
            )
        source_inputs = IndependentSourceInputs(
            as_of=business_date,
            opening_depository=source_opening,
            settlement_outcomes=tuple(all_settlement_outcomes),
            open_fails=open_fails,
            loan_instructions=loan_register.instructions,
        )
        independent_readers = build_independent_sources(books, source_inputs)
        street_readers = independent_readers
        if mutation == "STREET_ONE_SHARE" and day_index == 0:
            depository_reader = independent_readers[0]

            def read_one_share_street_difference(
                reader: ObservedSourceReader = depository_reader,
            ) -> PositionSource:
                source = reader.read()
                first_position = source.positions[0]
                return PositionSource(
                    source.name,
                    source.location,
                    source.as_of,
                    (
                        DepositoryPosition(
                            first_position.issue,
                            first_position.location,
                            first_position.quantity + Decimal(1),
                        ),
                        *source.positions[1:],
                    ),
                )

            street_readers = (
                ObservedSourceReader(depository_reader.name, read_one_share_street_difference),
                *independent_readers[1:],
            )
        if mutation == "UNSOURCED_BANK_CONTROL" and day_index == 0:
            _post_unsourced_bank_control(books, business_date, f"SYN-SCF1-ISSUE-{0:04d}")
        reconciliation_specs = (
            (
                "stock-record-to-street",
                "DTC",
                street_readers[0],
            ),
            (
                "ftr-to-cns-fail-statement",
                "FAIL_TO_RECEIVE",
                street_readers[1],
            ),
            (
                "stock-loan-to-contract-register",
                "STOCK_LOANED",
                street_readers[2],
            ),
        )
        observed_results = tuple(
            reconcile_observed_street(
                books,
                reader,
                tuple(item for item in prior_breaks if item.location == location),
                as_of=business_date,
                item_id=item_id,
                failure_location=location,
            )
            for item_id, location, reader in reconciliation_specs
        )
        breaks = tuple(item for item_breaks, _ in observed_results for item in item_breaks)
        source_completions = tuple(completion for _, completion in observed_results)
        if mutation == "UNPOSTED_DEPOSIT_INSTRUCTION" and day_index == 0:
            instruction_log.append(
                MoneyInstruction(
                    "SCF1-MUTATION-UNPOSTED-DEPOSIT",
                    business_date,
                    Decimal("1.00"),
                    InstructionKind.CUSTOMER_DEPOSIT,
                    "FIRM-OPERATING-CASH",
                )
            )
        if mutation == "RESERVE_DEPOSIT_NOT_RECEIVED" and day_index == 0:
            books.post(
                _deposit_entry(
                    entry_id="SCF1-MUTATION-RESERVE-NOT-RECEIVED",
                    event_number=870_000_000,
                    account_type=AccountType.RESERVE_BANK_CUSTOMER,
                    amount=Decimal("1.00"),
                    effective=business_date,
                    authority="PS3C_SYNTHETIC_RESERVE_RECEIPT_MUTATION",
                    actor=_actor(),
                )
            )
            instruction_log.append(
                MoneyInstruction(
                    "SCF1-MUTATION-RESERVE-STATEMENT-RECEIVED",
                    business_date,
                    Decimal(),
                    InstructionKind.RESERVE_TRANSFER,
                    "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
                )
            )
            instruction_log.append(
                MoneyInstruction(
                    "SCF1-MUTATION-RESERVE-CASH-RECEIVED",
                    business_date,
                    Decimal("-1.00"),
                    InstructionKind.RESERVE_TRANSFER,
                    "FIRM-OPERATING-CASH",
                )
            )
        cash_statement = instruction_log.statement(
            "synthetic-firm-bank",
            business_date,
            kinds=frozenset(
                {
                    InstructionKind.OPENING,
                    InstructionKind.CNS_SETTLEMENT,
                    InstructionKind.CUSTOMER_DEPOSIT,
                    InstructionKind.RESERVE_TRANSFER,
                }
            ),
            account_ids=frozenset({"CLEARING", "FIRM-OPERATING-CASH"}),
        )
        cash_result = reconcile_ps1("cash-to-bank", books, cash_statement, business_date)
        reserve_statement = instruction_log.statement(
            "synthetic-reserve-banks",
            business_date,
            kinds=frozenset({InstructionKind.RESERVE_TRANSFER}),
            account_ids=frozenset(
                {
                    "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
                    "RESERVE_BANK_PAB@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
                }
            ),
        )
        if mutation == "RESERVE_DEPOSIT_NOT_RECEIVED" and day_index == 0:
            instruction_log.append(
                MoneyInstruction(
                    "SCF1-MUTATION-RESERVE-NOT-RECEIVED",
                    business_date,
                    Decimal("1.00"),
                    InstructionKind.RESERVE_TRANSFER,
                    "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK",
                )
            )
        reserve_result = reconcile_ps1(
            "reserve-bank-to-books", books, reserve_statement, business_date
        )
        count_confirmation_rows: list[SecuritiesConfirmation] = []
        count_source_failed = False
        for reader in independent_readers:
            try:
                source = reader.read()
            except Exception:
                count_source_failed = True
                continue
            count_confirmation_rows.extend(
                SecuritiesConfirmation(
                    f"{reader.name}:{position.issue}:{position.location}",
                    business_date,
                    position.issue,
                    position.location,
                    -position.quantity,
                )
                for position in source.positions
            )
        count_confirmations = tuple(count_confirmation_rows)
        securities_count = build_securities_count(count_confirmations, business_date)
        securities_result = reconcile_ps1(
            "securities-count", books, securities_count, business_date
        )
        if count_source_failed:
            securities_result = securities_result.__class__(
                securities_result.item_id,
                ControlStatus.FAILED,
                securities_result.breaks,
                securities_result.sources_read,
            )
        source_completions += tuple(
            ReconciliationCompletion(
                result.item_id,
                business_date,
                result.sources_read,
                len(result.breaks),
                (
                    ReconciliationStatus.FAILED
                    if result.status == ControlStatus.FAILED or result.breaks
                    else ReconciliationStatus.COMPLETED
                ),
                (
                    "source failure or reconciliation differences detected"
                    if result.status == ControlStatus.FAILED or result.breaks
                    else None
                ),
            )
            for result in (cash_result, reserve_result, securities_result)
        )
        reconciled_sources = tuple(
            reader.read()
            for (_, _, reader), completion in zip(
                reconciliation_specs,
                source_completions[: len(reconciliation_specs)],
                strict=True,
            )
            if completion.status == "COMPLETED"
        )
        completion = source_completions[0]
        prior_breaks = breaks
        (
            protections,
            required_outcomes,
            protection_reasons,
            protection_figures,
            focus_tie_out,
            early_warning_notices,
            reserve_deposits,
            i14,
            i6,
        ) = _protections(
            books,
            business_date,
            prices,
            profile,
            day_index,
            mutation,
            expected_customer_accounts,
            net_worth=(Decimal("10000") if early_warning_stress else net_worth),
            reserve_stress=reserve_stress,
        )
        for deposit in reserve_deposits:
            if deposit.deposit_date is None or not deposit.amount:
                continue
            instruction_log.append(
                MoneyInstruction(
                    f"SCF1-RESERVE-{day_index}-{deposit.computation}",
                    deposit.deposit_date,
                    deposit.amount,
                    InstructionKind.RESERVE_TRANSFER,
                    (
                        "RESERVE_BANK_CUSTOMER@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK"
                        if deposit.computation == "customer"
                        else "RESERVE_BANK_PAB@SYNTHETIC-NON-AFFILIATED-RESERVE-BANK"
                    ),
                )
            )
            instruction_log.append(
                MoneyInstruction(
                    f"SCF1-RESERVE-CASH-{day_index}-{deposit.computation}",
                    deposit.deposit_date,
                    -deposit.amount,
                    InstructionKind.RESERVE_TRANSFER,
                    "FIRM-OPERATING-CASH",
                )
            )
        carry_complete = set(carried_fails) <= set(carried_input)
        covered_cns_issues = {item.position.security_id for item in settlements}
        invariants = {
            "I1_QUANTITY_MONEY_CONSERVE": i1,
            "I2_BOOKED_FROM_REPORTS": i2,
            "I3_STOCK_RECORD_EQUALS_STREET": _reconciliation_held(
                source_completions,
                tuple(item_id for item_id, _, _ in reconciliation_specs),
                breaks,
            ),
            "I4_EVERY_DIFFERENCE_OWNED": all(item.owner for item in breaks) and carry_complete,
            "I5_RESIDUALS_TWO_SIDED": all(
                result.residual is None
                or (result.residual.quantity is not None and result.residual.cash is not None)
                for result in settlements
            )
            and {position.security_id for position in cns_positions} <= covered_cns_issues,
            "I6_DEFAULT_AND_STALE_HOLD": i6,
            "I7_MARKET_ACCESS_REFUSES": bool(tuple(item for item in executions if item.refused))
            and all(item.quantity > profile.order_size_max for item in executions if item.refused)
            and all(
                item.quantity <= profile.order_size_max for item in executions if not item.refused
            ),
            # The reserve engines can post authorized same-day deposits after the
            # duplicate replay check. I8 measures that replay check, not the later
            # protection movements that become the next day's opening books.
            "I8_REPLAY_DIGEST": before == replay_digest,
            "I11_POSITION_ROLL_FORWARD": i11,
            "I12_IDEMPOTENT_REPLAY": i12,
            "I13_FOCUS_TIE_OUT": focus_tie_out.held,
            "I16_EARLY_WARNING_DRAFT_OWNED": i14,
        }
        fails_by_age: dict[str, int] = defaultdict(int)
        for settlement in settlements:
            if settlement.residual is not None:
                fails_by_age[str(settlement.residual.aged_business_days)] += 1
        closes.append(
            FirmDay(
                business_date=business_date,
                executions=len(executions),
                invariants=invariants,
                fails_by_age=dict(fails_by_age),
                breaks_by_owner=dict(
                    defaultdict(
                        int,
                        {
                            item.owner: sum(
                                1 for candidate in breaks if candidate.owner == item.owner
                            )
                            for item in breaks
                        },
                    )
                ),
                street_breaks=breaks,
                reconciliation_completion=completion,
                reconciliation_calendar=reconciliation_calendar(business_date, source_completions),
                source_inputs=source_inputs,
                reconciled_sources=reconciled_sources,
                protection_dispositions=protections,
                protection_required=required_outcomes,
                protection_reasons=protection_reasons,
                protection_figures=protection_figures,
                focus_tie_out=focus_tie_out,
                early_warning_notices=early_warning_notices,
                rule_204_close_outs={
                    issue: rule_204_deadline(
                        settlement_date=settlement_date,
                        sale_kind="SHORT",
                        calendar=MarketCalendar.load(Market.US_EQUITIES),
                    )
                    for issue, fails in carried_input.items()
                    for fail in fails
                    for settlement_date in (fail.opening_settlement_date,)
                },
                economics_digest="sha256:"
                + hashlib.sha256(
                    canonical_bytes_of(
                        {
                            "entries": books.entries,
                            "cns": [asdict(item) for item in settlements],
                        }
                    )
                ).hexdigest(),
            )
        )
        # Protection posts same-day reserve movements after the trading close.
        # They are real book activity and therefore form the next day's opening.
        opening_positions, opening_cash = _balances(books)
        carried_fails = next_fails
    elapsed = time.perf_counter() - started
    peak_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith("linux"):
        peak_memory *= 1024
    firm_run = FirmRun(
        profile=profile,
        seed=seed,
        days=tuple(closes),
        elapsed_seconds=elapsed,
        executions_per_second=total_executions / elapsed,
        peak_memory_bytes=peak_memory,
    )
    if verify_replay:
        replay = run_firm(
            profile,
            seed=seed,
            days=days,
            start=start,
            mutation=mutation,
            verify_replay=False,
            net_worth=net_worth,
            reserve_stress=reserve_stress,
            early_warning_stress=early_warning_stress,
        )
        firm_run = replace(
            firm_run,
            peak_memory_bytes=max(
                value
                for value in (firm_run.peak_memory_bytes, replay.peak_memory_bytes)
                if value is not None
            ),
            days=tuple(
                replace(
                    day,
                    invariants={
                        **day.invariants,
                        "I8_REPLAY_DIGEST": day.economics_digest == other.economics_digest,
                    },
                )
                for day, other in zip(firm_run.days, replay.days, strict=True)
            ),
        )
    return firm_run


def publish_firm(run: FirmRun, output: Path) -> None:
    from simulator.runner import publish_run

    payload = asdict(run)
    payload["firm_profile"] = payload["profile"]
    payload["closes"] = payload.pop("days")
    payload["all_invariants_pass"] = all(all(day.invariants.values()) for day in run.days)
    publish_run(payload, output)
