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
        accounts=(
            AccountCapacity(
                account_id="A",
                buying_power=1000,
                margin_excess=200,
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
