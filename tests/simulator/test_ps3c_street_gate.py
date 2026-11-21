"""PS-3C Part 1 run-level central street reconciliation tests."""

from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack


def _small_profile():  # type: ignore[no-untyped-def]
    return load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small")


def test_street_one_share_mutation_fails_its_central_gate_row() -> None:
    day = run_firm(_small_profile(), days=1, mutation="STREET_ONE_SHARE", verify_replay=False).days[
        0
    ]
    rows = {row.item_id: row for row in day.reconciliation_calendar}
    street = rows["stock-record-to-street"]
    assert street.status == "FAILED", "street-row status control did not fail"
    assert street.break_count == 1, "street-row status control did not report one break"
    assert all(
        row.status == "RAN" and row.break_count == 0
        for item_id, row in rows.items()
        if item_id != "stock-record-to-street"
    ), "street mutation changed an unrelated reconciliation row"
