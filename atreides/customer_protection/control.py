"""Partial possession-or-control location and conservation check.

EXPERIMENTAL (charter section 18.6). A challenger computation over a stock
record the caller supplies. It does not move a security and it files nothing.
It accepts the caller's fully-paid and excess-margin classifications and does
not establish compliance with 17 CFR 240.15c3-3(b) to (d).

WHAT IT CHECKS
--------------
Rule 15c3-3(b)(1) requires a broker-dealer to obtain and keep physical
possession or control of all fully paid and excess margin securities it carries
for customers. For each issue:

1. The requirement: fully paid plus excess margin quantity, as the books state.
2. Where the issue sits: every holding names a location type, and the location
   type must be one the loaded rule text names. Rule 15c3-3(c) locations count
   as control. Rule 15c3-3(d)(1) to (4) locations are the noncontrol locations
   the rule makes the firm act on. **Any other location type is INDETERMINATE**,
   by name, because the engine cannot say whether it is control.
3. Conservation: the holdings across all locations must add up to the firm's
   total position in the issue per its books. If they do not, the location
   breakdown is not evidence of anything, and the issue HOLDs.
4. The shortfall: the requirement less the quantity in control locations.
5. Where there is a shortfall and the same issue sits in a noncontrol location,
   the action Rule 15c3-3(d) requires, with the loaded deadlines and ages:
   release from lien or return from loan within the loaded business days of
   issuing instructions, and prompt steps (a buy-in or otherwise) for fails to
   receive, distributions receivable and short allocations older than the
   loaded number of calendar days.

NOT MODELED, AND SAID SO
------------------------
- The temporary-lag allowance of (b)(2) and the securities-borrowed agreement of
  (b)(3). A lag is a shortfall here; a FINOP (Financial and Operations
  Principal) decides whether it is excused.
- The timing of the daily determination in (d) and the weekly allowance for
  inactive margin accounts. The engine checks the as-of state it is given.
- Classification of a customer's securities as fully paid or excess margin.
  That needs account-level debit balances; the quantities are inputs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import Field, field_validator

from atreides.customer_protection.common import (
    Frozen,
    NonNegativeMoney,
    RuleReader,
    RuleRef,
    decide,
)
from atreides.customer_protection.rules.model import CLAIM_LABEL, RuleKind, RuleTable

__all__ = [
    "ControlAction",
    "ControlInputs",
    "ControlResult",
    "Holding",
    "IssueControl",
    "IssueRequirement",
    "Quantity",
    "check_possession_or_control",
]

ZERO = Decimal(0)

#: A non-negative quantity of securities. Exact, like money, and refused if inexact.
Quantity = NonNegativeMoney

LIEN_OR_LOAN = "15c3-3.noncontrol.d1"
LIEN_DAYS = "15c3-3.d1.lien_release_days"
LOAN_DAYS = "15c3-3.d1.loan_return_days"
#: Noncontrol locations whose action turns on age, and the rule id of each age.
AGED = {
    "15c3-3.noncontrol.d2": "15c3-3.d2.fail_to_receive_age",
    "15c3-3.noncontrol.d3": "15c3-3.d3.distribution_receivable_age",
    "15c3-3.noncontrol.d4": "15c3-3.d4.short_allocation_age",
}


class Holding(Frozen):
    """Some quantity of one issue at one location type."""

    #: Rule id of a loaded Rule 15c3-3(c) or (d) location, for example
    #: ``15c3-3.control.c5`` (a bank) or ``15c3-3.noncontrol.d1`` (lien or loan).
    location: str
    quantity: Quantity
    #: (d)(2) to (d)(4): calendar days the item has been in this state.
    age_days: Quantity | None = None
    #: (d)(1): True if loaned, False if subject to a lien securing borrowed money.
    loaned: bool | None = None


class IssueRequirement(Frozen):
    """One issue: what the firm must hold, and where it is."""

    issue: str = Field(min_length=1)
    fully_paid: Quantity | None
    excess_margin: Quantity | None
    #: The firm's total position in the issue per its stock record.
    books_total: Quantity | None
    holdings: tuple[Holding, ...]


class ControlInputs(Frozen):
    """The as-of stock record the check reads."""

    as_of: date
    issues: tuple[IssueRequirement, ...]


class ControlAction(Frozen):
    """What Rule 15c3-3(d) requires for one noncontrol holding of a short issue."""

    location: str
    quantity: Quantity
    paragraph: str
    action: str
    #: (d)(1): business days after instructions to obtain possession or control.
    deadline_business_days: Decimal | None = None
    #: (d)(2) to (d)(4): the age past which prompt steps are required.
    age_threshold_days: Decimal | None = None
    #: Whether the rule's condition for this action is met. ``None`` if it cannot be told.
    required: bool | None


class IssueControl(Frozen):
    """The check for one issue."""

    issue: str
    required: Quantity | None
    in_control: Quantity
    in_noncontrol: Quantity
    at_unknown_locations: Quantity
    books_total: Quantity | None
    conserved: bool | None
    shortfall: Quantity | None
    actions: tuple[ControlAction, ...]


class ControlResult(Frozen):
    """The check, its evidence, and its disposition."""

    engine: Literal["possession_or_control"] = "possession_or_control"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    as_of: date
    disposition: Disposition
    issues: tuple[IssueControl, ...]
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
        self.breaches: list[str] = []


def _action(
    holding: Holding, issue: str, rules: RuleReader, found: _Findings
) -> ControlAction:
    if holding.location == LIEN_OR_LOAN:
        if holding.loaned is None:
            found.missing_inputs.append(f"loaned[{issue}]")
            days = None
        else:
            days = rules.value(LOAN_DAYS if holding.loaned else LIEN_DAYS)
        return ControlAction(
            location=holding.location,
            quantity=holding.quantity,
            paragraph="15c3-3(d)(1)",
            action=(
                "issue instructions for the return of the loaned securities or their release "
                "from the lien not later than the business day after the determination"
            ),
            deadline_business_days=days,
            required=True,
        )
    age_rule = AGED.get(holding.location)
    if age_rule is None:
        rules.flag(f"noncontrol location {holding.location!r} is loaded but has no modeled action")
        return ControlAction(
            location=holding.location,
            quantity=holding.quantity,
            paragraph="15c3-3(d)",
            action="not modeled",
            required=None,
        )
    threshold = rules.value(age_rule)
    if holding.age_days is None:
        found.missing_inputs.append(f"age_days[{issue}, {holding.location}]")
    required = (
        None if threshold is None or holding.age_days is None else holding.age_days > threshold
    )
    return ControlAction(
        location=holding.location,
        quantity=holding.quantity,
        paragraph=f"15c3-3(d)({holding.location[-1]})",
        action="take prompt steps to obtain possession or control, through a buy-in or otherwise",
        age_threshold_days=threshold,
        required=required,
    )


def _check_issue(
    requirement: IssueRequirement,
    control: set[str],
    noncontrol: set[str],
    rules: RuleReader,
    found: _Findings,
) -> IssueControl:
    issue = requirement.issue
    for name in ("fully_paid", "excess_margin", "books_total"):
        if getattr(requirement, name) is None:
            found.missing_inputs.append(f"{name}[{issue}]")

    in_control = in_noncontrol = unknown = ZERO
    for holding in requirement.holdings:
        if holding.location in control:
            rules.present(holding.location)
            in_control += holding.quantity
        elif holding.location in noncontrol:
            rules.present(holding.location)
            in_noncontrol += holding.quantity
        else:
            rules.flag(
                f"location type {holding.location!r} is not a location the loaded "
                "Rule 15c3-3(c) or (d) text names"
            )
            unknown += holding.quantity

    total = in_control + in_noncontrol + unknown
    conserved = None if requirement.books_total is None else total == requirement.books_total
    if conserved is False:
        found.breaches.append(
            f"{issue}: holdings across locations ({total}) do not equal the books "
            f"({requirement.books_total})"
        )

    required = (
        None
        if requirement.fully_paid is None or requirement.excess_margin is None
        else requirement.fully_paid + requirement.excess_margin
    )
    shortfall = None if required is None else max(required - in_control, ZERO)
    actions: tuple[ControlAction, ...] = ()
    if shortfall is not None and shortfall > ZERO:
        found.breaches.append(
            f"{issue}: {shortfall} fully paid or excess margin securities are not in "
            "possession or control"
        )
        actions = tuple(
            _action(holding, issue, rules, found)
            for holding in requirement.holdings
            if holding.location in noncontrol
        )
    return IssueControl(
        issue=issue,
        required=required,
        in_control=in_control,
        in_noncontrol=in_noncontrol,
        at_unknown_locations=unknown,
        books_total=requirement.books_total,
        conserved=conserved,
        shortfall=shortfall,
        actions=actions,
    )


def check_possession_or_control(inputs: ControlInputs, table: RuleTable) -> ControlResult:
    """Check possession or control issue by issue. Pure: no I/O, no clock."""
    rules = RuleReader(table)
    found = _Findings()
    control = set(rules.of_kind(RuleKind.CONTROL_LOCATION))
    noncontrol = set(rules.of_kind(RuleKind.NONCONTROL_LOCATION))
    reasons: list[str] = []
    if not control:
        rules.flag("no Rule 15c3-3(c) control location is loaded")
    issues = tuple(
        _check_issue(requirement, control, noncontrol, rules, found)
        for requirement in inputs.issues
    )
    if not inputs.issues:
        reasons.append("no issues were supplied; nothing was checked")
        found.missing_inputs.append("issues")
    missing_rules = rules.missing
    return ControlResult(
        as_of=inputs.as_of,
        disposition=decide(missing_rules, found.missing_inputs, found.breaches),
        issues=issues,
        missing_rules=missing_rules,
        missing_inputs=tuple(sorted(set(found.missing_inputs))),
        unrecognised_inputs=(),
        breaches=tuple(found.breaches),
        reasons=tuple(reasons),
        rules_used=rules.used,
    )
