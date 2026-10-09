"""DEADLINE-1 WP-3 acceptance tests for FINRA Rule 11870 ACATS clocks."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from cannae_kernel.disposition import Disposition

from atreides.deadlines import AcatsTransfer, assess_acats, load_rule_table

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


def test_validation_due_honors_a_holiday_between_instruction_and_due_date() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-1",
        instruction_at=datetime(2026, 10, 9, 15, tzinfo=UTC),
    )
    result = assess_acats(
        transfer,
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(date(2026, 10, 12)),
    )
    assert result.disposition is Disposition.PASS
    assert result.validation_due == date(2026, 10, 13)
    assert result.completion_due is None


def test_completion_due_honors_a_holiday_between_validation_and_due_date() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-2",
        instruction_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
        validation_at=datetime(2026, 10, 9, 15, tzinfo=UTC),
    )
    result = assess_acats(
        transfer,
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(date(2026, 10, 12)),
    )
    assert result.disposition is Disposition.PASS
    assert result.validation_due == date(2026, 10, 9)
    assert result.completion_due == date(2026, 10, 15)


def test_output_records_functional_table_version_and_provenance() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-3",
        instruction_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
    )
    result = assess_acats(transfer, evaluated_at=AS_OF, calendar=HolidayCalendar())
    assert result.table_version == "deadline-rules/0.3-acats"
    assert result.rule_citations == ("FINRA Rule 11870(b)(1)", "FINRA Rule 11870(e)")
    assert (
        result.source_sha256 == "ce5f85f26523ec8cba337851eae7c53b0f887d0621dc586fa0d38474a326b34b"
    )
    assert result.enforcement_status == "ADVISORY_ONLY"


def test_absent_or_expired_acats_version_is_indeterminate() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-4",
        instruction_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
    )
    table = load_rule_table(as_of=date(2026, 10, 9))
    expired = assess_acats(
        transfer,
        evaluated_at=datetime(2026, 10, 10, 12, tzinfo=UTC),
        calendar=HolidayCalendar(),
        table=table,
    )
    assert expired.disposition is Disposition.INDETERMINATE
    assert expired.missing_rules == ("finra_11870.current_acats_version",)

    without_source = table.model_copy(
        update={
            "sources": tuple(
                source for source in table.sources if source.source_id != "finra-11870"
            )
        }
    )
    absent = assess_acats(
        transfer,
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        table=without_source,
    )
    assert absent.disposition is Disposition.INDETERMINATE


def test_missing_calendar_is_hold() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-5",
        instruction_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
    )
    result = assess_acats(transfer, evaluated_at=AS_OF, calendar=None)
    assert result.disposition is Disposition.HOLD
    assert result.missing_inputs == ("business_calendar",)


def test_unloaded_acats_rule_is_indeterminate() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-UNLOADED",
        instruction_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
    )
    table = load_rule_table(as_of=date(2026, 10, 9))
    without_completion = table.model_copy(
        update={
            "rules": tuple(rule for rule in table.rules if rule.rule_id != "finra_11870.completion")
        }
    )
    result = assess_acats(
        transfer,
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        table=without_completion,
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.missing_rules == ("finra_11870.completion",)


def test_unvalidated_transfer_past_validation_date_is_hold() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-VALIDATION-OVERDUE",
        instruction_at=datetime(2026, 10, 1, 15, tzinfo=UTC),
    )
    table = load_rule_table(as_of=date(2026, 10, 9))
    result = assess_acats(
        transfer,
        evaluated_at=AS_OF,
        calendar=HolidayCalendar(),
        table=table,
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == ("finra_11870.validation_overdue",)


def test_late_validation_and_overdue_completion_are_hold() -> None:
    transfer = AcatsTransfer(
        transfer_id="SYNTHETIC-ACATS-6",
        instruction_at=datetime(2026, 10, 1, 15, tzinfo=UTC),
        validation_at=datetime(2026, 10, 5, 15, tzinfo=UTC),
    )
    table = load_rule_table(as_of=date(2026, 10, 9))
    result = assess_acats(
        transfer,
        evaluated_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
        calendar=HolidayCalendar(),
        table=table,
    )
    assert result.disposition is Disposition.HOLD
    assert result.breaches == (
        "finra_11870.validation_late",
        "finra_11870.completion_overdue",
    )
