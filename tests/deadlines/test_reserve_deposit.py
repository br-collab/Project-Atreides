"""DEADLINE-1 WP-5 acceptance tests for Rule 15c3-3(e)(3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest
from cannae_kernel.disposition import Disposition

from atreides.deadlines import (
    ReserveComputation,
    ReserveComputationBasis,
    assess_reserve_deposit,
    load_rule_table,
)

AS_OF = datetime(2026, 10, 9, 12, tzinfo=UTC)
BANKING_OPEN = time(8, tzinfo=timezone(timedelta(hours=-4)))


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


def _computation(basis: ReserveComputationBasis | str | None) -> ReserveComputation:
    return ReserveComputation(
        computation_id="SYNTHETIC-RESERVE-1",
        computed_at=datetime(2026, 10, 9, 21, tzinfo=UTC),
        basis=basis,
    )


@pytest.mark.parametrize(
    ("basis", "paragraph"),
    [
        (ReserveComputationBasis.WEEKLY, "17 CFR 240.15c3-3(e)(3)(i)(A)"),
        (ReserveComputationBasis.REQUIRED_DAILY, "17 CFR 240.15c3-3(e)(3)(i)(B)(1)"),
        (ReserveComputationBasis.QUALIFYING_MONTHLY, "17 CFR 240.15c3-3(e)(3)(i)(C)"),
        (ReserveComputationBasis.ADDITIONAL, "17 CFR 240.15c3-3(e)(3)(iv)"),
        (ReserveComputationBasis.VOLUNTARY_DAILY, "17 CFR 240.15c3-3(e)(3)(iv)-(v)"),
    ],
)
def test_each_computation_basis_preserves_its_paragraph_and_loaded_deadline(
    basis: ReserveComputationBasis, paragraph: str
) -> None:
    result = assess_reserve_deposit(
        _computation(basis),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(date(2026, 10, 12)),
        banking_open=BANKING_OPEN,
    )
    assert result.disposition is Disposition.PASS
    assert result.due_at == datetime(2026, 10, 14, 9, tzinfo=timezone(timedelta(hours=-4)))
    assert result.computation_basis == basis.value
    assert result.paragraph_reference == paragraph
    assert result.table_version == "deadline-rules/0.5-reserve-deposit"
    assert (
        result.source_sha256 == "c7d7067f656bb6032182c0d81530a78d6d80d59cc4a842be84d9e43d13609443"
    )
    assert result.enforcement_status == "ADVISORY_ONLY"
    assert result.claim_label == "EXPERIMENTAL"


def test_reserve_deadline_is_indeterminate_until_rules_are_loaded() -> None:
    table = load_rule_table(as_of=date(2026, 10, 9)).model_copy(update={"rules": ()})
    result = assess_reserve_deposit(
        _computation(ReserveComputationBasis.WEEKLY),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        banking_open=BANKING_OPEN,
        table=table,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == (
        "rule_15c3_3.reserve.weekly",
        "rule_15c3_3.reserve.opening_offset",
    )


def test_missing_or_unknown_basis_fails_closed() -> None:
    missing = assess_reserve_deposit(
        _computation(None),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        banking_open=BANKING_OPEN,
    )
    assert missing.disposition is Disposition.HOLD
    assert missing.missing_inputs == ("computation_basis",)

    unknown = assess_reserve_deposit(
        _computation("UNKNOWN"),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        banking_open=BANKING_OPEN,
    )
    assert unknown.disposition is Disposition.INDETERMINATE


def test_missing_banking_open_or_calendar_fails_closed() -> None:
    no_open = assess_reserve_deposit(
        _computation(ReserveComputationBasis.WEEKLY),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        banking_open=None,
    )
    assert no_open.disposition is Disposition.INDETERMINATE
    assert no_open.missing_rules == ("opening_of_banking_business",)

    naive_open = assess_reserve_deposit(
        _computation(ReserveComputationBasis.WEEKLY),
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        banking_open=time(8),
    )
    assert naive_open.disposition is Disposition.INDETERMINATE

    no_calendar = assess_reserve_deposit(
        _computation(ReserveComputationBasis.WEEKLY),
        evaluated_at=AS_OF,
        calendar=None,
        banking_open=BANKING_OPEN,
    )
    assert no_calendar.disposition is Disposition.HOLD
    assert no_calendar.missing_inputs == ("business_calendar",)


def test_overdue_reserve_deposit_is_hold() -> None:
    table = load_rule_table(as_of=date(2026, 10, 9))
    result = assess_reserve_deposit(
        _computation(ReserveComputationBasis.WEEKLY),
        evaluated_at=datetime(2026, 10, 14, 14, tzinfo=UTC),
        calendar=HolidayCalendar(date(2026, 10, 12)),
        banking_open=BANKING_OPEN,
        table=table,
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == ("rule_15c3_3.reserve_deposit_overdue",)
