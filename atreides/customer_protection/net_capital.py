"""Net capital engine (17 CFR 240.15c3-1) with early warning (17 CFR 240.17a-11).

EXPERIMENTAL (charter section 18.6). A challenger computation, not the book of
record. A FINOP (Financial and Operations Principal) signs what is filed; this
engine files nothing and never claims the firm is in compliance.

WHAT IT COMPUTES
----------------
1. Tentative net capital: net worth, plus the additions the caller supplies
   (allowable subordinated liabilities and the like), less the deductions the
   caller supplies (non-allowable assets and the like), before haircuts. This
   is Rule 15c3-1(c)(15)'s "net capital before deducting the securities
   haircuts". Each adjustment names the paragraph the caller relies on; the
   engine sums what it is given and does not classify balance sheet lines.
2. Securities haircuts, for two classes only:

   - government, Rule 15c3-1(c)(2)(vi)(A): the maturity bands and rates as
     loaded, by the category method of (A)(1), or by subcategory where the firm
     elects (A)(2). The (A)(3) to (A)(5) exclusions and elections are not
     modeled, and each would change the result, so the firm states whether each
     applies (SC2-WP3-01). Unstated is a missing input (HOLD). One that applies
     is a rule path this engine cannot compute (INDETERMINATE). Either way no
     government haircut is claimed. A firm with no government positions is not
     asked.
   - equity, the "all other securities" haircut of (c)(2)(vi)(J): the loaded
     rate on the greater of the long or short position, and the loaded rate on
     the amount by which the lesser exceeds the loaded share of the greater.

   Any other asset class is INDETERMINATE, by name.
3. Net capital: tentative net capital less haircuts.
4. The minimum requirement, the greater of:

   - the ratio requirement. Aggregate indebtedness standard (a)(1)(i):
     aggregate indebtedness may not exceed the loaded multiple of net capital
     (a different one in the firm's first months). Alternative standard
     (a)(1)(ii): the greater of the loaded floor and the loaded percentage of
     aggregate debit items. **Aggregate debit items are the Exhibit A total
     debits before the reserve formula reduction**, which is
     :attr:`~atreides.customer_protection.reserve.ReserveResult.total_debits`.
   - the activity minimum of (a)(2) for the firm's category.

5. Excess net capital: net capital less the minimum requirement.
6. Early-warning trigger indicators, Rule 17a-11(b), thresholds as loaded: (b)(1) aggregate
   indebtedness over its multiple of net capital, (b)(2) net capital under its
   percentage of aggregate debit items, (b)(3) net capital under its multiple
   of the minimum requirement, (b)(5) the leverage test against tentative net
   capital unless the firm reports that activity monthly. (b)(4), backtesting
   exceptions, applies to model-based firms and is not modeled.

The trigger indicators are not notification logic. This engine does not decide
the recipient, deadline or delivery method, send a notice, retain filing
evidence, amend a notice, or perform supervisory escalation.

EXACTNESS
---------
Every figure is exact Decimal arithmetic except one: under the aggregate
indebtedness standard the ratio requirement is aggregate indebtedness divided by
the loaded multiple, and that quotient need not terminate. It is computed at
the Decimal context precision and :attr:`NetCapitalResult.ratio_requirement_exact`
says whether it is exact. **No breach or warning is decided from that quotient.**
Each test multiplies instead (aggregate indebtedness against multiple times net
capital), which is exact.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, Inexact, localcontext
from enum import StrEnum
from typing import Literal

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import Field, field_validator

from atreides.customer_protection.common import (
    Frozen,
    Money,
    NonNegativeMoney,
    RuleReader,
    RuleRef,
    decide,
)
from atreides.customer_protection.reserve import NetCapitalStandard
from atreides.customer_protection.rules.model import CLAIM_LABEL, RuleTable

__all__ = [
    "GOVERNMENT_BANDS",
    "AssetClass",
    "BrokerDealerCategory",
    "CapitalAdjustment",
    "EarlyWarning",
    "GovernmentElection",
    "HaircutLine",
    "NetCapitalInputs",
    "NetCapitalResult",
    "Position",
    "compute_net_capital",
]

ZERO = Decimal(0)

AI_CEILING = "15c3-1.a1i.ai_ceiling"
AI_CEILING_FIRST_YEAR = "15c3-1.a1i.ai_ceiling_first_year"
FIRST_YEAR_MONTHS = "15c3-1.a1i.first_year_months"
ALT_FLOOR = "15c3-1.a1ii.alternative_floor"
ALT_PERCENT = "15c3-1.a1ii.alternative_debit_percent"
GOV_OFFSET = "15c3-1.c2viA1.offset_percent"
EQUITY_RATE = "15c3-1.c2viJ.rate"
EQUITY_LESSER_THRESHOLD = "15c3-1.c2viJ.lesser_threshold"
EQUITY_EXCESS_RATE = "15c3-1.c2viJ.excess_rate"
WARN_AI = "17a-11.b1.ai_warning"
WARN_ALT = "17a-11.b2.alternative_warning"
WARN_MINIMUM = "17a-11.b3.minimum_warning"
WARN_LEVERAGE = "17a-11.b5.leverage_warning"

#: Rule 15c3-1(c)(2)(vi)(A)(1) categories and their subcategories, as rule-id stems.
GOVERNMENT_BANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cat1", ("i", "ii", "iii", "iv")),
    ("cat2", ("i", "ii")),
    ("cat3", ("i", "ii")),
    ("cat4", ("i", "ii", "iii", "iv")),
)


class BrokerDealerCategory(StrEnum):
    """The firm's activity under Rule 15c3-1(a)(2), which sets its activity minimum."""

    #: (a)(2)(i): carries customer or broker-dealer accounts and holds their funds or securities.
    CARRYING = "carrying"
    #: (a)(2)(ii): exempt from Rule 15c3-3 under its paragraph (k)(2)(i).
    K2I_EXEMPT = "k2i_exempt"
    #: (a)(2)(iii): a dealer.
    DEALER = "dealer"
    #: (a)(2)(iv): introduces accounts on a fully disclosed basis and receives securities.
    INTRODUCING = "introducing"
    #: (a)(2)(v): redeemable shares of registered investment companies.
    INVESTMENT_COMPANY_SHARES = "investment_company_shares"
    #: (a)(2)(vi): none of the above.
    OTHER = "other"


