"""Dated, source-labelled business-day calendars for deadline engines."""

from __future__ import annotations

from datetime import date, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeadlineCalendar(Protocol):
    """Calendar decisions are inputs; Atreides embeds no holiday list."""

    def add_business_days(self, start: date, days: int) -> date: ...

    def add_settlement_days(self, start: date, days: int) -> date: ...


class Market(StrEnum):
    US_GOVERNMENT_SECURITIES = "US_GOVERNMENT_SECURITIES"
    US_EQUITIES = "US_EQUITIES"


class CalendarIndeterminateError(ValueError):
    """The calendar cannot decide because the requested year is not loaded."""


class _CalendarSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    license_class: str = Field(min_length=1)


class _CalendarFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    market: Market
    source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    confidence: str = Field(min_length=1)
    holidays: dict[int, tuple[date, ...]]
    year_sources: dict[int, tuple[_CalendarSource, ...]] = Field(default_factory=dict)
    regular_close: time | None = None
    early_close: time | None = None
    early_closes: dict[int, tuple[date, ...]] = Field(default_factory=dict)
    session_sources: tuple[_CalendarSource, ...] = ()

    @model_validator(mode="after")
    def _dates_match_years(self) -> Self:
        for year, dates in self.holidays.items():
            if any(day.year != year for day in dates):
                raise ValueError(f"holiday is outside declared year {year}")
        for year, dates in self.early_closes.items():
            if year not in self.holidays:
                raise ValueError(f"early closes name year {year} without holiday data")
            if any(day.year != year for day in dates):
                raise ValueError(f"early close is outside declared year {year}")
            if any(day in self.holidays[year] for day in dates):
                raise ValueError(f"early close in {year} is also a holiday")
        if self.early_closes and (self.regular_close is None or self.early_close is None):
            raise ValueError("early closes need both a regular and an early close time")
        if self.early_closes and not self.session_sources:
            raise ValueError("session close data needs a source")
        if any(year not in self.holidays for year in self.year_sources):
            raise ValueError("calendar year source names a year without holiday data")
        return self


class MarketCalendar:
    """Business-day decisions from committed, dated market calendar data."""

    def __init__(self, document: _CalendarFile) -> None:
        self.market = document.market
        self.source = document.source
        self.source_url = document.source_url
        self.confidence = document.confidence
        self.year_sources = document.year_sources
        self._holidays = {year: frozenset(days) for year, days in document.holidays.items()}
        self._regular_close = document.regular_close
        self._early_close = document.early_close
        self._early_closes = {year: frozenset(days) for year, days in document.early_closes.items()}
        self.session_sources = document.session_sources

    @classmethod
    def load(cls, market: Market) -> MarketCalendar:
        path = Path(__file__).with_name("calendars") / f"{market.value.lower()}.json"
        return cls(_CalendarFile.model_validate_json(path.read_bytes()))

    @property
    def loaded_years(self) -> tuple[int, ...]:
        return tuple(sorted(self._holidays))

    def is_business_day(self, value: date) -> bool:
        if value.year not in self._holidays:
            raise CalendarIndeterminateError(
                f"{self.market.value} calendar has no loaded data for {value.year}"
            )
        return value.weekday() < 5 and value not in self._holidays[value.year]

    def session_close(self, value: date) -> time:
        """Local close time of the regular session on a business day.

        Raises ``CalendarIndeterminateError`` when the year has no session-close data, and
        ``ValueError`` when the market is closed that day. A missing early-close list is never
        read as "no early closes".
        """

        if not self.is_business_day(value):
            raise ValueError(f"{self.market.value} is closed on {value.isoformat()}")
        if value.year not in self._early_closes or self._regular_close is None:
            raise CalendarIndeterminateError(
                f"{self.market.value} calendar has no session-close data for {value.year}"
            )
        if value in self._early_closes[value.year]:
            if self._early_close is None:
                raise CalendarIndeterminateError(f"{self.market.value} has no early close time")
            return self._early_close
        return self._regular_close

    def add_business_days(self, start: date, days: int) -> date:
        if days < 0:
            raise ValueError("business-day count cannot be negative")
        cursor = start
        remaining = days
        while remaining:
            cursor += timedelta(days=1)
            if self.is_business_day(cursor):
                remaining -= 1
        return cursor

    def add_settlement_days(self, start: date, days: int) -> date:
        return self.add_business_days(start, days)

    def business_days_after(self, start: date, close: date) -> int:
        if close <= start:
            return 0
        cursor = start
        total = 0
        while cursor < close:
            cursor += timedelta(days=1)
            if self.is_business_day(cursor):
                total += 1
        return total
