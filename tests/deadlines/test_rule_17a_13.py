"""DEADLINE-1 WP-4 acceptance tests for Rule 17a-13 security counts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from cannae_kernel.disposition import Disposition

from atreides.deadlines import SecurityCountInput, assess_security_count, load_rule_table

AS_OF = datetime(2026, 10, 9, 12, tzinfo=UTC)


class HolidayCalendar:
    def __init__(self, *holidays: date) -> None:
        self.holidays = frozenset(holidays)

    def add_business_days(self, start: date, days: int) -> date:
        result = start
        remaining = days
        while remaining:
            result += timedelta(days=1)
            if result.weekday() < 5 and result not in self.holidays:
                remaining -= 1
        return result

    def add_settlement_days(self, start: date, days: int) -> date:
        return self.add_business_days(start, days)


def test_next_count_window_uses_loaded_two_and_four_month_limits() -> None:
    result = assess_security_count(
        SecurityCountInput(prior_count_dates=(date(2026, 6, 30),)),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert result.disposition is Disposition.PASS
    assert result.next_count_earliest == date(2026, 8, 30)
    assert result.next_count_latest == date(2026, 10, 30)
    assert result.table_version == "deadline-rules/0.4-rule-17a-13"
    assert (
        result.source_sha256 == "85c88c8a834c42d508252964dd069d2099bb01a42a0d1ef8a5e6030630838f5b"
    )


def test_count_more_than_four_months_after_prior_is_flagged() -> None:
    result = assess_security_count(
        SecurityCountInput(
            prior_count_dates=(date(2026, 5, 31),),
            count_date=date(2026, 10, 1),
        ),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert result.disposition is Disposition.HOLD
    assert result.spacing_valid is False
    assert result.breaches == ("rule_17a_13.count_too_late",)


def test_count_less_than_two_months_after_prior_is_flagged() -> None:
    result = assess_security_count(
        SecurityCountInput(
            prior_count_dates=(date(2026, 8, 31),),
            count_date=date(2026, 10, 30),
        ),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == ("rule_17a_13.count_too_soon",)


def test_seven_business_day_recording_deadline_honors_holiday() -> None:
    result = assess_security_count(
        SecurityCountInput(
            prior_count_dates=(date(2026, 6, 9),),
            count_date=date(2026, 10, 9),
        ),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(date(2026, 10, 12)),
    )
    assert result.disposition is Disposition.PASS
    assert result.spacing_valid is True
    assert result.difference_recording_due == date(2026, 10, 21)


def test_latest_prior_count_controls_the_window() -> None:
    result = assess_security_count(
        SecurityCountInput(
            prior_count_dates=(date(2026, 1, 31), date(2026, 6, 30)),
            count_date=date(2026, 8, 30),
        ),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert result.prior_count_date == date(2026, 6, 30)
    assert result.spacing_valid is True


def test_missing_prior_count_or_calendar_is_hold() -> None:
    no_prior = assess_security_count(
        SecurityCountInput(prior_count_dates=()),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert no_prior.disposition is Disposition.HOLD
    assert no_prior.missing_inputs == ("prior_count_date",)

    no_calendar = assess_security_count(
        SecurityCountInput(prior_count_dates=(date(2026, 6, 30),)),
        evaluated_at=AS_OF,
        calendar=None,
    )
    assert no_calendar.disposition is Disposition.HOLD
    assert no_calendar.missing_inputs == ("business_calendar",)


def test_missing_loaded_rule_is_indeterminate() -> None:
    table = load_rule_table(as_of=date(2026, 10, 9))
    incomplete = table.model_copy(
        update={
            "rules": tuple(
                rule for rule in table.rules if rule.rule_id != "rule_17a_13.difference_recording"
            )
        }
    )
    result = assess_security_count(
        SecurityCountInput(prior_count_dates=(date(2026, 6, 30),)),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        table=incomplete,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == ("rule_17a_13.difference_recording",)


def test_missing_count_after_latest_date_is_hold() -> None:
    result = assess_security_count(
        SecurityCountInput(prior_count_dates=(date(2026, 5, 31),)),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == ("rule_17a_13.count_overdue",)
