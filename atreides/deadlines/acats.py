"""FINRA Rule 11870 ACATS validation and completion deadline advisory."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from cannae_kernel.disposition import Disposition
from pydantic import AwareDatetime, Field

from atreides.deadlines.calendar import DeadlineCalendar
from atreides.deadlines.model import DeadlineAssessment, DeadlineRuleTable, RuleUnit, _Frozen
from atreides.deadlines.rules import load_rule_table

VALIDATION_RULE_ID = "finra_11870.validation"
COMPLETION_RULE_ID = "finra_11870.completion"


class AcatsTransfer(_Frozen):
    transfer_id: str = Field(min_length=1)
    instruction_at: AwareDatetime
    validation_at: AwareDatetime | None = None


class AcatsAssessment(DeadlineAssessment):
    transfer_id: str
    validation_due: date | None
    completion_due: date | None
    table_version: str
    rule_citations: tuple[str, ...]
    source_sha256: str | None


def _result(
    transfer: AcatsTransfer,
    table: DeadlineRuleTable,
    evaluated_at: datetime,
    **values: Any,
) -> AcatsAssessment:
    return AcatsAssessment(
        disposition=values.pop("disposition"),
        due_at=None,
        missing_rules=values.pop("missing_rules", ()),
        missing_inputs=values.pop("missing_inputs", ()),
        breaches=values.pop("breaches", ()),
        evaluated_at=evaluated_at,
        transfer_id=transfer.transfer_id,
        validation_due=values.pop("validation_due", None),
        completion_due=values.pop("completion_due", None),
        table_version=table.table_version,
        rule_citations=values.pop("rule_citations", ()),
        source_sha256=values.pop("source_sha256", None),
        **values,
    )


def _days(value: Decimal, rule_id: str) -> int:
    integral = value.to_integral_value()
    if value != integral:
        raise ValueError(f"{rule_id}: deadline day count is not an integer")
    return int(integral)


def assess_acats(
    transfer: AcatsTransfer,
    *,
    evaluated_at: datetime,
    calendar: DeadlineCalendar | None,
    table: DeadlineRuleTable | None = None,
) -> AcatsAssessment:
    """Compute validation and completion dates from the current loaded table."""
    loaded = table or load_rule_table(as_of=evaluated_at.date())
    finra_source = next(
        (source for source in loaded.sources if source.source_id == "finra-11870"), None
    )
    if (
        finra_source is None
        or finra_source.effective_date is None
        or evaluated_at.date() < finra_source.effective_date
        or finra_source.expires_at is None
        or evaluated_at.date() > finra_source.expires_at
    ):
        return _result(
            transfer,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=("finra_11870.current_acats_version",),
        )
    validation_rule = loaded.get(VALIDATION_RULE_ID)
    completion_rule = loaded.get(COMPLETION_RULE_ID)
    missing = tuple(
        rule_id
        for rule_id, rule in (
            (VALIDATION_RULE_ID, validation_rule),
            (COMPLETION_RULE_ID, completion_rule),
        )
        if rule is None
    )
    if missing:
        return _result(
            transfer,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=missing,
        )
    if calendar is None:
        return _result(
            transfer,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("business_calendar",),
        )
    if validation_rule is None or completion_rule is None:
        raise AssertionError("rule presence checked above")
    if validation_rule.unit is not RuleUnit.BUSINESS_DAYS:
        return _result(
            transfer,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"{VALIDATION_RULE_ID}:unsupported_unit",),
        )
    if completion_rule.unit is not RuleUnit.BUSINESS_DAYS:
        return _result(
            transfer,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"{COMPLETION_RULE_ID}:unsupported_unit",),
        )

    validation_due = calendar.add_business_days(
        transfer.instruction_at.date(), _days(validation_rule.value, VALIDATION_RULE_ID)
    )
    completion_due = (
        calendar.add_business_days(
            transfer.validation_at.date(), _days(completion_rule.value, COMPLETION_RULE_ID)
        )
        if transfer.validation_at is not None
        else None
    )
    breaches: list[str] = []
    if transfer.validation_at is None and evaluated_at.date() > validation_due:
        breaches.append("finra_11870.validation_overdue")
    if transfer.validation_at is not None and transfer.validation_at.date() > validation_due:
        breaches.append("finra_11870.validation_late")
    if completion_due is not None and evaluated_at.date() > completion_due:
        breaches.append("finra_11870.completion_overdue")
    return _result(
        transfer,
        loaded,
        evaluated_at,
        disposition=Disposition.HOLD if breaches else Disposition.PASS,
        validation_due=validation_due,
        completion_due=completion_due,
        breaches=tuple(breaches),
        rule_citations=(validation_rule.citation, completion_rule.citation),
        source_sha256=validation_rule.source_sha256,
    )
