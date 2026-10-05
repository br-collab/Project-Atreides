"""WP-4 acceptance: the synthetic DTC ISO 20022 adapter (ORDER SC-1).

Acceptance criteria, mapped:

- Round trip passes at both pinned profile versions:
  ``test_every_family_round_trips_at_both_releases`` (22 cases) and the property
  ``test_property_announcement_terms_round_trip``.
- A message for the wrong profile version is refused:
  ``test_a_message_of_the_other_release_is_refused`` (every family, both directions) and
  ``test_a_message_of_another_family_is_refused``.
- Synthetic output uses ``Provenance.FACT_SYNTHETIC``; external facts use ``FACT_EXTERNAL``
  and name their source: ``test_emitted_messages_are_synthetic_and_name_the_adapter`` and
  ``test_a_decoded_message_carries_the_provenance_its_reader_states``.
- Every source records URL, retrieval date and SHA-256: ``test_every_pinned_source_*``.
- Honest validation: structural checks run in CI; the XSD check
  ``test_every_emitted_message_is_valid_against_dtc_xsds`` runs only where DTC's XSDs have
  been downloaded and ``DTC_CA_XSD_DIR`` points at them. In CI it is skipped, and a skip
  is not a pass.

Every event, account and balance below is SYNTHETIC.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cannae_kernel.provenance import Provenance
from hypothesis import given
from hypothesis import strategies as st

import atreides.corporate_actions.iso20022 as adapter_module
from atreides.corporate_actions import (
    DTC_PACKAGES,
    DTC_XSDS,
    PROFILES,
    AdapterRefusalError,
    AdapterRefusalReason,
    CashMovement,
    CorporateActionEvent,
    ElectionInstruction,
    ElectionOption,
    EncodedMessage,
    EventDates,
    EventTerms,
    EventType,
    MessageFamily,
    MovementBalances,
    MovementReport,
    OptionType,
    Participation,
    Release,
    SecuritiesMovement,
    SourceIdentity,
    decode_announcement,
    decode_instruction,
    decode_movement,
    encode_announcement,
    encode_instruction,
    encode_movement,
)
from atreides.corporate_actions import dtc_sources as sources_module

D = Decimal
ISIN = "USSYNTHETIC0"
ADAPTER = SourceIdentity(source_id="synthetic-dtc-iso20022-adapter")
DTC = SourceIdentity(source_id="DTC", reference="SYNTHETIC-DTC-MSG-1")
OPTIONS = (
    ElectionOption(option_id="001", description="SYNTHETIC cash", option_type=OptionType.CASH),
    ElectionOption(option_id="002", description="SYNTHETIC no action",
                   option_type=OptionType.NOAC),
)
REPO = Path(__file__).resolve().parents[2]


def event(
    event_type: EventType = EventType.CASH_DIVIDEND,
    participation: Participation = Participation.MANDATORY,
    terms: EventTerms | None = None,
    **changes: Any,
) -> CorporateActionEvent:
    elective = participation is not Participation.MANDATORY
    base: dict[str, Any] = {
        "event_id": "SYN-" + event_type.value.replace("_", "")[:8].upper(),
        "security_id": ISIN,
        "event_type": event_type,
        "participation": participation,
        "dates": EventDates(
            announcement_date=date(2026, 10, 1), record_date=date(2026, 10, 15),
            election_deadline=date(2026, 10, 20) if elective else None,
            protect_deadline=(
                date(2026, 10, 22) if participation is Participation.VOLUNTARY else None
            ),
            payable_date=date(2026, 10, 30),
        ),
        "terms": terms or EventTerms(),
        "provenance": Provenance.FACT_SYNTHETIC,
        "source": ADAPTER,
    }
    if elective:
        base |= {"options": OPTIONS, "default_option_id": "002"}
    base |= changes
    return CorporateActionEvent(**base)


CASH = EventTerms(cash_rate_per_share=D("0.25"), currency="USD")
ANNOUNCEMENTS = {
    "cash-dividend": event(terms=CASH),
    "stock-dividend": event(EventType.STOCK_DIVIDEND, terms=EventTerms(
        stock_rate_per_share=D("0.05"))),
    "split": event(EventType.SPLIT, terms=EventTerms(split_new=3, split_old=2)),
    "reverse-split": event(EventType.REVERSE_SPLIT, terms=EventTerms(split_new=1, split_old=10)),
    "merger": event(EventType.MERGER),
    "lottery-redemption": event(EventType.REDEMPTION_LOTTERY),
    "tender-offer": event(EventType.TENDER_OFFER, Participation.VOLUNTARY),
    "rights": event(EventType.RIGHTS, Participation.VOLUNTARY),
    "choice-dividend": event(EventType.CASH_DIVIDEND, Participation.MANDATORY_WITH_CHOICE),
}
CHOICE = ANNOUNCEMENTS["choice-dividend"]
INSTRUCTION = ElectionInstruction(
    instruction_id="I-1", account_id="ACCT-A", option_id="001", quantity=D("100"),
    received_date=date(2026, 10, 15), provenance=Provenance.FACT_EXTERNAL, source=DTC,
)


def movement(
    stage: str = "confirmation",
    moved: CashMovement | SecuritiesMovement | None = None,
    balances: MovementBalances | None = None,
    **changes: Any,
) -> MovementReport:
    advice = stage == "preliminary_advice"
    base: dict[str, Any] = {
        "stage": stage, "event_id": "SYN-DVCA-1", "event_type": EventType.CASH_DIVIDEND,
        "participation": Participation.MANDATORY if advice else None,
        "security_id": ISIN, "account_id": "ACCT-A", "option_id": "001",
        "option_type": OptionType.CASH, "default_option": True if advice else None,
        "balances": balances or (
            MovementBalances(eligible_balance=D(100)) if advice
            else MovementBalances(confirmed_balance=D(100))
        ),
        "movement": moved or CashMovement(amount=D("25"), currency="USD"),
        "direction": "credit", "movement_date": date(2026, 10, 30),
        "provenance": Provenance.FACT_SYNTHETIC, "source": ADAPTER,
    }
    return MovementReport(**(base | changes))


MOVEMENTS = {
    "advice-cash": movement("preliminary_advice", balances=MovementBalances(
        eligible_balance=D(100), pending_delivery_balance=D(0),
        pending_receipt_balance=D(-5), settlement_position_balance=D(100))),
    "advice-securities": movement(
        "preliminary_advice", SecuritiesMovement(security_id=ISIN, quantity=D(10)),
        MovementBalances(eligible_balance=D(200)), option_type=OptionType.SECU),
    "confirmation-cash": movement("confirmation", CashMovement(amount=D("25.5"), currency="USD"),
                                  MovementBalances(confirmed_balance=D(100),
                                                   eligible_balance=D(100),
                                                   pending_receipt_balance=D(3))),
    "confirmation-securities": movement(
        "confirmation", SecuritiesMovement(security_id=ISIN, quantity=D(10)),
        MovementBalances(confirmed_balance=D(-200)), option_type=OptionType.SECU,
        direction="debit"),
}


def roundtrip(case: str, release: Release) -> tuple[EncodedMessage, object, object]:
    if case in ANNOUNCEMENTS:
        original: object = ANNOUNCEMENTS[case]
        message = encode_announcement(ANNOUNCEMENTS[case], release)
        back: object = decode_announcement(message.xml, release,
                                           provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)
    elif case == "instruction":
        original, message = INSTRUCTION, encode_instruction(INSTRUCTION, CHOICE, release)
        back = decode_instruction(message.xml, release, event=CHOICE, instruction_id="I-1",
                                  received_date=date(2026, 10, 15),
                                  provenance=Provenance.FACT_EXTERNAL, source=DTC)
    else:
        report = MOVEMENTS[case]
        original, message = report, encode_movement(report, release)
        back = decode_movement(message.xml, release, report.stage,
                               provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)
    return message, original, back


CASES = [*ANNOUNCEMENTS, "instruction", *MOVEMENTS]


# --- round trip and version -------------------------------------------------------------------


@pytest.mark.parametrize("release", list(Release))
@pytest.mark.parametrize("case", CASES)
def test_every_family_round_trips_at_both_releases(case: str, release: Release) -> None:
    message, original, back = roundtrip(case, release)
    assert back == original
    assert message.release is release
    assert f'xmlns="urn:iso:std:iso:20022:tech:xsd:{message.message_id}"'.encode() in message.xml


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize(("written", "read"), [(Release.SR2025, Release.SR2026),
                                               (Release.SR2026, Release.SR2025)])
def test_a_message_of_the_other_release_is_refused(
    case: str, written: Release, read: Release
) -> None:
    message, *_ = roundtrip(case, written)
    with pytest.raises(AdapterRefusalError) as refused:
        if message.family is MessageFamily.ANNOUNCEMENT:
            decode_announcement(message.xml, read, provenance=Provenance.FACT_SYNTHETIC,
                                source=ADAPTER)
        elif message.family is MessageFamily.INSTRUCTION:
            decode_instruction(message.xml, read, event=CHOICE, instruction_id="I-1",
                               received_date=date(2026, 10, 15),
                               provenance=Provenance.FACT_EXTERNAL, source=DTC)
        else:
            stage = MOVEMENTS[case].stage
            decode_movement(message.xml, read, stage, provenance=Provenance.FACT_SYNTHETIC,
                            source=ADAPTER)
    assert refused.value.reason is AdapterRefusalReason.WRONG_VERSION
    assert PROFILES[(read, message.family)].message_id in refused.value.detail


def test_a_message_of_another_family_is_refused() -> None:
    announcement = encode_announcement(ANNOUNCEMENTS["cash-dividend"], Release.SR2026)
    with pytest.raises(AdapterRefusalError) as refused:
        decode_movement(announcement.xml, Release.SR2026, "confirmation",
                        provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)
    assert refused.value.reason is AdapterRefusalReason.WRONG_MESSAGE


# --- provenance ------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_emitted_messages_are_synthetic_and_name_the_adapter(case: str) -> None:
    message, *_ = roundtrip(case, Release.SR2026)
    assert message.provenance is Provenance.FACT_SYNTHETIC
    assert message.source.source_id == adapter_module.ADAPTER_SOURCE_ID
    assert message.source.reference == message.message_id


def test_a_decoded_message_carries_the_provenance_its_reader_states() -> None:
    message = encode_announcement(ANNOUNCEMENTS["cash-dividend"], Release.SR2026)
    external = decode_announcement(message.xml, Release.SR2026,
                                   provenance=Provenance.FACT_EXTERNAL, source=DTC)
    assert external.provenance is Provenance.FACT_EXTERNAL and external.source == DTC


@pytest.mark.parametrize("provenance", [Provenance.POLICY_RESULT, Provenance.HUMAN_JUDGMENT])
def test_a_decoded_message_is_a_reported_fact(provenance: Provenance) -> None:
    message = encode_announcement(ANNOUNCEMENTS["cash-dividend"], Release.SR2026)
    with pytest.raises(AdapterRefusalError, match="reported fact"):
        decode_announcement(message.xml, Release.SR2026, provenance=provenance, source=DTC)


# --- the pinned sources ----------------------------------------------------------------------


def test_every_pinned_source_records_url_retrieval_and_sha256() -> None:
    assert len(DTC_PACKAGES) == 6 and len(DTC_XSDS) == 8
    for package in DTC_PACKAGES:
        assert package.url.startswith("https://files.dtcc.com/download/assets/")
        assert package.retrieved_dtg == "202610051734"
        assert len(package.sha256) == 64
    packages = {p.package_id: p for p in DTC_PACKAGES}
    for xsd in DTC_XSDS:
        assert packages[xsd.package_id].release is xsd.release
        assert xsd.path_in_package.endswith(xsd.message_id.replace(".", "_") + ".xsd")


def test_every_pinned_source_gives_one_profile_per_release_and_family() -> None:
    assert set(PROFILES) == {(r, f) for r in Release for f in MessageFamily}
    expected = {
        (Release.SR2025, MessageFamily.ANNOUNCEMENT): "seev.031.001.15",
        (Release.SR2026, MessageFamily.ANNOUNCEMENT): "seev.031.001.16",
        (Release.SR2025, MessageFamily.INSTRUCTION): "seev.033.001.13",
        (Release.SR2026, MessageFamily.INSTRUCTION): "seev.033.001.14",
        (Release.SR2025, MessageFamily.MOVEMENT_PRELIMINARY_ADVICE): "seev.035.001.16",
        (Release.SR2026, MessageFamily.MOVEMENT_PRELIMINARY_ADVICE): "seev.035.001.17",
        (Release.SR2025, MessageFamily.MOVEMENT_CONFIRMATION): "seev.036.001.16",
        (Release.SR2026, MessageFamily.MOVEMENT_CONFIRMATION): "seev.036.001.17",
    }
    assert {key: p.message_id for key, p in PROFILES.items()} == expected
    for profile in PROFILES.values():
        assert profile.namespace == "urn:iso:std:iso:20022:tech:xsd:" + profile.message_id


def test_no_schema_file_is_committed() -> None:
    """Bill's decision of 5 October 2026: no ISO 20022 schema is vendored for this order."""
    for folder in (REPO / "atreides" / "corporate_actions", REPO / "tests" / "corporate_actions"):
        assert not list(folder.rglob("*.xsd"))


