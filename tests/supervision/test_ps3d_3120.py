"""Rule 3120 reads the JUnit file the test runner wrote."""

from pathlib import Path
from xml.etree import ElementTree

from atreides.supervision.controls import (
    executed_names_from_junit,
    load_wsp_register,
    run_3120_testing,
)
from tests.supervision.junit_runner import execute_tests_to_junit

WSP_PATH = "tests/supervision/test_wsp_gates.py"
DESELECTED = "tests/supervision/test_wsp_gates.py::test_confirmation_gate"
CONTROL = "3120 JUnit executed-name control"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(junit_xml: Path, *, deselect: tuple[str, ...] = ()) -> None:
    execute_tests_to_junit(
        junit_xml,
        paths=(WSP_PATH,),
        deselect=deselect,
        cwd=_repo_root(),
    )


def test_3120_reads_executed_names_from_junit_xml(tmp_path: Path) -> None:
    junit_xml = tmp_path / "3120-sc01.xml"
    _run(junit_xml)
    report = run_3120_testing(junit_xml=junit_xml)
    executed = executed_names_from_junit(junit_xml)
    register_names = {str(row["test"]) for row in load_wsp_register()}
    assert executed == register_names, CONTROL
    assert report.exception_count == 0, CONTROL
    assert {item.test_name for item in report.tests if item.status == "PASS"} == executed, CONTROL

    root = ElementTree.parse(junit_xml).getroot()
    parents = {child: parent for parent in root.iter() for child in list(parent)}
    removed = False
    for case in list(root.iter("testcase")):
        if case.attrib.get("name") == "test_confirmation_gate":
            parents[case].remove(case)
            removed = True
    assert removed, CONTROL
    junit_xml.write_text(ElementTree.tostring(root, encoding="unicode"), encoding="utf-8")

    reread = run_3120_testing(junit_xml=junit_xml)
    missing = next(item for item in reread.tests if item.test_name == "test_confirmation_gate")
    assert reread.exception_count == 1, CONTROL
    assert missing.status == "EXCEPTION", CONTROL
    assert missing.remediation_owner == "SYNTHETIC_REGISTERED_PRINCIPAL_REPORTING", CONTROL


def test_3120_deselect_one_wsp_test_is_one_exception(tmp_path: Path) -> None:
    junit_xml = tmp_path / "3120-sc02.xml"
    _run(junit_xml, deselect=(DESELECTED,))
    report = run_3120_testing(junit_xml=junit_xml)
    assert "test_confirmation_gate" not in executed_names_from_junit(junit_xml), CONTROL
    exceptions = [item for item in report.tests if item.status == "EXCEPTION"]
    assert len(exceptions) == 1, CONTROL
    assert exceptions[0].test_name == "test_confirmation_gate", CONTROL
    assert exceptions[0].remediation_owner == "SYNTHETIC_REGISTERED_PRINCIPAL_REPORTING", CONTROL
    assert report.exception_count == 1, CONTROL
