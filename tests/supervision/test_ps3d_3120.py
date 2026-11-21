"""Rule 3120 grades each written supervisory procedure from the runner's JUnit outcomes.

A row passes only when the run-level test it names ran and passed. A failed or errored test,
an absent or skipped test, and a row with no run-level test yet are each one exception.
"""

from pathlib import Path

import pytest

from atreides.supervision.controls import (
    TestingReport,
    TestOutcome,
    evaluate_3120,
    junit_key,
    junit_outcomes,
    load_wsp_register,
    register_node_ids,
    run_3120_testing,
)
from atreides.supervision.controls import (
    wsp_register_version as load_wsp_register_version,
)
from tests.supervision.junit_runner import execute_tests_to_junit

KYC_NODE = (
    "tests/test_ps3c_kyc_storage.py::test_golden_path_refuses_a_chain_stored_for_another_kyc_record"
)
CONTROL = "3120 run-level outcome control"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, TestingReport]:
    junit_xml = tmp_path_factory.mktemp("3120") / "3120-full.xml"
    execute_tests_to_junit(junit_xml, paths=register_node_ids(), cwd=_repo_root())
    return junit_xml, run_3120_testing(junit_xml=junit_xml)


def _gap_gates() -> set[str]:
    return {str(row["gate"]) for row in load_wsp_register() if not row.get("test")}


def test_every_named_run_level_test_runs_and_only_honest_gaps_are_exceptions(
    full_run: tuple[Path, TestingReport],
) -> None:
    junit_xml, report = full_run
    outcomes = junit_outcomes(junit_xml)
    gaps = _gap_gates()
    assert gaps, "the register declares its open gaps"
    for item in report.tests:
        if item.gate in gaps:
            assert item.outcome is TestOutcome.NO_RUN_LEVEL_TEST, CONTROL
            assert item.status == "EXCEPTION" and item.remediation_owner, CONTROL
        else:
            assert item.outcome is TestOutcome.PASSED, (item.gate, CONTROL)
            classname, name = junit_key(item.test_name)
            assert any(
                case_class == classname and (case == name or case.startswith(f"{name}["))
                for case_class, case in outcomes
            ), CONTROL
    assert report.exception_count == len(gaps), CONTROL
    assert report.register_version == load_wsp_register_version(), CONTROL


def test_deselecting_one_run_level_test_is_exactly_one_not_run_exception(
    tmp_path: Path, full_run: tuple[Path, TestingReport]
) -> None:
    _, baseline = full_run
    junit_xml = tmp_path / "3120-deselect.xml"
    execute_tests_to_junit(
        junit_xml, paths=register_node_ids(), deselect=(KYC_NODE,), cwd=_repo_root()
    )
    report = run_3120_testing(junit_xml=junit_xml)
    changed = [
        (before.gate, after.outcome)
        for before, after in zip(baseline.tests, report.tests, strict=True)
        if before.outcome is not after.outcome
    ]
    assert changed == [("KYC", TestOutcome.NOT_RUN)], CONTROL
    assert report.exception_count == baseline.exception_count + 1, CONTROL


def _write(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


def _row(gate: str, node_id: str) -> dict[str, object]:
    return {"gate": gate, "supervisor_role": f"OWNER_{gate}", "test": node_id}


def test_a_wsp_test_that_ran_and_failed_is_a_failed_exception(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_wsp_planted.py",
        "import pytest\n\n"
        "def test_passes():\n    assert True\n\n"
        "def test_broken_control():\n    assert False, 'planted control break'\n\n"
        "@pytest.fixture\ndef boom():\n    raise RuntimeError('planted setup error')\n\n"
        "def test_errors(boom):\n    assert True\n\n"
        "@pytest.mark.skip(reason='planted skip')\ndef test_skipped():\n    assert True\n\n"
        "@pytest.mark.parametrize('case', ['good', 'bad'])\n"
        "def test_cases(case):\n    assert case == 'good'\n",
    )
    junit_xml = tmp_path / "3120-planted.xml"
    execute_tests_to_junit(junit_xml, paths=("test_wsp_planted.py",), cwd=tmp_path)
    register = (
        _row("passes", "test_wsp_planted.py::test_passes"),
        _row("broken", "test_wsp_planted.py::test_broken_control"),
        _row("errors", "test_wsp_planted.py::test_errors"),
        _row("skipped", "test_wsp_planted.py::test_skipped"),
        _row("one bad case", "test_wsp_planted.py::test_cases"),
        _row("good case", "test_wsp_planted.py::test_cases[good]"),
    )
    report = evaluate_3120(register, junit_xml)
    outcomes = {item.gate: item.outcome for item in report.tests}
    assert outcomes == {
        "passes": TestOutcome.PASSED,
        "broken": TestOutcome.FAILED,
        "errors": TestOutcome.FAILED,
        "skipped": TestOutcome.NOT_RUN,
        "one bad case": TestOutcome.FAILED,
        "good case": TestOutcome.PASSED,
    }, CONTROL
    assert report.exception_count == 4, CONTROL
    broken = next(item for item in report.tests if item.gate == "broken")
    assert broken.status == "EXCEPTION" and broken.remediation_owner == "OWNER_broken", CONTROL


def test_a_same_named_test_in_another_module_does_not_satisfy_the_row(tmp_path: Path) -> None:
    _write(tmp_path, "test_owner.py", "def test_same():\n    assert True\n")
    _write(tmp_path, "test_impostor.py", "def test_same():\n    assert True\n")
    junit_xml = tmp_path / "3120-impostor.xml"
    execute_tests_to_junit(junit_xml, paths=("test_impostor.py",), cwd=tmp_path)
    report = evaluate_3120((_row("owner", "test_owner.py::test_same"),), junit_xml)
    assert report.tests[0].outcome is TestOutcome.NOT_RUN, CONTROL


def test_junit_key_follows_pytest_classname() -> None:
    assert junit_key("tests/simulator/test_x.py::test_y[a-b]") == (
        "tests.simulator.test_x",
        "test_y[a-b]",
    )
    assert junit_key("tests/test_x.py::TestGroup::test_y") == ("tests.test_x.TestGroup", "test_y")
    with pytest.raises(ValueError, match="WSP_NODE_ID_INVALID"):
        junit_key("test_y")
