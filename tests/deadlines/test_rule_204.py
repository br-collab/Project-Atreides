"""DEADLINE-1 WP-2 acceptance tests for the Regulation SHO Rule 204 clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from cannae_kernel.disposition import Disposition

from atreides.deadlines import Rule204Fail, Rule204Origin, assess_rule_204, load_rule_table

OPEN = time(9, 30, tzinfo=timezone(timedelta(hours=-4)))
BEFORE_DUE = datetime(2026, 10, 6, 8, tzinfo=UTC)


class WeekdayCalendar:
    def add_business_days(self, start: date, days: int) -> date:
        return self._add_weekdays(start, days)

    def add_settlement_days(self, start: date, days: int) -> date:
        return self._add_weekdays(start, days)

    @staticmethod
    def _add_weekdays(start: date, days: int) -> date:
        result = start
        remaining = days
        while remaining:
            result += timedelta(days=1)
            if result.weekday() < 5:
                remaining -= 1
        return result


def _fail(origin: Rule204Origin | str | None) -> Rule204Fail:
    return Rule204Fail(
        security="SYNTHETIC-EQUITY",
        trade_date=date(2026, 10, 2),
        settlement_date=date(2026, 10, 5),
        fail_quantity=Decimal("100"),
        origin_class=origin,
    )


@pytest.mark.parametrize(
    ("origin", "expected_date", "rule_id"),
    [
        (Rule204Origin.SHORT_OR_GENERAL, date(2026, 10, 6), "rule_204.short_or_general"),
        (Rule204Origin.LONG, date(2026, 10, 8), "rule_204.long"),
        (Rule204Origin.MARKET_MAKING, date(2026, 10, 8), "rule_204.market_making"),
        (Rule204Origin.DEEMED_OWNED, date(2026, 11, 6), "rule_204.deemed_owned"),
    ],
)
def test_each_origin_uses_its_loaded_deadline(
    origin: Rule204Origin, expected_date: date, rule_id: str
) -> None:
    result = assess_rule_204(
        _fail(origin),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=OPEN,
    )
    assert result.disposition is Disposition.PASS
    assert result.due_at is not None
    assert result.due_at.date() == expected_date
    assert result.due_at.timetz() == OPEN
    assert result.rule_id == rule_id
    assert result.rule_citation is not None
    assert (
        result.source_sha256 == "4c4223552ab13f947bbc2c2cec19af70fc4ee1ea5b1baeb9443c3e2665a581bf"
    )
    assert result.enforcement_status == "ADVISORY_ONLY"
    assert result.claim_label == "EXPERIMENTAL"


def test_origin_class_missing_is_hold_and_is_not_defaulted() -> None:
    result = assess_rule_204(
        _fail(None),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=OPEN,
    )
    assert result.disposition is Disposition.HOLD
    assert result.due_at is None
    assert result.missing_inputs == ("origin_class",)


def test_unknown_origin_class_is_indeterminate() -> None:
    result = assess_rule_204(
        _fail("UNKNOWN"),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=OPEN,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.due_at is None


def test_overdue_closeout_is_hold_and_reports_preborrow_condition() -> None:
    result = assess_rule_204(
        _fail(Rule204Origin.SHORT_OR_GENERAL),
        evaluated_at=datetime(2026, 10, 6, 15, tzinfo=UTC),
        calendar=WeekdayCalendar(),
        regular_trading_open=OPEN,
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == ("rule_204.close_out_overdue",)
    assert result.preborrow_condition_applies is True


def test_missing_regular_trading_open_is_indeterminate() -> None:
    result = assess_rule_204(
        _fail(Rule204Origin.SHORT_OR_GENERAL),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=None,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == ("regular_trading_hours",)


def test_naive_regular_trading_open_is_indeterminate() -> None:
    result = assess_rule_204(
        _fail(Rule204Origin.SHORT_OR_GENERAL),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=time(9, 30),
    )
    assert result.disposition is Disposition.INDETERMINATE


def test_missing_settlement_calendar_is_hold() -> None:
    result = assess_rule_204(
        _fail(Rule204Origin.LONG),
        evaluated_at=BEFORE_DUE,
        calendar=None,
        regular_trading_open=OPEN,
    )
    assert result.disposition is Disposition.HOLD
    assert result.missing_inputs == ("settlement_calendar",)


def test_unloaded_rule_is_indeterminate() -> None:
    empty = load_rule_table()
    empty = empty.model_copy(update={"rules": ()})
    result = assess_rule_204(
        _fail(Rule204Origin.LONG),
        evaluated_at=BEFORE_DUE,
        calendar=WeekdayCalendar(),
        regular_trading_open=OPEN,
        table=empty,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == ("rule_204.long",)


def test_rule_204_table_is_hash_pinned_and_loads_without_refusal() -> None:
    table = load_rule_table()
    assert table.table_version == "deadline-rules/0.2-rule-204"
    assert len(table.rules) == 4
    assert table.rejected == ()
