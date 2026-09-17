"""ATR-I-03 regression: a submission object is unconstructible at runtime.

``InstructionArtifact.is_submission`` is typed ``Literal[False]``, but the
class is a plain dataclass, so until Wave 2 the annotation was enforced only
by a static checker: the Atreides inventory probe (15 Sep 2026, commit
31b62f0) and stress case E6.2 both constructed one with
``is_submission=True``. The cockpit's ``InstructionPackage`` rejected
``True`` at construction but accepted ``0`` and let
``model_copy(update={"is_submission": True})`` through.

Fixed in W2A-1: the artifact enforces the pin in ``__post_init__``, and the
package is strict on the field and revalidates on copy.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from pydantic import ValidationError

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail
from atreides.cockpit import InstructionPackage, PackageDisposition, PortalRegime
from atreides.messaging.emit import InstructionArtifact


def _artifact(**changes: object) -> InstructionArtifact:
    fields: dict[str, object] = {
        "header_xml": b"<AppHdr/>",
        "document_xml": b"<Document/>",
        "message_definition": "pacs.009.001.13",
        "profile_name": "base-iso20022",
        "profile_verified": True,
        "dsor_lineage_uri": None,
    }
    fields.update(changes)
    return InstructionArtifact(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 1, "true", "False", None, 0, 0.0])
def test_instruction_artifact_accepts_only_false(value: object) -> None:
    with pytest.raises(ValueError, match="ATR-I-03"):
        _artifact(is_submission=value)
    assert _artifact().is_submission is False


def test_stress_e6_2_positional_submission_artifact_is_refused() -> None:
    # Stress case E6.2 built the artifact positionally.
    with pytest.raises(ValueError, match="ATR-I-03"):
        InstructionArtifact(b"", b"", "m", "p", True, None, True)  # type: ignore[arg-type]


def test_dataclasses_replace_cannot_produce_a_submission() -> None:
    with pytest.raises(ValueError, match="ATR-I-03"):
        dataclasses.replace(_artifact(), is_submission=True)  # type: ignore[arg-type]


def _package(**changes: object) -> InstructionPackage:
    fields: dict[str, object] = {
        "operation_id": uuid.uuid4(),
        "regime": PortalRegime.CCP,
        "disposition": PackageDisposition.GATE_HELD,
        "rail": SettlementRail.FICC_GSD_DVP,
        "settlement_kind": SettlementKind.DVP,
        "cusip": None,
        "net_delivery_quantity": None,
        "net_payment_amount": None,
        "dsor_pre_trade_record_id": uuid.uuid4(),
        "authority_stamp": {},
        "quorum_required": False,
        "for_human_entry": False,
    }
    fields.update(changes)
    return InstructionPackage(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 1, 0, "true", "false", None])
def test_instruction_package_accepts_only_false(value: object) -> None:
    with pytest.raises(ValidationError):
        _package(is_submission=value)
    assert _package().is_submission is False


def test_instruction_package_copy_cannot_produce_a_submission() -> None:
    pkg = _package()
    with pytest.raises(ValidationError):
        pkg.model_copy(update={"is_submission": True})
    assert pkg.model_copy(update={"notes": "x"}).notes == "x"
    assert pkg.model_copy() == pkg


def test_instruction_package_json_cannot_carry_a_submission() -> None:
    raw = _package().model_dump_json().replace('"is_submission":false', '"is_submission":true')
    with pytest.raises(ValidationError):
        InstructionPackage.model_validate_json(raw)
