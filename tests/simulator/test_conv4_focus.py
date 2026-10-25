"""CONV-4 FOCUS tie-out and records acceptance tests."""

from simulator.focus import attack_focus, run_focus


def test_focus_ties_books_to_engines_at_every_month_end() -> None:
    result = run_focus()
    assert result["source_pin_status"] == "INDETERMINATE"
    closes = result["closes"]
    assert isinstance(closes, list)
    assert len(closes) == 3
    assert all(close["invariants"]["I13_FOCUS_TIE_OUT"] for close in closes)


def test_17a3_inventory_does_not_invent_missing_records() -> None:
    closes = run_focus()["closes"]
    assert isinstance(closes, list)
    for close in closes:
        records = close["17a_3_records"]
        assert "daily cash blotter" in records["produced"]
        assert "order memoranda" in records["not_produced"]


def test_real_engine_lie_reruns_and_turns_i13_false() -> None:
    # The governing 17 CFR 240.17a-3(a)(1) paragraph is quoted beside run_focus.
    assert attack_focus() == {"net-capital-engine-lie": True}
