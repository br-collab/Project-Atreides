"""CONV-1B regression: I9 must catch an engine that lies, not only a rewritten pipeline output.

The built-in CONV-1B mutations overwrite the conversion disposition after the
engines run. These tests instead patch the real engines (reserve, possession or
control, net capital) to return a wrong disposition, so a defect inside an engine
is caught the same way an examiner would expose it. I9 compares the hold required
by declared evidence and simulated facts with the hold the engines produced
(simulator/conversion.py), so each lie must turn I9 false on exactly the days it
changes, and the run must report a failure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition

from simulator import conversion, estate

I9 = "I9_CONVERSION_GATED"


def _lie(original: Callable[..., Any], disposition: Disposition) -> Callable[..., Any]:
    def lying(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        update: dict[str, object] = {"disposition": disposition}
        if disposition is Disposition.PASS and "breaches" in type(result).model_fields:
            update["breaches"] = ()
        return result.model_copy(update=update)

    return lying


@pytest.fixture
def patch_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str, Disposition], None]]:
    def apply(engine: str, disposition: Disposition) -> None:
        if engine == "reserve":
            lying = _lie(estate.compute_reserve, disposition)
            monkeypatch.setattr(conversion, "compute_reserve", lying)
            monkeypatch.setattr(estate, "compute_reserve", lying)
        elif engine == "control":
            lying = _lie(conversion.check_possession_or_control, disposition)
            monkeypatch.setattr(conversion, "check_possession_or_control", lying)
        else:
            lying = _lie(conversion.compute_net_capital, disposition)
            monkeypatch.setattr(conversion, "compute_net_capital", lying)

    yield apply


def _carrying(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [close for close in run["closes"] if close["phase"] == "carrying"]


def test_unpatched_variants_keep_i9_true() -> None:
    for variant in conversion.VARIANTS:
        assert conversion.run_conversion_variant(variant)["all_invariants_pass"], variant


@pytest.mark.parametrize(
    ("engine", "disposition", "variant", "expected_reason"),
    [
        # A wrongful HOLD on days the clean run funds and controls in full.
        ("reserve", Disposition.HOLD, "clean", None),
        # A wrongful PASS while the first deposit is short.
        ("reserve", Disposition.PASS, "short-first-deposit", "reserve shortfall"),
        # A wrongful PASS while securities still sit at the prior clearing firm.
        ("control", Disposition.PASS, "late-transfer", "possession or control"),
        # A wrongful PASS when declared net worth is below the carrying minimum.
        ("net_capital", Disposition.PASS, "capital-short", "net capital"),
        # A wrongful HOLD of possession or control after every issue is at DTC.
        ("control", Disposition.HOLD, "clean", None),
    ],
)
def test_engine_lie_fails_i9_on_every_affected_day(
    patch_engine: Callable[[str, Disposition], None],
    engine: str,
    disposition: Disposition,
    variant: str,
    expected_reason: str | None,
) -> None:
    honest = _carrying(conversion.run_conversion_variant(variant))
    patch_engine(engine, disposition)
    run = conversion.run_conversion_variant(variant)
    lied = _carrying(run)
    assert run["all_invariants_pass"] is False

    if expected_reason is None:
        # Wrongful HOLD: every carrying day the honest run passes must now fail I9.
        affected = [
            i for i, close in enumerate(honest) if close["conversion_disposition"] == "PASS"
        ]
    else:
        # Wrongful PASS: every day the required hold names the hidden reason must fail I9.
        affected = [
            i
            for i, close in enumerate(honest)
            if expected_reason in close["required_conversion_reasons"]
        ]
        assert all(
            expected_reason in lied[i]["required_conversion_reasons"]
            and expected_reason not in lied[i]["conversion_reasons"]
            for i in affected
        )
    assert affected, "the variant must contain a day the lie changes"
    assert all(lied[i]["invariants"][I9] is False for i in affected)
