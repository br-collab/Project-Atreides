"""WP-2 acceptance: the reserve formula engine.

Acceptance criteria (ORDER SC-2, WP-2):

- Adding a credit never lowers the requirement:
  ``test_property_adding_a_credit_never_lowers_the_requirement``.
- A mode switch changes the reduction exactly as loaded:
  ``test_property_mode_switch_changes_the_reduction_exactly_as_loaded``.
- Worked examples labelled SYNTHETIC: every balance below is SYNTHETIC, invented
  to exercise the arithmetic. None is taken from the rule text or any firm.
- Separate PAB computation, weekly and daily modes: the ``pab`` and ``mode`` tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given
from hypothesis import strategies as st

from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    BankCashDeposit,
    ComputationMode,
    LineBalance,
    NetCapitalStandard,
    ReserveAccounts,
    ReserveInputs,
    ReserveResult,
    compute_reserve,
    with_customer_excess_debits,
)
from atreides.customer_protection.rules import RuleTable, load_rule_table
from tests.customer_protection.conftest import TableEditor, without

AS_OF = date(2026, 10, 2)
D = Decimal
TABLE = load_rule_table()

#: SYNTHETIC. Credits 12,000,000; debits 9,000,000, of which Item 10 is 8,000,000.
SYNTHETIC_LINES = {
    "15c3-3a.item.01": D("10000000"),
    "15c3-3a.item.02": D("2000000"),
    "15c3-3a.item.10": D("8000000"),
    "15c3-3a.item.11": D("1000000"),
}


def lines(overrides: Mapping[str, Decimal | None] | None = None) -> tuple[LineBalance, ...]:
    values: dict[str, Decimal | None] = {
        rule_id: SYNTHETIC_LINES.get(rule_id, D(0))
        for rule_id in EXHIBIT_A_CREDITS + EXHIBIT_A_DEBITS
    }
    values.update(overrides or {})
    return tuple(LineBalance(rule_id=k, amount=v) for k, v in values.items())


def inputs(**changes: Any) -> ReserveInputs:
    base: dict[str, Any] = {
        "accounts": ReserveAccounts.CUSTOMER,
        "as_of": AS_OF,
        "standard": NetCapitalStandard.ALTERNATIVE,
        "mode": ComputationMode.WEEKLY,
        "lines": lines(),
        "average_total_credits": D("400000000"),
        "previously_daily_required": False,
        "cash_deposits": (
            BankCashDeposit(
                bank="SYNTHETIC BANK A", amount=D("2000000"), affiliated=False,
                bank_equity_capital=D("100000000"),
            ),
        ),
        "qualified_securities_deposit": D("1000000"),
    }
    base.update(changes)
    return ReserveInputs(**base)


# --- worked examples (SYNTHETIC) -----------------------------------------------------


def test_synthetic_customer_alternative_weekly() -> None:
    result = compute_reserve(inputs(), TABLE)
    assert result.total_credits == D("12000000")
    assert result.total_debits == D("9000000")
    assert result.debit_reduction_rate == D("0.03")
    assert result.debit_reduction == D("270000")
    assert result.net_debits == D("8730000")
    assert result.requirement == D("3270000")
    assert result.eligible_deposit == D("3000000")
    assert result.shortfall == D("270000")
    assert result.disposition is Disposition.HOLD
    assert result.daily_required is False
    assert result.claim_label == "EXPERIMENTAL"
    assert "short of the requirement by 270000" in result.breaches[0]


def test_synthetic_customer_alternative_daily_required() -> None:
    result = compute_reserve(
        inputs(
            mode=ComputationMode.DAILY,
            average_total_credits=D("600000000"),
            daily_requirement_effective_date=AS_OF,
        ),
        TABLE,
    )
    assert result.daily_required is True
    assert result.debit_reduction_rate == D("0.02")
    assert result.requirement == D("3180000")
    assert result.shortfall == D("180000")


def test_synthetic_customer_aggregate_indebtedness_uses_note_e3_on_item_10() -> None:
    result = compute_reserve(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS), TABLE
    )
    assert result.debit_reduction_rate == D("0.01")
    assert result.debit_reduction == D("80000")
    assert result.requirement == D("3080000")


def test_no_shortfall_passes() -> None:
    result = compute_reserve(inputs(qualified_securities_deposit=D("2000000")), TABLE)
    assert result.shortfall == D(0)
    assert result.disposition is Disposition.PASS
    assert result.missing_rules == () and result.breaches == ()
    assert {ref.rule_id for ref in result.rules_used} >= {
        "15c3-1.a1iiA.weekly_debit_reduction", "15c3-3.e3iB1.daily_threshold",
    }


def test_debits_over_credits_requires_nothing_and_reports_excess_debits() -> None:
    result = compute_reserve(
        inputs(lines=lines({"15c3-3a.item.01": D("1000000")}), qualified_securities_deposit=D(0)),
        TABLE,
    )
    assert result.requirement == D(0)
    assert result.excess_debits == D("8730000") - D("3000000")
    assert result.disposition is Disposition.PASS


# --- properties ------------------------------------------------------------------------

money = st.decimals(min_value=0, max_value=10**10, places=2, allow_nan=False)


@given(
    credits=st.lists(money, min_size=9, max_size=9),
    debits=st.lists(money, min_size=6, max_size=6),
    added=money,
    line=st.sampled_from(EXHIBIT_A_CREDITS),
    standard=st.sampled_from(list(NetCapitalStandard)),
    mode=st.sampled_from([ComputationMode.WEEKLY, ComputationMode.DAILY]),
)
def test_property_adding_a_credit_never_lowers_the_requirement(
    credits: list[Decimal],
    debits: list[Decimal],
    added: Decimal,
    line: str,
    standard: NetCapitalStandard,
    mode: ComputationMode,
) -> None:
    values = dict(zip(EXHIBIT_A_CREDITS + EXHIBIT_A_DEBITS, credits + debits, strict=True))
    before = compute_reserve(
        inputs(lines=lines(dict(values)), standard=standard, mode=mode), TABLE
    )
    values[line] += added
    after = compute_reserve(
        inputs(lines=lines(dict(values)), standard=standard, mode=mode), TABLE
    )
    assert before.requirement is not None and after.requirement is not None
    assert after.requirement >= before.requirement


@given(debits=st.lists(money, min_size=6, max_size=6), credits=money)
def test_property_mode_switch_changes_the_reduction_exactly_as_loaded(
    debits: list[Decimal], credits: Decimal
) -> None:
    weekly_rate = TABLE.get("15c3-1.a1iiA.weekly_debit_reduction")
    daily_rate = TABLE.get("15c3-1.a1iiA.daily_debit_reduction")
    assert weekly_rate is not None and weekly_rate.value is not None
    assert daily_rate is not None and daily_rate.value is not None
    values = dict(zip(EXHIBIT_A_DEBITS, debits, strict=True))
    values["15c3-3a.item.01"] = credits
    common = {
        "lines": lines(values),
        "average_total_credits": D("500000000"),
        "daily_requirement_effective_date": AS_OF,
    }
    weekly = compute_reserve(inputs(mode=ComputationMode.WEEKLY, **common), TABLE)
    daily = compute_reserve(inputs(mode=ComputationMode.DAILY, **common), TABLE)
    total = sum(debits, D(0))
    assert weekly.debit_reduction == total * weekly_rate.value
    assert daily.debit_reduction == total * daily_rate.value
    assert weekly.debit_reduction is not None and daily.debit_reduction is not None
    assert weekly.debit_reduction - daily.debit_reduction == total * (
        weekly_rate.value - daily_rate.value
    )


def test_a_changed_rate_in_the_table_changes_the_reduction(edited_table: TableEditor) -> None:
    """Mutation check: the engine reads the rate from the table, not from itself."""
    rule_id = "15c3-1.a1iiA.weekly_debit_reduction"
    table = edited_table(without(rule_id))
    result = compute_reserve(inputs(), table)
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == (rule_id,)
    assert result.requirement is None


# --- modes ------------------------------------------------------------------------------


def test_daily_threshold_reached_but_weekly_computation_holds() -> None:
    result = compute_reserve(
        inputs(
            average_total_credits=D("500000000"),
            daily_requirement_effective_date=AS_OF,
            qualified_securities_deposit=D("9000000"),
        ),
        TABLE,
    )
    assert result.daily_required is True
    assert result.disposition is Disposition.HOLD
    assert "not daily" in result.breaches[0]


def test_missing_average_total_credits_holds() -> None:
    result = compute_reserve(
        inputs(average_total_credits=None, qualified_securities_deposit=D("9000000")), TABLE
    )
    assert result.daily_required is None
    assert result.missing_inputs == ("average_total_credits",)
    assert result.disposition is Disposition.HOLD


def test_daily_threshold_inside_phase_in_is_not_yet_required() -> None:
    result = compute_reserve(
        inputs(
            average_total_credits=D("500000000"),
            daily_requirement_effective_date=AS_OF + timedelta(days=1),
        ),
        TABLE,
    )
    assert result.daily_required is False
    assert "phase-in" in result.reasons[0]


def test_daily_threshold_needs_an_evidenced_effective_date() -> None:
    result = compute_reserve(inputs(average_total_credits=D("500000000")), TABLE)
    assert result.daily_required is None
    assert "daily_requirement_effective_date" in result.missing_inputs
    assert result.disposition is Disposition.HOLD


def test_prior_daily_firm_remains_daily_until_sixty_days_after_exit_notice() -> None:
    still_daily = compute_reserve(
        inputs(
            mode=ComputationMode.DAILY,
            previously_daily_required=True,
            daily_exit_notice_date=AS_OF - timedelta(days=59),
        ),
        TABLE,
    )
    weekly = compute_reserve(
        inputs(
            previously_daily_required=True,
            daily_exit_notice_date=AS_OF - timedelta(days=60),
        ),
        TABLE,
    )
    assert still_daily.daily_required is True
    assert weekly.daily_required is False


def test_prior_daily_firm_without_exit_notice_remains_daily() -> None:
    result = compute_reserve(
        inputs(mode=ComputationMode.DAILY, previously_daily_required=True), TABLE
    )
    assert result.daily_required is True


def test_below_threshold_needs_prior_daily_status() -> None:
    result = compute_reserve(inputs(previously_daily_required=None), TABLE)
    assert result.daily_required is None
    assert "previously_daily_required" in result.missing_inputs


def test_exit_notice_period_must_be_loaded(edited_table: TableEditor) -> None:
    result = compute_reserve(
        inputs(
            mode=ComputationMode.DAILY,
            previously_daily_required=True,
            daily_exit_notice_date=AS_OF,
        ),
        edited_table(without("15c3-3.e3iB2.exit_notice")),
    )
    assert result.daily_required is None
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    ("notice_days_before", "rate", "reason"),
    [
        (30, D("0.02"), None),
        (29, D("0.03"), "less than the required period"),
        (None, D("0.03"), "no voluntary daily notice"),
    ],
)
def test_voluntary_daily_needs_its_notice(
    notice_days_before: int | None, rate: Decimal, reason: str | None
) -> None:
    notice = None if notice_days_before is None else AS_OF - timedelta(days=notice_days_before)
    result = compute_reserve(
        inputs(mode=ComputationMode.DAILY, voluntary_daily_notice_date=notice), TABLE
    )
    assert result.daily_required is False
    assert result.debit_reduction_rate == rate
    if reason is None:
        assert result.reasons == ()
    else:
        assert reason in result.reasons[0]


def _monthly(**changes: Any) -> ReserveInputs:
    base: dict[str, Any] = {
        "standard": NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
        "mode": ComputationMode.MONTHLY,
        "aggregate_indebtedness": D("4000000"),
        "net_capital": D("1000000"),
        "aggregate_customer_funds": D("900000"),
    }
    base.update(changes)
    return inputs(**base)


def test_monthly_deposit_is_the_loaded_factor_of_the_requirement() -> None:
    result = compute_reserve(_monthly(), TABLE)
    assert result.deposit_factor == D("1.05")
    assert result.requirement == D("3080000") * D("1.05")
    assert not any("monthly" in b for b in result.breaches)


@pytest.mark.parametrize(
    "changes",
    [{"aggregate_indebtedness": D("8000001")}, {"aggregate_customer_funds": D("1000001")}],
)
def test_monthly_over_a_ceiling_holds(changes: dict[str, Decimal]) -> None:
    result = compute_reserve(_monthly(**changes), TABLE)
    assert any("monthly computation is not available" in b for b in result.breaches)
    assert result.disposition is Disposition.HOLD


def test_monthly_without_eligibility_evidence_holds() -> None:
    result = compute_reserve(
        _monthly(net_capital=None, qualified_securities_deposit=D(10**8)), TABLE
    )
    assert result.missing_inputs == ("net_capital",)
    assert result.disposition is Disposition.HOLD


def test_monthly_on_the_alternative_standard_holds() -> None:
    result = compute_reserve(_monthly(standard=NetCapitalStandard.ALTERNATIVE), TABLE)
    assert any("at least weekly" in b for b in result.breaches)


def test_monthly_pab_is_available_for_an_eligible_firm_without_customer_factor() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=False,
        ),
        TABLE,
    )
    assert result.deposit_factor == D(1)
    assert result.requirement == D("3000000")
    assert result.missing_rules == ()


def test_monthly_pab_is_unavailable_to_a_customer_carrying_firm() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=True,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=False,
        ),
        TABLE,
    )
    assert result.disposition is Disposition.HOLD
    assert "carries customer" in result.breaches[0]


def test_monthly_pab_requires_four_clean_weeks_after_an_additional_deposit() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=True,
            pab_clean_weekly_computations=D(3),
        ),
        TABLE,
    )
    assert result.disposition is Disposition.HOLD
    assert "recovery" in result.breaches[0]


def test_monthly_pab_with_four_clean_weeks_is_available_again() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=True,
            pab_clean_weekly_computations=D(4),
        ),
        TABLE,
    )
    assert result.deposit_factor == D(1)
    assert not any("recovery" in breach for breach in result.breaches)


def test_monthly_pab_recovery_needs_the_clean_week_count() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=True,
        ),
        TABLE,
    )
    assert "pab_clean_weekly_computations" in result.missing_inputs
    assert result.disposition is Disposition.HOLD


def test_monthly_pab_needs_eligibility_evidence() -> None:
    result = compute_reserve(_monthly(accounts=ReserveAccounts.PAB), TABLE)
    assert set(result.missing_inputs) >= {
        "carries_customer_accounts",
        "conducts_proprietary_trading_business",
        "pab_last_monthly_required_additional_deposit",
    }
    assert result.disposition is Disposition.HOLD


def test_monthly_pab_proprietary_trading_is_ineligible() -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=True,
            pab_last_monthly_required_additional_deposit=False,
        ),
        TABLE,
    )
    assert result.disposition is Disposition.HOLD


def test_monthly_pab_provision_must_be_loaded(edited_table: TableEditor) -> None:
    result = compute_reserve(
        _monthly(
            accounts=ReserveAccounts.PAB,
            carries_customer_accounts=False,
            conducts_proprietary_trading_business=False,
            pab_last_monthly_required_additional_deposit=False,
        ),
        edited_table(without("15c3-3.e3iii.pab_monthly")),
    )
    assert result.deposit_factor is None
    assert result.disposition is Disposition.INDETERMINATE


# --- PAB ---------------------------------------------------------------------------------


def pab(**changes: Any) -> ReserveInputs:
    return inputs(accounts=ReserveAccounts.PAB, **changes)


@pytest.mark.parametrize("mode", [ComputationMode.WEEKLY, ComputationMode.DAILY])
def test_pab_on_the_alternative_standard_takes_no_debit_reduction(
    mode: ComputationMode,
) -> None:
    result = compute_reserve(pab(mode=mode), TABLE)
    assert result.disposition is Disposition.PASS
    assert result.missing_rules == ()
    assert result.total_debits == D("9000000")
    assert result.debit_reduction == D(0)
    assert result.requirement == D("3000000")


def test_pab_on_aggregate_indebtedness_takes_no_note_e3_reduction() -> None:
    result = compute_reserve(pab(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS), TABLE)
    assert result.debit_reduction == D(0)
    assert result.requirement == D("3000000")
    assert result.shortfall == D(0)
    assert result.disposition is Disposition.PASS


def test_pab_without_note_4_loaded_is_indeterminate(edited_table: TableEditor) -> None:
    table = edited_table(without("15c3-3a.pab_note_4.no_note_e3"))
    result = compute_reserve(pab(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS), table)
    assert result.disposition is Disposition.INDETERMINATE


def test_pab_requirement_is_satisfied_by_same_date_customer_excess_debits() -> None:
    customer = compute_reserve(
        inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
               lines=lines({"15c3-3a.item.01": D("1000000")})),
        TABLE,
    )
    assert customer.excess_debits == D("8920000") - D("3000000")
    linked = with_customer_excess_debits(
        pab(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS, qualified_securities_deposit=D(0),
            cash_deposits=()),
        customer,
    )
    result = compute_reserve(linked, TABLE)
    assert result.requirement == D("3000000")
    assert result.customer_excess_debits_applied == D("3000000")
    assert result.shortfall == D(0)


def test_customer_excess_debits_from_another_date_are_not_applied() -> None:
    result = compute_reserve(
        pab(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS, customer_excess_debits=D("10"),
            customer_computation_as_of=AS_OF - timedelta(days=1)),
        TABLE,
    )
    assert result.customer_excess_debits_applied == D(0)
    assert "another date" in result.reasons[0]


def test_customer_excess_debits_need_the_provision(edited_table: TableEditor) -> None:
    table = edited_table(without("15c3-3.e4.pab_from_customer_excess_debits"))
    result = compute_reserve(
        pab(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS, customer_excess_debits=D("10"),
            customer_computation_as_of=AS_OF),
        table,
    )
    assert result.customer_excess_debits_applied is None
    assert result.disposition is Disposition.INDETERMINATE


# --- lines -------------------------------------------------------------------------------


def test_a_missing_line_balance_holds_and_is_named() -> None:
    result = compute_reserve(inputs(lines=lines({"15c3-3a.item.04": None})), TABLE)
    assert result.missing_inputs == ("15c3-3a.item.04",)
    assert result.total_credits is None
    assert result.disposition is Disposition.HOLD


def test_an_omitted_line_is_missing_too() -> None:
    kept = tuple(line for line in lines() if line.rule_id != "15c3-3a.item.13")
    result = compute_reserve(inputs(lines=kept), TABLE)
    assert result.missing_inputs == ("15c3-3a.item.13",)


def test_an_unloaded_exhibit_a_line_is_indeterminate(edited_table: TableEditor) -> None:
    result = compute_reserve(inputs(), edited_table(without("15c3-3a.item.04")))
    assert result.missing_rules == ("15c3-3a.item.04",)
    assert result.disposition is Disposition.INDETERMINATE


def test_a_loaded_line_the_engine_does_not_model_is_indeterminate(
    edited_table: TableEditor,
) -> None:
    def add(document: dict[str, Any]) -> None:
        row = next(r for r in document["items"] if r["id"] == "15c3-3a.item.15")
        document["items"].append(dict(row, id="15c3-3a.item.16"))

    result = compute_reserve(inputs(), edited_table(add))
    assert result.missing_rules == (
        "15c3-3a.item.16 (listed in the loaded Exhibit A, not modeled)",
    )
    assert result.disposition is Disposition.INDETERMINATE


def test_an_unrecognised_input_line_is_indeterminate() -> None:
    extra = (*lines(), LineBalance(rule_id="15c3-3a.item.99", amount=D(1)))
    result = compute_reserve(inputs(lines=extra), TABLE)
    assert result.unrecognised_inputs == ("line 15c3-3a.item.99 is not an Exhibit A line",)
    assert result.disposition is Disposition.INDETERMINATE


def test_a_missing_note_e3_is_indeterminate(edited_table: TableEditor) -> None:
    table = edited_table(without("15c3-3a.note_e3.debit_reduction"))
    result = compute_reserve(inputs(standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS), table)
    assert result.debit_reduction is None
    assert result.disposition is Disposition.INDETERMINATE


def test_a_missing_daily_threshold_is_indeterminate(edited_table: TableEditor) -> None:
    result = compute_reserve(inputs(), edited_table(without("15c3-3.e3iB1.daily_threshold")))
    assert result.daily_required is None
    assert result.disposition is Disposition.INDETERMINATE


def test_a_missing_notice_period_falls_back_to_weekly(edited_table: TableEditor) -> None:
    table = edited_table(without("15c3-3.e3v.voluntary_daily_notice"))
    result = compute_reserve(
        inputs(mode=ComputationMode.DAILY, voluntary_daily_notice_date=AS_OF - timedelta(days=90)),
        table,
    )
    assert result.debit_reduction_rate == D("0.03")
    assert result.disposition is Disposition.INDETERMINATE


# --- deposits ------------------------------------------------------------------------------


def test_cash_at_an_affiliated_bank_does_not_count() -> None:
    deposit = BankCashDeposit(bank="SYNTHETIC AFFILIATE", amount=D("5000000"), affiliated=True)
    result = compute_reserve(inputs(cash_deposits=(deposit,)), TABLE)
    assert result.eligible_deposit == D("1000000")
    assert result.excluded_deposit == D("5000000")


def test_cash_over_the_bank_equity_cap_does_not_count() -> None:
    deposit = BankCashDeposit(
        bank="SYNTHETIC SMALL BANK", amount=D("5000000"), affiliated=False,
        bank_equity_capital=D("10000000"),
    )
    result = compute_reserve(inputs(cash_deposits=(deposit,)), TABLE)
    assert result.eligible_deposit == D("1500000") + D("1000000")
    assert result.excluded_deposit == D("3500000")


def test_unknown_bank_equity_holds() -> None:
    deposit = BankCashDeposit(bank="SYNTHETIC BANK B", amount=D(1), affiliated=False)
    result = compute_reserve(inputs(cash_deposits=(deposit,)), TABLE)
    assert result.missing_inputs == ("bank_equity_capital[SYNTHETIC BANK B]",)
    assert result.eligible_deposit is None and result.shortfall is None
    assert result.disposition is Disposition.HOLD


def test_missing_qualified_securities_holds() -> None:
    result = compute_reserve(inputs(qualified_securities_deposit=None), TABLE)
    assert result.missing_inputs == ("qualified_securities_deposit",)
    assert result.disposition is Disposition.HOLD


@pytest.mark.parametrize(
    ("rule_id", "affiliated"),
    [("15c3-3.e5.affiliated_bank_excluded", True), ("15c3-3.e5.bank_equity_cap", False)],
)
def test_deposit_rules_that_are_not_loaded_are_indeterminate(
    edited_table: TableEditor, rule_id: str, affiliated: bool
) -> None:
    deposit = BankCashDeposit(
        bank="SYNTHETIC", amount=D(1), affiliated=affiliated, bank_equity_capital=D(100)
    )
    result = compute_reserve(inputs(cash_deposits=(deposit,)), edited_table(without(rule_id)))
    assert result.eligible_deposit is None
    assert result.disposition is Disposition.INDETERMINATE


def test_no_cash_deposits_is_a_statement_not_a_gap() -> None:
    result = compute_reserve(inputs(cash_deposits=()), TABLE)
    assert result.eligible_deposit == D("1000000")
    assert result.excluded_deposit == D(0)


# --- the result model ----------------------------------------------------------------------


def test_the_result_coerces_its_disposition_at_the_boundary(table: RuleTable) -> None:
    result = compute_reserve(inputs(), table)
    dumped = result.model_dump()
    dumped["disposition"] = "PASS"
    assert ReserveResult.model_validate(dumped).disposition is Disposition.PASS
    dumped["disposition"] = "PROCEED"
    assert ReserveResult.model_validate(dumped).disposition is Disposition.INDETERMINATE


def test_the_computation_is_deterministic() -> None:
    assert compute_reserve(inputs(), TABLE).model_dump_json() == compute_reserve(
        inputs(), TABLE
    ).model_dump_json()
