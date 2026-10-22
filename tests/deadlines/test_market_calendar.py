from datetime import date

import pytest

from atreides.deadlines.calendar import CalendarIndeterminateError, Market, MarketCalendar


def test_government_calendar_crosses_year_end_without_failing_open() -> None:
    calendar = MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES)
    assert calendar.add_business_days(date(2026, 12, 31), 1) == date(2027, 1, 4)


def test_unloaded_year_is_indeterminate_with_reason() -> None:
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    with pytest.raises(CalendarIndeterminateError, match="no loaded data for 2028"):
        calendar.is_business_day(date(2028, 1, 3))
