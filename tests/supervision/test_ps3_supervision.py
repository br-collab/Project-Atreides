from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atreides.supervision.aml import (
    AMLPolicy,
    EventKind,
    MonitoringEvent,
    close_case,
    extend_for_unidentified_suspect,
    missed_clock_exception,
    monitor,
    record_human_decision,
    sign_aml_officer_attestation,
    unidentified_suspect_basis,
)
from atreides.supervision.controls import (
    TestOutcome,
    build_3130_draft,
    build_public_summary,
    junit_key,
    load_wsp_register,
    record_review,
    register_node_ids,
    run_3120_testing,
)
from simulator.golden_path import run_golden_path
from tests.supervision.junit_runner import execute_tests_to_junit

REPO_ROOT = Path(__file__).resolve().parents[2]


def _junit_from_runner(tmp_path: Path, name: str, *, deselect: tuple[str, ...] = ()) -> Path:
    junit_xml = tmp_path / name
    execute_tests_to_junit(
        junit_xml,
        paths=register_node_ids(),
        deselect=deselect,
        cwd=REPO_ROOT,
    )
    return junit_xml


def test_wsp_register_names_a_run_level_test_or_declares_the_gap() -> None:
    rows = load_wsp_register()
    assert len(rows) == 18
    assert {row["gate"] for row in rows} >= {"account opening", "KYC", "early warning"}
    for row in rows:
        node_id = row.get("test")
        if node_id is None:
            assert str(row.get("test_gap", "")).strip(), row["gate"]
            continue
        path, _ = str(node_id).split("::", 1)
        assert (REPO_ROOT / path).is_file(), node_id
        junit_key(str(node_id))


def test_wsp_rows_have_complete_supervisory_fields() -> None:
    required = {
        "gate",
        "rule",
        "control",
        "supervisor_role",
        "review_frequency",
        "evidence",
        "escalation_path",
    }
    assert all(
        required <= row.keys()
        and all(row[key] for key in required)
        and (row.get("test") or row.get("test_gap"))
        for row in load_wsp_register()
    )


def test_supervisory_review_refuses_self_review() -> None:
    with pytest.raises(ValueError, match="SELF_REVIEW_REFUSED"):
        record_review(
            decision_id="D1",
            decider="P1",
            reviewer="P1",
            outcome="AFFIRMED",
            reviewed_at=datetime(2026, 11, 18, tzinfo=UTC),
        )


def test_golden_path_produces_review_record_for_every_gate() -> None:
    records = tuple(
        record_review(
            decision_id=str(row["gate"]),
            decider=f"DECIDER:{row['gate']}",
            reviewer=str(row["supervisor_role"]),
            outcome="AFFIRMED",
            reviewed_at=datetime(2026, 11, 18, tzinfo=UTC),
        )
        for row in load_wsp_register()
    )
    assert len(records) == 18


def test_3120_run_executes_and_reports_every_wsp_row(tmp_path: Path) -> None:
    rows = load_wsp_register()
    report = run_3120_testing(junit_xml=_junit_from_runner(tmp_path, "3120-all.xml"))
    gaps = sum(not row.get("test") for row in rows)
    assert report.addressed_to == "SYNTHETIC_SENIOR_MANAGEMENT"
    assert [item.gate for item in report.tests] == [str(row["gate"]) for row in rows]
    assert report.exception_count == gaps
    assert all(
        item.outcome is TestOutcome.NO_RUN_LEVEL_TEST and item.remediation_owner
        for item in report.tests
        if item.status == "EXCEPTION"
    )


def test_3130_is_unsigned_draft_citing_3120_report(tmp_path: Path) -> None:
    empty = tmp_path / "3120-empty.xml"
    empty.write_text('<testsuite name="empty" tests="0"></testsuite>\n', encoding="utf-8")
    report = run_3120_testing(junit_xml=empty)
    draft = build_3130_draft(report=report, ceo="SYNTHETIC_CEO")
    assert draft.status == "UNSIGNED_DRAFT"
    assert draft.signed_by is None
    assert draft.testing_report_id == report.report_id


def event(
    kind: EventKind,
    day: int,
    *,
    related: str | None = None,
    owner: str | None = None,
    security: str | None = None,
) -> MonitoringEvent:
    return MonitoringEvent(
        f"E-{kind}-{day}",
        "PLANTED",
        kind,
        date(2026, 11, day),
        Decimal("10000"),
        related,
        owner,
        security,
    )


def test_aml_monitor_reads_books_and_instruction_log() -> None:
    cases = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )
    assert {case.alert.scenario for case in cases} == {"DEPOSIT_WITHDRAWAL_NO_TRADING"}


def test_aml_alert_opens_case_using_policy_thresholds() -> None:
    cases = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(movement_threshold=Decimal("20000")),
    )
    assert len(cases) == 1
    assert cases[0].case_id == f"CASE-{cases[0].alert.alert_id}"


def test_aml_deposit_withdrawal_scenario() -> None:
    planted = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )
    golden = monitor(
        customer_id="GOLDEN",
        books_events=(),
        instruction_events=(),
        policy=AMLPolicy(),
    )
    assert len(planted) == 1
    assert golden == ()


def test_aml_unrelated_accounts_scenario() -> None:
    planted = monitor(
        customer_id="PLANTED",
        books_events=(),
        instruction_events=(event(EventKind.TRANSFER, 2, related="OTHER", owner="OWNER"),),
        policy=AMLPolicy(),
    )
    assert planted[0].alert.scenario == "UNRELATED_ACCOUNT_TRANSFER"


