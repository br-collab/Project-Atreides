from datetime import date
from decimal import Decimal
from pathlib import Path

from cannae_kernel.disposition import Disposition

from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.margin.engine import MarginAccount, MarginPosition, compute_margin


def test_margin_traces_rules_calls_and_advisory_liquidation() -> None:
    account = MarginAccount(
        account_id="CUSTOMER-1",
        cash_balance=Decimal("-900"),
        positions=(
            MarginPosition(issue="LONG", quantity=10, price=100, new_trade=True),
            MarginPosition(issue="CHEAP", quantity=-100, price=4, new_trade=True),
            MarginPosition(issue="SHORT", quantity=-10, price=10),
        ),
    )
    result = compute_margin(
        account,
        trade_date=date(2026, 10, 22),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        house_maintenance_rate=Decimal("0.40"),
    )
    assert result.long_market_value == 1000
    assert result.short_market_value == 500
    assert result.reg_t_initial_requirement == 700
    assert result.finra_maintenance_requirement == 700
    assert result.house_requirement == 600
    assert result.disposition is Disposition.HOLD
    assert {call.kind for call in result.calls} == {"REG_T", "MAINTENANCE"}
    assert result.calls[0].due_date == date(2026, 10, 28)
    assert result.liquidation is not None and result.liquidation.advisory_only
    assert len(result.rules_used) == 7


def test_house_call_and_pass() -> None:
    weak = MarginAccount(
        account_id="A", cash_balance=0, positions=(MarginPosition(issue="X", quantity=1, price=10),)
    )
    hold = compute_margin(
        weak,
        trade_date=date(2026, 10, 22),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        house_maintenance_rate=Decimal("1.1"),
    )
    assert {call.kind for call in hold.calls} == {"HOUSE"}
    strong = weak.model_copy(update={"cash_balance": Decimal(100)})
    passed = compute_margin(
        strong,
        trade_date=date(2026, 10, 22),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        house_maintenance_rate=Decimal("0.30"),
    )
    assert passed.disposition is Disposition.PASS and passed.liquidation is None


def test_missing_or_changed_pinned_source_is_indeterminate() -> None:
    source = Path(__file__).parents[2] / "atreides/margin/rules/sources/finra-4210.txt"
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"changed")
        result = compute_margin(
            MarginAccount(account_id="A", cash_balance=0, positions=()),
            trade_date=date(2026, 10, 22),
            calendar=MarketCalendar.load(Market.US_EQUITIES),
            house_maintenance_rate=Decimal("0.30"),
        )
        assert result.disposition is Disposition.INDETERMINATE
        assert result.finra_maintenance_requirement is None
        assert result.missing_rules
    finally:
        source.write_bytes(original)
