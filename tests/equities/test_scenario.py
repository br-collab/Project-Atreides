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