_MINIMUM_RULE = {
    BrokerDealerCategory.CARRYING: "15c3-1.a2i.minimum.carrying",
    BrokerDealerCategory.K2I_EXEMPT: "15c3-1.a2ii.minimum.k2i_exempt",
    BrokerDealerCategory.DEALER: "15c3-1.a2iii.minimum.dealer",
    BrokerDealerCategory.INTRODUCING: "15c3-1.a2iv.minimum.introducing",
    BrokerDealerCategory.INVESTMENT_COMPANY_SHARES: "15c3-1.a2v.minimum.investment_company_shares",
    BrokerDealerCategory.OTHER: "15c3-1.a2vi.minimum.other",
}


class AssetClass(StrEnum):
    """Haircut classes this engine computes. Anything else is INDETERMINATE."""

    #: Rule 15c3-1(c)(2)(vi)(A): issued or guaranteed by the United States or an agency.
    GOVERNMENT = "government"
    #: Rule 15c3-1(c)(2)(vi)(J): all other securities, which is where equity falls.
    EQUITY = "equity"


class GovernmentElection(StrEnum):
    """How government haircuts are computed."""

    #: Rule 15c3-1(c)(2)(vi)(A)(1): by category, with the long and short offset.
    CATEGORY = "category"
    #: Rule 15c3-1(c)(2)(vi)(A)(2): by subcategory, elected instead of (A)(1).
    SUBCATEGORY = "subcategory"


