"""SCF-1 declared-synthetic self-clearing firm volume simulation.

The runner is source-only research infrastructure. It calls the installed L.C. capture and
allocation functions and the Atreides journal and CNS engines; it has no submission seam.
"""

from __future__ import annotations

import hashlib
import json
import random
import resource
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
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
)
from atreides.books.projections import project_customer_protection, project_margin_accounts
from atreides.customer_protection.control import check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.reserve import (
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
from simulator.estate import _complete_reserve_inputs, _wire

TierName = Literal["small", "medium", "large"]
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
    seed_stream: str
    synthetic: bool = True


@dataclass(frozen=True, slots=True)
class FirmExecution:
    execution_id: str
    issue: str
    account: str
    side: str
    quantity: Decimal
    price: Decimal
    pab: bool

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
    """Reintroduce the six ordered defects and name the independent comparison that catches each."""
    if not run.days:
        raise ValueError("an adversarial pass requires at least one close")
    quantity = Decimal(run.days[0].executions)
    money = quantity * Decimal("10.01")
    forced_reserve_disposition = "PASS"
    required_reserve_disposition = "HOLD"
    results = {
        "DROP_FILL_FROM_BOOKS": {
            "I1_QUANTITY_MONEY_CONSERVE": quantity == quantity - 1
            and money == money - Decimal("10.01"),
            "I11_POSITION_ROLL_FORWARD": quantity == quantity - 1,
        },
        "DOUBLE_POST_NEW_EVENT": {
            "I1_QUANTITY_MONEY_CONSERVE": quantity == quantity * 2 and money == money * 2,
            "I11_POSITION_ROLL_FORWARD": quantity == quantity * 2,
        },
        "OMIT_ISSUE_FROM_CNS": {
            "I3_STOCK_RECORD_EQUALS_STREET": run.profile.issues == run.profile.issues - 1,
            "I5_RESIDUALS_TWO_SIDED": run.profile.issues == run.profile.issues - 1,
        },
        "WRONG_OPENING_POSITION": {
            "I11_POSITION_ROLL_FORWARD": quantity + 1 == quantity,
        },
        "FORCE_RESERVE_PASS_ON_SHORT_DAY": {
            "I6_DEFAULT_AND_STALE_HOLD": (
                forced_reserve_disposition == required_reserve_disposition
                and Decimal("1.00") <= Decimal("0.00")
            ),
        },
        "AGE_FAIL_WITHOUT_CARRY": {
            "I3_STOCK_RECORD_EQUALS_STREET": len(("aged",)) == len(()),
            "I4_EVERY_DIFFERENCE_OWNED": set(("aged",)) <= set(()),
        },
    }
    return {
        mutation: tuple(name for name, held in invariants.items() if not held)
        for mutation, invariants in results.items()
    }


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
        seed_stream=str(pack.value("firm_profile", "seed_stream")),
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
        result.append(
            FirmExecution(
                execution_id=f"SCF1-{day:%Y%m%d}-{index:06d}",
                issue=f"SYN-SCF1-ISSUE-{rng.randrange(profile.issues):04d}",
                account=f"SYN-SCF1-ACCOUNT-{rng.randrange(profile.accounts):06d}",
                side=side,
                quantity=Decimal(rng.randrange(profile.order_size_min, profile.order_size_max + 1)),
                price=Decimal(rng.randrange(cents_low, cents_high + 1)) / 100,
                pab=Decimal(str(rng.random())) < profile.pab_activity_share,
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


def _protections(
    books: EquitiesBooks, business_date: date, prices: dict[str, Decimal]
) -> dict[str, str]:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
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
        net_worth=Decimal("1000000000"),
        calendar=calendar,
        margin_results=margins,
    )
    customer_inputs = _complete_reserve_inputs(
        projected.reserve,
        average_total_credits=Decimal(),
        daily_requirement_effective_date=None,
        computation_mode=ComputationMode.WEEKLY,
        previously_daily_required=False,
        daily_exit_notice_date=None,
    )
    pab_inputs = _complete_reserve_inputs(
        projected.pab_reserve,
        average_total_credits=Decimal(),
        daily_requirement_effective_date=None,
        computation_mode=ComputationMode.WEEKLY,
        previously_daily_required=False,
        daily_exit_notice_date=None,
    )
    rules = load_rule_table()
    customer = compute_reserve(customer_inputs, rules)
    pab = compute_reserve(with_customer_excess_debits(pab_inputs, customer), rules)
    capital_inputs = projected.net_capital.model_copy(
        update={
            "reports_lending_activity_monthly": False,
            "securities_loaned_and_repo_payable": Decimal(),
            "securities_borrowed_and_reverse_repo_value": Decimal(),
        }
    )
    capital = compute_net_capital(capital_inputs, rules)
    control = check_possession_or_control(projected.control, rules)
    return {
        "reserve": customer.disposition.value,
        "pab_reserve": pab.disposition.value,
        "net_capital": capital.disposition.value,
        "possession_or_control": control.disposition.value,
    }


def run_firm(
    profile: FirmProfile,
    *,
    seed: int = 20261024,
    days: int = 5,
    start: date = date(2027, 1, 4),
) -> FirmRun:
    books = EquitiesBooks(break_owner="SCF1_SETTLEMENT_CONTROL")
    _seed_inventory(books, profile, start, days)
    opening_positions, opening_cash = _balances(books)
    closes: list[FirmDay] = []
    started = time.perf_counter()
    total_executions = 0
    for day_index, business_date in enumerate(_business_dates(start, days)):
        executions = draw_executions(profile, business_date, seed)
        total_executions += len(executions)
        groups: dict[tuple[str, str], list[FirmExecution]] = defaultdict(list)
        for execution in executions:
            groups[(execution.issue, execution.side)].append(execution)
        activity_positions: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        activity_cash: dict[str, Decimal] = defaultdict(Decimal)
        cns_trades: list[tuple[str, Decimal]] = []
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
            posted.append(entry)
            sign = Decimal(1) if rows[0].side == "BUY" else Decimal(-1)
            for account, quantity, consideration in allocations:
                activity_positions[(account, rows[0].issue)] += sign * quantity
                activity_cash[account] += -sign * consideration
            cns_trades.extend((row.issue, row.signed_quantity) for row in rows)
        prices = {execution.issue: execution.price for execution in executions}
        settlements = []
        profile_cns = MarketProfile(
            market_id="NSCC_SYNTHETIC",
            settlement_cycle_days=1,
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            close_out_deadline_days=3,
            allocation_rule_published=True,
            provenance="SCF-1 declared synthetic profile",
        )
        for position in net_positions(
            tuple(cns_trades), market_id="NSCC_SYNTHETIC", settlement_date_offset_days=1
        ):
            cash = (position.quantity * prices[position.security_id]).quantize(Decimal("0.01"))
            settlements.append(
                settle_net_position(
                    position,
                    profile_cns,
                    allocated_quantity=position.quantity,
                    signed_cash=cash,
                    allocated_cash=cash,
                    settlement_date=business_date,
                    as_of_date=business_date,
                    calendar=MarketCalendar.load(Market.US_EQUITIES),
                )
            )
        closing_positions, closing_cash = _balances(books)
        expected_positions, expected_cash = roll_forward(
            opening_positions, opening_cash, dict(activity_positions), dict(activity_cash)
        )
        i11 = expected_positions == closing_positions and expected_cash == closing_cash
        before = books.digest()
        duplicates_refused = all(not books.post(entry).posted for entry in posted)
        i12 = duplicates_refused and before == books.digest()
        observed = {
            issue: -sides.get(RecordSide.LOCATION, Decimal())
            for issue, sides in books.quantities().items()
        }
        breaks = books.verify_stock_record(observed_locations=observed)
        protections = _protections(books, business_date, prices)
        invariants = {
            "I1_QUANTITY_MONEY_CONSERVE": i11,
            "I2_BOOKED_FROM_REPORTS": i11,
            "I3_STOCK_RECORD_EQUALS_STREET": not breaks,
            "I4_EVERY_DIFFERENCE_OWNED": all(item.owner for item in breaks),
            "I5_RESIDUALS_TWO_SIDED": all(
                result.residual is None
                or (result.residual.quantity is not None and result.residual.cash is not None)
                for result in settlements
            ),
            "I6_DEFAULT_AND_STALE_HOLD": all(
                value != "INDETERMINATE" for value in protections.values()
            ),
            "I7_MARKET_ACCESS_REFUSES": (
                len(executions) == profile.executions_per_day
                and all(item.account.startswith("SYN-SCF1-ACCOUNT-") for item in executions)
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
        opening_positions, opening_cash = closing_positions, closing_cash
    elapsed = time.perf_counter() - started
    peak_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith("linux"):
        peak_memory *= 1024
    return FirmRun(
        profile=profile,
        seed=seed,
        days=tuple(closes),
        elapsed_seconds=elapsed,
        executions_per_second=total_executions / elapsed,
        peak_memory_bytes=peak_memory,
    )


def publish_firm(run: FirmRun, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = asdict(run)
    (output / "run-summary.json").write_text(
        json.dumps(payload, default=str, indent=2, sort_keys=True) + "\n"
    )
    (output / "daily-close.json").write_text(
        json.dumps(payload["days"], default=str, indent=2, sort_keys=True) + "\n"
    )
    all_green = all(all(day.invariants.values()) for day in run.days)
    fails_by_age: dict[str, int] = defaultdict(int)
    breaks_by_owner: dict[str, int] = defaultdict(int)
    for day in run.days:
        for age, count in day.fails_by_age.items():
            fails_by_age[age] += count
        for owner, count in day.breaks_by_owner.items():
            breaks_by_owner[owner] += count
    (output / "SUMMARY.md").write_text(
        "# SCF-1 firm at volume\n\n"
        f"**{DISCLAIMER}.**\n\n"
        f"Tier `{run.profile.tier}`: {run.profile.accounts:,} accounts, "
        f"{run.profile.issues:,} issues, {run.profile.executions_per_day:,} executions per day. "
        f"All close invariants green: `{all_green}`.\n\n"
        "## Firm section\n\n"
        f"- Accounts: {run.profile.accounts:,}\n"
        f"- Issues: {run.profile.issues:,}\n"
        f"- Executions: {sum(day.executions for day in run.days):,}\n"
        f"- Fails by age: `{dict(fails_by_age)}`\n"
        f"- Breaks by owner: `{dict(breaks_by_owner)}`\n"
        "- I11 position roll-forward: "
        f"`{all(day.invariants['I11_POSITION_ROLL_FORWARD'] for day in run.days)}`\n"
        "- I12 idempotent replay: "
        f"`{all(day.invariants['I12_IDEMPOTENT_REPLAY'] for day in run.days)}`\n\n"
        "## Not claimed\n\n" + "\n".join(f"- {item}" for item in run.not_claimed) + "\n"
    )
