"""Named written supervisory procedure tests the Rule 3120 runner executes.

Each function name is the ``test`` field of one register row. A deselected
function is absent from the JUnit file, and Rule 3120 records that absence.
"""

from atreides.supervision.controls import load_wsp_register


def _row(test_name: str) -> dict[str, object]:
    matches = [row for row in load_wsp_register() if row["test"] == test_name]
    assert len(matches) == 1, test_name
    return matches[0]


def test_account_opening_gate() -> None:
    assert _row("test_account_opening_gate")["gate"] == "account opening"


def test_kyc_gate() -> None:
    assert _row("test_kyc_gate")["gate"] == "KYC"


def test_customer_profile_gate() -> None:
    assert _row("test_customer_profile_gate")["gate"] == "customer profile"


def test_recommendation_gate() -> None:
    assert _row("test_recommendation_gate")["gate"] == "recommendation"


def test_market_access_gate() -> None:
    assert _row("test_market_access_gate")["gate"] == "market access"


def test_approved_intent_gate() -> None:
    assert _row("test_approved_intent_gate")["gate"] == "approved intent"


def test_fill_booking_gate() -> None:
    assert _row("test_fill_booking_gate")["gate"] == "fill booking"


def test_confirmation_gate() -> None:
    assert _row("test_confirmation_gate")["gate"] == "confirmation"


def test_statement_gate() -> None:
    assert _row("test_statement_gate")["gate"] == "statement"


def test_stock_record_reconciliation_gate() -> None:
    assert _row("test_stock_record_reconciliation_gate")["gate"] == "stock record to street"


def test_fail_reconciliation_gate() -> None:
    assert _row("test_fail_reconciliation_gate")["gate"] == "fail to receive to CNS"


def test_stock_loan_reconciliation_gate() -> None:
    assert _row("test_stock_loan_reconciliation_gate")["gate"] == "stock loan to register"


def test_cash_reconciliation_gate() -> None:
    assert _row("test_cash_reconciliation_gate")["gate"] == "cash to bank"


def test_reserve_reconciliation_gate() -> None:
    assert _row("test_reserve_reconciliation_gate")["gate"] == "reserve bank to books"


def test_securities_count_gate() -> None:
    assert _row("test_securities_count_gate")["gate"] == "securities count"


def test_reserve_gate() -> None:
    assert _row("test_reserve_gate")["gate"] == "reserve"


def test_net_capital_gate() -> None:
    assert _row("test_net_capital_gate")["gate"] == "net capital"


def test_early_warning_gate() -> None:
    assert _row("test_early_warning_gate")["gate"] == "early warning"
