"""Authoritative settled readback is the only source of finality.

Every scenario below runs the real readback engine and the adapter in one
execution. A hand-built status is not the proof. Asset-final and cash-final
evidence appear only when that engine says the entry settled and nothing
contradicts it.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.finality import (
    ConditionalityStatus,
    FinalityAssertion,
    FinalityType,
    RevocabilityStatus,
)
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance
from lxml import etree
from pydantic import ValidationError

from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.finality_evidence import (
    EvidenceState,
    FinalityEvidence,
    finality_from_readback,
)
from atreides.messaging.readback import (
    ReadbackBreak,
    ReadbackBreakCode,
    ReadbackMatch,
    SettlementStatus,
    StatusEntry,
    StatusReport,
    absent_readback,
    ingest_readback,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "iso20022"
NS = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16"
T0 = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
OBSERVED = T0 + timedelta(hours=1)
EVENT = EventId("evt_" + "6" * 26)
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "6" * 26),
    actor_kind=ActorKind.EXTERNAL_EMULATOR,
    role="synthetic-venue",
    entitlement_refs=(),
    authenticated=True,
)
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
    status: str | None = "ACSC",
    end_to_end_id: str | None = "E2E-001",
    echoed_amount: str | None = None,
) -> str:
    parts = ["    <TxInfAndSts>"]
    if end_to_end_id is not None:
        parts.append(f"      <OrgnlEndToEndId>{end_to_end_id}</OrgnlEndToEndId>")
    parts.append("      <OrgnlTxId>TX-001</OrgnlTxId>")
    if status is not None:
        parts.append(f"      <TxSts>{status}</TxSts>")
    if echoed_amount is not None:
        parts.append(
            "      <OrgnlTxRef>"
            f'<IntrBkSttlmAmt Ccy="USD">{echoed_amount}</IntrBkSttlmAmt>'
            "</OrgnlTxRef>"
        )
    parts.append("    </TxInfAndSts>")
    return "\n".join(parts)


def _report(*, tx_blocks: str | None = None) -> bytes:
    body = tx_blocks if tx_blocks is not None else _tx_block()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Document xmlns="{NS}">\n'
        "  <FIToFIPmtStsRpt>\n"
        "    <GrpHdr>\n"
        "      <MsgId>STS-9001</MsgId>\n"
        "      <CreDtTm>2026-08-14T13:00:00Z</CreDtTm>\n"
        "    </GrpHdr>\n"
        "    <OrgnlGrpInfAndSts>\n"
        "      <OrgnlMsgId>MSG-001</OrgnlMsgId>\n"
        "      <OrgnlMsgNmId>pacs.009.001.13</OrgnlMsgNmId>\n"
        "    </OrgnlGrpInfAndSts>\n"
        f"{body}\n"
        "  </FIToFIPmtStsRpt>\n"
        "</Document>\n"
    )
    return xml.encode("utf-8")


def _grade(
    match: ReadbackMatch,
    entry: StatusEntry | None,
    **overrides: object,
) -> FinalityEvidence:
    fields: dict[str, object] = {
        "leg": "cash",
        "governing_rule_set": "synthetic-readback/0.1",
        "authoritative_actor": ACTOR,
        "authoritative_event_id": EVENT,
        "effective_time": T0,
        "observation_time": OBSERVED,
        "evidence_reference": "STS-9001",
        "conditionality_status": ConditionalityStatus.UNCONDITIONAL,
        "revocability_status": RevocabilityStatus.IRREVOCABLE,
        "provenance": Provenance.FACT_SYNTHETIC,
    }
    fields.update(overrides)
    return finality_from_readback(match, entry, **fields)  # type: ignore[arg-type]


def _settled() -> tuple[ReadbackMatch, StatusEntry]:
    match = ingest_readback(_report(), (_instruction(),))
    return match, match.report.entries[0]


def _no_claim(evidence: FinalityEvidence) -> None:
    text = evidence.reason.casefold()
    for word in _FORBIDDEN:
        assert word not in text


def test_the_settled_scenario_is_a_schema_valid_status_report() -> None:
    schema = etree.XMLSchema(etree.parse(str(FIXTURES / "pacs.002.001.16.xsd")))
    document = etree.fromstring(_report())
    assert schema.validate(document), str(schema.error_log)


def test_settled_readback_emits_cash_final_and_asset_final() -> None:
    match, entry = _settled()
    assert entry.status is SettlementStatus.SETTLED
    assert not match.breaks
    cash = _grade(match, entry)
    asset = _grade(match, entry, leg="asset")
    external = _grade(match, entry, provenance=Provenance.FACT_EXTERNAL)
    same_time = _grade(match, entry, observation_time=T0)
    for evidence, finality_type in (
        (cash, FinalityType.CASH_FINAL),
        (asset, FinalityType.ASSET_FINAL),
        (external, FinalityType.CASH_FINAL),
        (same_time, FinalityType.CASH_FINAL),
    ):
        assert evidence.state is EvidenceState.FINAL
        assert evidence.disposition is Disposition.PASS
        assert evidence.assertion is not None
        assert evidence.assertion.finality_type is finality_type
        assert evidence.assertion.confidence is None
        _no_claim(evidence)
    assert cash.assertion is not None
    assert cash.assertion.governing_rule_set == "synthetic-readback/0.1"
    assert cash.assertion.authoritative_actor == ACTOR
    assert cash.assertion.authoritative_event_id == EVENT
    assert cash.assertion.effective_time == T0
    assert cash.assertion.observation_time == OBSERVED
    assert cash.assertion.evidence_reference == "STS-9001"
    assert cash.assertion.conditionality_status is ConditionalityStatus.UNCONDITIONAL
    assert cash.assertion.revocability_status is RevocabilityStatus.IRREVOCABLE
    assert cash.assertion.provenance is Provenance.FACT_SYNTHETIC
    assert external.assertion is not None
    assert external.assertion.provenance is Provenance.FACT_EXTERNAL
    assert asset.leg == "asset"
    assert cash.state is not EvidenceState.SETTLED


@pytest.mark.parametrize(
    ("code", "state"),
    [
        ("RCVD", EvidenceState.MATCHED),
        ("ACTC", EvidenceState.ACCEPTED),
        ("ACCP", EvidenceState.ACCEPTED),
        ("ACSP", EvidenceState.ACCEPTED),
        ("PDNG", EvidenceState.ACCEPTED),
        ("ACWP", EvidenceState.ACCEPTED),
        ("ACWC", EvidenceState.ACCEPTED),
        ("RJCT", EvidenceState.REFUSED),
        ("CANC", EvidenceState.REFUSED),
    ],
)
def test_earlier_statuses_do_not_emit_finality(code: str, state: EvidenceState) -> None:
    match = ingest_readback(_report(tx_blocks=_tx_block(status=code)), (_instruction(),))
    evidence = _grade(match, match.report.entries[0])
    assert evidence.state is state
    assert evidence.disposition is Disposition.HOLD
    assert evidence.assertion is None
    assert evidence.state is not EvidenceState.FINAL
    _no_claim(evidence)


def test_received_accepted_and_settled_are_distinct_states() -> None:
    received = ingest_readback(_report(tx_blocks=_tx_block(status="RCVD")), (_instruction(),))
    accepted = ingest_readback(_report(tx_blocks=_tx_block(status="ACTC")), (_instruction(),))
    settled, entry = _settled()
    received_state = _grade(received, received.report.entries[0]).state
    accepted_state = _grade(accepted, accepted.report.entries[0]).state
    settled_state = _grade(settled, entry).state
    assert received_state is EvidenceState.MATCHED
    assert accepted_state is EvidenceState.ACCEPTED
    assert settled_state is EvidenceState.FINAL
    assert len({received_state, accepted_state, settled_state}) == 3


def test_absent_unknown_and_disagreement_do_not_pass() -> None:
    settled, entry = _settled()
    absent = _grade(
        absent_readback(),
        StatusEntry(status_code="ACSC", status=SettlementStatus.SETTLED, end_to_end_id="E2E-001"),
    )
    missing = _grade(settled, None)
    not_in_report = _grade(settled, replace(entry, end_to_end_id="E2E-OTHER"))
    unknown = ingest_readback(_report(tx_blocks=_tx_block(status="ZZZZ")), (_instruction(),))
    unrecognised = _grade(unknown, unknown.report.entries[0])
    conflict = ReadbackMatch(
        report=settled.report,
        matched={entry.end_to_end_id: SettlementStatus.RECEIVED},
        breaks=(),
        is_absent=False,
    )
    disagreed = _grade(conflict, entry)
    for evidence in (absent, missing, not_in_report, unrecognised, disagreed):
        assert evidence.disposition is Disposition.INDETERMINATE
        assert evidence.assertion is None
        assert evidence.state is not EvidenceState.FINAL
        _no_claim(evidence)
    assert unrecognised.state is EvidenceState.UNREAD
    assert unknown.report.entries[0].status is SettlementStatus.UNRECOGNIZED


def test_an_unmatched_identity_is_indeterminate() -> None:
    nameless = StatusEntry(status_code="ACSC", status=SettlementStatus.SETTLED)
    named = StatusEntry(
        status_code="ACSC",
        status=SettlementStatus.SETTLED,
        end_to_end_id="E2E-001",
    )
    for entry in (nameless, named):
        report = StatusReport(
            message_id="STS-9001",
            created_at="2026-08-14T13:00:00Z",
            namespace=NS,
            original_message_id="MSG-001",
            original_message_name_id=None,
            group_status_code=None,
            entries=(entry,),
        )
        match = ReadbackMatch(report=report, matched={}, breaks=(), is_absent=False)
        evidence = _grade(match, entry)
        assert evidence.disposition is Disposition.INDETERMINATE
        assert evidence.assertion is None


def test_a_break_on_the_settled_entry_holds_and_another_entry_does_not() -> None:
    mismatched = ingest_readback(
        _report(tx_blocks=_tx_block(status="ACSC", echoed_amount="1.00")),
        (_instruction(),),
    )
    held = _grade(mismatched, mismatched.report.entries[0])
    assert any(item.code is ReadbackBreakCode.AMOUNT_MISMATCH for item in mismatched.breaks)
    assert held.state is EvidenceState.SETTLED
    assert held.disposition is Disposition.HOLD
    assert held.assertion is None
    clean, entry = _settled()
    other_payment = ReadbackMatch(
        report=clean.report,
        matched=dict(clean.matched),
        breaks=(
            ReadbackBreak(
                ReadbackBreakCode.UNSOLICITED_STATUS,
                "status for a different payment",
                end_to_end_id="E2E-999",
            ),
        ),
        is_absent=False,
    )
    still_final = _grade(other_payment, entry)
    assert still_final.state is EvidenceState.FINAL
    assert still_final.assertion is not None


def test_non_fact_provenance_does_not_emit() -> None:
    match, entry = _settled()
    for provenance in (Provenance.FORECAST, Provenance.POLICY_RESULT, Provenance.HUMAN_JUDGMENT):
        evidence = _grade(match, entry, provenance=provenance)
        assert evidence.state is EvidenceState.SETTLED
        assert evidence.disposition is Disposition.INDETERMINATE
        assert evidence.assertion is None


def test_a_stale_fact_holds_and_an_unusable_clock_is_indeterminate() -> None:
    match, entry = _settled()
    stale = _grade(match, entry, observation_time=T0 - timedelta(seconds=1))
    assert stale.state is EvidenceState.SETTLED
    assert stale.disposition is Disposition.HOLD
    assert stale.assertion is None
    unusable = (
        _grade(match, entry, effective_time=None),
        _grade(match, entry, observation_time=None),
        _grade(match, entry, effective_time=datetime(2026, 8, 14, 12, 0)),
        _grade(match, entry, observation_time=datetime(2026, 8, 14, 13, 0)),
        _grade(
            match,
            entry,
            effective_time=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=-4))),
        ),
        _grade(
            match,
            entry,
            observation_time=datetime(2026, 8, 14, 13, 0, tzinfo=timezone(timedelta(hours=-4))),
        ),
    )
    for evidence in unusable:
        assert evidence.state is EvidenceState.SETTLED
        assert evidence.disposition is Disposition.INDETERMINATE
        assert evidence.assertion is None


def test_missing_or_illegal_kernel_fields_do_not_pass() -> None:
    match, entry = _settled()
    for overrides in (
        {"governing_rule_set": ""},
        {"governing_rule_set": None},
        {"evidence_reference": ""},
        {"evidence_reference": None},
        {"conditionality_status": "NOT_A_STATUS"},
    ):
        evidence = _grade(match, entry, **overrides)
        assert evidence.state is EvidenceState.SETTLED
        assert evidence.disposition is Disposition.INDETERMINATE
        assert evidence.assertion is None


def test_evidence_cannot_pass_without_a_matching_assertion() -> None:
    assertion = _grade(*_settled()).assertion
    assert assertion is not None
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.FINAL,
            disposition=Disposition.PASS,
            reason="missing the assertion",
            leg="cash",
        )
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.SETTLED,
            disposition=Disposition.PASS,
            reason="settled is not final",
            leg="cash",
        )
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.FINAL,
            disposition=Disposition.HOLD,
            reason="a hold cannot carry finality",
            leg="cash",
            assertion=assertion,
        )
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.MATCHED,
            disposition=Disposition.HOLD,
            reason="an earlier state cannot carry an assertion",
            leg="cash",
            assertion=assertion,
        )
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.FINAL,
            disposition=Disposition.PASS,
            reason="the leg and the type disagree",
            leg="asset",
            assertion=assertion,
        )
    judged = FinalityAssertion(
        finality_type=FinalityType.CASH_FINAL,
        governing_rule_set="synthetic-readback/0.1",
        authoritative_actor=ACTOR,
        authoritative_event_id=EVENT,
        effective_time=T0,
        observation_time=OBSERVED,
        evidence_reference="STS-9001",
        conditionality_status=ConditionalityStatus.UNKNOWN,
        revocability_status=RevocabilityStatus.UNKNOWN,
        provenance=Provenance.HUMAN_JUDGMENT,
        confidence=Decimal("1"),
    )
    with pytest.raises(ValidationError):
        FinalityEvidence(
            state=EvidenceState.FINAL,
            disposition=Disposition.PASS,
            reason="a confidence would make the fact look inferred",
            leg="cash",
            assertion=judged,
        )
