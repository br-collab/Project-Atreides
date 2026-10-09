"""Regulation SHO Rule 204 deadline advisory."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from cannae_kernel.disposition import Disposition
from pydantic import Field

from atreides.deadlines.calendar import DeadlineCalendar
from atreides.deadlines.model import DeadlineAssessment, DeadlineRule, DeadlineRuleTable, _Frozen
from atreides.deadlines.rules import load_rule_table


class Rule204Origin(StrEnum):
    SHORT_OR_GENERAL = "SHORT_OR_GENERAL"
    LONG = "LONG"
    MARKET_MAKING = "MARKET_MAKING"
    DEEMED_OWNED = "DEEMED_OWNED"


RULE_IDS: dict[Rule204Origin, str] = {
    Rule204Origin.SHORT_OR_GENERAL: "rule_204.short_or_general",
    Rule204Origin.LONG: "rule_204.long",
    Rule204Origin.MARKET_MAKING: "rule_204.market_making",
    Rule204Origin.DEEMED_OWNED: "rule_204.deemed_owned",
}


class Rule204Fail(_Frozen):
    security: str = Field(min_length=1)
    trade_date: date
    settlement_date: date
    fail_quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    origin_class: Rule204Origin | str | None


class Rule204Assessment(DeadlineAssessment):
    security: str
    fail_quantity: Decimal
    origin_class: str | None
    table_version: str
    rule_id: str | None
    rule_citation: str | None
    source_sha256: str | None
    preborrow_condition_applies: bool


def _result(
    fail: Rule204Fail,
    table: DeadlineRuleTable,
    evaluated_at: datetime,
    **values: Any,
) -> Rule204Assessment:
    return Rule204Assessment(
        disposition=values.pop("disposition"),
        due_at=values.pop("due_at", None),
        missing_rules=values.pop("missing_rules", ()),
        missing_inputs=values.pop("missing_inputs", ()),
        breaches=values.pop("breaches", ()),
        evaluated_at=evaluated_at,
        security=fail.security,
        fail_quantity=fail.fail_quantity,
        origin_class=(
            fail.origin_class.value
            if isinstance(fail.origin_class, Rule204Origin)
            else fail.origin_class
        ),
        table_version=table.table_version,
        rule_id=values.pop("rule_id", None),
        rule_citation=values.pop("rule_citation", None),
        source_sha256=values.pop("source_sha256", None),
        preborrow_condition_applies=values.pop("preborrow_condition_applies", False),
        **values,
    )


def _whole_days(rule: DeadlineRule) -> int:
    if rule.value != rule.value.to_integral_value():
        raise ValueError(f"{rule.rule_id}: deadline day count is not an integer")
    return int(rule.value)


def assess_rule_204(
    fail: Rule204Fail,
    *,
    evaluated_at: datetime,
    calendar: DeadlineCalendar | None,
    regular_trading_open: time | None,
    table: DeadlineRuleTable | None = None,
) -> Rule204Assessment:
    """Compute the advisory close-out due time from loaded rule data."""
    loaded = table or load_rule_table()
    if fail.origin_class is None:
        return _result(
            fail,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("origin_class",),
        )
    try:
        origin = Rule204Origin(fail.origin_class)
    except ValueError:
        return _result(
            fail,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"origin_class:{fail.origin_class}",),
        )

    rule_id = RULE_IDS[origin]
    rule = loaded.get(rule_id)
    if rule is None:
        return _result(
            fail,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(rule_id,),
            rule_id=rule_id,
        )
    provenance = {
        "rule_id": rule.rule_id,
        "rule_citation": rule.citation,
        "source_sha256": rule.source_sha256,
    }
    if rule.requires_caller_opening_time and (
        regular_trading_open is None or regular_trading_open.tzinfo is None
    ):
        return _result(
            fail,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=("regular_trading_hours",),
            **provenance,
        )

    days = _whole_days(rule)
    if rule.unit.value == "SETTLEMENT_DAYS":
        if calendar is None:
            return _result(
                fail,
                loaded,
                evaluated_at,
                disposition=Disposition.HOLD,
                missing_inputs=("settlement_calendar",),
                **provenance,
            )
        due_date = calendar.add_settlement_days(fail.settlement_date, days)
    elif rule.unit.value == "CALENDAR_DAYS":
        due_date = fail.trade_date + timedelta(days=days)
    else:
        return _result(
            fail,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"{rule_id}:unsupported_unit",),
            **provenance,
        )

    if regular_trading_open is None:
        raise AssertionError("opening time presence checked above")
    due_at = datetime.combine(due_date, regular_trading_open)
    overdue = evaluated_at > due_at
    return _result(
        fail,
        loaded,
        evaluated_at,
        disposition=Disposition.HOLD if overdue else Disposition.PASS,
        due_at=due_at,
        breaches=("rule_204.close_out_overdue",) if overdue else (),
        preborrow_condition_applies=overdue,
        **provenance,
    )
