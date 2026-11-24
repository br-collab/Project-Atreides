from datetime import date

import pytest

from atreides.deadlines.calendar import CalendarIndeterminateError, Market, MarketCalendar


def test_government_calendar_crosses_year_end_without_failing_open() -> None:
    calendar = MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES)
    assert calendar.add_business_days(date(2026, 12, 31), 1) == date(2027, 1, 4)


def test_unloaded_year_is_indeterminate_with_reason() -> None:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    with pytest.raises(CalendarIndeterminateError, match="no loaded data for 2029"):
        calendar.is_business_day(date(2029, 1, 2))


def test_close1_stress_years_are_sourced_and_observe_good_friday() -> None:
    government = MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES)
    equities = MarketCalendar.load(Market.US_EQUITIES)
    for calendar in (government, equities):
        assert {2020, 2023} <= set(calendar.loaded_years)
        assert calendar.year_sources[2020]
        assert calendar.year_sources[2023]
        assert not calendar.is_business_day(date(2020, 4, 10))
        assert not calendar.is_business_day(date(2023, 4, 7))

    assert len(government.year_sources[2020]) == 2
    assert len(government.year_sources[2023]) == 2


def test_session_close_reads_nyse_early_closes() -> None:
    from datetime import time

    calendar = MarketCalendar.load(Market.US_EQUITIES)
    assert calendar.session_close(date(2026, 11, 27)) == time(13, 0)
    assert calendar.session_close(date(2026, 12, 24)) == time(13, 0)
    assert calendar.session_close(date(2027, 11, 26)) == time(13, 0)
    assert calendar.session_close(date(2026, 11, 25)) == time(16, 0)


def test_session_close_fails_closed_without_data_or_on_a_holiday() -> None:
    import pytest

    from atreides.deadlines.calendar import CalendarIndeterminateError

    calendar = MarketCalendar.load(Market.US_EQUITIES)
    with pytest.raises(CalendarIndeterminateError):
        calendar.session_close(date(2023, 11, 24))
    with pytest.raises(ValueError, match="closed"):
        calendar.session_close(date(2026, 11, 26))
    with pytest.raises(CalendarIndeterminateError):
        MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES).session_close(date(2026, 11, 27))


def test_nyse_2028_calendar_from_the_exchange_announcement() -> None:
    """F3: 2028 as NYSE Group announced it on 23 Dec 2025.

    1 Jan 2028 is a Saturday, so no New Year's Day holiday is observed and 3 Jan is open.
    """

    from datetime import time

    calendar = MarketCalendar.load(Market.US_EQUITIES)
    holidays_2028 = [
        date(2028, 1, 17),
        date(2028, 2, 21),
        date(2028, 4, 14),
        date(2028, 5, 29),
        date(2028, 6, 19),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
    ]
    for day in holidays_2028:
        assert not calendar.is_business_day(day), day
    assert calendar.is_business_day(date(2028, 1, 3))
    assert calendar.is_business_day(date(2028, 12, 22))
    assert calendar.session_close(date(2028, 7, 3)) == time(13, 0)
    assert calendar.session_close(date(2028, 11, 24)) == time(13, 0)
    assert calendar.session_close(date(2028, 12, 22)) == time(16, 0)
    assert calendar.add_business_days(date(2027, 12, 31), 1) == date(2028, 1, 3)
