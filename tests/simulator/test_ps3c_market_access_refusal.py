"""PS-3C Part 5: a real market-access refusal is recorded and does not stop close."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = "firm market-access refusal recording control"


def test_over_limit_order_is_refused_and_five_day_firm_run_closes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from simulator.calibration import load_calibration_pack\n"
            "from simulator.firm import load_firm_profile, run_firm\n"
            "run = run_firm(load_firm_profile(load_calibration_pack('firm-synthetic/6'),"
            " 'small'), days=5, mutation='MARKET_ACCESS_OVER_LIMIT', verify_replay=False)\n"
            "print('refusals', [len(day.refused_orders) for day in run.days])\n"
            "print('reconciliations', [[(row.status.value, row.break_count) for row in"
            " day.reconciliation_calendar] for day in run.days])\n"
            "print('control_breaks', [len(day.control_breaks) for day in run.days])\n",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    assert result.returncode == 0, (CONTROL, result.stderr[-4000:])
    assert "refusals [1, 0, 0, 0, 0]" in result.stdout, (CONTROL, result.stdout)
    assert "control_breaks [0, 0, 0, 0, 0]" in result.stdout, (CONTROL, result.stdout)
    assert result.stdout.count("('RAN', 0)") == 30, (CONTROL, result.stdout)

