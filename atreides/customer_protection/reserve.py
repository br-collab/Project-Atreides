"""Customer and PAB reserve formula engine (17 CFR 240.15c3-3(e) and Exhibit A).

EXPERIMENTAL (charter section 18.6). A challenger computation, not the book of
record. It files nothing, and it never claims the firm is in compliance.

WHAT IT COMPUTES
----------------
For one computation, customer or PAB (proprietary accounts of broker-dealers):

1. Total credits: the sum of the Exhibit A credit lines (Items 1 to 9).
2. Total debits: the sum of the Exhibit A debit lines (Items 10 to 15). This is
   the aggregate debit items figure **before** any reduction, which is the
   figure the net capital alternative standard takes 2 percent of.
3. The debit reduction:

   - aggregate indebtedness standard, customer: Note E(3), a percentage of
     Item 10,
   - aggregate indebtedness standard, PAB: none, per PAB Note 4,
   - alternative standard, customer: Rule 15c3-1(a)(1)(ii)(A), a percentage of
     aggregate debit items in lieu of Note E(3), the weekly percentage unless
     the computation is daily and the 2 percent is available (daily required,
     or voluntary daily with the written notice given far enough ahead),
   - alternative standard, PAB: **INDETERMINATE**. The loaded text does not say
     whether the Rule 15c3-1(a)(1)(ii)(A) reduction, given "in lieu of" Note
     E(3), applies to a PAB computation that Note E(3) never applied to. The
     engine will not guess; it names the missing rule.

4. The requirement: the excess of credits over reduced debits, or zero,
   multiplied by the monthly deposit factor when the computation is monthly.
5. The deposit that counts: cash at a non-affiliated bank up to the cap on
   the bank's equity capital, cash at an affiliated bank excluded, plus
   qualified securities (Rule 15c3-3(e)(5)).
6. For a PAB computation, the part of the requirement satisfied by excess
   debits in the customer computation of the same date (Rule 15c3-3(e)(4)).
7. The shortfall: requirement less the deposit that counts, or zero.

Every percentage, threshold and line comes from the rule table. The Exhibit A
lines this engine models are listed in :data:`EXHIBIT_A_CREDITS` and
:data:`EXHIBIT_A_DEBITS`; if the loaded text lists a line not here, or does not
list one that is, the result is INDETERMINATE.

WHAT THE INPUT LINES MEAN
-------------------------
Each line balance is the figure for that Exhibit A line as the firm's books
state it, after the Notes that adjust a line (Notes A to H, and E(1), E(2),
E(4), E(5), E(6)) and **before** the Note E(3) one percent, which is the only
note this engine applies, because it is the one that turns on the net capital
standard. The engine cannot see account-level data and does not pretend to
check the other Notes.

NOT MODELED, AND SAID SO
------------------------
- The six-month phase-in to daily computation and the 60-day exit notice
  (Rule 15c3-3(e)(3)(i)(B)): average total credits at or over the threshold
  is treated as daily required. A firm inside its phase-in is HOLD, which is
  the conservative error.
- Monthly PAB computation (Rule 15c3-3(e)(3)(iii)): INDETERMINATE.
- No rounding. A figure is as exact as its inputs. Rounding is the filer's
  presentation, and the challenger classifies a difference inside a stated
  tolerance as rounding.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import field_validator

from atreides.customer_protection.common import (
    Frozen,
    Money,
    NonNegativeMoney,
    RuleReader,
    RuleRef,
    decide,
)
from atreides.customer_protection.rules.model import CLAIM_LABEL, RuleKind, RuleTable

__all__ = [
    "EXHIBIT_A_CREDITS",
    "EXHIBIT_A_DEBITS",
    "BankCashDeposit",
    "ComputationMode",
    "LineBalance",
    "NetCapitalStandard",
    "ReserveAccounts",
    "ReserveInputs",
    "ReserveResult",
    "compute_reserve",
    "with_customer_excess_debits",
]

ZERO = Decimal(0)
ONE = Decimal(1)

#: Exhibit A credit lines, Items 1 to 9, as rule ids.
EXHIBIT_A_CREDITS: tuple[str, ...] = tuple(
    f"15c3-3a.item.0{n}" for n in "123456789"
)
#: Exhibit A debit lines, Items 10 to 15, as rule ids.
EXHIBIT_A_DEBITS: tuple[str, ...] = tuple(f"15c3-3a.item.1{n}" for n in "012345")
ITEM_10 = EXHIBIT_A_DEBITS[0]

NOTE_E3 = "15c3-3a.note_e3.debit_reduction"
PAB_NOTE_4 = "15c3-3a.pab_note_4.no_note_e3"
WEEKLY_BASIS = "15c3-1.a1iiA.weekly_basis"
WEEKLY_REDUCTION = "15c3-1.a1iiA.weekly_debit_reduction"
DAILY_REDUCTION = "15c3-1.a1iiA.daily_debit_reduction"
#: Deliberately absent from the table. See the module docstring.
PAB_ALTERNATIVE_REDUCTION = "15c3-1.a1iiA.pab_debit_reduction"
#: Deliberately absent from the table: monthly PAB computation is not modeled.
PAB_MONTHLY = "15c3-3.e3iii.pab_monthly"
DAILY_THRESHOLD = "15c3-3.e3iB1.daily_threshold"
VOLUNTARY_NOTICE = "15c3-3.e3v.voluntary_daily_notice"
MONTHLY_AI_CEILING = "15c3-3.e3iC.monthly_ai_ceiling"
MONTHLY_FUNDS_CEILING = "15c3-3.e3iC.monthly_customer_funds_ceiling"
MONTHLY_FACTOR = "15c3-3.e3iC.monthly_deposit_factor"
PAB_FROM_CUSTOMER = "15c3-3.e4.pab_from_customer_excess_debits"
AFFILIATED_EXCLUDED = "15c3-3.e5.affiliated_bank_excluded"
BANK_EQUITY_CAP = "15c3-3.e5.bank_equity_cap"


class ReserveAccounts(StrEnum):
    """Which reserve computation this is."""

    #: The Customer Reserve Bank Account computation.
    CUSTOMER = "customer"
    #: The PAB Reserve Bank Account computation.
    PAB = "pab"


class NetCapitalStandard(StrEnum):
    """The firm's net capital ratio standard under Rule 15c3-1(a)(1)."""

    #: Rule 15c3-1(a)(1)(i).
    AGGREGATE_INDEBTEDNESS = "aggregate_indebtedness"
    #: Rule 15c3-1(a)(1)(ii), elected.
    ALTERNATIVE = "alternative"


