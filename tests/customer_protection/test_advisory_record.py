"""WP-5 acceptance: the ADVISORY_ONLY advisory and its DSOR record.

Acceptance criteria (ORDER SC-2, WP-5):

- Replay is byte identical: ``test_replay_through_the_store_is_byte_identical``.
- Breach yields HOLD in the artifact: ``test_a_breach_yields_hold_in_the_advisory`` and
  ``test_a_projected_breach_yields_hold_in_the_advisory``.
- A tampered stored record fails replay verification:
  ``test_a_tampered_stored_record_fails_replay_verification``.
- An AST (abstract syntax tree) test proves no module imports aureon, L.C. or any
  enforcement path: ``test_package_source.py::test_no_import_of_aureon_lc_or_the_network``
  and ``test_no_module_imports_the_rest_of_atreides``.
- Docstrings state ADVISORY_ONLY: ``test_docstrings_state_advisory_only``.

Every balance below is SYNTHETIC.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from cannae_kernel.canonical import digest
from cannae_kernel.disposition import Disposition
from pydantic import ValidationError

import atreides.customer_protection as package
from atreides.customer_protection import advisory as advisory_module
from atreides.customer_protection import record as record_module
from atreides.customer_protection.advisory import CustomerProtectionAdvisory, advise
from atreides.customer_protection.control import ControlInputs
from atreides.customer_protection.net_capital import NetCapitalInputs
from atreides.customer_protection.record import (
    CustomerProtectionComputationRecord,
    record_computation,
    verify_replay,
)
from atreides.customer_protection.reserve import LineBalance, ReserveInputs, compute_reserve
from atreides.customer_protection.rules import load_rule_table
from atreides.dsor import DSORRecord, DSORStore, RecordKind, SettlementDomainOutput
from tests.customer_protection import test_control, test_net_capital, test_reserve
from tests.customer_protection.conftest import TableEditor, without

D = Decimal
TABLE = load_rule_table()
NOW = datetime(2026, 10, 4, 16, 30, tzinfo=UTC)


def op(n: int) -> UUID:
    return UUID(int=n)


def engine_inputs() -> list[ReserveInputs | NetCapitalInputs | ControlInputs]:
    return [
        test_reserve.inputs(),
        test_net_capital.inputs(),
        ControlInputs(as_of=test_control.AS_OF, issues=(test_control.issue(),)),
    ]


# --- the advisory -----------------------------------------------------------------------


def test_enforcement_status_is_advisory_only_and_admits_nothing_else() -> None:
    inputs = test_reserve.inputs()
    advisory = advise(inputs, compute_reserve(inputs, TABLE), TABLE)
    assert advisory.enforcement_status == "ADVISORY_ONLY"
    assert advisory.claim_label == "EXPERIMENTAL"
    dumped = advisory.model_dump()
    dumped["enforcement_status"] = "ENFORCED"
    with pytest.raises(ValidationError):
        CustomerProtectionAdvisory.model_validate(dumped)


def test_a_breach_yields_hold_in_the_advisory() -> None:
    inputs = test_reserve.inputs()
    advisory = advise(inputs, compute_reserve(inputs, TABLE), TABLE)
    assert advisory.disposition is Disposition.HOLD
    assert advisory.reasons_for_hold == (
        "breach: customer reserve deposit is short of the requirement by 270000.00",
    )


def test_a_projected_breach_yields_hold_in_the_advisory() -> None:
    inputs = test_net_capital.inputs(
        net_worth=D("1453750"), aggregate_debit_items=D("1000000")
    )
    advisory = record_computation(inputs, TABLE, operation_id=op(1), recorded_at=NOW).advisory
    assert advisory.disposition is Disposition.HOLD
    assert "early warning" in advisory.reasons_for_hold[0]


def test_a_clean_computation_passes_with_notes_only() -> None:
    advisory = record_computation(
        test_net_capital.inputs(), TABLE, operation_id=op(2), recorded_at=NOW
    ).advisory
    assert advisory.disposition is Disposition.PASS
    assert advisory.reasons_for_hold == ()
    assert advisory.reasons[0].startswith("note: Rule 17a-11(b)(5) not assessed")


def test_missing_rules_and_inputs_travel_with_the_advisory(edited_table: TableEditor) -> None:
    table = edited_table(without("15c3-1.a1iiA.weekly_debit_reduction"))
    inputs = test_reserve.inputs(qualified_securities_deposit=None)
    advisory = advise(inputs, compute_reserve(inputs, table), table)
    assert advisory.disposition is Disposition.INDETERMINATE
    assert advisory.missing_rules == ("15c3-1.a1iiA.weekly_debit_reduction",)
    assert advisory.missing_inputs == ("qualified_securities_deposit",)


def test_unrecognised_inputs_are_reasons() -> None:
    lines = (*test_reserve.lines(), LineBalance(rule_id="x", amount=D(1)))
    inputs = test_reserve.inputs(lines=lines)
    advisory = advise(inputs, compute_reserve(inputs, TABLE), TABLE)
    assert "unrecognised input: line x is not an Exhibit A line" in advisory.reasons


@pytest.mark.parametrize(
    ("disposition", "reasons", "message"),
    [
        ("PASS", ("breach: anything",), "carries no breach"),
        ("BLOCK", (), "never blocks"),
    ],
)
def test_the_advisory_refuses_a_pass_with_a_breach_and_any_block(
    disposition: str, reasons: tuple[str, ...], message: str
) -> None:
    inputs = test_reserve.inputs(qualified_securities_deposit=D("2000000"))
    dumped = advise(inputs, compute_reserve(inputs, TABLE), TABLE).model_dump()
    dumped.update(disposition=disposition, reasons=reasons)
    with pytest.raises(ValidationError, match=message):
        CustomerProtectionAdvisory.model_validate(dumped)


def test_the_advisory_coerces_an_unknown_disposition_to_indeterminate() -> None:
    inputs = test_reserve.inputs()
    dumped = advise(inputs, compute_reserve(inputs, TABLE), TABLE).model_dump()
    dumped["disposition"] = "PROCEED"
    assert CustomerProtectionAdvisory.model_validate(dumped).disposition is (
        Disposition.INDETERMINATE
    )


def test_the_advisory_binds_inputs_result_and_rule_text() -> None:
    inputs = test_reserve.inputs()
    result = compute_reserve(inputs, TABLE)
    advisory = advise(inputs, result, TABLE)
    assert advisory.input_digest == digest(inputs)
    assert advisory.result_digest == digest(result)
    assert advisory.rule_table_digest == TABLE.table_digest
    assert [v.citation for v in advisory.rule_versions] == [
        "17 CFR 240.15c3-1", "17 CFR 240.15c3-3", "17 CFR 240.15c3-3a",
    ]


# --- the DSOR record ---------------------------------------------------------------------


def test_the_dsor_admits_the_record_kind() -> None:
    assert "customer_protection_computation" in RecordKind.__args__  # type: ignore[attr-defined]
    assert "CustomerProtectionComputationRecord" in str(SettlementDomainOutput)


@pytest.mark.parametrize("index", [0, 1, 2], ids=["reserve", "net_capital", "control"])
def test_replay_through_the_store_is_byte_identical(index: int) -> None:
    inputs = engine_inputs()[index]
    record = record_computation(inputs, TABLE, operation_id=op(10 + index), recorded_at=NOW)
    assert record.recorded_dtg == "202610041630"
    with DSORStore(":memory:") as store:
        stored = store.append(record, dtg=NOW)
        assert stored.kind == "customer_protection_computation"
        assert store.payload_bytes(stored.record_id) == record.model_dump_json().encode()
        replayed = store.replay(stored.record_id)
        assert isinstance(replayed, CustomerProtectionComputationRecord)
        assert replayed == record
        assert replayed.model_dump_json() == record.model_dump_json()
        assert store.replay(stored.record_id).model_dump_json() == replayed.model_dump_json()
        (journaled,) = store.records()
        assert isinstance(journaled, DSORRecord) and journaled.output == record
    verification = verify_replay(replayed, TABLE)
    assert verification.verified is True
    assert verification.disposition is Disposition.PASS
    again = record_computation(inputs, TABLE, operation_id=op(10 + index), recorded_at=NOW)
    assert again.model_dump_json() == record.model_dump_json()


def _tamper(
    record: CustomerProtectionComputationRecord, old: bytes, new: bytes
) -> CustomerProtectionComputationRecord:
    """Alter the stored payload underneath the store, as an attacker with the file would."""
    with DSORStore(":memory:") as store:
        stored = store.append(record, dtg=NOW)
        payload = store.payload_bytes(stored.record_id)
        assert old in payload
        store._conn.execute(
            "UPDATE dsor_records SET payload = ? WHERE record_id = ?",
            (payload.replace(old, new).decode(), str(stored.record_id)),
        )
        replayed = store.replay(stored.record_id)
    assert isinstance(replayed, CustomerProtectionComputationRecord)
    return replayed


@pytest.mark.parametrize(
    ("old", "new", "finding"),
    [
        (b'"shortfall":"270000.00"', b'"shortfall":"0"', "not what the recorded inputs compute"),
        (b'"disposition":"HOLD"', b'"disposition":"INDETERMINATE"', "recorded result"),
        (b'"qualified_securities_deposit":"1000000"',
         b'"qualified_securities_deposit":"1000001"', "input digest"),
    ],
)
def test_a_tampered_stored_record_fails_replay_verification(
    old: bytes, new: bytes, finding: str
) -> None:
    record = record_computation(test_reserve.inputs(), TABLE, operation_id=op(20), recorded_at=NOW)
    verification = verify_replay(_tamper(record, old, new), TABLE)
    assert verification.verified is False
    assert verification.disposition is Disposition.HOLD
    assert any(finding in f for f in verification.findings), verification.findings


def test_tampered_rule_versions_fail_replay_verification() -> None:
    record = record_computation(test_reserve.inputs(), TABLE, operation_id=op(21), recorded_at=NOW)
    altered = record.model_copy(update={"rule_versions": record.rule_versions[:1]})
    verification = verify_replay(altered, TABLE)
    assert verification.findings == (
        "the recorded rule versions are not the ones the computation read",
    )


def test_a_tampered_advisory_fails_replay_verification() -> None:
    record = record_computation(test_reserve.inputs(), TABLE, operation_id=op(22), recorded_at=NOW)
    altered = record.model_copy(
        update={"advisory": record.advisory.model_copy(update={"reasons": ()})}
    )
    assert verify_replay(altered, TABLE).findings == (
        "the recorded advisory is not the advisory the computation gives",
    )


def test_replay_against_other_rule_text_is_indeterminate(edited_table: TableEditor) -> None:
    record = record_computation(test_reserve.inputs(), TABLE, operation_id=op(23), recorded_at=NOW)
    other = edited_table(without("17a-11.b1.ai_warning"))
    verification = verify_replay(record, other)
    assert verification.disposition is Disposition.INDETERMINATE
    assert verification.verified is False


def test_the_record_carries_advisory_only_and_refuses_anything_else() -> None:
    record = record_computation(test_reserve.inputs(), TABLE, operation_id=op(24), recorded_at=NOW)
    assert record.enforcement_status == "ADVISORY_ONLY"
    dumped: dict[str, Any] = record.model_dump()
    dumped["enforcement_status"] = "GATE"
    with pytest.raises(ValidationError):
        CustomerProtectionComputationRecord.model_validate(dumped)


def test_a_one_way_import_graph() -> None:
    """Either import order works: the DSOR imports this package, never the reverse."""
    for first in ("atreides.customer_protection.record", "atreides.dsor.record"):
        subprocess.run([sys.executable, "-c", f"import {first}"], check=True)


@pytest.mark.parametrize("module", [package, advisory_module, record_module])
def test_docstrings_state_advisory_only(module: Any) -> None:
    text = " ".join(module.__doc__.split())
    assert "ADVISORY_ONLY" in text
    assert "enforces nothing" in text.lower()
    assert "ADVISORY_ONLY" in (CustomerProtectionAdvisory.__doc__ or "")
    assert "ADVISORY_ONLY" in (CustomerProtectionComputationRecord.__doc__ or "")
