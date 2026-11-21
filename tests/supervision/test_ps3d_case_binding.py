"""PS-3D Phase A: an officer attestation applies only to the case it names.

The golden path and the firm run do not call these functions yet. SAR is a suspicious
activity report.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from atreides.supervision.aml import (
    AMLCase,
    AMLPolicy,
    EventKind,
    MonitoringEvent,
    extend_for_unidentified_suspect,
    monitor,
    record_human_decision,
    unidentified_suspect_basis,
)
from simulator.synthetic_attestation_fixture import sign_aml_officer_attestation

CONTROL_DECISION = "SAR decision case binding control"
CONTROL_EXTENSION = "extension case binding control"


def _case_for(customer: str) -> AMLCase:
    return monitor(
        customer_id=customer,
        books_events=(
            MonitoringEvent(
                f"E-DEP-{customer}",
                customer,
                EventKind.CASH_DEPOSIT,
                date(2026, 11, 1),
                Decimal("10000"),
            ),
        ),
        instruction_events=(
            MonitoringEvent(
                f"E-WD-{customer}",
                customer,
                EventKind.CASH_WITHDRAWAL,
                date(2026, 11, 2),
                Decimal("10000"),
            ),
        ),
        policy=AMLPolicy(),
    )[0]


def test_signed_no_sar_is_refused_on_a_second_case() -> None:
    first = _case_for("PLANTED")
    second = _case_for("OTHER")
    assert first.alert.detected_on == second.alert.detected_on
    assert first.case_id != second.case_id
    wire = sign_aml_officer_attestation(
        {
            "purpose": "SAR_DECISION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "outcome": "NO_SAR",
            "reason": "documented synthetic reason",
            "decided_on": "2026-11-05",
            "case_id": first.case_id,
            "alert_id": first.alert.alert_id,
        }
    )
    decided = record_human_decision(first, wire)
    assert decided.decision is not None
    assert decided.decision.outcome == "NO_SAR"
    try:
        record_human_decision(second, wire)
    except ValueError as exc:
        assert CONTROL_DECISION in str(exc)
    else:
        raise AssertionError(CONTROL_DECISION)


def test_signed_extension_is_refused_on_a_second_case_detected_the_same_day() -> None:
    first = _case_for("PLANTED")
    second = _case_for("OTHER")
    assert first.alert.detected_on == second.alert.detected_on
    decided = first.alert.detected_on + timedelta(days=10)
    basis = unidentified_suspect_basis(first.alert.detected_on)
    signed = sign_aml_officer_attestation(
        {
            "purpose": "UNIDENTIFIED_SUSPECT_EXTENSION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "decided_on": decided.isoformat(),
            "basis": basis,
            "case_id": first.case_id,
            "alert_id": first.alert.alert_id,
        }
    )
    extended = extend_for_unidentified_suspect(first, signed, decided, basis, policy=AMLPolicy())
    assert extended.extended_due_on == first.alert.detected_on + timedelta(days=60)
    try:
        extend_for_unidentified_suspect(second, signed, decided, basis, policy=AMLPolicy())
    except ValueError as exc:
        assert CONTROL_EXTENSION in str(exc)
    else:
        raise AssertionError(CONTROL_EXTENSION)