# --- what the profile cannot say, refused at encoding -----------------------------------------


@pytest.mark.parametrize(
    ("built", "match"),
    [
        (event(terms=CASH, event_id="SYN_WITH_UNDERSCORE"), "character set"),
        (event(terms=CASH, event_id="SYN-FAR-TOO-LONG-ID"), "longer than 16"),
        (event(terms=CASH, security_id="SYNTHETIC-XYZ"), "not an ISIN"),
        (event(EventType.CASH_DIVIDEND, Participation.MANDATORY_WITH_CHOICE, terms=CASH),
         "terms on an elective event"),
        (event(EventType.TENDER_OFFER, Participation.VOLUNTARY, options=(),
               default_option_id=None), "without options"),
        (event(EventType.TENDER_OFFER, Participation.VOLUNTARY, options=(
            ElectionOption(option_id="001", description="SYNTHETIC"),), default_option_id=None),
         "states no type"),
        (event(EventType.TENDER_OFFER, Participation.VOLUNTARY, options=(
            ElectionOption(option_id="1", description="SYNTHETIC", option_type=OptionType.CASH),),
            default_option_id=None), "three-digit"),
        (event(EventType.TENDER_OFFER, Participation.VOLUNTARY, options=(
            ElectionOption(option_id="001", description="SYNTHETIC_CASH",
                           option_type=OptionType.CASH),), default_option_id=None),
         "character set"),
        (event(terms=EventTerms(cash_rate_per_share=D("0.25"), currency="USD",
                                stock_rate_per_share=D("0.05"))), "not both"),
        (event(EventType.STOCK_DIVIDEND, terms=EventTerms(stock_rate_per_share=D("0.05"),
                                                          split_new=2, split_old=1)), "not both"),
        (event(terms=CASH, dates=EventDates(announcement_date=date(2026, 10, 1))),
         "payment date is required"),
        (event(terms=EventTerms(cash_rate_per_share=D("0.12345678901234"), currency="USD")),
         "decimal places"),
    ],
)
def test_an_announcement_the_profile_cannot_say_is_refused(
    built: CorporateActionEvent, match: str
) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        encode_announcement(built, Release.SR2026)
    assert refused.value.reason is AdapterRefusalReason.NOT_REPRESENTABLE