class CapitalAdjustment(Frozen):
    """One addition to or deduction from net worth, as the books state it."""

    description: str = Field(min_length=1)
    #: The Rule 15c3-1 paragraph the caller relies on, for example "(c)(2)(iv)(B)".
    paragraph: str = Field(min_length=1)
    amount: NonNegativeMoney | None


class Position(Frozen):
    """The firm's position in one issue, at market value."""

    issue: str = Field(min_length=1)
    #: A value of :class:`AssetClass`. Any other string is accepted and is INDETERMINATE.
    asset_class: str
    long_market_value: NonNegativeMoney
    short_market_value: NonNegativeMoney
    #: Government positions only: months from the computation date to maturity.
    months_to_maturity: NonNegativeMoney | None = None


class NetCapitalInputs(Frozen):
    """Everything one net capital computation reads."""

    as_of: date
    standard: NetCapitalStandard
    category: BrokerDealerCategory
    net_worth: Money | None
    additions: tuple[CapitalAdjustment, ...] = ()
    deductions: tuple[CapitalAdjustment, ...] = ()
    positions: tuple[Position, ...] = ()
    government_election: GovernmentElection = GovernmentElection.CATEGORY
    #: Government positions only. Rule 15c3-1(c)(2)(vi)(A)(3): whether the firm elects to
    #: exclude offsetting securities across categories. ``None`` means not stated.
    elects_a3_cross_category_exclusion: bool | None = None
    #: Government positions only. Rule 15c3-1(c)(2)(vi)(A)(4): whether the firm elects to
    #: include securities deliverable against government securities futures. ``None`` means
    #: not stated.
    elects_a4_futures_deliverable_inclusion: bool | None = None
    #: Government positions only. Rule 15c3-1(c)(2)(vi)(A)(5): whether the firm is a
    #: government securities dealer whose deduction is 75 percent of the one otherwise
    #: computed. ``None`` means not stated.
    qualifies_a5_government_dealer_reduction: bool | None = None
    #: Aggregate indebtedness standard only.
    aggregate_indebtedness: NonNegativeMoney | None = None
    #: Aggregate indebtedness standard only: months since the firm commenced business.
    months_in_business: NonNegativeMoney | None = None
    #: Alternative standard: Exhibit A total debits before the reserve formula reduction.
    aggregate_debit_items: NonNegativeMoney | None = None
    #: Rule 17a-11(b)(5): whether the firm reports this activity monthly to its examining
    #: authority, which removes the notice requirement. ``None`` means not stated.
    reports_lending_activity_monthly: bool | None = None
    #: Rule 17a-11(b)(5), government securities excluded.
    securities_loaned_and_repo_payable: NonNegativeMoney | None = None
    securities_borrowed_and_reverse_repo_value: NonNegativeMoney | None = None


class HaircutLine(Frozen):
    """One haircut deduction and where its rate came from."""

    asset_class: AssetClass
    description: str
    amount: Money
    paragraph: str


class EarlyWarning(Frozen):
    """One Rule 17a-11(b) trigger indicator, not proof that notice was given."""

    rule_id: str
    paragraph: str
    triggered: bool | None
    #: The figure the measure is compared with, as loaded and computed.
    threshold: Money | None
    measure: Money | None
    #: Measure less threshold for "less than" tests, threshold less measure for "in excess
    #: of" tests: positive means the warning is not triggered.
    cushion: Money | None
    note: str


class NetCapitalResult(Frozen):
    """The computation, its evidence, and its disposition."""

    engine: Literal["net_capital"] = "net_capital"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    as_of: date
    standard: NetCapitalStandard
    disposition: Disposition
    net_worth: Money | None
    total_additions: Money | None
    total_deductions: Money | None
    tentative_net_capital: Money | None
    haircuts: Money | None
    haircut_lines: tuple[HaircutLine, ...]
    net_capital: Money | None
    ratio_requirement: Money | None
    #: False when the aggregate indebtedness quotient did not terminate. See module docstring.
    ratio_requirement_exact: bool | None
    activity_minimum: Money | None
    minimum_requirement: Money | None
    excess_net_capital: Money | None
    early_warnings: tuple[EarlyWarning, ...]
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


