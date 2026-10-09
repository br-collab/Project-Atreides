"""Exchange Act Rule 17a-13 security-count deadline advisory."""

from __future__ import annotations

import calendar as month_calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from cannae_kernel.disposition import Disposition

from atreides.deadlines.calendar import DeadlineCalendar
from atreides.deadlines.model import DeadlineAssessment, DeadlineRuleTable, RuleUnit, _Frozen
from atreides.deadlines.rules import load_rule_table

MINIMUM_RULE_ID = "rule_17a_13.minimum_spacing"
MAXIMUM_RULE_ID = "rule_17a_13.maximum_spacing"
RECORDING_RULE_ID = "rule_17a_13.difference_recording"


class SecurityCountInput(_Frozen):
    prior_count_dates: tuple[date, ...]
    count_date: date | None = None


class SecurityCountAssessment(DeadlineAssessment):
    prior_count_date: date | None
    count_date: date | None
    next_count_earliest: date | None
    next_count_latest: date | None
    difference_recording_due: date | None
    spacing_valid: bool | None
    table_version: str
    rule_citations: tuple[str, ...]
    source_sha256: str | None


def _result(
    count: SecurityCountInput,
    table: DeadlineRuleTable,
    evaluated_at: datetime,
    **values: Any,
) -> SecurityCountAssessment:
    return SecurityCountAssessment(
        disposition=values.pop("disposition"),
        due_at=None,
        missing_rules=values.pop("missing_rules", ()),
        missing_inputs=values.pop("missing_inputs", ()),
        breaches=values.pop("breaches", ()),
        evaluated_at=evaluated_at,
        prior_count_date=values.pop("prior_count_date", None),
        count_date=count.count_date,
        next_count_earliest=values.pop("next_count_earliest", None),
        next_count_latest=values.pop("next_count_latest", None),
        difference_recording_due=values.pop("difference_recording_due", None),
        spacing_valid=values.pop("spacing_valid", None),
        table_version=table.table_version,
        rule_citations=values.pop("rule_citations", ()),
        source_sha256=values.pop("source_sha256", None),
        **values,
    )


def _whole(value: Decimal, rule_id: str) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"{rule_id}: parameter is not an integer")
    return int(value)


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def assess_security_count(
    count: SecurityCountInput,
    *,
    evaluated_at: datetime,
    calendar: DeadlineCalendar | None,
    table: DeadlineRuleTable | None = None,
) -> SecurityCountAssessment:
    """Compute the next count window and unresolved-difference recording date."""
    loaded = table or load_rule_table(as_of=evaluated_at.date())
    rules = {
        rule_id: loaded.get(rule_id)
        for rule_id in (MINIMUM_RULE_ID, MAXIMUM_RULE_ID, RECORDING_RULE_ID)
    }
    missing = tuple(rule_id for rule_id, rule in rules.items() if rule is None)
    if missing:
        return _result(
            count,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=missing,
        )
    if not count.prior_count_dates:
        return _result(
            count,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("prior_count_date",),
        )
    if calendar is None:
        return _result(
            count,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("business_calendar",),
        )
    minimum = rules[MINIMUM_RULE_ID]
    maximum = rules[MAXIMUM_RULE_ID]
    recording = rules[RECORDING_RULE_ID]
    if minimum is None or maximum is None or recording is None:
        raise AssertionError("rule presence checked above")
    if minimum.unit is not RuleUnit.MONTHS or maximum.unit is not RuleUnit.MONTHS:
        return _result(
            count,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=("rule_17a_13.spacing_units",),
        )
    if recording.unit is not RuleUnit.BUSINESS_DAYS:
        return _result(
            count,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"{RECORDING_RULE_ID}:unsupported_unit",),
        )

    prior = max(count.prior_count_dates)
    earliest = _add_months(prior, _whole(minimum.value, MINIMUM_RULE_ID))
    latest = _add_months(prior, _whole(maximum.value, MAXIMUM_RULE_ID))
    recording_due = (
        calendar.add_business_days(count.count_date, _whole(recording.value, RECORDING_RULE_ID))
        if count.count_date is not None
        else None
    )
    spacing_valid = earliest <= count.count_date <= latest if count.count_date is not None else None
    breaches: list[str] = []
    if count.count_date is not None and count.count_date < earliest:
        breaches.append("rule_17a_13.count_too_soon")
    if count.count_date is not None and count.count_date > latest:
        breaches.append("rule_17a_13.count_too_late")
    if count.count_date is None and evaluated_at.date() > latest:
        breaches.append("rule_17a_13.count_overdue")
    return _result(
        count,
        loaded,
        evaluated_at,
        disposition=Disposition.HOLD if breaches else Disposition.PASS,
        breaches=tuple(breaches),
        prior_count_date=prior,
        next_count_earliest=earliest,
        next_count_latest=latest,
        difference_recording_due=recording_due,
        spacing_valid=spacing_valid,
        rule_citations=(minimum.citation, maximum.citation, recording.citation),
        source_sha256=minimum.source_sha256,
    )
