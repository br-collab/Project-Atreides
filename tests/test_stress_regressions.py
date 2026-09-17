"""Stress-probe cases fixed in Wave 2, pinned one by one (W2A-6).

``tests/test_stress_probe.py`` pins the verdict *tally*. A tally can stay still
while one case is fixed and another quietly regresses, so each case fixed in
Wave 2 is also pinned here by id. The behaviour behind each has its own ordinary
regression test, named below.

=====  ===========  ==================================================================
Case   Finding      Behavioural regression test
=====  ===========  ==================================================================
H3.4   ATR-I-09     tests/rails/test_funding_window_cap.py
H6.2   ATR-I-06     tests/test_halt_propagation.py
H6.3   ATR-I-04     tests/rails/test_cato_f_record.py
H7.5   ATR-I-07     tests/cockpit/test_risk_control_breach.py
E2.5   ATR-I-05     tests/rails/test_probe_raw_string_finality.py
E6.2   ATR-I-03     tests/messaging/test_probe_submission_artifact.py
E7.5   ATR-I-04     tests/rails/test_cato_f_record.py
=====  ===========  ==================================================================

E6.4 (ATR-I-08, the quorum validator) is out of Wave 2 scope. It stays BROKE in
the probe and is a strict xfail in tests/contracts/operations/test_base.py.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import stress_probe  # noqa: E402

FIXED_IN_WAVE_2 = ("H3.4", "H6.2", "H6.3", "H7.5", "E2.5", "E6.2", "E7.5")
_BY_ID = {case.case_id: case for case in stress_probe.CASES}


@pytest.mark.parametrize("case_id", FIXED_IN_WAVE_2)
def test_fixed_case_holds(case_id: str) -> None:
    result = stress_probe.run_case(_BY_ID[case_id])
    assert result["verdict"] == stress_probe.HELD, result["observed"]


def test_the_remaining_broken_case_is_the_one_deferred_to_wave_6() -> None:
    broke = [
        c.case_id
        for c in stress_probe.CASES
        if stress_probe.run_case(c)["verdict"] in {stress_probe.BROKE, stress_probe.CRASHED}
    ]
    assert broke == ["E6.4"]


def test_every_named_regression_test_exists() -> None:
    rows = re.findall(r"^([HE]\d\.\d)\s+ATR-I-\d+\s+(\S+)$", __doc__ or "", flags=re.M)
    assert tuple(case for case, _ in rows) == FIXED_IN_WAVE_2
    paths = {path for _, path in rows}
    for path in paths:
        assert (REPO / path).is_file(), path