class _Findings:
    def __init__(self) -> None:
        self.missing_inputs: list[str] = []
        self.unrecognised: list[str] = []
        self.breaches: list[str] = []
        self.reasons: list[str] = []


def _total(
    adjustments: tuple[CapitalAdjustment, ...], name: str, found: _Findings
) -> Decimal | None:
    missing = [f"{name}[{a.description}]" for a in adjustments if a.amount is None]
    found.missing_inputs.extend(missing)
    if missing:
        return None
    return sum((a.amount for a in adjustments if a.amount is not None), ZERO)


def _government_bands(rules: RuleReader) -> list[tuple[str, str, Decimal | None, Decimal | None]]:
    """(category, subcategory, rate, upper bound in months) in maturity order."""
    bands: list[tuple[str, str, Decimal | None, Decimal | None]] = []
    last = GOVERNMENT_BANDS[-1][0], GOVERNMENT_BANDS[-1][1][-1]
    for category, subcategories in GOVERNMENT_BANDS:
        for sub in subcategories:
            stem = f"15c3-1.c2viA1.{category}.{sub}"
            upper = None if (category, sub) == last else rules.value(f"{stem}.upper_months")
            bands.append((category, sub, rules.value(f"{stem}.rate"), upper))
    return bands


def _government_provisions_ruled_out(
    inputs: NetCapitalInputs, rules: RuleReader, found: _Findings
) -> bool:
    """Whether the firm has stated that none of (A)(3) to (A)(5) applies.

    Each changes the government haircut and none is modeled, so the haircut computed
    here is the firm's haircut only when all three are ruled out. Not stating one is a
    missing input. Stating that one applies is a rule path this engine does not have.
    """
    ruled_out = True
    for stated, name, paragraph, provision in (
        (
            inputs.elects_a3_cross_category_exclusion,
            "elects_a3_cross_category_exclusion",
            "(c)(2)(vi)(A)(3)",
            "the election to exclude offsetting securities across categories",
        ),
        (
            inputs.elects_a4_futures_deliverable_inclusion,
            "elects_a4_futures_deliverable_inclusion",
            "(c)(2)(vi)(A)(4)",
            "the election to include securities deliverable against government futures",
        ),
        (
            inputs.qualifies_a5_government_dealer_reduction,
            "qualifies_a5_government_dealer_reduction",
            "(c)(2)(vi)(A)(5)",
            "the 75 percent deduction for a qualifying government securities dealer",
        ),
    ):
        if stated is None:
            found.missing_inputs.append(name)
            ruled_out = False
        elif stated:
            rules.flag(f"Rule 15c3-1{paragraph}, {provision}, applies and is not modeled")
            ruled_out = False
    return ruled_out


