"""Caller-supplied calendars for deadline engines."""

from __future__ import annotations

from datetime import date
from typing import Protocol


class DeadlineCalendar(Protocol):
    """Calendar decisions are inputs; Atreides embeds no holiday list."""

    def add_business_days(self, start: date, days: int) -> date: ...

    def add_settlement_days(self, start: date, days: int) -> date: ...
