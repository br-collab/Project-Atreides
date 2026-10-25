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
from lc.events import LifecycleState
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
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
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
from simulator.estate import (
    DEPOSIT_BREACH_OUTCOMES,
    DepositDraw,
    DepositPolicy,
    _complete_reserve_inputs,
    _post_reserve_deposits,
    _wire,
    simulated_filed_credit_total,
)
from simulator.protection_oracle import EXCESS_MARGIN_THRESHOLD, required_net_capital
from simulator.protection_oracle import required_control as required_possession_or_control
from simulator.settlement import rule_204_deadline

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
    seed_stream: str
    synthetic: bool = True
    #: FIX-11 declared control deficit: (day index, issue index, shares short), or None.
    control_deficit: tuple[int, int, Decimal] | None = None


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
    protection_dispositions: dict[str, str]
    protection_required: dict[str, str]
    protection_reasons: dict[str, tuple[str, ...]]
    protection_figures: dict[str, Decimal | None]
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
    not_claimed: tuple[str, ...] = NOT_CLAIMED


MUTATIONS = (
    "DROP_FILL_FROM_BOOKS",
    "DOUBLE_POST_NEW_EVENT",
    "OMIT_ISSUE_FROM_CNS",
    "WRONG_OPENING_POSITION",
    "FORCE_RESERVE_PASS_ON_SHORT_DAY",
    "AGE_FAIL_WITHOUT_CARRY",
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
        seed_stream=str(pack.value("firm_profile", "seed_stream")),
        control_deficit=_control_deficit(pack),
    )


def _control_deficit(pack: CalibrationPack) -> tuple[int, int, Decimal] | None:
    try:
        declared = cast(dict[str, object], pack.value("firm_profile", "control_deficit"))
    except (KeyError, ValueError):
        return None
    return (
        int(cast(int, declared["day_index"])),
        int(cast(int, declared["issue_index"])),
        Decimal(str(declared["shortfall_shares"])),
    )


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
                order_id=child, quantity=total, event=_event(4_000_003 + sequence * 10, base)
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


def _seed_inventory(books: EquitiesBooks, profile: FirmProfile, start: date, days: int) -> None:
    """Declare synthetic opening firm inventory sufficient for generated sells and shorts."""
    per_issue = Decimal(profile.executions_per_day * profile.order_size_max * days)
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
                    LedgerLine(
                        account_id="SYN-SCF1-FIRM-INVENTORY",
                        account_type=AccountType.FIRM_PROPRIETARY,
                        record_side=RecordSide.OWNERSHIP,
                        issue=issue,
                        quantity=per_issue,
                    ),
                    LedgerLine(
                        account_id="DTC",
                        account_type=AccountType.DTC,
                        record_side=RecordSide.LOCATION,
                        issue=issue,
                        quantity=-per_issue,
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
    carried_fails: dict[str, tuple[Decimal, Decimal, date]],
    business_date: date,
    prices: dict[str, Decimal],
    day_index: int,
) -> dict[tuple[str, str], Decimal]:
    """Post declared synthetic borrows that cover open CNS fails through the real books."""
    activity: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for offset, (issue, (quantity, cash, settlement_date)) in enumerate(
        sorted(carried_fails.items())
    ):
        if quantity == 0:
            continue
        event_id = _id("evt_", 840_000_000 + day_index * 10_000 + offset)
        borrowed = abs(quantity)
        activity[("SYN-SCF2-STOCK-BORROWED", issue)] += borrowed
        activity[("SYN-SCF1-FIRM-INVENTORY", issue)] -= borrowed
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
                        account_id="SYN-SCF1-FIRM-INVENTORY",
                        account_type=AccountType.FIRM_PROPRIETARY,
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
    profile: FirmProfile,
    business_date: date,
    prices: dict[str, Decimal],
    day_index: int,
) -> None:
    """Post the declared stock loan that leaves one issue short of control, then recall it.

    The loan moves firm inventory from DTC (a Rule 15c3-3(c) control location) to stock
    loaned (a (d)(1) noncontrol location). Ownership does not change, so the stock record
    still balances. The loan is sized from the independent requirement, so the issue is
    short by exactly the declared number of shares on the declared close.
    """
    if profile.control_deficit is None:
        return
    deficit_day, issue_index, shortfall = profile.control_deficit
    issue = f"SYN-SCF1-ISSUE-{issue_index:04d}"
    if day_index == deficit_day + 1:
        loaned = sum(
            (
                -line.quantity
                for entry in books.entries
                if entry.authority == "FIX11_DECLARED_CONTROL_DEFICIT"
                for line in entry.lines
                if line.account_type is AccountType.STOCK_LOANED
            ),
            Decimal(),
        )
        if loaned:
            books.post(
                _loan_entry(
                    f"FIX11-RECALL-{day_index}", 850_000_001, issue, -loaned, business_date
                )
            )
        return
    if day_index != deficit_day:
        return
    requirement = required_possession_or_control(books, prices, load_rule_table())
    if requirement is None:
        raise ValueError("the control deficit needs a derivable control requirement")
    required = requirement.required.get(issue, Decimal())
    held = requirement.in_control.get(issue, Decimal())
    loan = held - required + shortfall
    if loan <= 0 or loan > held:
        raise ValueError(f"declared control deficit cannot be built for {issue}")
    books.post(_loan_entry(f"FIX11-LOAN-{day_index}", 850_000_000, issue, loan, business_date))


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


