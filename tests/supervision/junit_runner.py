"""Run the written supervisory procedure tests and keep the JUnit file.

The package does not start a process. This runner lives with the tests so the
supervisory package stays free of a transport import.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def execute_tests_to_junit(
    junit_xml: Path,
    *,
    paths: tuple[str, ...],
    deselect: tuple[str, ...] = (),
    cwd: Path | None = None,
) -> None:
    """Run pytest and keep the JUnit file it writes.

    Deselected tests are absent from that file. The caller does not supply the
    executed-name set.
    """

    if not paths:
        raise ValueError("WSP_JUNIT_PATHS_REQUIRED")
    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    if junit_xml.exists():
        junit_xml.unlink()
    command = [
        sys.executable,
        "-m",
        "pytest",
        *paths,
        "-o",
        "addopts=",
        "-q",
        "--tb=line",
        "--noconftest",
        f"--junitxml={junit_xml}",
        *(f"--deselect={item}" for item in deselect),
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if not junit_xml.is_file():
        detail = (completed.stderr or completed.stdout)[-400:]
        raise RuntimeError(f"WSP_JUNIT_NOT_WRITTEN: {detail}")
    if completed.returncode not in {0, 1}:
        detail = (completed.stderr or completed.stdout)[-400:]
        raise RuntimeError(f"WSP_JUNIT_RUNNER_FAILED: {completed.returncode} {detail}")
