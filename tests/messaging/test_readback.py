"""Tests for readback ingest.

The load-bearing assertion in this file is that silence is not rejection.
Everything else supports it.

Fixtures are built here and validated against the published
``pacs.002.001.16`` XSD, so the parser is exercised against documents a venue
could actually send rather than against strings shaped to match the parser.
That matters more than usual here: the whole point of the module is that
schema validity is a floor, and demonstrating the gap requires messages that
really are schema-valid.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from lxml import etree

import atreides.messaging.readback as readback_module
from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.readback import (
    RECOGNISED_STATUS_CODES,
    ReadbackBreakCode,
    ReadbackParseError,
    SettlementStatus,
    absent_readback,
    classify_status_code,
    ingest_readback,
    parse_status_report,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "iso20022"
NS = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16"

D = Decimal


def _schema(name: str) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(FIXTURES / f"{name}.xsd")))


def _instruction(
    *,
    message_id: str = "MSG-001",
    end_to_end_id: str = "E2E-001",
    amount: Decimal = Decimal("1000000.00"),
    currency: str = "USD",
) -> CashLegInstruction:
    fi = FinancialInstitution(bicfi="AAAAUS33XXX")
    return CashLegInstruction(
        message_id=message_id,
        end_to_end_id=end_to_end_id,
        created_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        amount=amount,
        currency=currency,
        debtor=fi,
        creditor=FinancialInstitution(bicfi="BBBBUS33XXX"),
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=fi,
        receiver=FinancialInstitution(bicfi="BBBBUS33XXX"),
    )


def _tx_block(
    *,
    status: str | None = "ACSC",
    end_to_end_id: str | None = "E2E-001",
    tx_id: str | None = "TX-001",
    reason: str | None = None,
    echoed_amount: str | None = None,
    echoed_currency: str = "USD",
) -> str:
    parts = ["    <TxInfAndSts>"]
    if end_to_end_id is not None:
        parts.append(f"      <OrgnlEndToEndId>{end_to_end_id}</OrgnlEndToEndId>")
    if tx_id is not None:
        parts.append(f"      <OrgnlTxId>{tx_id}</OrgnlTxId>")
    if status is not None:
        parts.append(f"      <TxSts>{status}</TxSts>")
    if reason is not None:
        parts.append(
            "      <StsRsnInf>"
            f"<Rsn><Cd>{reason}</Cd></Rsn>"
            "</StsRsnInf>"
        )
    if echoed_amount is not None:
        parts.append(
            "      <OrgnlTxRef>"
            f'<IntrBkSttlmAmt Ccy="{echoed_currency}">{echoed_amount}</IntrBkSttlmAmt>'
            "</OrgnlTxRef>"
        )
    parts.append("    </TxInfAndSts>")
    return "\n".join(parts)


def _report(
    *,
    original_message_id: str | None = "MSG-001",
    namespace: str = NS,
    tx_blocks: str | None = None,
    group_status: str | None = None,
) -> bytes:
    grp = ""
    if original_message_id is not None:
        grp = (
            "    <OrgnlGrpInfAndSts>\n"
            f"      <OrgnlMsgId>{original_message_id}</OrgnlMsgId>\n"
            "      <OrgnlMsgNmId>pacs.009.001.13</OrgnlMsgNmId>\n"
            + (f"      <GrpSts>{group_status}</GrpSts>\n" if group_status else "")
            + "    </OrgnlGrpInfAndSts>\n"
        )
    body = tx_blocks if tx_blocks is not None else _tx_block()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Document xmlns="{namespace}">\n'
        "  <FIToFIPmtStsRpt>\n"
        "    <GrpHdr>\n"
        "      <MsgId>STS-9001</MsgId>\n"
        "      <CreDtTm>2026-08-14T13:00:00Z</CreDtTm>\n"
        "    </GrpHdr>\n"
        f"{grp}"
        f"{body}\n"
        "  </FIToFIPmtStsRpt>\n"
        "</Document>\n"
    )
    return xml.encode("utf-8")


# ---------------------------------------------------------------------------
# The fixtures are real messages
# ---------------------------------------------------------------------------


class TestFixturesAreSchemaValid:
    """If these fail, every other test in this file is testing a fiction."""

    def test_settled_report_validates_against_the_published_xsd(self) -> None:
        schema = _schema("pacs.002.001.16")
        doc = etree.fromstring(_report())
        assert schema.validate(doc), str(schema.error_log)

    def test_report_with_no_status_code_is_still_schema_valid(self) -> None:
        """The gap this module exists to close.

        Every child of PaymentTransaction177 is optional, so a status report
        with no status passes the schema. Schema validity is a floor, not an
        acceptance criterion.
        """
        schema = _schema("pacs.002.001.16")
        doc = etree.fromstring(_report(tx_blocks=_tx_block(status=None)))
        assert schema.validate(doc), str(schema.error_log)

    def test_report_with_no_identifiers_is_still_schema_valid(self) -> None:
        schema = _schema("pacs.002.001.16")
        doc = etree.fromstring(
            _report(tx_blocks=_tx_block(end_to_end_id=None, tx_id=None))
        )
        assert schema.validate(doc), str(schema.error_log)


# ---------------------------------------------------------------------------
# Parsing refuses what the business cannot use
# ---------------------------------------------------------------------------


def test_a_usable_report_parses() -> None:
    report = parse_status_report(_report())
    assert report.message_id == "STS-9001"
    assert report.original_message_id == "MSG-001"
    assert len(report.entries) == 1
    assert report.entries[0].status is SettlementStatus.SETTLED


def test_entry_without_a_status_code_is_collected_not_raised() -> None:
    """Schema-valid and unusable: a status report with no status is not a
    report about anything. That is an entry-level problem, so it is collected
    rather than raised - see the partial-batch tests below for why."""
    report = parse_status_report(_report(tx_blocks=_tx_block(status=None)))
    assert report.entries == ()
    assert len(report.malformed) == 1
    assert "carries no TxSts" in report.malformed[0].reason


def test_entry_without_any_identifier_is_collected_not_raised() -> None:
    report = parse_status_report(
        _report(tx_blocks=_tx_block(end_to_end_id=None, tx_id=None))
    )
    assert report.entries == ()
    assert "no original identifier" in report.malformed[0].reason


def test_a_different_message_definition_is_refused_by_namespace() -> None:
    """A pacs.008 in a pacs.002 slot is refused rather than parsed for
    whatever happens to match. The namespace check now runs against the
    payload rather than the root, and still refuses."""
    with pytest.raises(ReadbackParseError, match=r"not a pacs\.002 namespace"):
        parse_status_report(
            _report(namespace="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.14")
        )


def test_namespace_is_read_from_the_document_not_assumed() -> None:
    """A venue on a different minor version is a parse question, not a
    silent zero-match."""
    other = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10"
    report = parse_status_report(_report(namespace=other))
    assert report.namespace == other
    assert len(report.entries) == 1


def test_malformed_xml_is_refused() -> None:
    with pytest.raises(ReadbackParseError, match="not well-formed"):
        parse_status_report(b"<Document>")


def test_a_document_with_no_status_report_in_it_is_refused() -> None:
    """Refused by the absence of the payload, not by the shape of whatever
    wraps it."""
    with pytest.raises(ReadbackParseError, match="not a payment status report"):
        parse_status_report(f'<Document xmlns="{NS}"><Nothing/></Document>'.encode())


def test_group_header_must_carry_its_identifiers() -> None:
    xml = (
        f'<Document xmlns="{NS}"><FIToFIPmtStsRpt><GrpHdr>'
        "<MsgId>X</MsgId></GrpHdr></FIToFIPmtStsRpt></Document>"
    )
    with pytest.raises(ReadbackParseError, match="MsgId and CreDtTm"):
        parse_status_report(xml.encode())


def test_a_report_with_no_transactions_parses_to_no_entries() -> None:
    """A group-level-only acknowledgement is a real message shape and is not
    an error. It simply establishes nothing per transaction."""
    report = parse_status_report(_report(tx_blocks="", group_status="ACTC"))
    assert report.entries == ()
    assert report.group_status_code == "ACTC"


# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(RECOGNISED_STATUS_CODES))
def test_every_recognised_code_classifies(code: str) -> None:
    status = classify_status_code(code)
    assert status is not SettlementStatus.UNRECOGNIZED


def test_an_unknown_code_classifies_rather_than_raising() -> None:
    """An unknown code is a finding about a payment, and the payment still
    needs a record."""
    assert classify_status_code("ZZZZ") is SettlementStatus.UNRECOGNIZED


def test_an_unknown_code_produces_a_break() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="ZZZZ")), (_instruction(),)
    )
    assert [b.code for b in match.breaks] == [
        ReadbackBreakCode.UNRECOGNIZED_STATUS_CODE
    ]
    assert match.clean is False


def test_accepted_not_posted_is_not_folded_into_settled() -> None:
    """It looks settled and is not. An operator reading "accepted" and acting
    as though the money moved has taken a position the record does not
    support."""
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="ACWP")), (_instruction(),)
    )
    assert match.matched["E2E-001"] is SettlementStatus.ACCEPTED_NOT_POSTED
    assert match.settled_ids == ()


def test_accepted_with_change_is_always_a_break() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="ACWC")), (_instruction(),)
    )
    assert ReadbackBreakCode.ACCEPTED_WITH_CHANGE in {b.code for b in match.breaks}


def test_rejection_is_a_break_and_carries_the_reason() -> None:
    """An instruction that passed every gate and did not settle is an event
    the record must carry, not a quiet terminal state."""
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="RJCT", reason="AM04")),
        (_instruction(),),
    )
    (found,) = [b for b in match.breaks if b.code is ReadbackBreakCode.REJECTED]
    assert "AM04" in found.detail


def test_rejection_without_a_reason_code_still_records_the_absence() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="RJCT")), (_instruction(),)
    )
    (found,) = [b for b in match.breaks if b.code is ReadbackBreakCode.REJECTED]
    assert "no reason code supplied" in found.detail


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_a_clean_settlement_matches_and_breaks_nothing() -> None:
    match = ingest_readback(_report(), (_instruction(),))
    assert match.clean is True
    assert match.settled_ids == ("E2E-001",)


def test_unsolicited_status_breaks_and_does_not_match() -> None:
    """Atreides never submits, so a status for an instruction it never
    prepared is either a venue misroute or a payment that left the firm
    outside the governed path."""
    match = ingest_readback(
        _report(
            original_message_id=None,
            tx_blocks=_tx_block(end_to_end_id="E2E-GHOST"),
        ),
        (_instruction(),),
    )
    (found,) = match.breaks
    assert found.code is ReadbackBreakCode.UNSOLICITED_STATUS
    assert "outside the governed path" in found.detail
    assert match.matched == {}


def test_identifier_disagreement_breaks_and_the_framework_does_not_choose() -> None:
    """Silently preferring one key is how a system acknowledges the wrong
    payment."""
    a = _instruction(message_id="MSG-A", end_to_end_id="E2E-A")
    b = _instruction(message_id="MSG-B", end_to_end_id="E2E-B")
    match = ingest_readback(
        _report(
            original_message_id="MSG-B",
            tx_blocks=_tx_block(end_to_end_id="E2E-A"),
        ),
        (a, b),
    )
    (found,) = match.breaks
    assert found.code is ReadbackBreakCode.IDENTIFIER_DISAGREEMENT
    assert "MSG-A" in found.detail
    assert "MSG-B" in found.detail
    assert match.matched == {}


def test_agreement_across_both_identifiers_is_the_match() -> None:
    a = _instruction(message_id="MSG-A", end_to_end_id="E2E-A")
    b = _instruction(message_id="MSG-B", end_to_end_id="E2E-B")
    match = ingest_readback(
        _report(original_message_id="MSG-A", tx_blocks=_tx_block(end_to_end_id="E2E-A")),
        (a, b),
    )
    assert match.clean is True
    assert match.matched == {"E2E-A": SettlementStatus.SETTLED}


def test_entry_with_only_a_transaction_id_cannot_be_matched_in_this_revision() -> None:
    """OrgnlTxId and OrgnlUETR are recorded and not used to match. Recording
    the limit as a break beats matching on a key with no evidence behind
    it."""
    match = ingest_readback(
        _report(tx_blocks=_tx_block(end_to_end_id=None)), (_instruction(),)
    )
    assert [b.code for b in match.breaks] == [
        ReadbackBreakCode.MALFORMED_STATUS_ENTRY
    ]


# ---------------------------------------------------------------------------
# Echoed values
# ---------------------------------------------------------------------------


def test_amount_mismatch_is_detected() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(echoed_amount="999999.00")), (_instruction(),)
    )
    (found,) = [b for b in match.breaks if b.code is ReadbackBreakCode.AMOUNT_MISMATCH]
    assert "999999.00" in found.detail


def test_matching_amount_breaks_nothing() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(echoed_amount="1000000.00")), (_instruction(),)
    )
    assert match.clean is True


def test_currency_mismatch_is_detected() -> None:
    match = ingest_readback(
        _report(
            tx_blocks=_tx_block(echoed_amount="1000000.00", echoed_currency="EUR")
        ),
        (_instruction(),),
    )
    assert ReadbackBreakCode.CURRENCY_MISMATCH in {b.code for b in match.breaks}


def test_an_unechoed_amount_is_not_a_mismatch() -> None:
    """Absence of an echo is not a disagreement."""
    match = ingest_readback(_report(), (_instruction(),))
    assert ReadbackBreakCode.AMOUNT_MISMATCH not in {b.code for b in match.breaks}


# ---------------------------------------------------------------------------
# Progression and regression
# ---------------------------------------------------------------------------


def test_forward_progression_breaks_nothing() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="ACSC")),
        (_instruction(),),
        {"E2E-001": SettlementStatus.IN_PROGRESS},
    )
    assert match.clean is True


def test_an_identical_repeated_status_is_idempotent() -> None:
    """Venues resend."""
    match = ingest_readback(
        _report(), (_instruction(),), {"E2E-001": SettlementStatus.SETTLED}
    )
    assert match.clean is True


def test_regression_from_settled_is_a_break() -> None:
    """A settlement the record shows as complete is being reported as not
    complete."""
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="RJCT")),
        (_instruction(),),
        {"E2E-001": SettlementStatus.SETTLED},
    )
    codes = {b.code for b in match.breaks}
    assert ReadbackBreakCode.STATUS_REGRESSION in codes


def test_backward_movement_below_settled_is_also_a_regression() -> None:
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="RCVD")),
        (_instruction(),),
        {"E2E-001": SettlementStatus.IN_PROGRESS},
    )
    assert ReadbackBreakCode.STATUS_REGRESSION in {b.code for b in match.breaks}


def test_two_terminal_statuses_are_a_conflict_not_a_regression() -> None:
    """A conflict is usually a duplicate or crossed message; a regression is
    usually real. The remedy differs, so the codes differ."""
    match = ingest_readback(
        _report(tx_blocks=_tx_block(status="CANC")),
        (_instruction(),),
        {"E2E-001": SettlementStatus.REJECTED},
    )
    codes = {b.code for b in match.breaks}
    assert ReadbackBreakCode.STATUS_CONFLICT in codes
    assert ReadbackBreakCode.STATUS_REGRESSION not in codes


# ---------------------------------------------------------------------------
# Silence is not rejection
# ---------------------------------------------------------------------------


def test_absent_readback_establishes_nothing() -> None:
    m = absent_readback()
    assert m.is_absent is True
    assert m.matched == {}
    assert m.clean is False


def test_absent_readback_is_never_a_rejection() -> None:
    """The load-bearing assertion. Treating an unacknowledged instruction as
    failed and re-issuing it is the mechanism that produces duplicate
    payments on a gross-final rail."""
    m = absent_readback()
    assert ReadbackBreakCode.REJECTED not in {b.code for b in m.breaks}
    assert m.settled_ids == ()
    assert "not settlement, not rejection" in m.breaks[0].detail


def test_absent_readback_carries_its_reason() -> None:
    m = absent_readback("operator has not yet retrieved the venue portal file")
    assert "portal file" in m.breaks[0].detail


def test_absent_readback_has_its_own_code() -> None:
    """Nothing came back is not a defect in a message. It is the absence of
    one, and it is distinct from every other code because there is no venue
    assertion to disagree with."""
    assert absent_readback().breaks[0].code is ReadbackBreakCode.NO_READBACK


# ---------------------------------------------------------------------------
# Determinism and the no-submission constraint
# ---------------------------------------------------------------------------


def test_identical_bytes_produce_identical_results() -> None:
    payload = _report(tx_blocks=_tx_block(status="RJCT", reason="AM04"))
    a = ingest_readback(payload, (_instruction(),))
    b = ingest_readback(payload, (_instruction(),))
    assert a.matched == b.matched
    assert a.breaks == b.breaks


def test_multiple_entries_reconcile_independently() -> None:
    match = ingest_readback(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A", status="ACSC"),
                    _tx_block(end_to_end_id="E2E-B", status="RJCT"),
                    _tx_block(end_to_end_id="E2E-GHOST", status="ACSC"),
                ]
            ),
        ),
        (
            _instruction(message_id="MSG-A", end_to_end_id="E2E-A"),
            _instruction(message_id="MSG-B", end_to_end_id="E2E-B"),
        ),
    )
    assert match.settled_ids == ("E2E-A",)
    assert {b.code for b in match.breaks} == {
        ReadbackBreakCode.REJECTED,
        ReadbackBreakCode.UNSOLICITED_STATUS,
    }


# ---------------------------------------------------------------------------
# Deliberate absence
# ---------------------------------------------------------------------------


def test_no_function_here_resubmits() -> None:
    """Placeholder marking a deliberate absence.

    Nothing in this module re-issues an instruction on any status, and there
    is no test of one. That is the duplicate-payment interlock. A reader
    looking for automatic retry should find this note instead of a gap.
    Doctrine: CASH-001 SVII, SVIII.
    """
    assert not any(
        name.startswith(("resubmit", "retry", "reissue"))
        for name in readback_module.__all__
    )


def test_a_break_with_no_detail_is_rejected() -> None:
    from atreides.messaging.readback import ReadbackBreak

    with pytest.raises(ValueError, match="not a finding"):
        ReadbackBreak(ReadbackBreakCode.REJECTED, "")


def test_a_pacs002_namespace_with_the_wrong_body_is_refused() -> None:
    """A pacs.002 namespace on a document containing no status report is
    still not a status report. The payload decides, not the wrapper."""
    xml = f'<Document xmlns="{NS}"><SomethingElse/></Document>'
    with pytest.raises(ReadbackParseError, match="not a payment status report"):
        parse_status_report(xml.encode())


def test_an_unparseable_echoed_amount_is_recorded_as_absent() -> None:
    """The document is otherwise usable. Refusing the whole message over one
    unparseable field would be less honest than having nothing to compare."""
    bad = _tx_block().replace(
        "    </TxInfAndSts>",
        '      <OrgnlTxRef><IntrBkSttlmAmt Ccy="USD">not-a-number'
        "</IntrBkSttlmAmt></OrgnlTxRef>\n    </TxInfAndSts>",
    )
    report = parse_status_report(_report(tx_blocks=bad))
    assert report.entries[0].echoed_amount is None


def test_an_empty_original_transaction_reference_echoes_nothing() -> None:
    bad = _tx_block().replace(
        "    </TxInfAndSts>",
        "      <OrgnlTxRef/>\n    </TxInfAndSts>",
    )
    report = parse_status_report(_report(tx_blocks=bad))
    assert report.entries[0].echoed_amount is None
    assert report.entries[0].echoed_currency is None


# ---------------------------------------------------------------------------
# Partial batches - one bad record must not cost the file
# ---------------------------------------------------------------------------


def test_one_malformed_entry_does_not_cost_the_rest_of_the_file() -> None:
    """The reason the document/entry boundary exists.

    A venue file carrying a thousand statuses, one of which is malformed, is
    a file with 999 usable statuses. Raising on the first bad record would
    cost the operator the other 999, and malformed records are most likely
    precisely when volume is highest and the desk can least afford to lose
    the batch.
    """
    report = parse_status_report(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A", status="ACSC"),
                    _tx_block(end_to_end_id="E2E-BAD", status=None),
                    _tx_block(end_to_end_id="E2E-B", status="ACSC"),
                ]
            ),
        )
    )
    assert [e.end_to_end_id for e in report.entries] == ["E2E-A", "E2E-B"]
    assert len(report.malformed) == 1


def test_the_good_entries_in_a_partial_batch_still_reconcile() -> None:
    match = ingest_readback(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A", status="ACSC"),
                    _tx_block(end_to_end_id="E2E-BAD", status=None),
                    _tx_block(end_to_end_id="E2E-B", status="ACSC"),
                ]
            ),
        ),
        (
            _instruction(message_id="MSG-A", end_to_end_id="E2E-A"),
            _instruction(message_id="MSG-B", end_to_end_id="E2E-B"),
        ),
    )
    assert match.settled_ids == ("E2E-A", "E2E-B")


def test_a_malformed_entry_still_surfaces_as_a_break() -> None:
    """Collected is not forgiven. The entry did not parse and somebody has
    to know that."""
    match = ingest_readback(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A", status="ACSC"),
                    _tx_block(end_to_end_id="E2E-BAD", status=None),
                ]
            ),
        ),
        (_instruction(message_id="MSG-A", end_to_end_id="E2E-A"),),
    )
    (found,) = [
        b for b in match.breaks if b.code is ReadbackBreakCode.MALFORMED_STATUS_ENTRY
    ]
    assert "E2E-BAD" == found.end_to_end_id
    assert "the rest of the file was reconciled" in found.detail.lower()
    assert match.clean is False


def test_the_file_accounts_for_every_block_the_venue_sent() -> None:
    """A count that silently shrinks is worse than a finding."""
    report = parse_status_report(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A"),
                    _tx_block(status=None, end_to_end_id="E2E-BAD"),
                    _tx_block(end_to_end_id=None, tx_id=None),
                ]
            ),
        )
    )
    assert report.entry_count == 3
    assert len(report.entries) == 1
    assert len(report.malformed) == 2


def test_the_ordinal_locates_the_bad_record_in_the_file() -> None:
    """An operator has to find it in the original to fix it."""
    report = parse_status_report(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(
                [
                    _tx_block(end_to_end_id="E2E-A"),
                    _tx_block(end_to_end_id="E2E-B"),
                    _tx_block(end_to_end_id="E2E-BAD", status=None),
                ]
            ),
        )
    )
    assert report.malformed[0].ordinal == 2


def test_document_level_problems_still_raise() -> None:
    """A problem with the document means nothing in it can be trusted."""
    with pytest.raises(ReadbackParseError, match="not well-formed"):
        parse_status_report(b"<Document>")


def test_a_file_of_nothing_but_bad_records_parses_to_no_entries() -> None:
    """Still not an exception. The file was readable; its contents were not,
    and that is a finding about a thousand payments rather than about a
    file."""
    report = parse_status_report(
        _report(
            original_message_id=None,
            tx_blocks="\n".join(_tx_block(status=None) for _ in range(3)),
        )
    )
    assert report.entries == ()
    assert len(report.malformed) == 3


# ---------------------------------------------------------------------------
# Messages somebody else actually sent
# ---------------------------------------------------------------------------

THIRD_PARTY = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "third_party"
    / "issettled"
)


@pytest.mark.parametrize(
    "filename",
    [
        "pacs.002.001.11-payment-tdso.xml",
        "pacs.002.001.11-payment-tdsa.xml",
        "pacs.002.001.11-redeem-tdsa.xml",
    ],
)
def test_a_real_third_party_status_report_parses(filename: str) -> None:
    """These are not messages this framework would have written, which is
    the entire reason they are held.

    Each sits inside a proprietary envelope alongside a business application
    header and an XML signature. The pacs.002 payload is not the document
    root, and the payload element itself carries the envelope's namespace
    while its children carry the ISO one. The first version of this parser
    refused all three - and would have reported a conformant sender as
    non-conformant, which points an investigation at the wrong party.
    """
    report = parse_status_report((THIRD_PARTY / filename).read_bytes())
    assert report.namespace.startswith("urn:iso:std:iso:20022:tech:xsd:pacs.002")
    assert report.message_id
    assert len(report.entries) == 1
    assert report.malformed == ()


def test_a_real_status_code_classifies_without_special_casing() -> None:
    """RCVD and ACTC arrive from a live implementation and land in the
    recognised set with no per-venue handling."""
    report = parse_status_report(
        (THIRD_PARTY / "pacs.002.001.11-payment-tdso.xml").read_bytes()
    )
    assert report.entries[0].status is SettlementStatus.RECEIVED


def test_a_proprietary_reason_code_is_carried_not_interpreted() -> None:
    """The reason code in these files is a four-digit proprietary value, not
    an ISO external code. It is recorded verbatim; nothing here pretends to
    know what it means."""
    report = parse_status_report(
        (THIRD_PARTY / "pacs.002.001.11-payment-tdso.xml").read_bytes()
    )
    assert report.entries[0].reason_codes == ("0202",)


def test_an_unknown_third_party_status_is_unsolicited_not_a_parse_error() -> None:
    """A real message about an instruction this framework never prepared is
    exactly the unsolicited case, and it should reconcile to that rather
    than fail to parse."""
    match = ingest_readback(
        (THIRD_PARTY / "pacs.002.001.11-payment-tdso.xml").read_bytes(), ()
    )
    assert [b.code for b in match.breaks] == [ReadbackBreakCode.UNSOLICITED_STATUS]


def test_the_vendored_fixtures_carry_their_licence() -> None:
    """Apache 2.0 requires the notice to travel with the files."""
    assert (THIRD_PARTY / "LICENSE").exists()
    notice = (THIRD_PARTY / "NOTICE.md").read_text()
    assert "Apache License 2.0" in notice
    assert "github.com/issettled" in notice
