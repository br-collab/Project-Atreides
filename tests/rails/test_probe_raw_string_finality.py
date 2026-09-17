"""ATR-I-05 probe: a raw-string finality class must not fail open.

``project_funding`` checks ``finality_class is FinalityClass.CORRESPONDENT_DEPENDENT``.
An identity check never matches a plain string, so a finality class that
arrives as a string (from JSON, for example) skips the correspondent-dependent
branch and falls through to FUNDED. The Atreides inventory probe (15 Sep 2026,
commit 31b62f0) found the enum returns INDETERMINATE and the equivalent raw
string returns FUNDED.

Both spellings are probed: the enum's own value and the lower-case form named
in the Wave 0 tasking order. Either may be refused at the boundary (raising) or
coerced to a safe outcome; neither may return FUNDED.

test_enum_correspondent_dependent_is_indeterminate is an ordinary test that
pins the safe outcome the raw strings must not undercut.

Marked strict xfail: CI stays green while the defect stands, and the run fails
the day the Wave 2 fix (work package T1) lands without the marker being removed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from atreides.rails.finality import FinalityClass
from atreides.rails.funding_state import FundingDisposition, FundingInputs, project_funding

D = Decimal


def _inputs(finality_class: Any) -> FundingInputs:
    # Well funded on every other axis, so FUNDED is the answer unless the
    # correspondent-dependent branch is taken.
    return FundingInputs(
        opening_position=D("10000000"),
        obligation=D("1000000"),
        finality_class=finality_class,
        settlement_offset_seconds=3600,
        window_close_offset_seconds=14400,
        net_debit_cap=D("50000000"),
        clearing_fund_requirement=D("500000"),
        clearing_fund_posted=D("500000"),
    )


def test_enum_correspondent_dependent_is_indeterminate() -> None:
    projection = project_funding(_inputs(FinalityClass.CORRESPONDENT_DEPENDENT))
    assert projection.disposition is FundingDisposition.INDETERMINATE


@pytest.mark.xfail(strict=True, reason="ATR-I-05 — fixed in Wave 2")
@pytest.mark.parametrize("raw", ["correspondent_dependent", "CORRESPONDENT_DEPENDENT"])
def test_raw_string_correspondent_dependent_is_not_funded(raw: str) -> None:
    try:
        disposition = project_funding(_inputs(raw)).disposition
    except (TypeError, ValueError):
        return  # refused at the boundary: safe
    assert disposition is not FundingDisposition.FUNDED
