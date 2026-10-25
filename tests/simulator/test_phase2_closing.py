"""PHASE-2 closing attacks and publication checks."""

from typing import Any

import pytest
from cannae_kernel.disposition import Disposition

from simulator import firm
from simulator.firm import load_firm_profile, run_firm
from simulator.phase2 import publish_phase2
from simulator.runner import load_calibration_pack


def _one_day() -> firm.FirmRun:
    return run_firm(
        load_firm_profile(load_calibration_pack("firm-synthetic/1"), "small"),
        days=1,
        verify_replay=False,
    )


@pytest.mark.parametrize("engine", ["pab", "net_capital", "possession_or_control"])
def test_each_protection_engine_lie_turns_i6_false(
    monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    if engine == "pab":
        original = firm._post_reserve_deposits

        def lie(*args: Any, **kwargs: Any) -> Any:
            reserve, pab, deposits = original(*args, **kwargs)
            return (
                reserve,
                pab.model_copy(update={"disposition": Disposition.INDETERMINATE}),
                deposits,
            )

        monkeypatch.setattr(firm, "_post_reserve_deposits", lie)
    elif engine == "net_capital":
        original_capital = firm.compute_net_capital

        def lie_capital(*args: Any, **kwargs: Any) -> Any:
            return original_capital(*args, **kwargs).model_copy(
                update={"disposition": Disposition.INDETERMINATE}
            )

        monkeypatch.setattr(firm, "compute_net_capital", lie_capital)
    else:
        original_control = firm.check_possession_or_control

        def lie_control(*args: Any, **kwargs: Any) -> Any:
            return original_control(*args, **kwargs).model_copy(
                update={"disposition": Disposition.INDETERMINATE}
            )

        monkeypatch.setattr(firm, "check_possession_or_control", lie_control)
    assert not _one_day().days[0].invariants["I6_DEFAULT_AND_STALE_HOLD"]


def test_phase2_publication_keeps_not_claimed_and_named_reasons(tmp_path) -> None:  # type: ignore[no-untyped-def]
    publish_phase2(tmp_path)
    text = (tmp_path / "SUMMARY.md").read_text()
    assert "Not claimed" in text
    assert "missing declared NSCC membership evidence" in text
    assert (tmp_path / "run-summary.json").is_file()
