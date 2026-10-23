"""Dated, source-labelled business-day calendars for deadline engines."""

from __future__ import annotations

from datetime import date, timedelta
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

    @model_validator(mode="after")
    def _dates_match_years(self) -> Self:
        for year, dates in self.holidays.items():
            if any(day.year != year for day in dates):
                raise ValueError(f"holiday is outside declared year {year}")
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
