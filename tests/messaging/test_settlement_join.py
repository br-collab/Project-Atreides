"""Reconciliation joins the real artifact, receipt, readback, and finality types.

No fixture in this module stands in for those types. The emitter produces the
artifact, the receipt type records the external action, ingest_readback
produces the match, and the join calls the finality adapter.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.finality import ConditionalityStatus, FinalityType, RevocabilityStatus
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance

from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import emit_instruction_artifact, instruction_artifact_digest
from atreides.messaging.finality_evidence import finality_from_readback
from atreides.messaging.readback import (
    ReadbackMatch,
    SettlementStatus,
    absent_readback,
    ingest_readback,
)
from atreides.messaging.receipt import ExternalAction, ExternalActionReceipt
from atreides.messaging.settlement_join import JoinedStage, SettlementJoin, join_settlement_evidence

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
OBSERVED = T0 + timedelta(hours=1)
RECEIPT_EVENT = EventId("evt_" + "4" * 26)
OTHER_EVENT = EventId("evt_" + "5" * 26)
FINALITY_EVENT = EventId("evt_" + "6" * 26)
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "6" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-venue",
    entitlement_refs=(),
    authenticated=True,
)
NS = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16"
_FORBIDDEN = ("compliant", "approved", "cleared", "certified")


def _instruction() -> CashLegInstruction:
    member = FinancialInstitution(bicfi="AAAAUS33XXX")
    return CashLegInstruction(
        message_id="MSG-001",
        end_to_end_id="E2E-001",
        created_at=T0,
        amount=Decimal("1000000.00"),
        currency="USD",
        debtor=member,
        creditor=FinancialInstitution(bicfi="BBBBUS33XXX"),
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=member,
        receiver=FinancialInstitution(bicfi="BBBBUS33XXX"),
    )


def _tx_block(
    *,
    status: str = "ACSC",
    end_to_end_id: str | None = "E2E-001",
    echoed: str | None = None,
) -> str:
    parts = ["    <TxInfAndSts>"]
    if end_to_end_id is not None:
        parts.append(f"      <OrgnlEndToEndId>{end_to_end_id}</OrgnlEndToEndId>")
    parts.append("      <OrgnlTxId>TX-001</OrgnlTxId>")
    parts.append(f"      <TxSts>{status}</TxSts>")
    if echoed is not None:
        parts.append(
            "      <OrgnlTxRef>"
            f'<IntrBkSttlmAmt Ccy="USD">{echoed}</IntrBkSttlmAmt>'
            "</OrgnlTxRef>"
        )
    parts.append("    </TxInfAndSts>")
    return "\n".join(parts)


def _report(
    *,
    status: str = "ACSC",
    original_message_id: str = "MSG-001",
    end_to_end_id: str | None = "E2E-001",
    echoed: str | None = None,
) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Document xmlns="{NS}">\n'
        "  <FIToFIPmtStsRpt>\n"
        "    <GrpHdr>\n"
        "      <MsgId>STS-9001</MsgId>\n"
        "      <CreDtTm>2026-08-14T13:00:00Z</CreDtTm>\n"
        "    </GrpHdr>\n"
        "    <OrgnlGrpInfAndSts>\n"
        f"      <OrgnlMsgId>{original_message_id}</OrgnlMsgId>\n"
        "      <OrgnlMsgNmId>pacs.009.001.13</OrgnlMsgNmId>\n"
        "    </OrgnlGrpInfAndSts>\n"
        f"{_tx_block(status=status, end_to_end_id=end_to_end_id, echoed=echoed)}\n"
        "  </FIToFIPmtStsRpt>\n"
        "</Document>\n"
    )
    return xml.encode("utf-8")


def _receipt(
    instruction: CashLegInstruction,
    digest: str,
    **overrides: object,
) -> ExternalActionReceipt:
    fields: dict[str, object] = {
        "entitled_member_id": "member-1",
        "event_id": RECEIPT_EVENT,
        "action": ExternalAction.SETTLEMENT_INSTRUCTION,
        "artifact_digest": digest,
        "observation_time": OBSERVED,
        "provenance": Provenance.FACT_SYNTHETIC,
        "message_id": instruction.message_id,
        "end_to_end_id": instruction.end_to_end_id,
    }
    fields.update(overrides)
    return ExternalActionReceipt.model_validate(fields)


def _join(
    instruction: CashLegInstruction,
    receipts: tuple[ExternalActionReceipt, ...],
    match: ReadbackMatch,
    **overrides: object,
) -> SettlementJoin:
    artifact = emit_instruction_artifact(instruction)
    entry = match.report.entries[0] if match.report.entries else None
    fields: dict[str, object] = {
        "leg": "cash",
        "governing_rule_set": "synthetic-readback/0.1",
        "authoritative_actor": ACTOR,
        "authoritative_event_id": FINALITY_EVENT,
        "effective_time": T0,
        "observation_time": OBSERVED,
        "evidence_reference": "STS-9001",
        "conditionality_status": ConditionalityStatus.UNCONDITIONAL,
        "revocability_status": RevocabilityStatus.IRREVOCABLE,
        "provenance": Provenance.FACT_SYNTHETIC,
    }
    fields.update(overrides)
    return join_settlement_evidence(
        artifact,
        instruction,
        receipts,
        match,
        entry,
        **fields,  # type: ignore[arg-type]
    )


def _no_claim(join: SettlementJoin) -> None:
    text = join.reason.casefold()
    for word in _FORBIDDEN:
        assert word not in text
    assert join.assertion is None or join.assertion.confidence is None


def test_a_matching_receipt_and_settled_readback_publish_finality() -> None:
    instruction = _instruction()
    artifact = emit_instruction_artifact(instruction)
    digest = instruction_artifact_digest(artifact)
    match = ingest_readback(_report(), (instruction,))
    entry = match.report.entries[0]
    assert entry.status is SettlementStatus.SETTLED
    assert not match.breaks
    receipt = _receipt(instruction, digest)
    cash = _join(instruction, (receipt,), match)
    asset = _join(instruction, (receipt,), match, leg="asset")
    direct = finality_from_readback(
        match,
        entry,
        leg="cash",
        governing_rule_set="synthetic-readback/0.1",
        authoritative_actor=ACTOR,
        authoritative_event_id=FINALITY_EVENT,
        effective_time=T0,
        observation_time=OBSERVED,
        evidence_reference="STS-9001",
        conditionality_status=ConditionalityStatus.UNCONDITIONAL,
        revocability_status=RevocabilityStatus.IRREVOCABLE,
        provenance=Provenance.FACT_SYNTHETIC,
    )
    assert cash.stage is JoinedStage.FINAL
    assert cash.disposition is Disposition.PASS
    assert cash.assertion is not None
    assert cash.assertion.finality_type is FinalityType.CASH_FINAL
    assert cash.assertion.confidence is None
    assert cash.assertion == direct.assertion
    assert asset.assertion is not None
    assert asset.assertion.finality_type is FinalityType.ASSET_FINAL
    assert cash.artifact_digest == digest
    assert artifact.is_submission is False
    _no_claim(cash)


def test_instructed_matched_accepted_settled_and_final_stay_distinct() -> None:
    instruction = _instruction()
    digest = instruction_artifact_digest(emit_instruction_artifact(instruction))
    receipt = _receipt(instruction, digest)
    instructed = _join(instruction, (receipt,), absent_readback())
    matched = _join(
        instruction,
        (receipt,),
        ingest_readback(_report(status="RCVD"), (instruction,)),
    )
    accepted = _join(
        instruction,
        (receipt,),
        ingest_readback(_report(status="ACTC"), (instruction,)),
    )
    settled = _join(
        instruction,
        (receipt,),
        ingest_readback(_report(echoed="1.00"), (instruction,)),
    )
    final = _join(instruction, (receipt,), ingest_readback(_report(), (instruction,)))
    assert instructed.stage is JoinedStage.INSTRUCTED
    assert instructed.disposition is Disposition.INDETERMINATE
    assert instructed.assertion is None
    assert matched.stage is JoinedStage.MATCHED
    assert matched.disposition is Disposition.HOLD
    assert accepted.stage is JoinedStage.ACCEPTED
    assert accepted.disposition is Disposition.HOLD
    assert settled.stage is JoinedStage.SETTLED
    assert settled.disposition is Disposition.HOLD
    assert settled.assertion is None
    assert final.stage is JoinedStage.FINAL
    assert final.disposition is Disposition.PASS
    assert len({item.stage for item in (instructed, matched, accepted, settled, final)}) == 5
    for item in (instructed, matched, accepted, settled, final):
        _no_claim(item)


def test_a_missing_or_wrong_receipt_does_not_publish_finality() -> None:
    instruction = _instruction()
    digest = instruction_artifact_digest(emit_instruction_artifact(instruction))
    match = ingest_readback(_report(), (instruction,))
    missing = _join(instruction, (), match)
    stale = _join(
        instruction,
        (_receipt(instruction, digest, observation_time=T0 - timedelta(minutes=1)),),
        match,
    )
    other = _join(
        instruction,
        (_receipt(instruction, digest, artifact_digest="sha256:" + "cd" * 32),),
        match,
    )
    tampered = emit_instruction_artifact(instruction)
    broken = replace(tampered, document_xml=tampered.document_xml + b" ")
    wrong_artifact = join_settlement_evidence(
        broken,
        instruction,
        (_receipt(instruction, digest),),
        match,
        match.report.entries[0],
        leg="cash",
        governing_rule_set="synthetic-readback/0.1",
        authoritative_actor=ACTOR,
        authoritative_event_id=FINALITY_EVENT,
        effective_time=T0,
        observation_time=OBSERVED,
        evidence_reference="STS-9001",
        conditionality_status=ConditionalityStatus.UNCONDITIONAL,
        revocability_status=RevocabilityStatus.IRREVOCABLE,
        provenance=Provenance.FACT_SYNTHETIC,
    )
    assert missing.stage is not JoinedStage.FINAL
    assert missing.disposition is Disposition.INDETERMINATE
    assert missing.assertion is None
    assert stale.disposition is Disposition.HOLD
    assert stale.assertion is None
    assert other.disposition is Disposition.HOLD
    assert other.assertion is None
    assert wrong_artifact.disposition is not Disposition.PASS
    assert wrong_artifact.assertion is None
    for item in (missing, stale, other, wrong_artifact):
        _no_claim(item)


def test_contradictory_identities_hold() -> None:
    instruction = _instruction()
    digest = instruction_artifact_digest(emit_instruction_artifact(instruction))
    match = ingest_readback(_report(), (instruction,))
    other_receipt = _join(
        instruction,
        (_receipt(instruction, digest, end_to_end_id="E2E-009", event_id=OTHER_EVENT),),
        match,
    )
    other_message = _join(
        instruction,
        (_receipt(instruction, digest),),
        ingest_readback(_report(original_message_id="MSG-009"), (instruction,)),
    )
    assert other_receipt.disposition is Disposition.HOLD
    assert other_receipt.assertion is None
    assert other_message.disposition is Disposition.HOLD
    assert other_message.assertion is None
    _no_claim(other_receipt)
    _no_claim(other_message)


def test_a_clearing_submission_is_not_a_settlement_instruction() -> None:
    instruction = _instruction()
    digest = instruction_artifact_digest(emit_instruction_artifact(instruction))
    clearing = _receipt(instruction, digest, action=ExternalAction.CLEARING_SUBMISSION)
    absent = _join(instruction, (clearing,), absent_readback())
    settled = _join(instruction, (clearing,), ingest_readback(_report(), (instruction,)))
    assert absent.stage is JoinedStage.UNREAD
    assert absent.disposition is Disposition.INDETERMINATE
    assert settled.stage is not JoinedStage.FINAL
    assert settled.assertion is None
    assert settled.disposition is Disposition.INDETERMINATE
    _no_claim(absent)
    _no_claim(settled)


def test_refusal_is_not_final_and_an_unread_source_is_not_a_pass() -> None:
    instruction = _instruction()
    digest = instruction_artifact_digest(emit_instruction_artifact(instruction))
    receipt = _receipt(instruction, digest)
    refused = _join(
        instruction,
        (receipt,),
        ingest_readback(_report(status="RJCT"), (instruction,)),
    )
    unread = _join(instruction, (), absent_readback())
    assert refused.stage is JoinedStage.REFUSED
    assert refused.disposition is Disposition.HOLD
    assert refused.assertion is None
    assert unread.stage is JoinedStage.UNREAD
    assert unread.disposition is Disposition.INDETERMINATE
    assert unread.assertion is None
    _no_claim(refused)
    _no_claim(unread)