class ComputationMode(StrEnum):
    """How often the firm computes, under Rule 15c3-3(e)(3)."""

    #: Rule 15c3-3(e)(3)(i)(A).
    WEEKLY = "weekly"
    #: Required under (e)(3)(i)(B)(1), or voluntary under (e)(3)(v).
    DAILY = "daily"
    #: Rule 15c3-3(e)(3)(i)(C), customer computation only.
    MONTHLY = "monthly"


class LineBalance(Frozen):
    """One Exhibit A line as the books state it. ``None`` means the balance was not supplied."""

    rule_id: str
    amount: NonNegativeMoney | None


class BankCashDeposit(Frozen):
    """Cash on deposit in a reserve bank account at one bank."""

    bank: str
    amount: NonNegativeMoney
    affiliated: bool
    #: The bank's equity capital per its most recent Call Report. Not needed if affiliated.
    bank_equity_capital: NonNegativeMoney | None = None


class ReserveInputs(Frozen):
    """Everything one reserve computation reads. Values are as the system of record states them."""

    accounts: ReserveAccounts
    as_of: date
    standard: NetCapitalStandard
    mode: ComputationMode
    lines: tuple[LineBalance, ...]
    #: Average total credits under Rule 15c3-3(e)(3)(i)(B)(1), from the 12 most recent filings.
    average_total_credits: NonNegativeMoney | None
    #: Date the written notice of a voluntary daily election was given, if one was.
    voluntary_daily_notice_date: date | None = None
    #: Monthly eligibility evidence (Rule 15c3-3(e)(3)(i)(C)).
    aggregate_indebtedness: NonNegativeMoney | None = None
    net_capital: Money | None = None
    aggregate_customer_funds: NonNegativeMoney | None = None
    cash_deposits: tuple[BankCashDeposit, ...] = ()
    #: Market value of qualified securities on deposit. ``None`` means not supplied.
    qualified_securities_deposit: NonNegativeMoney | None
    #: PAB only: excess debits in the same-date customer computation (Rule 15c3-3(e)(4)).
    customer_excess_debits: NonNegativeMoney | None = None
    customer_computation_as_of: date | None = None