@pytest.mark.parametrize(
    ("instruction", "built", "reason", "match"),
    [
        (INSTRUCTION, ANNOUNCEMENTS["tender-offer"], AdapterRefusalReason.NOT_IN_PROFILE, "TEND"),
        (INSTRUCTION.model_copy(update={"protect": True}), CHOICE,
         AdapterRefusalReason.NOT_IN_PROFILE, "protect"),
        (INSTRUCTION.model_copy(update={"option_id": "009"}), CHOICE,
         AdapterRefusalReason.NOT_REPRESENTABLE, "announced option"),
        (INSTRUCTION.model_copy(update={"account_id": "ACCT_A"}), CHOICE,
         AdapterRefusalReason.NOT_REPRESENTABLE, "account"),
        (INSTRUCTION.model_copy(update={"quantity": D("123456789012345")}), CHOICE,
         AdapterRefusalReason.NOT_REPRESENTABLE, "14 digits"),
    ],
)
def test_an_instruction_the_profile_cannot_say_is_refused(
    instruction: ElectionInstruction, built: CorporateActionEvent,
    reason: AdapterRefusalReason, match: str,
) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        encode_instruction(instruction, built, Release.SR2026)
    assert refused.value.reason is reason


def test_an_unnumbered_option_cannot_be_instructed() -> None:
    lettered = event(EventType.CASH_DIVIDEND, Participation.MANDATORY_WITH_CHOICE, options=(
        ElectionOption(option_id="A", description="SYNTHETIC", option_type=OptionType.CASH),),
        default_option_id=None)
    with pytest.raises(AdapterRefusalError, match="three-digit"):
        encode_instruction(INSTRUCTION.model_copy(update={"option_id": "A"}), lettered,
                           Release.SR2026)


