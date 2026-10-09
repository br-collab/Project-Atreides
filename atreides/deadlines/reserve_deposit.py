"""Exchange Act Rule 15c3-3(e)(3) reserve-deposit deadline advisory."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from cannae_kernel.disposition import Disposition
from pydantic import AwareDatetime, Field

from atreides.deadlines.calendar import DeadlineCalendar
from atreides.deadlines.model import DeadlineAssessment, DeadlineRuleTable, RuleUnit, _Frozen
from atreides.deadlines.rules import load_rule_table


class ReserveComputationBasis(StrEnum):
    WEEKLY = "WEEKLY"
    REQUIRED_DAILY = "REQUIRED_DAILY"
    QUALIFYING_MONTHLY = "QUALIFYING_MONTHLY"
    ADDITIONAL = "ADDITIONAL"
    VOLUNTARY_DAILY = "VOLUNTARY_DAILY"


RULE_IDS: dict[ReserveComputationBasis, str] = {
    ReserveComputationBasis.WEEKLY: "rule_15c3_3.reserve.weekly",
    ReserveComputationBasis.REQUIRED_DAILY: "rule_15c3_3.reserve.required_daily",
    ReserveComputationBasis.QUALIFYING_MONTHLY: "rule_15c3_3.reserve.qualifying_monthly",
    ReserveComputationBasis.ADDITIONAL: "rule_15c3_3.reserve.additional",
    ReserveComputationBasis.VOLUNTARY_DAILY: "rule_15c3_3.reserve.voluntary_daily",
}
OFFSET_RULE_ID = "rule_15c3_3.reserve.opening_offset"


class ReserveComputation(_Frozen):
    computation_id: str = Field(min_length=1)
    computed_at: AwareDatetime
    basis: ReserveComputationBasis | str | None


class ReserveDepositAssessment(DeadlineAssessment):
    computation_id: str
    computation_basis: str | None
    paragraph_reference: str | None
    table_version: str
    rule_ids: tuple[str, ...]
    source_sha256: str | None


def _result(
    computation: ReserveComputation,
    table: DeadlineRuleTable,
    evaluated_at: datetime,
    **values: Any,
) -> ReserveDepositAssessment:
    return ReserveDepositAssessment(
        disposition=values.pop("disposition"),
        due_at=values.pop("due_at", None),
        missing_rules=values.pop("missing_rules", ()),
        missing_inputs=values.pop("missing_inputs", ()),
        breaches=values.pop("breaches", ()),
        evaluated_at=evaluated_at,
        computation_id=computation.computation_id,
        computation_basis=(
            computation.basis.value
            if isinstance(computation.basis, ReserveComputationBasis)
            else computation.basis
        ),
        paragraph_reference=values.pop("paragraph_reference", None),
        table_version=table.table_version,
        rule_ids=values.pop("rule_ids", ()),
        source_sha256=values.pop("source_sha256", None),
        **values,
    )


def _whole(value: Decimal, rule_id: str) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"{rule_id}: parameter is not an integer")
    return int(value)


def assess_reserve_deposit(
    computation: ReserveComputation,
    *,
    evaluated_at: datetime,
    calendar: DeadlineCalendar | None,
    banking_open: time | None,
    table: DeadlineRuleTable | None = None,
) -> ReserveDepositAssessment:
    """Compute the deposit due time without deciding basis eligibility."""
    loaded = table or load_rule_table(as_of=evaluated_at.date())
    if computation.basis is None:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("computation_basis",),
        )
    try:
        basis = ReserveComputationBasis(computation.basis)
    except ValueError:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=(f"computation_basis:{computation.basis}",),
        )
    basis_rule_id = RULE_IDS[basis]
    basis_rule = loaded.get(basis_rule_id)
    offset_rule = loaded.get(OFFSET_RULE_ID)
    missing = tuple(
        rule_id
        for rule_id, rule in ((basis_rule_id, basis_rule), (OFFSET_RULE_ID, offset_rule))
        if rule is None
    )
    if missing:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=missing,
            rule_ids=(basis_rule_id, OFFSET_RULE_ID),
        )
    if banking_open is None or banking_open.tzinfo is None:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=("opening_of_banking_business",),
            rule_ids=(basis_rule_id, OFFSET_RULE_ID),
        )
    if calendar is None:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.HOLD,
            missing_inputs=("business_calendar",),
            rule_ids=(basis_rule_id, OFFSET_RULE_ID),
        )
    if basis_rule is None or offset_rule is None:
        raise AssertionError("rule presence checked above")
    if basis_rule.unit is not RuleUnit.BUSINESS_DAYS or offset_rule.unit is not RuleUnit.CLOCK_TIME:
        return _result(
            computation,
            loaded,
            evaluated_at,
            disposition=Disposition.INDETERMINATE,
            missing_rules=("rule_15c3_3.reserve.units",),
            rule_ids=(basis_rule_id, OFFSET_RULE_ID),
        )

    due_date = calendar.add_business_days(
        computation.computed_at.date(), _whole(basis_rule.value, basis_rule_id)
    )
    due_at = datetime.combine(due_date, banking_open) + timedelta(
        hours=_whole(offset_rule.value, OFFSET_RULE_ID)
    )
    overdue = evaluated_at > due_at
    return _result(
        computation,
        loaded,
        evaluated_at,
        disposition=Disposition.HOLD if overdue else Disposition.PASS,
        due_at=due_at,
        breaches=("rule_15c3_3.reserve_deposit_overdue",) if overdue else (),
        paragraph_reference=basis_rule.citation,
        rule_ids=(basis_rule_id, OFFSET_RULE_ID),
        source_sha256=basis_rule.source_sha256,
    )
