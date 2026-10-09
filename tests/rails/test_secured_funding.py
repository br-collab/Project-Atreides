"""Actual secured funding is an observation. A projection is not one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance

from atreides.rails.cato_cash import FinalityClass
from atreides.rails.funding_state import FundingDisposition, FundingInputs, project_funding
from atreides.rails.secured_funding import (
    SecuredFunding,
    assess_secured_funding,
    read_secured_funding,
)

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
_FORBIDDEN = ("compliant", "approved", "cleared", "certified")


def _projection():
    return project_funding(
        FundingInputs(
            opening_position=Decimal("10000000"),
            obligation=Decimal("1000000"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=14400,
            net_debit_cap=Decimal("50000000"),
            clearing_fund_requirement=Decimal("500000"),
            clearing_fund_posted=Decimal("500000"),
        )
    )


def _observed(**overrides: object) -> SecuredFunding:
    fields: dict[str, object] = {
        "authoritative_source": "synthetic-custodian",
        "amount": Decimal("1000000.00"),
        "currency": "USD",
        "account_or_facility": "facility-1",
        "observation_time": T0,
        "provenance": Provenance.FACT_SYNTHETIC,
    }
    fields.update(overrides)
    return SecuredFunding.model_validate(fields)


def _no_claim(reason: str) -> None:
    folded = reason.casefold()
    for word in _FORBIDDEN:
        assert word not in folded


def test_a_funded_projection_is_not_secured_funding() -> None:
    projection = _projection()
    assert projection.disposition is FundingDisposition.FUNDED
    missing = assess_secured_funding(None, projection=projection)
    assert missing.disposition is Disposition.INDETERMINATE
    assert missing.amount is None
    assert missing.amount != Decimal(0)
    _no_claim(missing.reason)


def test_an_observation_passes_and_does_not_borrow_the_projection() -> None:
    projection = _projection()
    evidence = _observed(amount=Decimal("25.00"))
    graded = assess_secured_funding(evidence, projection=projection)
    assert graded.disposition is Disposition.PASS
    assert graded.amount == Decimal("25.00")
    assert graded.amount != projection.projected_position_at_settlement
    external = _observed(provenance=Provenance.FACT_EXTERNAL)
    assert assess_secured_funding(external).disposition is Disposition.PASS
    _no_claim(graded.reason)


def test_an_unreadable_observation_is_indeterminate_and_not_zero() -> None:
    payload = _observed().model_dump(mode="json")
    payload["provenance"] = "FORECAST"
    unread = read_secured_funding(payload)
    assert unread.disposition is Disposition.INDETERMINATE
    assert unread.amount is None
    blank = read_secured_funding({"amount": "0", "currency": "USD"})
    assert blank.disposition is Disposition.INDETERMINATE
    assert blank.amount is None
    observed_zero = assess_secured_funding(_observed(amount=Decimal(0)))
    assert observed_zero.disposition is Disposition.PASS
    assert observed_zero.amount == Decimal(0)
    _no_claim(unread.reason)
    _no_claim(blank.reason)


def test_a_stale_shape_is_refused_before_it_can_pass() -> None:
    naive = _observed().model_dump(mode="json")
    naive["observation_time"] = (T0.replace(tzinfo=None) - timedelta(0)).isoformat()
    unread = read_secured_funding(naive)
    assert unread.disposition is Disposition.INDETERMINATE
    _no_claim(unread.reason)