@pytest.mark.parametrize(
    ("report", "reason", "match"),
    [
        (movement(option_type=OptionType.NOAC), AdapterRefusalReason.NOT_IN_PROFILE, "NOAC"),
        (movement(movement=CashMovement(amount=D("1.123456"), currency="USD")),
         AdapterRefusalReason.NOT_REPRESENTABLE, "decimal places"),
        (movement(event_id="SYN_1"), AdapterRefusalReason.NOT_REPRESENTABLE, "character set"),
    ],
)
def test_a_movement_the_profile_cannot_say_is_refused(
    report: MovementReport, reason: AdapterRefusalReason, match: str
) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        encode_movement(report, Release.SR2026)
    assert refused.value.reason is reason


# --- what the model cannot hold, refused at decoding ------------------------------------------


def altered(case: str, old: str, new: str) -> bytes:
    message, *_ = roundtrip(case, Release.SR2026)
    assert old.encode() in message.xml, old
    return message.xml.replace(old.encode(), new.encode(), 1)


def read(case: str, xml: bytes) -> object:
    if case in ANNOUNCEMENTS:
        return decode_announcement(xml, Release.SR2026, provenance=Provenance.FACT_SYNTHETIC,
                                   source=ADAPTER)
    if case == "instruction":
        return decode_instruction(xml, Release.SR2026, event=CHOICE, instruction_id="I-1",
                                  received_date=date(2026, 10, 15),
                                  provenance=Provenance.FACT_EXTERNAL, source=DTC)
    return decode_movement(xml, Release.SR2026, MOVEMENTS[case].stage,
                           provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)