class ReserveResult(Frozen):
    """The computation, its evidence, and its disposition."""

    engine: Literal["reserve"] = "reserve"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    accounts: ReserveAccounts
    as_of: date
    disposition: Disposition
    total_credits: Money | None
    #: Aggregate debit items before any reduction.
    total_debits: Money | None
    debit_reduction_rate: Decimal | None
    debit_reduction: Money | None
    net_debits: Money | None
    excess_of_credits_over_debits: Money | None
    deposit_factor: Decimal | None
    requirement: Money | None
    #: Excess of reduced debits over credits, or zero.
    excess_debits: Money | None
    customer_excess_debits_applied: Money | None
    requirement_after_customer_excess_debits: Money | None
    eligible_deposit: Money | None
    excluded_deposit: Money | None
    shortfall: Money | None
    daily_required: bool | None
    missing_rules: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    unrecognised_inputs: tuple[str, ...]
    breaches: tuple[str, ...]
    reasons: tuple[str, ...]
    rules_used: tuple[RuleRef, ...]

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)


def with_customer_excess_debits(pab: ReserveInputs, customer: ReserveResult) -> ReserveInputs:
    """``pab`` with the customer computation's excess debits attached, for Rule 15c3-3(e)(4)."""
    return pab.model_copy(
        update={
            "customer_excess_debits": customer.excess_debits,
            "customer_computation_as_of": customer.as_of,
        }
    )


class _Findings:
    def __init__(self) -> None:
        self.missing_inputs: list[str] = []
        self.unrecognised: list[str] = []
        self.breaches: list[str] = []
        self.reasons: list[str] = []


def _sum(values: list[Decimal | None]) -> Decimal | None:
    if any(v is None for v in values):
        return None
    return sum((v for v in values if v is not None), ZERO)