def test_aml_fast_sale_scenario() -> None:
    planted = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.SECURITY_DEPOSIT, 1, security="S1"),),
        instruction_events=(event(EventKind.SECURITY_SALE, 3, security="S1"),),
        policy=AMLPolicy(),
    )
    assert planted[0].alert.scenario == "SECURITY_DEPOSIT_FAST_SALE"


def test_aml_case_close_requires_named_human_decision() -> None:
    case = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )[0]
    with pytest.raises(ValueError, match="HUMAN_DECISION_REQUIRED"):
        close_case(case)


def test_aml_missed_30_day_clock_is_supervisory_exception() -> None:
    case = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )[0]
    assert missed_clock_exception(case, as_of=date(2027, 1, 2))


def _planted_case():
    return monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )[0]


def _decision_wire(outcome: str, *, decided_on: date = date(2026, 11, 5)) -> bytes:
    return sign_aml_officer_attestation(
        {
            "purpose": "SAR_DECISION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "outcome": outcome,
            "reason": "documented synthetic reason",
            "decided_on": decided_on.isoformat(),
        }
    )


def test_a_sar_decision_does_not_stop_the_filing_clock() -> None:
    case = _planted_case()
    decided = record_human_decision(case, _decision_wire("SAR"))
    assert not missed_clock_exception(decided, as_of=case.due_on)
    assert missed_clock_exception(decided, as_of=case.due_on + timedelta(days=1))


def test_a_no_sar_decision_stops_the_clock() -> None:
    case = _planted_case()
    decided = record_human_decision(case, _decision_wire("NO_SAR"))
    assert not missed_clock_exception(decided, as_of=case.due_on + timedelta(days=10))


def test_unidentified_suspect_extension_caps_at_60_days_from_detection() -> None:
    case = _planted_case()
    decided = case.alert.detected_on + timedelta(days=10)
    basis = unidentified_suspect_basis(case.alert.detected_on)
    signed = sign_aml_officer_attestation(
        {
            "purpose": "UNIDENTIFIED_SUSPECT_EXTENSION",
            "officer": "HUMAN_AML_OFFICER:Alex",
            "decided_on": decided.isoformat(),
            "basis": basis,
        }
    )
    extended = extend_for_unidentified_suspect(case, signed, decided, basis, policy=AMLPolicy())
    assert extended.extended_due_on == case.alert.detected_on + timedelta(days=60)
    assert not missed_clock_exception(extended, as_of=case.due_on + timedelta(days=1))
    assert missed_clock_exception(extended, as_of=extended.extended_due_on + timedelta(days=1))
    with pytest.raises(ValueError, match="SAR_CLOCK_ALREADY_EXTENDED"):
        extend_for_unidentified_suspect(extended, signed, decided, basis, policy=AMLPolicy())


def test_one_token_trade_does_not_hide_deposit_withdrawal_movement() -> None:
    token = MonitoringEvent(
        "E-TRADE-3", "PLANTED", EventKind.TRADE, date(2026, 11, 3), Decimal("5")
    )
    cases = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1), token),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )
    assert [case.alert.scenario for case in cases] == ["DEPOSIT_WITHDRAWAL_NO_TRADING"]


def test_aml_file_decision_produces_unfiled_draft() -> None:
    case = monitor(
        customer_id="PLANTED",
        books_events=(event(EventKind.CASH_DEPOSIT, 1),),
        instruction_events=(event(EventKind.CASH_WITHDRAWAL, 2),),
        policy=AMLPolicy(),
    )[0]
    decided = record_human_decision(case, _decision_wire("SAR"))
    assert decided.draft_sar == {"status": "DRAFT_NOT_FILED", "case_id": case.case_id}


def test_sar_confidentiality_across_every_published_artifact() -> None:
    public = {"aml_alert_count": 3, "statement": {"positions": ["S1"]}, "pack": {"alerts": 3}}
    rendered = repr(public).lower()
    assert "sar" not in rendered
    assert "case-" not in rendered


def test_cop_and_pack_counts_equal_engine_results(tmp_path: Path) -> None:
    rows = load_wsp_register()
    report = run_3120_testing(junit_xml=_junit_from_runner(tmp_path, "3120-pub.xml"))
    summary = build_public_summary(
        wsp_rows=rows,
        testing_report=report,
        cat_summary={"record_count": 3, "exception_count": 1},
        aml_alert_count=3,
        surveillance_dispositions=("SURVEIL_CLEAR", "SURVEIL_DATA_INCOMPLETE"),
    )
    assert summary == {
        "wsp_count": len(rows),
        "3120_exception_count": report.exception_count,
        "cat_record_count": 3,
        "cat_exception_count": 1,
        "aml_alert_count": 3,
        "surveillance_dispositions": ("SURVEIL_CLEAR", "SURVEIL_DATA_INCOMPLETE"),
    }


def test_customer_artifacts_unchanged_and_free_of_ps3_data() -> None:
    result = run_golden_path()
    assert result.confirmation is not None
    assert result.statement is not None
    rendered = (result.confirmation.model_dump_json() + result.statement.model_dump_json()).lower()
    assert all(word not in rendered for word in ("supervis", "aml", "surveillance", "sar"))
    assert result.statement.closing_cash == Decimal("9000.00")