def _government_haircut(
    positions: list[Position],
    election: GovernmentElection,
    rules: RuleReader,
    found: _Findings,
) -> list[HaircutLine] | None:
    bands = _government_bands(rules)
    offset = rules.value(GOV_OFFSET) if election is GovernmentElection.CATEGORY else ZERO
    if offset is None or any(rate is None for _, _, rate, _ in bands) or any(
        upper is None for _, _, _, upper in bands[:-1]
    ):
        return None
    # Bands are in maturity order and each starts where the one before it ends, so a
    # position belongs to the first band whose upper bound it is under, or to the last.
    limits = [(category, sub, upper) for category, sub, _, upper in bands[:-1] if upper is not None]
    final = bands[-1][0], bands[-1][1]
    net: dict[tuple[str, str], Decimal] = {}
    for position in positions:
        months = position.months_to_maturity
        if months is None:
            found.missing_inputs.append(f"months_to_maturity[{position.issue}]")
            continue
        key = next(((c, s) for c, s, upper in limits if months < upper), final)
        net[key] = net.get(key, ZERO) + position.long_market_value - position.short_market_value
    if any(p.months_to_maturity is None for p in positions):
        return None
    rates = {(category, sub): rate for category, sub, rate, _ in bands if rate is not None}

    lines: list[HaircutLine] = []
    for category, subcategories in GOVERNMENT_BANDS:
        long_deductions = short_deductions = ZERO
        for sub in subcategories:
            rate = rates[(category, sub)]
            amount = net.get((category, sub), ZERO)
            if amount >= ZERO:
                long_deductions += amount * rate
            else:
                short_deductions += -amount * rate
        if long_deductions == ZERO and short_deductions == ZERO:
            continue
        if election is GovernmentElection.CATEGORY:
            deduction = abs(long_deductions - short_deductions) + offset * min(
                long_deductions, short_deductions
            )
            paragraph = "(c)(2)(vi)(A)(1)"
        else:
            deduction = long_deductions + short_deductions
            paragraph = "(c)(2)(vi)(A)(2)"
        lines.append(
            HaircutLine(
                asset_class=AssetClass.GOVERNMENT,
                description=f"government {category}",
                amount=deduction,
                paragraph=paragraph,
            )
        )
    return lines


def _equity_haircut(positions: list[Position], rules: RuleReader) -> list[HaircutLine] | None:
    rate = rules.value(EQUITY_RATE)
    threshold = rules.value(EQUITY_LESSER_THRESHOLD)
    excess_rate = rules.value(EQUITY_EXCESS_RATE)
    if rate is None or threshold is None or excess_rate is None:
        return None
    lines = []
    for position in positions:
        greater = max(position.long_market_value, position.short_market_value)
        lesser = min(position.long_market_value, position.short_market_value)
        excess = max(lesser - threshold * greater, ZERO)
        lines.append(
            HaircutLine(
                asset_class=AssetClass.EQUITY,
                description=position.issue,
                amount=rate * greater + excess_rate * excess,
                paragraph="(c)(2)(vi)(J)",
            )
        )
    return lines


def _haircuts(
    inputs: NetCapitalInputs, rules: RuleReader, found: _Findings
) -> tuple[Decimal | None, tuple[HaircutLine, ...]]:
    by_class: dict[AssetClass, list[Position]] = {c: [] for c in AssetClass}
    known = set(AssetClass.__members__.values())
    unknown = sorted({p.asset_class for p in inputs.positions if p.asset_class not in known})
    for asset_class in unknown:
        rules.flag(f"no haircut is loaded for asset class {asset_class!r}")
    for position in inputs.positions:
        if position.asset_class not in unknown:
            by_class[AssetClass(position.asset_class)].append(position)
    government: list[HaircutLine] | None = []
    if by_class[AssetClass.GOVERNMENT]:
        # Both run, so one pass names every missing maturity and every unstated provision.
        ruled_out = _government_provisions_ruled_out(inputs, rules, found)
        government = _government_haircut(
            by_class[AssetClass.GOVERNMENT], inputs.government_election, rules, found
        )
        if not ruled_out:
            government = None
    equities = by_class[AssetClass.EQUITY]
    equity = _equity_haircut(equities, rules) if equities else []
    if government is None or equity is None or unknown:
        return None, tuple(government or ()) + tuple(equity or ())
    lines = tuple(government) + tuple(equity)
    return sum((line.amount for line in lines), ZERO), lines