def _lines(
    inputs: ReserveInputs, rules: RuleReader, found: _Findings
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Total credits, total debits and Item 10, or ``None`` where a line is missing."""
    supplied = {line.rule_id: line.amount for line in inputs.lines}
    modeled = set(EXHIBIT_A_CREDITS) | set(EXHIBIT_A_DEBITS)
    for rule_id in rules.of_kind(RuleKind.EXHIBIT_A_CREDIT) + rules.of_kind(
        RuleKind.EXHIBIT_A_DEBIT
    ):
        if rule_id not in modeled:
            rules.flag(f"{rule_id} (listed in the loaded Exhibit A, not modeled)")
    for rule_id in supplied:
        if rule_id not in modeled:
            found.unrecognised.append(f"line {rule_id} is not an Exhibit A line")

    def balance(rule_id: str) -> Decimal | None:
        line_loaded = rules.present(rule_id)
        amount = supplied.get(rule_id)
        if amount is None:
            found.missing_inputs.append(rule_id)
        return amount if line_loaded else None

    credits = _sum([balance(rule_id) for rule_id in EXHIBIT_A_CREDITS])
    debits = _sum([balance(rule_id) for rule_id in EXHIBIT_A_DEBITS])
    return credits, debits, supplied.get(ITEM_10)


def _daily_required(
    inputs: ReserveInputs, rules: RuleReader, found: _Findings
) -> bool | None:
    threshold = rules.value(DAILY_THRESHOLD)
    if inputs.average_total_credits is None:
        found.missing_inputs.append("average_total_credits")
        return None
    if threshold is None:
        return None
    required = inputs.average_total_credits >= threshold
    if required and inputs.mode is not ComputationMode.DAILY:
        found.breaches.append(
            "average total credits are at or over the daily-computation threshold "
            "(Rule 15c3-3(e)(3)(i)(B)(1)); this computation is not daily"
        )
    return required


def _voluntary_daily_noticed(inputs: ReserveInputs, rules: RuleReader, found: _Findings) -> bool:
    days = rules.value(VOLUNTARY_NOTICE)
    notice = inputs.voluntary_daily_notice_date
    if days is None:
        return False
    if notice is None:
        found.reasons.append("no voluntary daily notice given; the weekly reduction applies")
        return False
    if inputs.as_of < notice + timedelta(days=int(days)):
        found.reasons.append(
            "voluntary daily notice given less than the required period before this "
            "computation (Rule 15c3-3(e)(3)(v)); the weekly reduction applies"
        )
        return False
    return True


def _reduction(
    inputs: ReserveInputs,
    rules: RuleReader,
    found: _Findings,
    debits: Decimal | None,
    item_10: Decimal | None,
    daily_required: bool | None,
) -> tuple[Decimal | None, Decimal | None]:
    """The debit reduction rate and amount."""
    customer = inputs.accounts is ReserveAccounts.CUSTOMER
    if inputs.standard is NetCapitalStandard.AGGREGATE_INDEBTEDNESS:
        if not customer:
            return (ZERO, ZERO) if rules.present(PAB_NOTE_4) else (None, None)
        rate = rules.value(NOTE_E3)
        if rate is None or item_10 is None:
            return rate, None
        return rate, rate * item_10

    if not customer:
        pab_rate = rules.value(PAB_ALTERNATIVE_REDUCTION)
        if pab_rate is None:
            found.reasons.append(
                "the loaded text does not settle whether the Rule 15c3-1(a)(1)(ii)(A) "
                "reduction applies to a PAB computation"
            )
        if pab_rate is None or debits is None:
            return pab_rate, None
        return pab_rate, pab_rate * debits
    if inputs.mode is ComputationMode.MONTHLY and rules.present(WEEKLY_BASIS):
        found.breaches.append(
            "a firm on the alternative standard computes at least weekly "
            "(Rule 15c3-1(a)(1)(ii)(A)); this computation is monthly"
        )
    daily = inputs.mode is ComputationMode.DAILY and (
        daily_required is True or _voluntary_daily_noticed(inputs, rules, found)
    )
    rate = rules.value(DAILY_REDUCTION if daily else WEEKLY_REDUCTION)
    if rate is None or debits is None:
        return rate, None
    return rate, rate * debits


def _deposit_factor(
    inputs: ReserveInputs, rules: RuleReader, found: _Findings
) -> Decimal | None:
    if inputs.mode is not ComputationMode.MONTHLY:
        return ONE
    if inputs.accounts is ReserveAccounts.PAB:
        return ONE if rules.present(PAB_MONTHLY) else None
    ceiling = rules.value(MONTHLY_AI_CEILING)
    funds_ceiling = rules.value(MONTHLY_FUNDS_CEILING)
    factor = rules.value(MONTHLY_FACTOR)
    evidence = {
        "aggregate_indebtedness": inputs.aggregate_indebtedness,
        "net_capital": inputs.net_capital,
        "aggregate_customer_funds": inputs.aggregate_customer_funds,
    }
    found.missing_inputs.extend(name for name, value in evidence.items() if value is None)
    if (
        ceiling is not None
        and funds_ceiling is not None
        and inputs.aggregate_indebtedness is not None
        and inputs.net_capital is not None
        and inputs.aggregate_customer_funds is not None
        and (
            inputs.aggregate_indebtedness > ceiling * inputs.net_capital
            or inputs.aggregate_customer_funds > funds_ceiling
        )
    ):
        found.breaches.append(
            "monthly computation is not available: aggregate indebtedness or customer "
            "funds exceed the Rule 15c3-3(e)(3)(i)(C) ceilings"
        )
    return factor


def _deposits(
    inputs: ReserveInputs, rules: RuleReader, found: _Findings
) -> tuple[Decimal | None, Decimal | None]:
    """The deposit that counts, and the amount excluded under Rule 15c3-3(e)(5)."""
    cap = rules.value(BANK_EQUITY_CAP) if inputs.cash_deposits else ZERO
    affiliated_rule = (
        rules.present(AFFILIATED_EXCLUDED)
        if any(d.affiliated for d in inputs.cash_deposits)
        else True
    )
    eligible: list[Decimal | None] = []
    for deposit in inputs.cash_deposits:
        if deposit.affiliated:
            eligible.append(ZERO if affiliated_rule else None)
        elif deposit.bank_equity_capital is None:
            found.missing_inputs.append(f"bank_equity_capital[{deposit.bank}]")
            eligible.append(None)
        elif cap is None:
            eligible.append(None)
        else:
            eligible.append(min(deposit.amount, cap * deposit.bank_equity_capital))
    if inputs.qualified_securities_deposit is None:
        found.missing_inputs.append("qualified_securities_deposit")
    cash = _sum(eligible)
    if cash is None or inputs.qualified_securities_deposit is None:
        return None, None
    excluded = sum((d.amount for d in inputs.cash_deposits), ZERO) - cash
    return cash + inputs.qualified_securities_deposit, excluded


def _customer_excess_applied(
    inputs: ReserveInputs, rules: RuleReader, found: _Findings, requirement: Decimal | None
) -> Decimal | None:
    if inputs.accounts is ReserveAccounts.CUSTOMER or inputs.customer_excess_debits is None:
        return ZERO
    if inputs.customer_computation_as_of != inputs.as_of:
        found.reasons.append(
            "customer excess debits are from another date; Rule 15c3-3(e)(4) uses the same date"
        )
        return ZERO
    if not rules.present(PAB_FROM_CUSTOMER) or requirement is None:
        return None
    return min(requirement, inputs.customer_excess_debits)


def compute_reserve(inputs: ReserveInputs, table: RuleTable) -> ReserveResult:
    """Compute one reserve requirement. Pure: no I/O, no clock."""
    rules = RuleReader(table)
    found = _Findings()

    credits, debits, item_10 = _lines(inputs, rules, found)
    daily_required = _daily_required(inputs, rules, found)
    rate, reduction = _reduction(inputs, rules, found, debits, item_10, daily_required)
    factor = _deposit_factor(inputs, rules, found)

    net_debits = None if debits is None or reduction is None else debits - reduction
    excess = None if credits is None or net_debits is None else credits - net_debits
    requirement = None if excess is None or factor is None else max(excess, ZERO) * factor
    excess_debits = None if excess is None else max(-excess, ZERO)

    applied = _customer_excess_applied(inputs, rules, found, requirement)
    after = None if requirement is None or applied is None else requirement - applied
    eligible, excluded = _deposits(inputs, rules, found)
    shortfall = None if after is None or eligible is None else max(after - eligible, ZERO)
    if shortfall is not None and shortfall > ZERO:
        found.breaches.append(
            f"{inputs.accounts.value} reserve deposit is short of the requirement by {shortfall}"
        )

    missing_rules = rules.missing
    disposition = decide(
        missing_rules + tuple(found.unrecognised), found.missing_inputs, found.breaches
    )
    return ReserveResult(
        accounts=inputs.accounts,
        as_of=inputs.as_of,
        disposition=disposition,
        total_credits=credits,
        total_debits=debits,
        debit_reduction_rate=rate,
        debit_reduction=reduction,
        net_debits=net_debits,
        excess_of_credits_over_debits=excess,
        deposit_factor=factor,
        requirement=requirement,
        excess_debits=excess_debits,
        customer_excess_debits_applied=applied,
        requirement_after_customer_excess_debits=after,
        eligible_deposit=eligible,
        excluded_deposit=excluded,
        shortfall=shortfall,
        daily_required=daily_required,
        missing_rules=missing_rules,
        missing_inputs=tuple(sorted(set(found.missing_inputs))),
        unrecognised_inputs=tuple(found.unrecognised),
        breaches=tuple(found.breaches),
        reasons=tuple(found.reasons),
        rules_used=rules.used,
    )
