"""R5: one name, one meaning, before the contracts are frozen.

`dsor_pre_trade_record_id` meant three different things across the boundary
`W3-contract-freeze.md` is freezing:

- on `GateResult` it named the settlement telemetry that validation had
  persisted. Removed in v0.4.0, because validation now persists nothing
  (ATR-I-02);
- on `InstructionPackage` and `BreakTicket` it was a `@property` alias for
  `dsor_record_id`, marked "Deprecated until Wave 3";
- on `SettlementTaskingRecord` it was a real, required field.

The third turned out not to be a DSOR reference at all. The cockpit set it to
`uuid5(NAMESPACE_URL, f"atreides:cockpit:{pre_hash}")` — **the same value it
assigns to `task_id`** — so it was a second copy of the record's own identifier,
and no DSOR record with that identifier exists. The nine test fixtures passed an
unrelated `uuid4()`. Nothing in any repository read it.

So the field was removed rather than renamed. The tasking record's identity is
`task_id`; its upstream provenance is `lineage_stub`, which carries the operation,
the authority, the pre-operation state hash and the `c2_handoff_id` slot. A third
field naming none of those had nothing to name.

`dsor_record_id` remains, on `InstructionPackage` and `BreakTicket`, meaning the
one thing it ever meant: the record written at emission.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from atreides.agents.tier1.outputs import SettlementTaskingRecord
from atreides.cockpit.clearing_cockpit import BreakTicket, InstructionPackage

ROOT = pathlib.Path(__file__).resolve().parents[2]

RETIRED_NAME = "dsor_pre_trade_record_id"


def test_the_retired_name_is_gone_from_the_package() -> None:
    """Not deprecated, not aliased — absent. An alias is a second meaning kept alive."""
    for model in (SettlementTaskingRecord, InstructionPackage, BreakTicket):
        assert not hasattr(model, RETIRED_NAME), (
            f"{model.__name__} still exposes {RETIRED_NAME}"
        )
        assert RETIRED_NAME not in getattr(model, "model_fields", {}), (
            f"{model.__name__} still declares {RETIRED_NAME} as a field"
        )


def test_the_retired_name_is_used_nowhere_in_the_package() -> None:
    """No production source may mention it at all, except to explain its removal.

    The rule is deliberately crisp rather than clever: a first attempt tried to
    tell prose from code by how the line was punctuated, and flagged both a
    CHANGELOG entry and a `not hasattr` assertion. Named exceptions with reasons
    are easier to read and harder to get wrong.

    Uses `git grep`, so an uncommitted file is not yet seen — which is why this
    runs in continuous integration and not only before a commit.
    """
    allowed = {
        # The removal is part of the record. Both name it in the past tense.
        "CHANGELOG.md",
        "tests/contracts/test_r5_dsor_naming.py",
        # The docstring explaining what GateResult used to carry (v0.4.0).
        "atreides/cockpit/clearing_cockpit.py",
        # ATR-I-02's regression test asserts the name is *absent*.
        "tests/cockpit/test_probe_pure_validation.py",
    }
    found = subprocess.run(
        ["git", "grep", "-n", RETIRED_NAME], cwd=ROOT,
        capture_output=True, text=True, check=False,
    ).stdout.splitlines()

    offenders = [line for line in found if line.split(":", 1)[0] not in allowed]
    assert offenders == [], (
        "the retired name is back:\n" + "\n".join(offenders)
    )


def test_where_it_is_still_named_it_is_named_as_gone() -> None:
    """An allowed mention must not be a live use."""
    for path in ("atreides/cockpit/clearing_cockpit.py",
                 "tests/cockpit/test_probe_pure_validation.py"):
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            if RETIRED_NAME not in line:
                continue
            assert f"{RETIRED_NAME}=" not in line and f".{RETIRED_NAME}" not in line, (
                f"{path}: the retired name is used, not described: {line.strip()}"
            )


def test_the_surviving_name_means_the_record_written_at_emission() -> None:
    """`dsor_record_id` keeps the one meaning it always had."""
    for model in (InstructionPackage, BreakTicket):
        assert "dsor_record_id" in model.model_fields, (
            f"{model.__name__} no longer carries dsor_record_id"
        )


def test_the_tasking_record_does_not_carry_its_own_identifier_twice() -> None:
    """What the removed field actually held: a duplicate of `task_id`."""
    fields = set(SettlementTaskingRecord.model_fields)
    assert "task_id" in fields
    assert not [f for f in fields if f.endswith("_record_id")], (
        "a record-identifier field is back on the tasking record; if it references "
        "something upstream, lineage_stub is where upstream provenance lives"
    )


def test_upstream_provenance_still_has_somewhere_to_go() -> None:
    """Removing the field is only safe because the lineage stub carries this."""
    stub = SettlementTaskingRecord.model_fields["lineage_stub"].annotation
    for field in ("operation_id", "authority_id", "pre_operation_state_hash", "c2_handoff_id"):
        assert field in stub.model_fields, (
            f"DSORLineageStub no longer carries {field}; the tasking record's upstream "
            f"provenance now has nowhere to live"
        )


@pytest.mark.parametrize("model", [SettlementTaskingRecord, InstructionPackage, BreakTicket],
                         ids=lambda m: m.__name__)
def test_no_field_still_calls_a_record_pre_trade(model) -> None:
    """Atreides is post-trade. 'Pre-trade' was the original error in the name."""
    offenders = [f for f in model.model_fields if "pre_trade" in f]
    assert offenders == [], f"{model.__name__} calls something pre-trade: {offenders}"