def _ratio_requirement(
    inputs: NetCapitalInputs, rules: RuleReader, found: _Findings
) -> tuple[Decimal | None, bool | None, Decimal | None]:
    """(ratio requirement, whether it is exact, the multiple or floor-bearing figure used)."""
    if inputs.standard is NetCapitalStandard.ALTERNATIVE:
        floor = rules.value(ALT_FLOOR)
        percent = rules.value(ALT_PERCENT)
        if inputs.aggregate_debit_items is None:
            found.missing_inputs.append("aggregate_debit_items")
            return None, None, None
        if floor is None or percent is None:
            return None, None, None
        return max(floor, percent * inputs.aggregate_debit_items), True, None

    if inputs.aggregate_indebtedness is None:
        found.missing_inputs.append("aggregate_indebtedness")
    if inputs.months_in_business is None:
        found.missing_inputs.append("months_in_business")
    first_year_months = rules.value(FIRST_YEAR_MONTHS)
    if inputs.months_in_business is None or first_year_months is None:
        return None, None, None
    multiple = rules.value(
        AI_CEILING_FIRST_YEAR if inputs.months_in_business < first_year_months else AI_CEILING
    )
    if multiple is None or inputs.aggregate_indebtedness is None:
        return None, None, multiple
    with localcontext() as context:
        context.clear_flags()
        quotient = inputs.aggregate_indebtedness / multiple
        exact = not context.flags[Inexact]
    return quotient, exact, multiple


def _warning(
    rule_id: str,
    paragraph: str,
    *,
    threshold: Decimal | None,
    measure: Decimal | None,
    less_than: bool,
    note: str,
) -> EarlyWarning:
    if threshold is None or measure is None:
        return EarlyWarning(
            rule_id=rule_id, paragraph=paragraph, triggered=None, threshold=threshold,
            measure=measure, cushion=None, note=note,
        )
    cushion = measure - threshold if less_than else threshold - measure
    triggered = measure < threshold if less_than else measure > threshold
    return EarlyWarning(
        rule_id=rule_id, paragraph=paragraph, triggered=triggered, threshold=threshold,
        measure=measure, cushion=cushion, note=note,
    )


def _early_warnings(
    inputs: NetCapitalInputs,
    rules: RuleReader,
    found: _Findings,
    net_capital: Decimal | None,
    tentative: Decimal | None,
    minimum: Decimal | None,
) -> tuple[EarlyWarning, ...]:
    warnings: list[EarlyWarning] = []
    if inputs.standard is NetCapitalStandard.AGGREGATE_INDEBTEDNESS:
        multiple = rules.value(WARN_AI)
        warnings.append(
            _warning(
                WARN_AI, "17a-11(b)(1)",
                threshold=(
                    None if multiple is None or net_capital is None else multiple * net_capital
                ),
                measure=inputs.aggregate_indebtedness,
                less_than=False,
                note="aggregate indebtedness against the loaded multiple of net capital",
            )
        )
    else:
        percent = rules.value(WARN_ALT)
        debits = inputs.aggregate_debit_items
        warnings.append(
            _warning(
                WARN_ALT, "17a-11(b)(2)",
                threshold=None if percent is None or debits is None else percent * debits,
                measure=net_capital,
                less_than=True,
                note="net capital against the loaded percentage of aggregate debit items",
            )
        )
    minimum_multiple = rules.value(WARN_MINIMUM)
    warnings.append(
        _warning(
            WARN_MINIMUM, "17a-11(b)(3)",
            threshold=(
                None if minimum_multiple is None or minimum is None else minimum_multiple * minimum
            ),
            measure=net_capital,
            less_than=True,
            note="net capital against the loaded multiple of the minimum requirement",
        )
    )
    warnings.extend(_leverage_warnings(inputs, rules, found, tentative))
    return tuple(warnings)


