"""Controls and negative controls for the SIM-1 governance scenarios."""

from cannae_kernel.governance import ActionClass, AutonomyLevel

from simulator.governance_scenarios import (
    run_governance_scenarios,
    run_hosting_provider_loss,
    run_unauthorized_core_write,
    run_vendor_model_regression,
)


def test_g1_records_versions_and_replays() -> None:
    result = run_vendor_model_regression()
    assert [row["stage"] for row in result["records"]] == [
        "detection", "quarantine", "rollback"
    ]
    assert [row["model_version"] for row in result["records"]] == [
        "2.0.0", "2.0.0", "1.4.2"
    ]
    assert result["replay_identical"] is True


def test_g2_records_human_exit_and_required_label() -> None:
    result = run_hosting_provider_loss()
    assert result["label"] == "simulated, not a tested exit plan"
    assert result["records"][1]["result"] == "HUMAN_APPROVED"
    assert result["replay_identical"] is True


def test_g3_uses_named_refusal_and_write_action_class() -> None:
    result = run_unauthorized_core_write()
    assert result["named_refusal"] == "HUMAN_APPROVER_REQUIRED"
    assert {row["action_class"] for row in result["records"]} == {
        ActionClass.WRITE_CORE_RECORD.value
    }
    assert result["replay_identical"] is True


def test_all_agent_records_name_autonomy_and_action_class() -> None:
    result = run_governance_scenarios()
    rows = [
        row
        for scenario in result["controlled"].values()
        for row in scenario["records"]
    ]
    assert all(row["autonomy_level"] == AutonomyLevel.DECISION_SUPPORT.value for row in rows)
    assert all(row["action_class"] for row in rows)


def test_g1_negative_control_asserts_missed_drift() -> None:
    result = run_vendor_model_regression(control_enabled=False)
    assert result == {"scenario": "G1", "control_enabled": False,
                      "failed_as_expected": True, "failure": "drift went undetected"}


def test_g2_negative_control_asserts_missing_exit() -> None:
    result = run_hosting_provider_loss(control_enabled=False)
    assert result["failed_as_expected"] is True
    assert result["failure"] == "no exit was executed"


def test_g3_negative_control_asserts_accepted_write() -> None:
    result = run_unauthorized_core_write(control_enabled=False)
    assert result["failed_as_expected"] is True
    assert result["accepted_status"] == "APPROVED"