def _protections(
    books: EquitiesBooks,
    business_date: date,
    prices: dict[str, Decimal],
    profile: FirmProfile,
    run_number: int,
    mutation: str | None,
    *,
    net_worth: Decimal = Decimal("1000000000"),
    reserve_stress: ReserveStress | None = None,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, tuple[str, ...]],
    dict[str, Decimal | None],
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
    required = {
        "reserve": "HOLD" if reserve_holds["customer"] else "PASS",
        "pab_reserve": "HOLD" if reserve_holds["pab"] else "PASS",
        "net_capital": (
            "UNDERIVABLE" if required_capital is None else required_capital.outcome
        ),
        "possession_or_control": (
            "UNDERIVABLE" if required_control is None else required_control.outcome
        ),
    }

    def total(lines: tuple[Any, ...], rule_ids: tuple[str, ...]) -> Decimal | None:
        selected = [line.amount for line in lines if line.rule_id in rule_ids]
        return (
            None
            if any(value is None for value in selected)
            else sum((cast(Decimal, value) for value in selected), Decimal())
        )

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
    }
    if required_capital is not None:
        figures["independent_net_capital"] = required_capital.net_capital
    if required_control is not None:
        figures["independent_control_short_issues"] = Decimal(len(required_control.short_issues))
    return (
        dispositions,
        required,
        reasons,
        figures,
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
) -> FirmRun:
    if mutation is not None and mutation not in MUTATIONS:
        raise ValueError(f"unknown firm mutation: {mutation}")
    books = EquitiesBooks(break_owner="SCF1_SETTLEMENT_CONTROL")
    _seed_inventory(books, profile, start, days)
    opening_positions, opening_cash = _balances(books)
    if mutation == "WRONG_OPENING_POSITION":
        opening_positions[next(iter(opening_positions))] += 1
    closes: list[FirmDay] = []
    carried_fails: dict[str, tuple[Decimal, Decimal, date]] = {}
    started = time.perf_counter()
    total_executions = 0
    for day_index, business_date in enumerate(_business_dates(start, days)):
        executions = draw_executions(profile, business_date, seed)
        total_executions += len(executions)
        accepted = tuple(execution for execution in executions if not execution.refused)
        groups: dict[tuple[str, str], list[FirmExecution]] = defaultdict(list)
        for execution in accepted:
            groups[(execution.issue, execution.side)].append(execution)
        activity_positions: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        activity_cash: dict[str, Decimal] = defaultdict(Decimal)
        carried_input = (
            {} if mutation == "AGE_FAIL_WITHOUT_CARRY" and day_index == 1 else carried_fails
        )
        cns_trades: list[tuple[str, Decimal]] = [
            (issue, quantity) for issue, (quantity, _, _) in carried_input.items()
        ]
        posted: list[JournalEntry] = []
        for batch_index, (_, rows_list) in enumerate(sorted(groups.items())):
            rows = tuple(rows_list)
            sequence = day_index * 10_000 + batch_index
            allocations = _lc_allocate_batch(rows, business_date, sequence)
            entry = _post_batch(
                books,
                rows,
                allocations,
                business_date,
                sequence,
                profile.margin_account_share,
            )
            if mutation == "DROP_FILL_FROM_BOOKS" and day_index == 0 and batch_index == 0:
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
            if mutation == "DOUBLE_POST_NEW_EVENT" and day_index == 0 and batch_index == 0:
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
            cns_trades.extend((row.issue, row.signed_quantity) for row in rows)
        prices = {execution.issue: execution.price for execution in executions}
        borrow_activity = _post_stock_borrows(
            books, carried_input, business_date, prices, day_index
        )
        _post_control_deficit(books, profile, business_date, prices, day_index)
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
        next_fails: dict[str, tuple[Decimal, Decimal, date]] = {}
        for position in cns_positions:
            if (
                mutation == "OMIT_ISSUE_FROM_CNS"
                and day_index == 0
                and position.security_id == omitted_issue
            ):
                continue
            carried_quantity, carried_cash, _ = carried_input.get(
                position.security_id, (Decimal(), Decimal(), business_date)
            )
            mark = prices.get(position.security_id)
            if mark is None:
                mark = abs(carried_cash / carried_quantity)
                prices[position.security_id] = mark
            cash = (position.quantity * mark).quantize(Decimal("0.01"))
            allocated_quantity = (position.quantity * (Decimal(1) - profile.fail_rate)).quantize(
                Decimal("1")
            )
            allocated_cash = (cash * (Decimal(1) - profile.fail_rate)).quantize(Decimal("0.01"))
            calendar = MarketCalendar.load(Market.US_EQUITIES)
            settlement_date = carried_input.get(
                position.security_id,
                (
                    Decimal(),
                    Decimal(),
                    calendar.add_business_days(business_date, position.settlement_date_offset_days),
                ),
            )[2]
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
                next_fails[position.security_id] = (
                    result.residual.quantity,
                    result.residual.cash,
                    settlement_date,
                )
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
        observed = {
            issue: sides.get(RecordSide.OWNERSHIP, Decimal())
            for issue, sides in books.quantities().items()
        }
        breaks = books.verify_stock_record(observed_locations=observed)
        protections, required_outcomes, protection_reasons, protection_figures, i6 = _protections(
            books,
            business_date,
            prices,
            profile,
            day_index,
            mutation,
            net_worth=net_worth,
            reserve_stress=reserve_stress,
        )
        carry_complete = set(carried_fails) <= set(carried_input)
        covered_cns_issues = {item.position.security_id for item in settlements}
        invariants = {
            "I1_QUANTITY_MONEY_CONSERVE": i1,
            "I2_BOOKED_FROM_REPORTS": i2,
            "I3_STOCK_RECORD_EQUALS_STREET": not breaks,
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
            "I8_REPLAY_DIGEST": before == books.digest(),
            "I11_POSITION_ROLL_FORWARD": i11,
            "I12_IDEMPOTENT_REPLAY": i12,
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
                protection_dispositions=protections,
                protection_required=required_outcomes,
                protection_reasons=protection_reasons,
                protection_figures=protection_figures,
                rule_204_close_outs={
                    issue: rule_204_deadline(
                        settlement_date=settlement_date,
                        sale_kind="SHORT",
                        calendar=MarketCalendar.load(Market.US_EQUITIES),
                    )
                    for issue, (_, _, settlement_date) in carried_input.items()
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
