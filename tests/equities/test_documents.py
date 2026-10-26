from datetime import UTC, datetime, timedelta

from atreides.equities.documents import (
    AccountCapacity,
    AccountCapacityDocument,
    AccountPosition,
    LocateDocument,
    LocateInventory,
    LocateRecord,
    attest_capacity,
    attest_locates,
)

NOW = datetime(2026, 10, 22, 14, tzinfo=UTC)


def test_real_emitters_attest_capacity_and_locates() -> None:
    capacity = AccountCapacityDocument(
        as_of=NOW,
        maximum_age_seconds=300,
        journal_digest="sha256:" + "1" * 64,
        firm_participant_id="SYNTHETIC-FIRM-PARTICIPANT",
        accounts=(
            AccountCapacity(
                account_id="A",
                capacity="CUSTOMER",
                buying_power=1000,
                margin_excess=200,
                margin_result_digest="sha256:" + "2" * 64,
                positions=(AccountPosition(issue="ACME", quantity=10),),
            ),
        ),
    )
    locates = LocateDocument(
        as_of=NOW,
        locates=(
            LocateRecord(
                locate_id="L1",
                source="SYNTHETIC_LENDER",
                located_at=NOW,
                expires_at=NOW + timedelta(hours=1),
                issue="ACME",
                quantity=10,
            ),
        ),
    )
    assert attest_capacity(capacity).payload_digest.startswith("sha256:")
    assert attest_locates(locates).payload_digest.startswith("sha256:")


def test_locate_refusal_paths_and_consumption() -> None:
    record = LocateRecord(
        locate_id="L1",
        source="SYNTHETIC_EASY_TO_BORROW",
        located_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        issue="ACME",
        quantity=10,
    )
    inventory = LocateInventory(LocateDocument(as_of=NOW, locates=(record,)))
    assert inventory.consume("missing", issue="ACME", quantity=1, at=NOW) == "LOCATE_MISSING"
    assert inventory.consume("L1", issue="OTHER", quantity=1, at=NOW) == "LOCATE_ISSUE_MISMATCH"
    assert (
        inventory.consume("L1", issue="ACME", quantity=1, at=NOW + timedelta(hours=2))
        == "LOCATE_EXPIRED"
    )
    assert inventory.consume("L1", issue="ACME", quantity=7, at=NOW) is None
    assert inventory.consume("L1", issue="ACME", quantity=4, at=NOW) == "LOCATE_INSUFFICIENT"


def _result(account_id: str):  # type: ignore[no-untyped-def]
    from cannae_kernel.disposition import Disposition

    from atreides.margin.engine import MarginResult, RuleTrace

    return MarginResult(
        account_id=account_id,
        disposition=Disposition.PASS,
        long_market_value=0,
        short_market_value=0,
        debit_balance=0,
        credit_balance=0,
        equity=0,
        reg_t_initial_requirement=0,
        finra_maintenance_requirement=0,
        house_requirement=0,
        excess_or_deficiency=100,
        calls=(),
        liquidation=None,
        rules_used=(
            RuleTrace(
                rule_id="reg_t.initial", citation="SYNTHETIC", source_sha256="0" * 64, value=1
            ),
        ),
        missing_rules=(),
    )


def test_capacity_comes_from_the_books_type_and_an_unclassified_account_is_refused() -> None:
    """INST-1 Amendment 3 (WP1b item 4): no default capacity, and none from an order author."""
    import pytest

    from atreides.books.ledger import AccountType
    from atreides.equities.documents import CAPACITY_BY_ACCOUNT_TYPE, project_capacity
    from atreides.margin.engine import MarginAccount

    assert CAPACITY_BY_ACCOUNT_TYPE[AccountType.CUSTOMER_MARGIN] == "CUSTOMER"
    assert CAPACITY_BY_ACCOUNT_TYPE[AccountType.PAB] == "PAB"
    assert CAPACITY_BY_ACCOUNT_TYPE[AccountType.FIRM_PROPRIETARY] == "PROPRIETARY"
    assert AccountType.DTC not in CAPACITY_BY_ACCOUNT_TYPE
    with pytest.raises(ValueError, match="ownership account type for A"):
        project_capacity(
            journal_digest="sha256:" + "1" * 64,
            as_of=NOW,
            maximum_age_seconds=300,
            margin_results=(_result("A"),),
            accounts=(MarginAccount(account_id="A", cash_balance=0, positions=()),),
            account_types={"A": AccountType.DTC},
            firm_participant_id="SYNTHETIC-FIRM-PARTICIPANT",
        )