@pytest.mark.parametrize(
    ("case", "old", "new", "reason", "match"),
    [
        ("cash-dividend", "<Cd>DVCA</Cd>", "<Cd>BRUP</Cd>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "event type"),
        ("cash-dividend", "<ISIN>USSYNTHETIC0</ISIN>",
         "<OthrId><Id>SYN</Id><Tp><Prtry>XX</Prtry></Tp></OthrId>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "not an ISIN"),
        ("cash-dividend", "<AnncmntDt><Dt><Dt>2026-10-01</Dt></Dt></AnncmntDt>", "",
         AdapterRefusalReason.NOT_REPRESENTABLE, "announcement date"),
        ("cash-dividend", "<Cd>INCO</Cd>", "<Cd>CAPO</Cd>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "gross income rate"),
        ("cash-dividend", "<Dt>2026-10-01</Dt>", "<Dt>1 October</Dt>",
         AdapterRefusalReason.MALFORMED, "ISO date"),
        ("cash-dividend", "<Amt Ccy=\"USD\">0.25</Amt>", "<Amt Ccy=\"USD\">a quarter</Amt>",
         AdapterRefusalReason.MALFORMED, "not a number"),
        ("tender-offer", "<AddtlInf><AddtlTxt><Lang>en</Lang><AddtlInf>SYNTHETIC cash"
         "</AddtlInf></AddtlTxt></AddtlInf>", "",
         AdapterRefusalReason.NOT_REPRESENTABLE, "no description"),
        ("tender-offer", "<RspnDdln><Dt><Dt>2026-10-20</Dt>",
         "<RspnDdln><Dt><Dt>2026-10-19</Dt>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "different deadlines"),
        ("tender-offer", "<DfltOptnInd>false</DfltOptnInd>", "<DfltOptnInd>true</DfltOptnInd>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "more than one default"),
        ("tender-offer", "<DfltOptnInd>false</DfltOptnInd>", "<DfltOptnInd>maybe</DfltOptnInd>",
         AdapterRefusalReason.MALFORMED, "default"),
        ("instruction", "<CorpActnEvtId>SYN-CASHDIVI</CorpActnEvtId>",
         "<CorpActnEvtId>SYN-OTHER</CorpActnEvtId>",
         AdapterRefusalReason.EVENT_MISMATCH, "SYN-OTHER"),
        ("instruction", "<Qty><Unit>100</Unit></Qty>", "<Cd>QALL</Cd>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "units"),
        ("instruction", "<AcctDtls><SfkpgAcct>ACCT-A</SfkpgAcct></AcctDtls>",
         "<AcctDtls />", AdapterRefusalReason.NOT_REPRESENTABLE, "no account"),
        ("confirmation-cash", "<CdtDbtInd>CRDT</CdtDbtInd>", "<CdtDbtInd>XXXX</CdtDbtInd>",
         AdapterRefusalReason.MALFORMED, "direction"),
        ("confirmation-cash", "<ShrtLngPos>LONG</ShrtLngPos>", "<ShrtLngPos>XXXX</ShrtLngPos>",
         AdapterRefusalReason.MALFORMED, "position"),
        ("confirmation-cash", "<CdtDbtInd>CRDT</CdtDbtInd>",
         "<CdtDbtInd>CRDT</CdtDbtInd></CshMvmntDtls><SctiesMvmntDtls><CdtDbtInd>CRDT</CdtDbtInd>"
         "</SctiesMvmntDtls><CshMvmntDtls><CdtDbtInd>CRDT</CdtDbtInd>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "exactly one"),
    ],
)
def test_a_message_the_model_cannot_hold_is_refused(
    case: str, old: str, new: str, reason: AdapterRefusalReason, match: str
) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        read(case, altered(case, old, new))
    assert refused.value.reason is reason


@pytest.mark.parametrize(
    ("case", "old", "new", "reason", "match"),
    [
        ("cash-dividend", "<Amt Ccy=\"USD\">0.25</Amt>", "<Amt Ccy=\"USD\">NaN</Amt>",
         AdapterRefusalReason.MALFORMED, "not finite"),
        ("cash-dividend", "<CorpActnEvtId>SYN-CASHDIVI</CorpActnEvtId>",
         "<CorpActnEvtId></CorpActnEvtId>", AdapterRefusalReason.MALFORMED, "is required"),
        ("tender-offer", "<OptnTp><Cd>CASH</Cd></OptnTp>", "<OptnTp><Cd>ABST</Cd></OptnTp>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "option type"),
        ("cash-dividend", "<RateAndAmtDtls><GrssDstrbtnRate><RateTpAndAmtAndRateSts><RateTp><Cd>"
         "INCO</Cd></RateTp><Amt Ccy=\"USD\">0.25</Amt></RateTpAndAmtAndRateSts>"
         "</GrssDstrbtnRate></RateAndAmtDtls>", "",
         AdapterRefusalReason.NOT_REPRESENTABLE, "states no rate"),
        ("stock-dividend", "<Qty2>20</Qty2>", "<Qty2>0</Qty2>",
         AdapterRefusalReason.MALFORMED, "zero"),
        ("split", "<Qty1>3</Qty1>", "<Qty1>3.5</Qty1>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "fractional"),
        ("stock-dividend", "<RateDtls>", "<RateDtlsGone>",
         AdapterRefusalReason.MALFORMED, "well-formed"),
        ("instruction", "<Unit>100</Unit>", "<Unit>0</Unit>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "instruction is not valid"),
        ("confirmation-cash", "<CorpActnGnlInf>", "<CorpActnGnlInfGone>",
         AdapterRefusalReason.MALFORMED, "well-formed"),
        ("confirmation-cash", "<SfkpgAcct>ACCT-A</SfkpgAcct>", "",
         AdapterRefusalReason.NOT_REPRESENTABLE, "no account"),
        ("confirmation-cash", "<AmtDtls><PstngAmt Ccy=\"USD\">25.5</PstngAmt></AmtDtls>",
         "<AmtDtls />", AdapterRefusalReason.NOT_REPRESENTABLE, "no amount"),
        ("confirmation-securities", "<PstngQty><Qty><Unit>10</Unit></Qty></PstngQty>", "",
         AdapterRefusalReason.NOT_REPRESENTABLE, "no quantity"),
        ("confirmation-cash", "<DtDtls><PstngDt><Dt>2026-10-30</Dt></PstngDt></DtDtls>",
         "<DtDtls />", AdapterRefusalReason.NOT_REPRESENTABLE, "no date"),
        ("confirmation-cash", "<FinInstrmId><ISIN>USSYNTHETIC0</ISIN></FinInstrmId>",
         "<FinInstrmId />", AdapterRefusalReason.NOT_REPRESENTABLE, "not an ISIN"),
        ("advice-cash", "<OptnNb>001</OptnNb>", "<OptnNb>01</OptnNb>",
         AdapterRefusalReason.NOT_REPRESENTABLE, "movement is not valid"),
    ],
)
def test_every_other_decoding_gap_is_refused_by_name(
    case: str, old: str, new: str, reason: AdapterRefusalReason, match: str
) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        read(case, altered(case, old, new))
    assert refused.value.reason is reason


def test_a_mandatory_option_without_a_modeled_movement_is_refused() -> None:
    xml = altered("stock-dividend",
                  "<RateDtls><AddtlQtyForExstgScties><QtyToQty><Qty1>1</Qty1><Qty2>20</Qty2>"
                  "</QtyToQty></AddtlQtyForExstgScties></RateDtls>", "")
    with pytest.raises(AdapterRefusalError, match="exactly one cash or securities movement"):
        read("stock-dividend", xml)


def test_an_elective_announcement_without_options_is_not_an_event() -> None:
    message = encode_announcement(ANNOUNCEMENTS["tender-offer"], Release.SR2026)
    start = message.xml.index(b"<CorpActnOptnDtls>")
    end = message.xml.rindex(b"</CorpActnOptnDtls>") + len(b"</CorpActnOptnDtls>")
    xml = message.xml[:start] + message.xml[end:]
    with pytest.raises(AdapterRefusalError, match="not a valid event") as refused:
        read("tender-offer", xml)
    assert refused.value.reason is AdapterRefusalReason.NOT_REPRESENTABLE


def test_a_movement_without_its_account_or_option_block_is_refused() -> None:
    message = encode_movement(MOVEMENTS["confirmation-cash"], Release.SR2026)
    start = message.xml.index(b"<CorpActnConfDtls>")
    end = message.xml.index(b"</CorpActnConfDtls>") + len(b"</CorpActnConfDtls>")
    with pytest.raises(AdapterRefusalError, match="one option's movement"):
        read("confirmation-cash", message.xml[:start] + message.xml[end:])


def test_a_movement_without_general_information_is_refused() -> None:
    message = encode_movement(MOVEMENTS["confirmation-cash"], Release.SR2026)
    start = message.xml.index(b"<CorpActnGnlInf>")
    end = message.xml.index(b"</CorpActnGnlInf>") + len(b"</CorpActnGnlInf>")
    with pytest.raises(AdapterRefusalError, match="CorpActnGnlInf is required"):
        read("confirmation-cash", message.xml[:start] + message.xml[end:])


def test_a_negative_value_is_never_written() -> None:
    """Unreachable through the models, which hold every written value non-negative, and
    kept as the guard DTC's ``minInclusive`` of zero calls for."""
    with pytest.raises(AdapterRefusalError, match="negative"):
        adapter_module._decimal(D(-1), (14, 5), "amount")


def test_a_mandatory_event_with_two_options_is_not_modeled() -> None:
    xml = altered("cash-dividend", "</CorpActnOptnDtls>",
                  "</CorpActnOptnDtls><CorpActnOptnDtls><OptnNb>002</OptnNb></CorpActnOptnDtls>")
    with pytest.raises(AdapterRefusalError, match="more than one option"):
        read("cash-dividend", xml)


@pytest.mark.parametrize(
    ("xml", "match"),
    [
        (b"not xml", "well-formed"),
        (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', "document type"),
        (b"<Document/>", "ISO 20022 Document"),
        (b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:seev.031.001.16"/>',
         "no CorpActnNtfctn"),
        (b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:seev.031.001.16"><CorpActnNtfctn/>'
         b"</Document>", "CorpActnGnlInf is required"),
    ],
)
def test_bytes_that_are_not_a_message_are_refused(xml: bytes, match: str) -> None:
    with pytest.raises(AdapterRefusalError, match=match) as refused:
        decode_announcement(xml, Release.SR2026, provenance=Provenance.FACT_SYNTHETIC,
                            source=ADAPTER)
    assert refused.value.reason is AdapterRefusalReason.MALFORMED


# --- properties ------------------------------------------------------------------------------


@given(
    release=st.sampled_from(Release),
    rate=st.decimals(min_value=D("0.0001"), max_value=D(1000), places=4),
    stock=st.decimals(min_value=D("0.001"), max_value=D(5), places=3),
    ratio=st.tuples(st.integers(2, 50), st.integers(1, 50)).filter(lambda t: t[0] > t[1]),
)
def test_property_announcement_terms_round_trip(
    release: Release, rate: Decimal, stock: Decimal, ratio: tuple[int, int]
) -> None:
    for built in (
        event(terms=EventTerms(cash_rate_per_share=rate, currency="USD")),
        event(EventType.STOCK_DIVIDEND, terms=EventTerms(stock_rate_per_share=stock)),
        event(EventType.SPLIT, terms=EventTerms(split_new=ratio[0], split_old=ratio[1])),
    ):
        message = encode_announcement(built, release)
        back = decode_announcement(message.xml, release, provenance=Provenance.FACT_SYNTHETIC,
                                   source=ADAPTER)
        assert back == built


@given(release=st.sampled_from(Release),
       quantity=st.decimals(min_value=D(0), max_value=D("99999999.99999"), places=5),
       balance=st.decimals(min_value=D(-10**9), max_value=D(10**9), places=0))
def test_property_movements_round_trip(release: Release, quantity: Decimal,
                                       balance: Decimal) -> None:
    for report in (
        movement("confirmation", CashMovement(amount=quantity, currency="USD"),
                 MovementBalances(confirmed_balance=balance, pending_delivery_balance=balance)),
        movement("preliminary_advice", SecuritiesMovement(security_id=ISIN, quantity=quantity),
                 MovementBalances(eligible_balance=balance), option_type=OptionType.SECU),
    ):
        back = decode_movement(encode_movement(report, release).xml, release, report.stage,
                               provenance=Provenance.FACT_SYNTHETIC, source=ADAPTER)
        assert back == report


# --- validation against DTC's own XSDs, where they have been downloaded ------------------------

XSD_DIR = os.environ.get("DTC_CA_XSD_DIR")


@pytest.mark.skipif(
    not XSD_DIR,
    reason="DTC's XSDs are not vendored (Bill, 5 October 2026); set DTC_CA_XSD_DIR to a folder "
           "holding the pinned files to run this check. A skip is not a pass.",
)
@pytest.mark.parametrize("release", list(Release))
@pytest.mark.parametrize("case", CASES)
def test_every_emitted_message_is_valid_against_dtc_xsds(case: str, release: Release) -> None:
    etree = pytest.importorskip("lxml.etree")
    message, *_ = roundtrip(case, release)
    pin = PROFILES[(release, message.family)].xsd
    path = Path(str(XSD_DIR)) / Path(pin.path_in_package).name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin.sha256, (
        f"{path.name} does not match its pinned SHA-256: DTC may have changed it"
    )
    schema = etree.XMLSchema(etree.parse(str(path)))
    assert schema.validate(etree.fromstring(message.xml)), schema.error_log.last_error


@pytest.mark.parametrize("module", [adapter_module, sources_module])
def test_docstrings_claim_structural_validation_only(module: Any) -> None:
    text = " ".join((module.__doc__ or "").split())
    assert "EXPERIMENTAL" in text
    assert "structural validation" in text.lower()
    for sentence in text.lower().replace(",", ".").split("."):
        if "schema validation" in sentence:
            assert any(word in sentence.split() for word in ("not", "never", "nowhere")), sentence


# --- the movement report model -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "changes", "match"),
    [
        ("preliminary_advice", {"participation": None}, "states participation"),
        ("preliminary_advice", {"default_option": None}, "states participation"),
        ("confirmation", {"participation": Participation.MANDATORY}, "does not state"),
        ("confirmation", {"default_option": True}, "does not state"),
        ("confirmation", {"balances": MovementBalances()}, "confirmed balance"),
        ("preliminary_advice", {"balances": MovementBalances(confirmed_balance=D(1))},
         "no confirmed balance"),
        ("confirmation", {"provenance": Provenance.POLICY_RESULT}, "reported fact"),
    ],
)
def test_a_movement_report_fits_its_stage(
    stage: str, changes: dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        movement(stage, **changes)


def test_a_movement_reports_its_quantity_whichever_it_moves() -> None:
    assert MOVEMENTS["confirmation-cash"].quantity == D("25.5")
    assert MOVEMENTS["confirmation-securities"].quantity == D(10)
