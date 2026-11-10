"""FIX-12 regressions for protection inputs N2 through N5."""

from datetime import date
from decimal import Decimal

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    LedgerLine,
    PostingSource,
    RecordSide,
    ReserveActivity,
)
from atreides.books.projections import project_customer_protection
from atreides.deadlines.calendar import Market, MarketCalendar
from tests.books.test_ledger import _margin_results, _reserve_entry, entry

AS_OF = date(2026, 10, 22)
PRICE = {"ACME": Decimal(100)}
RULE_15C3_1_SHA256 = "939491851c7975f6168c6a93e0879818d658250cab305d1364212c74f42c172a"
RULE_15C3_3_SHA256 = "c7d7067f656bb6032182c0d81530a78d6d80d59cc4a842be84d9e43d13609443"
RULE_15C3_3A_SHA256 = "8046b00e1ff4114afd773268cde5c2445fa714a1ed751def9499ee47d1682dbd"


def _project(books: EquitiesBooks):  # type: ignore[no-untyped-def]
    return project_customer_protection(
        books,
        as_of=AS_OF,
        prices=PRICE,
        net_worth=Decimal(1_000_000),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=_margin_results(books),
    )


def test_n2_customer_positions_are_not_firm_haircut_positions() -> None:
    # 17 CFR 240.15c3-1(c)(2)(vi), pinned by RULE_15C3_1_SHA256:
    # "of the market value of all securities, money market instruments or options in
    # the proprietary or other accounts of the broker or dealer." Bill's recorded N2
    # decision excludes customer positions from that scope.
    assert RULE_15C3_1_SHA256
    books = EquitiesBooks(break_owner="owner")
    books.post(entry())
    assert _project(books).net_capital.positions == ()


def test_n3_pab_free_credit_enters_pab_item_1() -> None:
    # 17 CFR 240.15c3-3a, PAB Note 1, pinned by RULE_15C3_3A_SHA256:
    # "Broker-dealers should use the formula in Exhibit A for the purposes of computing
    # the PAB reserve requirement, except that references to accounts, customer accounts,
    # or customers will be treated as references to PAB accounts."
    assert RULE_15C3_3A_SHA256
    books = EquitiesBooks(break_owner="owner")
    books.post(
        entry(
            "2",
            "pab-cash",
            source=PostingSource.CASH_MOVEMENT,
            lines=(
                LedgerLine(
                    account_id="SYN-PAB-1",
                    account_type=AccountType.PAB,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=Decimal(125),
                ),
                LedgerLine(
                    account_id="SYN-CASH",
                    account_type=AccountType.CASH,
                    record_side=RecordSide.MONEY,
                    currency="USD",
                    money=Decimal(-125),
                ),
            ),
        )
    )
    item_1 = next(
        line.amount
        for line in _project(books).pab_reserve.lines
        if line.rule_id == "15c3-3a.item.01"
    )
    assert item_1 == Decimal(125)


def test_n4_fail_to_deliver_is_not_a_d2_control_holding() -> None:
    # 17 CFR 240.15c3-3(d)(2), pinned by RULE_15C3_3_SHA256:
    # "Securities included on the broker's or dealer's books or records as failed to
    # receive more than 30 calendar days".
    assert RULE_15C3_3_SHA256
    books = EquitiesBooks(break_owner="owner")
    books.post(entry())
    books.post(
        _reserve_entry(
            event="3",
            account_type=AccountType.FAIL_TO_DELIVER,
            activity=ReserveActivity.CUSTOMER,
            quantity=Decimal(2),
            contract_price=Decimal(70),
            settlement_date=AS_OF,
        )
    )
    holdings = _project(books).control.issues[0].holdings
    assert all(holding.location != "15c3-3.noncontrol.d2" for holding in holdings)


def test_n5_stock_loan_holding_declares_loaned_true() -> None:
    # 17 CFR 240.15c3-3(d)(1), pinned by RULE_15C3_3_SHA256:
    # "Securities subject to a lien securing moneys borrowed by the broker or dealer or
    # securities loaned to another broker or dealer or a clearing corporation".
    assert RULE_15C3_3_SHA256
    books = EquitiesBooks(break_owner="owner")
    loan_lines = tuple(
        line.model_copy(update={"account_type": AccountType.STOCK_LOANED})
        if line.account_type is AccountType.DTC
        else line
        for line in entry().lines
    )
    books.post(entry("4", "loan", source=PostingSource.STOCK_LOAN, lines=loan_lines))
    holding = next(
        holding
        for holding in _project(books).control.issues[0].holdings
        if holding.location == "15c3-3.noncontrol.d1"
    )
    assert holding.loaned is True
