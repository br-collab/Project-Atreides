"""FIX-9 property evidence for every Atreides money and quantity path.

Each property records a fixed seed and runs 200 generated examples. Values are
generated at their domain's smallest supported unit: whole shares/par and cents.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    ReserveActivity,
)
from atreides.books.projections import project_customer_protection
from atreides.clearing.access import AccessDetermination, AccessPath, AccessStatus
from atreides.clearing.ficc import (
    ClearingAgency,
    FiccGsdNettingDocument,
    FiccGsdNettingRequest,
    NovatedObligation,
    produce_ficc_gsd_result,
)
from atreides.clearing.repo import RepoDocument, RepoLeg, RepoTerm, produce_repo_result
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.margin.engine import MarginAccount, MarginPosition, compute_margin
from tests.books.test_ledger import _line_amount, _reserve_entry, entry
from tests.clearing.test_ficc import _arrangement
from tests.clearing.test_repo import trade

PROPERTIES = settings(max_examples=200, deadline=None)
CENT = Decimal("0.01")


def cents(value: int) -> Decimal:
    return Decimal(value) * CENT


@PROPERTIES
@seed(29002)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=-100_000, max_value=100_000).filter(bool),
            st.integers(min_value=1, max_value=10_000_000),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_ficc_gsd_netting_conserves_par_and_money(rows: list[tuple[int, int]]) -> None:
    obligations = tuple(
        NovatedObligation(
            obligation_id=f"obligation-{index}",
            trade_ids=(f"trade-{index}",),
            member_id="member-a",
            cusip="91282CJL6",
            settlement_date=date(2026, 10, 22),
            signed_quantity=Decimal(quantity),
            signed_settlement_amount=cents(-money_cents if quantity > 0 else money_cents),
            settlement_currency="USD",
            novation_evidence_id=f"novation-{index}",
        )
        for index, (quantity, money_cents) in enumerate(rows)
    )
    result = produce_ficc_gsd_result(
        FiccGsdNettingRequest(
            clearing_agency=ClearingAgency.FICC_GSD,
            access=AccessDetermination(
                status=AccessStatus.ESTABLISHED,
                arrangement=_arrangement(AccessPath.FICC_DIRECT),
            ),
            obligations=obligations,
            clearing_acceptance_evidence_id="acceptance",
            netting_evidence_id="netting",
        )
    )
    assert result.payload is not None
    net = FiccGsdNettingDocument.model_validate_json(result.payload).net_settlement_obligations[0]
    assert net.net_quantity == sum((row.signed_quantity for row in obligations), Decimal(0))
    assert net.net_settlement_amount == sum(
        (row.signed_settlement_amount for row in obligations), Decimal(0)
    )
    assert net.net_settlement_amount == net.net_settlement_amount.quantize(CENT)


@PROPERTIES
@seed(29003)
@given(
    st.integers(min_value=1, max_value=10_000_000),
    st.integers(min_value=0, max_value=2_000),
    st.integers(min_value=1, max_value=10_000_000),
)
def test_repo_close_conserves_par_and_money_to_the_cent(
    par: int, rate_basis_points: int, start_money_cents: int
) -> None:
    result = produce_repo_result(
        trade=trade(
            term=RepoTerm.OVERNIGHT,
            close_date=date(2026, 10, 23),
            collateral_par=Decimal(par),
            start_money=cents(start_money_cents),
            repo_rate_percent=Decimal(rate_basis_points) / Decimal(100),
        ),
        access=AccessDetermination(
            status=AccessStatus.ESTABLISHED,
            arrangement=_arrangement(AccessPath.FICC_DIRECT),
        ),
    )
    assert result.payload is not None
    start, close = RepoDocument.model_validate_json(result.payload).legs
    assert start.leg is RepoLeg.START and close.leg is RepoLeg.CLOSE
    assert start.signed_par + close.signed_par == 0
    assert close.signed_money is not None
    assert close.signed_money == close.signed_money.quantize(CENT)
    assert start.signed_money is not None
    assert start.signed_money + close.signed_money == close.signed_money - abs(start.signed_money)


@PROPERTIES
@seed(29004)
@given(
    st.integers(min_value=1, max_value=10_000),
    st.integers(min_value=1, max_value=100_000),
    st.integers(min_value=-10_000_000, max_value=10_000_000),
)
def test_margin_preserves_market_value_and_accounting_identity(
    quantity: int, price_dollars: int, cash_cents: int
) -> None:
    account = MarginAccount(
        account_id="PROPERTY",
        cash_balance=cents(cash_cents),
        positions=(
            MarginPosition(
                issue="ACME",
                quantity=Decimal(quantity),
                price=Decimal(price_dollars),
                new_trade=True,
            ),
        ),
    )
    result = compute_margin(
        account,
        trade_date=date(2026, 10, 22),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        house_maintenance_rate=Decimal("0.30"),
        maintenance_call_due_business_days=2,
    )
    assert result.long_market_value == Decimal(quantity * price_dollars)
    assert result.equity == (
        result.long_market_value
        + result.credit_balance
        - result.short_market_value
        - result.debit_balance
    )
    assert result.reg_t_initial_requirement == result.long_market_value * Decimal("0.50")


@PROPERTIES
@seed(29005)
@given(
    st.integers(min_value=1, max_value=1_000_000),
    st.integers(min_value=1, max_value=100_000_000),
)
def test_books_journal_conserves_shares_and_money(quantity: int, money_cents: int) -> None:
    original = entry()
    lines = (
        original.lines[0].model_copy(update={"quantity": Decimal(quantity)}),
        original.lines[1].model_copy(update={"quantity": Decimal(-quantity)}),
        original.lines[2].model_copy(update={"money": -cents(money_cents)}),
        original.lines[3].model_copy(update={"money": cents(money_cents)}),
    )
    journal = JournalEntry.model_validate(original.model_dump() | {"lines": lines})
    assert sum((line.quantity for line in journal.lines), Decimal(0)) == 0
    assert sum((line.money for line in journal.lines), Decimal(0)) == 0


@PROPERTIES
@seed(29006)
@given(
    st.integers(min_value=1, max_value=1_000_000),
    st.integers(min_value=1, max_value=100_000_000),
)
def test_exhibit_a_contract_value_conserves_quantity_and_money(
    quantity: int, price_cents: int
) -> None:
    books = EquitiesBooks(break_owner="property")
    books.post(
        _reserve_entry(
            event="7",
            account_type=AccountType.FAIL_TO_RECEIVE,
            activity=ReserveActivity.CUSTOMER,
            quantity=Decimal(quantity),
            contract_price=cents(price_cents),
            settlement_date=date(2026, 10, 21),
        )
    )
    projected = project_customer_protection(
        books,
        as_of=date(2026, 10, 22),
        prices={"ACME": cents(price_cents)},
        net_worth=Decimal("1000000"),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=(),
    )
    amount = _line_amount(projected.reserve, "15c3-3a.item.04")
    assert amount == Decimal(quantity) * cents(price_cents)
    assert amount is not None and amount == amount.quantize(CENT)