def _leverage_warnings(
    inputs: NetCapitalInputs, rules: RuleReader, found: _Findings, tentative: Decimal | None
) -> list[EarlyWarning]:
    if inputs.reports_lending_activity_monthly is True:
        found.reasons.append(
            "Rule 17a-11(b)(5) not assessed: the firm reports this activity monthly"
        )
        return []
    if inputs.reports_lending_activity_monthly is None:
        found.missing_inputs.append("reports_lending_activity_monthly")
    multiple = rules.value(WARN_LEVERAGE)
    threshold = None if multiple is None or tentative is None else multiple * tentative
    measures = {
        "securities_loaned_and_repo_payable": inputs.securities_loaned_and_repo_payable,
        "securities_borrowed_and_reverse_repo_value": (
            inputs.securities_borrowed_and_reverse_repo_value
        ),
    }
    warnings = []
    for name, measure in measures.items():
        if measure is None:
            found.missing_inputs.append(name)
        warnings.append(
            _warning(
                WARN_LEVERAGE, "17a-11(b)(5)",
                threshold=threshold, measure=measure, less_than=False,
                note=f"{name} against the loaded multiple of tentative net capital",
            )
        )
    return warnings


def compute_net_capital(inputs: NetCapitalInputs, table: RuleTable) -> NetCapitalResult:
    """Compute net capital, the minimum requirement and early warning. Pure: no I/O, no clock."""
    rules = RuleReader(table)
    found = _Findings()

    if inputs.net_worth is None:
        found.missing_inputs.append("net_worth")
    additions = _total(inputs.additions, "additions", found)
    deductions = _total(inputs.deductions, "deductions", found)
    tentative = (
        None
        if inputs.net_worth is None or additions is None or deductions is None
        else inputs.net_worth + additions - deductions
    )
    haircuts, lines = _haircuts(inputs, rules, found)
    net_capital = None if tentative is None or haircuts is None else tentative - haircuts

    ratio, exact, multiple = _ratio_requirement(inputs, rules, found)
    activity = rules.value(_MINIMUM_RULE[inputs.category])
    minimum = None if ratio is None or activity is None else max(ratio, activity)
    excess = None if net_capital is None or minimum is None else net_capital - minimum

    if net_capital is not None and activity is not None and net_capital < activity:
        found.breaches.append(
            f"net capital is below the Rule 15c3-1(a)(2) minimum for a {inputs.category.value} firm"
        )
    if (
        inputs.standard is NetCapitalStandard.AGGREGATE_INDEBTEDNESS
        and net_capital is not None
        and multiple is not None
        and inputs.aggregate_indebtedness is not None
        and inputs.aggregate_indebtedness > multiple * net_capital
    ):
        found.breaches.append(
            "aggregate indebtedness exceeds the Rule 15c3-1(a)(1)(i) multiple of net capital"
        )
    if (
        inputs.standard is NetCapitalStandard.ALTERNATIVE
        and net_capital is not None
        and ratio is not None
        and net_capital < ratio
    ):
        found.breaches.append("net capital is below the Rule 15c3-1(a)(1)(ii) requirement")

    warnings = _early_warnings(inputs, rules, found, net_capital, tentative, minimum)
    found.breaches.extend(
        f"early warning: Rule {w.paragraph}, {w.note}" for w in warnings if w.triggered
    )

    missing_rules = rules.missing
    return NetCapitalResult(
        as_of=inputs.as_of,
        standard=inputs.standard,
        disposition=decide(
            missing_rules + tuple(found.unrecognised), found.missing_inputs, found.breaches
        ),
        net_worth=inputs.net_worth,
        total_additions=additions,
        total_deductions=deductions,
        tentative_net_capital=tentative,
        haircuts=haircuts,
        haircut_lines=lines,
        net_capital=net_capital,
        ratio_requirement=ratio,
        ratio_requirement_exact=exact,
        activity_minimum=activity,
        minimum_requirement=minimum,
        excess_net_capital=excess,
        early_warnings=warnings,
        missing_rules=missing_rules,
        missing_inputs=tuple(sorted(set(found.missing_inputs))),
        unrecognised_inputs=tuple(found.unrecognised),
        breaches=tuple(found.breaches),
        reasons=tuple(found.reasons),
        rules_used=rules.used,
    )
