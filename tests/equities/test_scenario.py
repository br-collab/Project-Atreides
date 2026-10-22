import json
from datetime import UTC, datetime

from atreides.equities.scenario import build_equities_publications


def test_end_to_end_atreides_run_replays_byte_for_byte() -> None:
    at = datetime(2026, 10, 22, 14, tzinfo=UTC)
    first = build_equities_publications(at)
    second = build_equities_publications(at)
    assert first == second
    assert set(first) == {
        "equities-account-capacity.json",
        "equities-locates.json",
        "equities-books.json",
        "equities-margin.json",
        "equities-protection-from-books.json",
    }
    assert b'"balanced":true' in first["equities-books.json"]
    assert b'"locate_id":"LOC-EQ1-1"' in first["equities-books.json"]
    assert b'"kind":"MAINTENANCE"' in first["equities-margin.json"]
    books = json.loads(first["equities-books.json"])
    margin = json.loads(first["equities-margin.json"])
    protection = json.loads(first["equities-protection-from-books.json"])
    capacity_envelope = json.loads(first["equities-account-capacity.json"])
    capacity = json.loads(capacity_envelope["payload"])
    assert books["journal_digest"] == margin["journal_digest"] == capacity["journal_digest"]
    assert len(capacity["accounts"]) == 3
    assert set(books["stock_record"]) == {"ACME", "PENNY"}
    assert protection["projection"]["derived"] == [
        "15c3-3a.item.01",
        "15c3-3a.item.04",
        "15c3-3a.item.10",
        "15c3-3a.item.11",
        "15c3-3a.item.12",
    ]
    moved = {item["account_id"]: item for item in margin["accounts_after_price_move"]}
    maintenance = next(
        call for call in moved["CUSTOMER-1"]["calls"] if call["kind"] == "MAINTENANCE"
    )
    assert maintenance["due_period_authority"] == "INTERNAL_POLICY"
    assert maintenance["due_date"] == "2026-10-26"
