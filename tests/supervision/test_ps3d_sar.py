"""PS-3D Part 5, Phase A: a SAR decision is a verified officer attestation.

The golden path and the firm run do not call these functions yet. That wiring is Phase B.
SAR is a suspicious activity report.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from atreides.supervision.aml import (
    AMLCase,
    AMLPolicy,
    EventKind,
    extend_for_unidentified_suspect,
    monitor,
    record_human_decision,
    sign_aml_officer_attestation,
    unidentified_suspect_basis,
)
from tests.supervision.test_ps3_supervision import event

CONTROL_DECISION = "SAR decision attestation control"
CONTROL_EXTENSION = "unidentified suspect extension control"
CONTROL_DAY_30 = "unidentified suspect day 30 control"


def _case() -> AMLCase:
    return monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )[0]


def test_unsigned_sar_decision_is_refused() -> None:
    unsigned = (
        b'{"decided_on":"2026-11-05","officer":"HUMAN_AML_OFFICER:Alex",'
        b'"outcome":"NO_SAR","purpose":"SAR_DECISION","reason":"unsigned"}'
    )
    try:
        record_human_decision(_case(), unsigned)
    except ValueError as exc:
        assert CONTROL_DECISION in str(exc)
    else:
        raise AssertionError(CONTROL_DECISION)


def test_unidentified_suspect_extension_refused_without_facts() -> None:
    case = _case()
    detected = case.alert.detected_on
    basis = unidentified_suspect_basis(detected)
    within = detected + timedelta(days=10)
    signed = sign_aml_officer_attestation(
        {
            "purpose": "UNIDENTIFIED_SUSPECT_EXTENSION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "decided_on": within.isoformat(),
            "basis": basis,
        }
    )
    with pytest.raises(ValueError, match=CONTROL_EXTENSION):
        extend_for_unidentified_suspect(case, b"", within, basis, policy=AMLPolicy())
    with pytest.raises(ValueError, match=CONTROL_EXTENSION):
        extend_for_unidentified_suspect(case, signed, within, "", policy=AMLPolicy())


def test_unidentified_suspect_extension_refused_after_day_30() -> None:
    case = _case()
    detected = case.alert.detected_on
    late = detected + timedelta(days=31)
    basis = unidentified_suspect_basis(detected)
    signed = sign_aml_officer_attestation(
        {
            "purpose": "UNIDENTIFIED_SUSPECT_EXTENSION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "decided_on": late.isoformat(),
            "basis": basis,
        }
    )
    try:
        extend_for_unidentified_suspect(case, signed, late, basis, policy=AMLPolicy())
    except ValueError as exc:
        assert CONTROL_DAY_30 in str(exc)
    else:
        raise AssertionError(CONTROL_DAY_30)


def test_signed_extension_records_the_attestation_on_the_case() -> None:
    case = _case()
    detected = case.alert.detected_on
    decided = detected + timedelta(days=10)
    basis = unidentified_suspect_basis(detected)
    signed = sign_aml_officer_attestation(
        {
            "purpose": "UNIDENTIFIED_SUSPECT_EXTENSION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "decided_on": decided.isoformat(),
            "basis": basis,
        }
    )
    extended = extend_for_unidentified_suspect(case, signed, decided, basis, policy=AMLPolicy())
    assert extended.extension_officer == "HUMAN_AML_OFFICER:Alex"
    assert extended.extension_attestation == signed
    assert extended.extension_decided_on == decided
    assert extended.extension_basis == basis
    assert extended.extended_due_on == detected + timedelta(days=60)
