"""WP-3 acceptance: the net capital engine.

Acceptance criteria (ORDER SC-2, WP-3):

- Minimum equals the greater of $250,000 and 2 percent of debit items:
  ``test_property_alternative_minimum_is_the_greater_of_floor_and_percent``, with
  both figures read from the loaded table, and the debit items being Exhibit A
  total debits before the reduction (``test_the_two_percent_uses_debits_before_reduction``).
- Cushion arithmetic exact: ``test_property_cushions_are_exact`` and the worked examples.
- Unknown asset class returns INDETERMINATE: ``test_an_unknown_asset_class_is_indeterminate``.
- Early warning thresholds only from Rule 17a-11 as loaded, INDETERMINATE when not
  loaded: ``test_an_unloaded_early_warning_threshold_is_indeterminate``.

Every balance below is SYNTHETIC.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given
from hypothesis import strategies as st

from atreides.customer_protection.net_capital import (
    BrokerDealerCategory,
    CapitalAdjustment,
    GovernmentElection,
    NetCapitalInputs,
    NetCapitalResult,
    Position,
    compute_net_capital,
)
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    ComputationMode,
    LineBalance,
    NetCapitalStandard,
    ReserveAccounts,
    ReserveInputs,
    compute_reserve,
)
from atreides.customer_protection.rules import load_rule_table
from tests.customer_protection.conftest import TableEditor, without

D = Decimal
AS_OF = date(2026, 10, 2)
TABLE = load_rule_table()

EQUITY = Position(
    issue="SYNTHETIC EQUITY XYZ", asset_class="equity",
    long_market_value=D("1000000"), short_market_value=D("300000"),
)
GOVERNMENT = (
    Position(issue="SYNTHETIC BILL", asset_class="government", long_market_value=D("2000000"),
             short_market_value=D(0), months_to_maturity=D(2)),
    Position(issue="SYNTHETIC NOTE 30M", asset_class="government", long_market_value=D("1000000"),
             short_market_value=D(0), months_to_maturity=D(30)),
    Position(issue="SYNTHETIC NOTE 18M", asset_class="government", long_market_value=D(0),
             short_market_value=D("500000"), months_to_maturity=D(18)),
)
#: Rule 15c3-1(c)(2)(vi)(A)(3) to (A)(5). The worked examples state that none applies, so
#: the modeled (A)(1) and (A)(2) haircut is the firm's haircut (SC2-WP3-01).
GOVERNMENT_PROVISIONS = (
    "elects_a3_cross_category_exclusion",
    "elects_a4_futures_deliverable_inclusion",
    "qualifies_a5_government_dealer_reduction",
)
NONE_APPLY = dict.fromkeys(GOVERNMENT_PROVISIONS, False)


def inputs(**changes: Any) -> NetCapitalInputs:
    base: dict[str, Any] = {
        "as_of": AS_OF,
        "standard": NetCapitalStandard.ALTERNATIVE,
        "category": BrokerDealerCategory.CARRYING,
        "net_worth": D("10000000"),
        "additions": (
            CapitalAdjustment(description="SYNTHETIC subordinated loan",
                              paragraph="(c)(2)(ii)", amount=D("1000000")),
        ),
        "deductions": (
            CapitalAdjustment(description="SYNTHETIC non-allowable assets",
                              paragraph="(c)(2)(iv)", amount=D("2000000")),
        ),
        "positions": (EQUITY, *GOVERNMENT),
        "aggregate_debit_items": D("100000000"),
        "reports_lending_activity_monthly": True,
        **NONE_APPLY,
    }
    base.update(changes)
    return NetCapitalInputs(**base)


def warning(result: NetCapitalResult, paragraph: str) -> Any:
    return next(w for w in result.early_warnings if w.paragraph == paragraph)


# --- worked examples (SYNTHETIC) -------------------------------------------------------


def test_synthetic_alternative_standard_carrying_firm() -> None:
    result = compute_net_capital(inputs(), TABLE)
    assert result.tentative_net_capital == D("9000000")
    # Equity (J): 15% of 1,000,000, plus 15% of (300,000 - 25% of 1,000,000).
    # Government category 2: |1,000,000 x 2% - 500,000 x 1.5%| + 50% x 7,500.
    assert [line.amount for line in result.haircut_lines] == [D("16250"), D("157500")]
    assert result.haircuts == D("173750")
    assert result.net_capital == D("8826250")
    assert result.ratio_requirement == D("2000000")
    assert result.activity_minimum == D("250000")
    assert result.minimum_requirement == D("2000000")
    assert result.excess_net_capital == D("6826250")
    assert warning(result, "17a-11(b)(2)").cushion == D("8826250") - D("5000000")
    assert warning(result, "17a-11(b)(3)").cushion == D("8826250") - D("2400000")
    assert result.disposition is Disposition.PASS
    assert result.claim_label == "EXPERIMENTAL"
    assert "not assessed" in result.reasons[0]


def test_synthetic_government_subcategory_election() -> None:
    result = compute_net_capital(
        inputs(positions=GOVERNMENT, government_election=GovernmentElection.SUBCATEGORY), TABLE
    )
    assert result.haircuts == D("20000") + D("7500")
    assert result.haircut_lines[0].paragraph == "(c)(2)(vi)(A)(2)"


def test_synthetic_aggregate_indebtedness_standard() -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("30000000"), months_in_business=D(36)),
        TABLE,
    )
    assert result.ratio_requirement == D("2000000")
    assert result.ratio_requirement_exact is True
    assert result.minimum_requirement == D("2000000")
    assert warning(result, "17a-11(b)(1)").threshold == D("12") * D("8826250")
    assert result.disposition is Disposition.PASS


def test_a_non_terminating_ratio_requirement_says_so_and_decides_nothing() -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("10000000"), months_in_business=D(36)),
        TABLE,
    )
    assert result.ratio_requirement_exact is False
    assert result.ratio_requirement is not None
    assert Fraction(result.ratio_requirement) * 15 != 10_000_000
    assert result.breaches == ()


def test_the_first_year_uses_the_lower_multiple() -> None:
    # 8,826,250 x 8 = 70,610,000: 75,000,000 breaches in year one, not after.
    first = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("75000000"), months_in_business=D(11)),
        TABLE,
    )
    later = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("75000000"), months_in_business=D(12)),
        TABLE,
    )
    assert any("(a)(1)(i)" in b for b in first.breaches)
    assert not any("(a)(1)(i)" in b for b in later.breaches)
    assert warning(later, "17a-11(b)(1)").triggered is False


def test_aggregate_indebtedness_over_the_warning_multiple_holds() -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("110000000"), months_in_business=D(36)),
        TABLE,
    )
    assert warning(result, "17a-11(b)(1)").triggered is True
    assert not any("(a)(1)(i)" in b for b in result.breaches)
    assert result.disposition is Disposition.HOLD


def test_net_capital_below_the_minimum_holds() -> None:
    result = compute_net_capital(inputs(net_worth=D("2900000")), TABLE)
    assert result.net_capital == D("1726250")
    assert result.excess_net_capital == D("-273750")
    assert any("(a)(1)(ii) requirement" in b for b in result.breaches)
    assert result.disposition is Disposition.HOLD


def test_net_capital_below_the_activity_minimum_holds() -> None:
    result = compute_net_capital(
        inputs(net_worth=D("1000000"), aggregate_debit_items=D(0)), TABLE
    )
    assert any("(a)(2) minimum for a carrying firm" in b for b in result.breaches)


def test_inside_the_early_warning_band_holds_without_a_deficiency() -> None:
    # Debit items of 1,000,000 make the 250,000 floor the minimum. Net capital 280,000
    # is above it and below 120% of it, and above 5% of debit items.
    result = compute_net_capital(
        inputs(net_worth=D("1453750"), aggregate_debit_items=D("1000000")), TABLE
    )
    assert result.net_capital == D("280000")
    assert result.minimum_requirement == D("250000")
    assert result.excess_net_capital == D("30000")
    assert warning(result, "17a-11(b)(2)").triggered is False
    assert warning(result, "17a-11(b)(3)").triggered is True
    assert warning(result, "17a-11(b)(3)").cushion == D("-20000")
    assert result.breaches == (
        "early warning: Rule 17a-11(b)(3), net capital against the loaded multiple of the "
        "minimum requirement",
    )
    assert result.disposition is Disposition.HOLD


def test_the_leverage_test_against_tentative_net_capital() -> None:
    result = compute_net_capital(
        inputs(reports_lending_activity_monthly=False,
               securities_loaned_and_repo_payable=D("225000001"),
               securities_borrowed_and_reverse_repo_value=D("1")),
        TABLE,
    )
    loaned, borrowed = (w for w in result.early_warnings if w.paragraph == "17a-11(b)(5)")
    assert loaned.threshold == D("225000000")
    assert loaned.triggered is True and borrowed.triggered is False
    assert result.disposition is Disposition.HOLD


def test_the_two_percent_uses_debits_before_reduction() -> None:
    lines = tuple(
        LineBalance(rule_id=r, amount=D("100000000") if r == "15c3-3a.item.10" else D(0))
        for r in EXHIBIT_A_CREDITS + EXHIBIT_A_DEBITS
    )
    reserve = compute_reserve(
        ReserveInputs(
            accounts=ReserveAccounts.CUSTOMER, as_of=AS_OF,
            standard=NetCapitalStandard.ALTERNATIVE, mode=ComputationMode.WEEKLY, lines=lines,
            average_total_credits=D(0), qualified_securities_deposit=D(0),
        ),
        TABLE,
    )
    assert reserve.net_debits == D("97000000")
    result = compute_net_capital(inputs(aggregate_debit_items=reserve.total_debits), TABLE)
    assert result.ratio_requirement == D("2000000")


# --- properties ---------------------------------------------------------------------------

money = st.decimals(min_value=0, max_value=10**11, places=2, allow_nan=False)


@given(debits=money)
def test_property_alternative_minimum_is_the_greater_of_floor_and_percent(debits: Decimal) -> None:
    floor = TABLE.get("15c3-1.a1ii.alternative_floor")
    percent = TABLE.get("15c3-1.a1ii.alternative_debit_percent")
    assert floor is not None and floor.value == D("250000")
    assert percent is not None and percent.value == D("0.02")
    result = compute_net_capital(inputs(aggregate_debit_items=debits), TABLE)
    assert result.minimum_requirement == max(D("250000"), D("0.02") * debits)


@given(net_worth=st.decimals(min_value=-10**9, max_value=10**10, places=2, allow_nan=False),
       debits=money)
def test_property_cushions_are_exact(net_worth: Decimal, debits: Decimal) -> None:
    result = compute_net_capital(
        inputs(net_worth=net_worth, aggregate_debit_items=debits), TABLE
    )
    assert result.net_capital is not None and result.minimum_requirement is not None
    assert result.excess_net_capital is not None
    assert result.excess_net_capital + result.minimum_requirement == result.net_capital
    b3 = warning(result, "17a-11(b)(3)")
    assert b3.cushion == result.net_capital - D("1.2") * result.minimum_requirement
    assert b3.triggered is (b3.cushion < 0)


# --- indeterminate and hold ----------------------------------------------------------------


def test_an_unknown_asset_class_is_indeterminate() -> None:
    corporate = Position(issue="SYNTHETIC BOND", asset_class="nonconvertible_debt",
                         long_market_value=D(1), short_market_value=D(0))
    result = compute_net_capital(inputs(positions=(EQUITY, corporate)), TABLE)
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == ("no haircut is loaded for asset class 'nonconvertible_debt'",)
    assert result.haircuts is None and result.net_capital is None


@pytest.mark.parametrize(
    "rule_id",
    [
        "15c3-1.c2viA1.cat2.ii.rate",
        "15c3-1.c2viA1.cat1.iii.upper_months",
        "15c3-1.c2viA1.offset_percent",
        "15c3-1.c2viJ.lesser_threshold",
    ],
)
def test_an_unloaded_haircut_rule_is_indeterminate(edited_table: TableEditor, rule_id: str) -> None:
    result = compute_net_capital(inputs(), edited_table(without(rule_id)))
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == (rule_id,)
    assert result.net_capital is None


@pytest.mark.parametrize(
    ("rule_id", "paragraph"),
    [("17a-11.b2.alternative_warning", "17a-11(b)(2)"),
     ("17a-11.b3.minimum_warning", "17a-11(b)(3)")],
)
def test_an_unloaded_early_warning_threshold_is_indeterminate(
    edited_table: TableEditor, rule_id: str, paragraph: str
) -> None:
    result = compute_net_capital(inputs(), edited_table(without(rule_id)))
    assert warning(result, paragraph).triggered is None
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    "rule_id",
    ["15c3-1.a1ii.alternative_floor", "15c3-1.a2i.minimum.carrying"],
)
def test_an_unloaded_minimum_is_indeterminate(edited_table: TableEditor, rule_id: str) -> None:
    result = compute_net_capital(inputs(), edited_table(without(rule_id)))
    assert result.minimum_requirement is None
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    "rule_id",
    ["15c3-1.a1i.first_year_months", "15c3-1.a1i.ai_ceiling", "17a-11.b1.ai_warning"],
)
def test_unloaded_aggregate_indebtedness_rules_are_indeterminate(
    edited_table: TableEditor, rule_id: str
) -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               aggregate_indebtedness=D("30000000"), months_in_business=D(36)),
        edited_table(without(rule_id)),
    )
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        ({"net_worth": None}, "net_worth"),
        ({"aggregate_debit_items": None}, "aggregate_debit_items"),
        ({"reports_lending_activity_monthly": None}, "reports_lending_activity_monthly"),
        (
            {"deductions": (CapitalAdjustment(description="SYNTHETIC", paragraph="(c)(2)(iv)",
                                              amount=None),)},
            "deductions[SYNTHETIC]",
        ),
        (
            {"positions": (Position(issue="SYNTHETIC NOTE", asset_class="government",
                                    long_market_value=D(1), short_market_value=D(0)),)},
            "months_to_maturity[SYNTHETIC NOTE]",
        ),
    ],
)
def test_missing_inputs_hold_and_are_named(changes: dict[str, Any], missing: str) -> None:
    result = compute_net_capital(inputs(**changes), TABLE)
    assert missing in result.missing_inputs
    assert result.disposition is Disposition.HOLD


def test_missing_aggregate_indebtedness_evidence_holds() -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS), TABLE
    )
    assert {"aggregate_indebtedness", "months_in_business"} <= set(result.missing_inputs)
    assert result.ratio_requirement is None
    assert result.disposition is Disposition.HOLD


def test_months_in_business_without_aggregate_indebtedness_holds() -> None:
    result = compute_net_capital(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS, months_in_business=D(36)),
        TABLE,
    )
    assert result.missing_inputs == ("aggregate_indebtedness",)


def test_missing_leverage_measures_hold() -> None:
    result = compute_net_capital(inputs(reports_lending_activity_monthly=False), TABLE)
    assert set(result.missing_inputs) == {
        "securities_loaned_and_repo_payable", "securities_borrowed_and_reverse_repo_value",
    }


# --- maturity bands ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("months", "rate"),
    [(D(0), D(0)), (D("2.99"), D(0)), (D(3), D("0.005")), (D(12), D("0.015")),
     (D(299), D("0.055")), (D(300), D("0.06")), (D(480), D("0.06"))],
)
def test_maturity_band_edges(months: Decimal, rate: Decimal) -> None:
    position = Position(issue="SYNTHETIC", asset_class="government",
                        long_market_value=D("1000000"), short_market_value=D(0),
                        months_to_maturity=months)
    result = compute_net_capital(inputs(positions=(position,)), TABLE)
    assert result.haircuts == D("1000000") * rate


def test_no_positions_means_no_haircut() -> None:
    result = compute_net_capital(inputs(positions=()), TABLE)
    assert result.haircuts == D(0) and result.haircut_lines == ()


@pytest.mark.parametrize("category", list(BrokerDealerCategory))
def test_every_category_minimum_is_loaded(category: BrokerDealerCategory) -> None:
    result = compute_net_capital(inputs(category=category), TABLE)
    assert result.activity_minimum is not None
    assert result.missing_rules == ()


def test_the_result_coerces_its_disposition_at_the_boundary() -> None:
    dumped = compute_net_capital(inputs(), TABLE).model_dump()
    dumped["disposition"] = "pass"
    assert NetCapitalResult.model_validate(dumped).disposition is Disposition.INDETERMINATE


# --- SC2-WP3-01: government provisions the engine does not model ----------------------
#
# Rule 15c3-1(c)(2)(vi)(A)(3) and (A)(4) are elections a firm may make, and (A)(5) cuts
# the deduction for a qualifying government securities dealer. Each changes the government
# haircut and none is modeled. The firm states whether each applies. Unstated is a missing
# input, so HOLD. One that applies is a rule path the engine cannot compute, so
# INDETERMINATE. Either way no government haircut is claimed.

def government_only(**changes: Any) -> NetCapitalInputs:
    """Government positions only, so the provisions alone decide the haircut."""
    base: dict[str, Any] = {"positions": GOVERNMENT}
    base.update(changes)
    return inputs(**base)


def test_a_caller_that_never_mentions_the_provisions_holds() -> None:
    """A caller written before these fields existed. Before SC2-WP3-01 this returned PASS
    with an (A)(1) haircut, because nothing could say whether (A)(3) to (A)(5) applied."""
    stated = government_only().model_dump()
    written_before = NetCapitalInputs(
        **{k: v for k, v in stated.items() if k not in GOVERNMENT_PROVISIONS}
    )
    result = compute_net_capital(written_before, TABLE)
    assert result.disposition is Disposition.HOLD
    assert set(GOVERNMENT_PROVISIONS) <= set(result.missing_inputs)
    assert result.haircuts is None


def test_unstated_government_provisions_hold_and_claim_no_haircut() -> None:
    unstated = {name: None for name in GOVERNMENT_PROVISIONS}
    result = compute_net_capital(government_only(**unstated), TABLE)
    assert set(GOVERNMENT_PROVISIONS) <= set(result.missing_inputs)
    assert result.disposition is Disposition.HOLD
    assert result.haircuts is None
    assert result.net_capital is None
    assert not [line for line in result.haircut_lines if line.asset_class == "government"]


@pytest.mark.parametrize("provision", GOVERNMENT_PROVISIONS)
def test_each_unstated_government_provision_is_named(provision: str) -> None:
    result = compute_net_capital(government_only(**{**NONE_APPLY, provision: None}), TABLE)
    assert provision in result.missing_inputs
    assert result.disposition is Disposition.HOLD
    assert result.haircuts is None


@pytest.mark.parametrize(
    ("provision", "paragraph"),
    [
        ("elects_a3_cross_category_exclusion", "(c)(2)(vi)(A)(3)"),
        ("elects_a4_futures_deliverable_inclusion", "(c)(2)(vi)(A)(4)"),
        ("qualifies_a5_government_dealer_reduction", "(c)(2)(vi)(A)(5)"),
    ],
)
def test_a_government_provision_that_applies_is_indeterminate(
    provision: str, paragraph: str
) -> None:
    result = compute_net_capital(government_only(**{**NONE_APPLY, provision: True}), TABLE)
    assert result.disposition is Disposition.INDETERMINATE
    assert any(paragraph in rule for rule in result.missing_rules)
    assert result.haircuts is None
    assert result.net_capital is None


def test_government_provisions_ruled_out_compute_the_modeled_haircut() -> None:
    stated = compute_net_capital(government_only(**NONE_APPLY), TABLE)
    assert stated.haircuts is not None
    assert {line.paragraph for line in stated.haircut_lines} == {"(c)(2)(vi)(A)(1)"}
    assert not set(GOVERNMENT_PROVISIONS) & set(stated.missing_inputs)


def test_government_provisions_are_not_asked_without_government_positions() -> None:
    """They change only the government haircut, so an equity-only firm is not asked."""
    unstated = {name: None for name in GOVERNMENT_PROVISIONS}
    result = compute_net_capital(inputs(positions=(EQUITY,), **unstated), TABLE)
    assert not set(GOVERNMENT_PROVISIONS) & set(result.missing_inputs)
    assert result.haircuts is not None


def test_unstated_provisions_and_a_missing_maturity_are_both_named() -> None:
    """One pass names everything a caller must supply, not the first gap only."""
    undated = Position(issue="SYNTHETIC NOTE", asset_class="government",
                       long_market_value=D(1), short_market_value=D(0))
    unstated = {name: None for name in GOVERNMENT_PROVISIONS}
    result = compute_net_capital(government_only(positions=(undated,), **unstated), TABLE)
    assert {"months_to_maturity[SYNTHETIC NOTE]", *GOVERNMENT_PROVISIONS} <= set(
        result.missing_inputs
    )
