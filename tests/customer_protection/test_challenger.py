"""WP-6 acceptance: the challenger report.

Acceptance criteria (ORDER SC-2, WP-6):

- Known variances classified: ``test_known_variances_are_classified`` shows rounding,
  timing, classification and match on one reserve computation.
- Unknown stays unknown: ``test_property_an_unexplained_variance_stays_unknown``,
  ``test_an_offset_in_another_group_does_not_explain``,
  ``test_a_near_offset_beyond_tolerance_does_not_explain``.

Every vendor figure below is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given
from hypothesis import strategies as st

from atreides.customer_protection.challenger import (
    ChallengerInputs,
    ChallengerReport,
    Figure,
    VarianceClass,
    VendorFigure,
    challenge,
    challenger_inputs,
    engine_figures,
)
from atreides.customer_protection.control import ControlInputs, check_possession_or_control
from atreides.customer_protection.net_capital import compute_net_capital
from atreides.customer_protection.record import (
    ChallengerComputation,
    record_computation,
    verify_replay,
)
from atreides.customer_protection.reserve import compute_reserve
from atreides.customer_protection.rules import RuleTable, load_rule_table
from atreides.dsor import DSORStore
from tests.customer_protection import test_control, test_net_capital, test_reserve
from tests.customer_protection.conftest import TableEditor, without

D = Decimal
TABLE = load_rule_table()
VENDOR = "SYNTHETIC VENDOR LEDGER"
AS_OF = test_reserve.AS_OF
TOLERANCE = D("1.00")


def reserve_case(
    overrides: dict[str, Decimal | None] | None = None,
    *,
    as_of: dict[str, date] | None = None,
    tolerance: Decimal | None = TOLERANCE,
    table: RuleTable = TABLE,
) -> tuple[ChallengerInputs, ChallengerReport]:
    inputs = test_reserve.inputs()
    result = compute_reserve(inputs, table)
    figures = engine_figures(inputs, result)
    vendor = tuple(
        VendorFigure(
            name=f.name,
            value=(overrides or {}).get(f.name, f.value),
            as_of=(as_of or {}).get(f.name),
        )
        for f in figures
    )
    challenger = challenger_inputs(
        inputs, result, vendor=VENDOR, vendor_as_of=AS_OF, vendor_figures=vendor,
        rounding_tolerance=tolerance,
    )
    return challenger, challenge(challenger)


def classes(report: ChallengerReport) -> dict[str, VarianceClass]:
    return {v.name: v.classification for v in report.variances}


def test_identical_figures_match_and_pass() -> None:
    _, report = reserve_case()
    assert set(classes(report).values()) == {VarianceClass.MATCH}
    assert report.disposition is Disposition.PASS
    assert report.claim_label == "EXPERIMENTAL"
    assert report.reasons == (f"compared with {VENDOR} as of {AS_OF}",)


def test_known_variances_are_classified() -> None:
    _, report = reserve_case(
        {
            # Rounding: within the client's tolerance.
            "requirement": D("3270000.40"),
            # Classification: 50,000 reported on Item 2 instead of Item 1. Totals unchanged.
            "15c3-3a.item.01": D("9950000"),
            "15c3-3a.item.02": D("2050000"),
        },
        as_of={"eligible_deposit": AS_OF - timedelta(days=1)},
    )
    found = classes(report)
    assert found["requirement"] is VarianceClass.ROUNDING
    assert found["15c3-3a.item.01"] is VarianceClass.CLASSIFICATION
    assert found["15c3-3a.item.02"] is VarianceClass.CLASSIFICATION
    assert found["total_credits"] is VarianceClass.MATCH
    # A figure that agrees is a match whatever its date: timing explains a difference.
    assert found["eligible_deposit"] is VarianceClass.MATCH
    item_01 = next(v for v in report.variances if v.name == "15c3-3a.item.01")
    assert item_01.variance == D("-50000")
    assert item_01.explanation == "offset by 15c3-3a.item.02"
    assert report.disposition is Disposition.HOLD


def test_a_difference_on_another_date_is_timing() -> None:
    _, report = reserve_case(
        {"eligible_deposit": D("2900000")},
        as_of={"eligible_deposit": AS_OF - timedelta(days=1)},
    )
    variance = next(v for v in report.variances if v.name == "eligible_deposit")
    assert variance.classification is VarianceClass.TIMING
    assert "as of 2026-10-01" in variance.explanation
    assert report.disposition is Disposition.HOLD


def test_rounding_alone_passes() -> None:
    _, report = reserve_case({"requirement": D("3269999.50")})
    assert classes(report)["requirement"] is VarianceClass.ROUNDING
    assert report.disposition is Disposition.PASS


def test_an_unexplained_variance_is_unknown_and_holds() -> None:
    _, report = reserve_case({"requirement": D("3280000")})
    assert classes(report)["requirement"] is VarianceClass.UNKNOWN
    assert report.breaches == (
        "requirement: unknown variance of 10000.00 (not explained)",
    )
    assert report.disposition is Disposition.HOLD


def test_an_offset_in_another_group_does_not_explain() -> None:
    # Item 1 (credits group) down 50,000, requirement (reserve group) up 50,000.
    _, report = reserve_case({"15c3-3a.item.01": D("9950000"), "requirement": D("3320000")})
    found = classes(report)
    assert found["15c3-3a.item.01"] is VarianceClass.UNKNOWN
    assert found["requirement"] is VarianceClass.UNKNOWN


def test_a_near_offset_beyond_tolerance_does_not_explain() -> None:
    _, report = reserve_case({"15c3-3a.item.01": D("9950000"), "15c3-3a.item.02": D("2050002")})
    found = classes(report)
    assert found["15c3-3a.item.01"] is VarianceClass.UNKNOWN
    assert found["15c3-3a.item.02"] is VarianceClass.UNKNOWN


def test_each_variance_pairs_at_most_once() -> None:
    _, report = reserve_case(
        {"15c3-3a.item.01": D("9950000"), "15c3-3a.item.02": D("2050000"),
         "15c3-3a.item.03": D("50000")}
    )
    found = classes(report)
    assert found["15c3-3a.item.03"] is VarianceClass.UNKNOWN
    assert found["15c3-3a.item.02"] is VarianceClass.CLASSIFICATION


@given(
    variance=st.decimals(min_value=D("1.01"), max_value=10**9, places=2, allow_nan=False),
    sign=st.sampled_from([D(1), D(-1)]),
    name=st.sampled_from(["requirement", "total_debits", "15c3-3a.item.04", "shortfall"]),
)
def test_property_an_unexplained_variance_stays_unknown(
    variance: Decimal, sign: Decimal, name: str
) -> None:
    challenger, _ = reserve_case()
    engine = next(f for f in challenger.engine_figures if f.name == name)
    assert engine.value is not None
    vendor = tuple(
        v if v.name != name else v.model_copy(update={"value": engine.value + sign * variance})
        for v in challenger.vendor_figures
    )
    report = challenge(challenger.model_copy(update={"vendor_figures": vendor}))
    assert classes(report)[name] is VarianceClass.UNKNOWN
    assert report.disposition is Disposition.HOLD


# --- missing evidence ---------------------------------------------------------------------


def test_no_tolerance_means_no_rounding_and_holds() -> None:
    _, report = reserve_case({"requirement": D("3270000.40")}, tolerance=None)
    assert classes(report)["requirement"] is VarianceClass.UNKNOWN
    assert "rounding_tolerance" in report.missing_inputs


def test_a_vendor_figure_that_is_missing_is_not_compared() -> None:
    _, report = reserve_case({"shortfall": None})
    assert classes(report)["shortfall"] is VarianceClass.NOT_COMPARED
    assert report.missing_inputs == ("figure:shortfall",)
    assert report.disposition is Disposition.HOLD


def test_a_vendor_only_figure_is_not_compared() -> None:
    challenger, _ = reserve_case()
    extra = (*challenger.vendor_figures, VendorFigure(name="haircut_total", value=D(1)))
    report = challenge(challenger.model_copy(update={"vendor_figures": extra}))
    only = next(v for v in report.variances if v.name == "haircut_total")
    assert only.group == "vendor_only"
    assert only.classification is VarianceClass.NOT_COMPARED


def test_an_engine_figure_that_could_not_be_computed_is_not_compared() -> None:
    inputs = test_reserve.inputs(qualified_securities_deposit=None)
    result = compute_reserve(inputs, TABLE)
    challenger = challenger_inputs(
        inputs, result, vendor=VENDOR, vendor_as_of=AS_OF,
        vendor_figures=(VendorFigure(name="shortfall", value=D(0)),),
        rounding_tolerance=TOLERANCE,
    )
    variance = next(v for v in challenge(challenger).variances if v.name == "shortfall")
    assert variance.classification is VarianceClass.NOT_COMPARED
    assert variance.explanation == "no engine figure"


def test_an_engine_with_a_missing_rule_makes_the_report_indeterminate(
    edited_table: TableEditor,
) -> None:
    table = edited_table(without("15c3-1.a1iiA.weekly_debit_reduction"))
    _, report = reserve_case(table=table)
    assert report.missing_rules == ("15c3-1.a1iiA.weekly_debit_reduction",)
    assert report.disposition is Disposition.INDETERMINATE


# --- other engines ------------------------------------------------------------------------


def test_net_capital_figures_include_each_haircut_line() -> None:
    inputs = test_net_capital.inputs()
    names = [f.name for f in engine_figures(inputs, compute_net_capital(inputs, TABLE))]
    assert names[:3] == ["net_worth", "total_additions", "total_deductions"]
    assert "haircut:SYNTHETIC EQUITY XYZ" in names
    assert "excess_net_capital" in names


def test_control_figures_are_per_issue() -> None:
    inputs = ControlInputs(as_of=test_control.AS_OF, issues=(test_control.issue(),))
    figures = engine_figures(inputs, check_possession_or_control(inputs, TABLE))
    assert figures == (
        Figure(name="SYNTHETIC ISSUE A:in_control", group="issue:SYNTHETIC ISSUE A",
               value=D(1200)),
        Figure(name="SYNTHETIC ISSUE A:shortfall", group="issue:SYNTHETIC ISSUE A",
               value=D(0)),
    )


# --- evidence --------------------------------------------------------------------------------


def test_a_challenger_comparison_is_recorded_and_replays() -> None:
    challenger, _ = reserve_case({"requirement": D("3280000")})
    record = record_computation(
        challenger, TABLE, operation_id=UUID(int=60),
        recorded_at=datetime(2026, 10, 4, 17, 0, tzinfo=UTC),
    )
    assert isinstance(record.computation, ChallengerComputation)
    assert record.advisory.subject == "challenger"
    assert record.advisory.enforcement_status == "ADVISORY_ONLY"
    assert record.advisory.disposition is Disposition.HOLD
    assert record.rule_versions == ()
    with DSORStore(":memory:") as store:
        stored = store.append(record)
        replayed = store.replay(stored.record_id)
    assert replayed.model_dump_json() == record.model_dump_json()
    assert verify_replay(replayed, TABLE).verified is True  # type: ignore[arg-type]


def test_the_report_coerces_its_disposition_at_the_boundary() -> None:
    _, report = reserve_case()
    dumped = report.model_dump()
    dumped["disposition"] = "proceed"
    assert ChallengerReport.model_validate(dumped).disposition is Disposition.INDETERMINATE


def test_a_vendor_must_be_named() -> None:
    challenger, _ = reserve_case()
    with pytest.raises(ValueError):
        ChallengerInputs.model_validate({**challenger.model_dump(), "vendor": ""})


def test_a_variance_exactly_at_the_tolerance_is_rounding() -> None:
    _, report = reserve_case({"requirement": D("3270001.00")})
    assert classes(report)["requirement"] is VarianceClass.ROUNDING
    _, report = reserve_case({"requirement": D("3270001.01")})
    assert classes(report)["requirement"] is VarianceClass.UNKNOWN
