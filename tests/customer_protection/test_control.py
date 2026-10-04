"""WP-4 acceptance: the possession or control check.

Acceptance criteria (ORDER SC-2, WP-4):

- A known shortfall is flagged: ``test_a_known_shortfall_is_flagged``.
- Conservation across locations: ``test_property_holdings_conserve_across_locations``
  and ``test_holdings_that_do_not_conserve_hold``.
- Unknown location type returns INDETERMINATE: ``test_an_unknown_location_is_indeterminate``.

Every quantity below is SYNTHETIC.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given
from hypothesis import strategies as st

from atreides.customer_protection.control import (
    ControlInputs,
    ControlResult,
    Holding,
    IssueRequirement,
    check_possession_or_control,
)
from atreides.customer_protection.rules import RuleKind, load_rule_table
from tests.customer_protection.conftest import TableEditor, without

D = Decimal
AS_OF = date(2026, 10, 2)
TABLE = load_rule_table()
BANK = "15c3-3.control.c5"
CLEARING = "15c3-3.control.c1"
LIEN = "15c3-3.noncontrol.d1"
FAIL = "15c3-3.noncontrol.d2"
DIVIDEND = "15c3-3.noncontrol.d3"
SHORT = "15c3-3.noncontrol.d4"


def issue(**changes: Any) -> IssueRequirement:
    base: dict[str, Any] = {
        "issue": "SYNTHETIC ISSUE A",
        "fully_paid": D(800),
        "excess_margin": D(200),
        "books_total": D(1500),
        "holdings": (
            Holding(location=CLEARING, quantity=D(900)),
            Holding(location=BANK, quantity=D(300)),
            Holding(location=LIEN, quantity=D(300), loaned=False),
        ),
    }
    base.update(changes)
    return IssueRequirement(**base)


def check(*issues: IssueRequirement, table: Any = TABLE) -> ControlResult:
    return check_possession_or_control(ControlInputs(as_of=AS_OF, issues=issues), table)


def test_issue_in_control_passes() -> None:
    result = check(issue())
    only = result.issues[0]
    assert only.required == D(1000)
    assert only.in_control == D(1200)
    assert only.in_noncontrol == D(300)
    assert only.conserved is True
    assert only.shortfall == D(0)
    assert only.actions == ()
    assert result.disposition is Disposition.PASS
    assert result.claim_label == "EXPERIMENTAL"


def test_a_known_shortfall_is_flagged() -> None:
    holdings = (
        Holding(location=CLEARING, quantity=D(600)),
        Holding(location=LIEN, quantity=D(500), loaned=False),
        Holding(location=FAIL, quantity=D(400), age_days=D(31)),
    )
    result = check(issue(holdings=holdings))
    only = result.issues[0]
    assert only.shortfall == D(400)
    assert result.breaches[0].startswith("SYNTHETIC ISSUE A: 400 fully paid")
    assert result.disposition is Disposition.HOLD
    lien, fail = only.actions
    assert lien.paragraph == "15c3-3(d)(1)" and lien.deadline_business_days == D(2)
    assert lien.required is True
    assert fail.paragraph == "15c3-3(d)(2)" and fail.age_threshold_days == D(30)
    assert fail.required is True


@pytest.mark.parametrize(
    ("holding", "days", "required"),
    [
        (Holding(location=LIEN, quantity=D(1), loaned=True), D(5), True),
        (Holding(location=FAIL, quantity=D(1), age_days=D(30)), None, False),
        (Holding(location=DIVIDEND, quantity=D(1), age_days=D(46)), None, True),
        (Holding(location=DIVIDEND, quantity=D(1), age_days=D(45)), None, False),
        (Holding(location=SHORT, quantity=D(1), age_days=D(31)), None, True),
    ],
)
def test_noncontrol_actions_use_the_loaded_deadlines_and_ages(
    holding: Holding, days: Decimal | None, required: bool
) -> None:
    result = check(
        issue(books_total=D(1), holdings=(holding,), fully_paid=D(1), excess_margin=D(0))
    )
    (action,) = result.issues[0].actions
    assert action.deadline_business_days == days
    assert action.required is required


def test_holdings_that_do_not_conserve_hold() -> None:
    result = check(issue(books_total=D(1600)))
    assert result.issues[0].conserved is False
    assert "do not equal the books" in result.breaches[0]
    assert result.disposition is Disposition.HOLD


quantity = st.decimals(min_value=0, max_value=10**9, places=0, allow_nan=False)
locations = st.sampled_from(
    TABLE.of_kind(RuleKind.CONTROL_LOCATION) + TABLE.of_kind(RuleKind.NONCONTROL_LOCATION)
)


@given(st.lists(st.tuples(locations.map(lambda r: r.id), quantity), min_size=1, max_size=12))
def test_property_holdings_conserve_across_locations(split: list[tuple[str, Decimal]]) -> None:
    holdings = tuple(
        Holding(location=loc, quantity=qty, loaned=True, age_days=D(0)) for loc, qty in split
    )
    total = sum((qty for _, qty in split), D(0))
    result = check(issue(holdings=holdings, books_total=total))
    only = result.issues[0]
    assert only.conserved is True
    assert only.in_control + only.in_noncontrol == total
    assert only.at_unknown_locations == D(0)
    assert only.shortfall == max(D(1000) - only.in_control, D(0))


def test_an_unknown_location_is_indeterminate() -> None:
    holdings = (
        Holding(location=CLEARING, quantity=D(1000)),
        Holding(location="SYNTHETIC VENDOR VAULT", quantity=D(500)),
    )
    result = check(issue(holdings=holdings))
    assert result.disposition is Disposition.INDETERMINATE
    assert result.issues[0].at_unknown_locations == D(500)
    assert result.issues[0].conserved is True
    assert "'SYNTHETIC VENDOR VAULT' is not a location" in result.missing_rules[0]


def test_a_control_location_that_is_not_loaded_is_indeterminate(
    edited_table: TableEditor,
) -> None:
    result = check(issue(), table=edited_table(without(BANK)))
    assert result.disposition is Disposition.INDETERMINATE
    assert result.issues[0].in_control == D(900)


def test_no_control_locations_loaded_is_indeterminate(edited_table: TableEditor) -> None:
    ids = [item.id for item in TABLE.of_kind(RuleKind.CONTROL_LOCATION)]
    result = check(issue(), table=edited_table(without(*ids)))
    assert "no Rule 15c3-3(c) control location is loaded" in result.missing_rules


def test_an_unloaded_deadline_is_indeterminate(edited_table: TableEditor) -> None:
    holdings = (Holding(location=LIEN, quantity=D(1500), loaned=False),)
    table = edited_table(without("15c3-3.d1.lien_release_days"))
    result = check(issue(holdings=holdings), table=table)
    assert result.issues[0].actions[0].deadline_business_days is None
    assert result.disposition is Disposition.INDETERMINATE


def test_an_unloaded_age_threshold_is_indeterminate(edited_table: TableEditor) -> None:
    holdings = (Holding(location=FAIL, quantity=D(1500), age_days=D(90)),)
    table = edited_table(without("15c3-3.d2.fail_to_receive_age"))
    result = check(issue(holdings=holdings), table=table)
    assert result.issues[0].actions[0].required is None
    assert result.disposition is Disposition.INDETERMINATE


def test_a_loaded_noncontrol_location_without_a_modeled_action_is_indeterminate(
    edited_table: TableEditor,
) -> None:
    def add(document: dict[str, Any]) -> None:
        row = next(r for r in document["items"] if r["id"] == FAIL)
        document["items"].append(dict(row, id="15c3-3.noncontrol.d9"))

    holdings = (Holding(location="15c3-3.noncontrol.d9", quantity=D(1500)),)
    result = check(issue(holdings=holdings), table=edited_table(add))
    assert result.issues[0].actions[0].action == "not modeled"
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        ({"fully_paid": None}, "fully_paid[SYNTHETIC ISSUE A]"),
        ({"excess_margin": None}, "excess_margin[SYNTHETIC ISSUE A]"),
        ({"books_total": None}, "books_total[SYNTHETIC ISSUE A]"),
        (
            {"holdings": (Holding(location=LIEN, quantity=D(1500)),)},
            "loaned[SYNTHETIC ISSUE A]",
        ),
        (
            {"holdings": (Holding(location=FAIL, quantity=D(1500)),)},
            f"age_days[SYNTHETIC ISSUE A, {FAIL}]",
        ),
    ],
)
def test_missing_inputs_hold_and_are_named(changes: dict[str, Any], missing: str) -> None:
    result = check(issue(**changes))
    assert missing in result.missing_inputs
    assert result.disposition is Disposition.HOLD


def test_no_issues_is_not_a_pass() -> None:
    result = check()
    assert result.disposition is Disposition.HOLD
    assert result.missing_inputs == ("issues",)


def test_several_issues_are_checked_independently() -> None:
    short = issue(issue="SYNTHETIC ISSUE B", fully_paid=D(2000))
    result = check(issue(), short)
    assert [i.shortfall for i in result.issues] == [D(0), D(1000)]
    assert result.disposition is Disposition.HOLD


def test_the_result_coerces_its_disposition_at_the_boundary() -> None:
    dumped = check(issue()).model_dump()
    dumped["disposition"] = "HOLD"
    assert ControlResult.model_validate(dumped).disposition is Disposition.HOLD
