"""PS-3C Part 2 run-level money reconciliation tests."""

import pytest

from atreides.books.ps1 import InstructionKind, InstructionLog
from simulator.firm import load_firm_profile, run_firm
from simulator.runner import load_calibration_pack


def _small_profile():  # type: ignore[no-untyped-def]
    return load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small")


@pytest.mark.parametrize(
    ("mutation", "failed_item_id"),
    [
        ("UNPOSTED_DEPOSIT_INSTRUCTION", "cash-to-bank"),
        ("RESERVE_DEPOSIT_NOT_RECEIVED", "reserve-bank-to-books"),
    ],
)
def test_money_mutation_fails_exactly_its_reconciliation_row(
    mutation: str, failed_item_id: str
) -> None:
    day = run_firm(_small_profile(), days=1, mutation=mutation, verify_replay=False).days[0]
    rows = {row.item_id: row for row in day.reconciliation_calendar}

    failed = rows[failed_item_id]
    assert failed.status == "FAILED", f"{failed_item_id} control did not fail"
    assert failed.break_count == 1, f"{failed_item_id} control did not report one break"
    assert all(
        row.status == "RAN" and row.break_count == 0
        for item_id, row in rows.items()
        if item_id != failed_item_id
    ), f"{mutation} changed an unrelated reconciliation row"


def test_clean_run_issues_opening_customer_and_reserve_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, InstructionKind]] = []
    original = InstructionLog.append

    def capture(self: InstructionLog, instruction) -> None:  # type: ignore[no-untyped-def]
        observed.append((instruction.instruction_id, instruction.kind))
        original(self, instruction)

    monkeypatch.setattr(InstructionLog, "append", capture)
    day = run_firm(_small_profile(), days=1, verify_replay=False).days[0]
    assert all(row.status == "RAN" and row.break_count == 0 for row in day.reconciliation_calendar)
    assert InstructionKind.OPENING in {kind for _, kind in observed}
    assert InstructionKind.CUSTOMER_DEPOSIT in {kind for _, kind in observed}
    assert "SCF1-OPENING-RESERVE-INSTRUCTION" in {identifier for identifier, _ in observed}
