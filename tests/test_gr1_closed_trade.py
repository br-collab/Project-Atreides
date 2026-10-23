from __future__ import annotations

import importlib
import sys
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.closed_trade import (
    InboundStatus,
    RuntimeProfile,
    TreasuryDvpInstruction,
    close_treasury_trade,
)
from atreides.reference_data import (
    AccountRecord,
    InstrumentRecord,
    LegalEntityRecord,
    SettlementInstructionRecord,
)
from emulators.ficc import emit_inbound


def instruction(
    *, quantity: Decimal = Decimal("1000000"), cash: Decimal = Decimal("995000")
) -> TreasuryDvpInstruction:
    effective = date(2026, 10, 1)
    lei = "5493001KJTIIGC8Y1R12"
    return TreasuryDvpInstruction(
        trade_id="TRADE-GR1-1",
        obligation_id="OBL-GR1-1",
        member_id="MEMBER-1",
        cusip="91282CJL6",
        quantity=quantity,
        cash_amount=cash,
        currency="USD",
        settlement_date=date(2026, 10, 23),
        instrument=InstrumentRecord(
            cusip="91282CJL6",
            figi="BBG01QJZQ6Z0",
            description="UST on-the-run",
            provenance="fixture:GR-1",
            effective_date=effective,
        ),
        member=LegalEntityRecord(
            lei=lei, entity_id="MEMBER-1", provenance="fixture:GR-1", effective_date=effective
        ),
        account=AccountRecord(
            account_id="ACCOUNT-1",
            owner_lei=lei,
            account_type="FICC_GSD_DIRECT",
            provenance="fixture:GR-1",
            effective_date=effective,
        ),
        ssi=SettlementInstructionRecord(
            ssi_id="SSI-1",
            account_id="ACCOUNT-1",
            settlement_location="FICC_GSD",
            cash_account_id="CASH-1",
            securities_account_id="FEDWIRE-1",
            provenance="fixture:GR-1",
            effective_date=effective,
        ),
    )


def close(inst: TreasuryDvpInstruction, **kwargs: object):
    return close_treasury_trade(
        inst,
        emit_inbound(inst, **kwargs),
        profile=RuntimeProfile.RESEARCH,
        break_owner="settlement-ops",
        age_business_days=1,
    )


def test_closed_trade_and_next_day_replay_are_byte_identical() -> None:
    inst = instruction()
    first = close(inst)
    replay = close(inst)
    assert first.disposition == "PASS" and first.books_posted
    assert first.breaks == ()
    assert first.economics_bytes == replay.economics_bytes
    assert b"pacs.002" in emit_inbound(inst).pacs002
    assert b"camt.054" in emit_inbound(inst).camt054


@pytest.mark.parametrize(
    "status", [InboundStatus.MATCHED, InboundStatus.PARTIAL, InboundStatus.UNMATCHED]
)
def test_nonfinal_statuses_hold(status: InboundStatus) -> None:
    result = close(instruction(), status=status)
    assert result.disposition == "HOLD" and not result.books_posted


def test_late_and_forced_mismatch_open_owned_aged_breaks() -> None:
    result = close(
        instruction(), amount_delta=Decimal("0.01"), quantity_delta=Decimal("-1"), late=True
    )
    assert result.disposition == "HOLD"
    assert result.breaks and all(
        item.owner == "settlement-ops" and item.age_business_days == 1 for item in result.breaks
    )


def test_production_refuses_synthetic_provenance() -> None:
    inst = instruction()
    with pytest.raises(ValueError, match="FACT_SYNTHETIC"):
        close_treasury_trade(
            inst,
            emit_inbound(inst),
            profile=RuntimeProfile.PRODUCTION,
            break_owner="ops",
            age_business_days=0,
        )


def test_production_profile_cannot_import_emulators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATREIDES_PROFILE", "production")
    sys.modules.pop("emulators", None)
    with pytest.raises(ImportError, match="production profile"):
        importlib.import_module("emulators")


# Rule 29: generated uneven quantities and cents; seed recorded for replay.
@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10**9),
    cash_cents=st.integers(min_value=1, max_value=10**12),
)
def test_money_and_securities_conserve_to_cent_and_share(quantity: int, cash_cents: int) -> None:
    inst = instruction(quantity=Decimal(quantity), cash=Decimal(cash_cents) / 100)
    result = close(inst)
    assert result.obligation_amount == result.ccp_output_amount == result.cash_movement_amount
    assert result.securities_movement_quantity == Decimal(quantity)
