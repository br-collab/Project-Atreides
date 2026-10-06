"""A synthetic DTC ISO 20022 adapter for corporate actions (ORDER SC-1, WP-4).

EXPERIMENTAL (charter section 18.6). Nothing here connects to DTC, and nothing
here transmits. The adapter turns this package's models into ISO 20022 XML in
DTC's published profiles and reads such XML back, so that the rest of the
package can be exercised against the shape of the real messages.

FOUR MESSAGES, TWO RELEASES
---------------------------
=============================  =========  =================  =================
Family                         Message    SR2025             SR2026
=============================  =========  =================  =================
announcement                   seev.031   seev.031.001.15    seev.031.001.16
instruction                    seev.033   seev.033.001.13    seev.033.001.14
movement preliminary advice    seev.035   seev.035.001.16    seev.035.001.17
movement confirmation          seev.036   seev.036.001.16    seev.036.001.17
=============================  =========  =================  =================

Every message identifier comes from an XSD in a pinned DTC package
(:mod:`~atreides.corporate_actions.dtc_sources`). A message is read only
against the release it is said to belong to: a message in the other release's
namespace is refused as the wrong version, and one of another family as the
wrong message.

STRUCTURAL VALIDATION, NOT SCHEMA VALIDATION
--------------------------------------------
No schema is vendored (Bill, 5 October 2026). What this module checks is a
structural profile read from DTC's XSDs: the namespace, the message element,
the elements the adapter needs, the code lists it maps, and the lengths,
character sets and digit limits of the values it writes. That is called
structural validation here and nowhere is it called schema validation. The
tests additionally validate every emitted message against DTC's own XSDs when
a reader has downloaded them (``DTC_CA_XSD_DIR``); in CI that test is skipped,
and a skip is not a pass.

WHAT IS CARRIED, AND WHAT IS REFUSED
------------------------------------
Each model maps to a stated subset of its message. Anything the model holds
that the profile cannot say is refused at encoding with a typed reason, never
dropped; anything a message says that the model cannot hold is refused at
decoding, never guessed. In particular:

- an announcement carries a mandatory event's terms on one option (cash: the
  gross income rate; stock dividend: additional quantity for existing
  securities; split: new to old), and an elective event's announced options.
  Terms on an elective event, and an elective event without options, are not
  representable;
- DTC's public instruction profile is the elective dividend one. It carries
  no instruction identifier and no protect, and its event types do not
  include tender offers, rights or mergers. An instruction's identifier and
  receipt date therefore come from the envelope when one is read;
- the underlying security is an ISIN. Other identification schemes are not
  modeled.

PROVENANCE
----------
Everything this adapter emits is ``FACT_SYNTHETIC`` and names the adapter as
its source. Whoever reads a message states what it is: ``FACT_EXTERNAL`` for
one received from DTC, with DTC named as the source, or ``FACT_SYNTHETIC``.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from fractions import Fraction
from typing import Final, Literal
from xml.etree import ElementTree as ET

from cannae_kernel.provenance import Provenance
from pydantic import ValidationError

from atreides.corporate_actions.dtc_sources import DTC_XSDS, DtcXsd, MessageFamily, Release
from atreides.corporate_actions.election import ElectionInstruction
from atreides.corporate_actions.events import (
    EVENT_FACT_PROVENANCE,
    CorporateActionEvent,
    ElectionOption,
    EventDates,
    EventTerms,
    EventType,
    OptionType,
    Participation,
    SourceIdentity,
)
from atreides.corporate_actions.movement import (
    CashMovement,
    MovementBalances,
    MovementReport,
    SecuritiesMovement,
)
from atreides.customer_protection.common import Frozen

__all__ = [
    "ADAPTER_SOURCE_ID",
    "INSTRUCTION_EVENT_CODES",
    "PROFILES",
    "AdapterRefusalError",
    "AdapterRefusalReason",
    "EncodedMessage",
    "MessageProfile",
    "decode_announcement",
    "decode_instruction",
    "decode_movement",
    "encode_announcement",
    "encode_instruction",
    "encode_movement",
]

ADAPTER_SOURCE_ID: Final = "synthetic-dtc-iso20022-adapter"
_NS_PREFIX: Final = "urn:iso:std:iso:20022:tech:xsd:"

_ROOTS: Final[dict[MessageFamily, str]] = {
    MessageFamily.ANNOUNCEMENT: "CorpActnNtfctn",
    MessageFamily.INSTRUCTION: "CorpActnInstr",
    MessageFamily.MOVEMENT_PRELIMINARY_ADVICE: "CorpActnMvmntPrlimryAdvc",
    MessageFamily.MOVEMENT_CONFIRMATION: "CorpActnMvmntConf",
}

EVENT_CODES: Final[dict[EventType, str]] = {
    EventType.CASH_DIVIDEND: "DVCA",
    EventType.STOCK_DIVIDEND: "DVSE",
    EventType.SPLIT: "SPLF",
    EventType.REVERSE_SPLIT: "SPLR",
    EventType.MERGER: "MRGR",
    EventType.TENDER_OFFER: "TEND",
    EventType.RIGHTS: "RHDI",
    EventType.REDEMPTION_LOTTERY: "DRAW",
    EventType.INTEREST_PAYMENT: "INTR",
    EventType.FINAL_MATURITY: "REDM",
    EventType.PARTIAL_REDEMPTION: "PRED",
    EventType.FULL_CALL: "MCAL",
    EventType.CAPITAL_GAINS_DISTRIBUTION: "CAPG",
    EventType.CAPITAL_DISTRIBUTION: "CAPD",
    EventType.REINVESTMENT: "DRIP",
}
_EVENT_TYPES: Final = {code: event_type for event_type, code in EVENT_CODES.items()}

PARTICIPATION_CODES: Final[dict[Participation, str]] = {
    Participation.MANDATORY: "MAND",
    Participation.VOLUNTARY: "VOLU",
    Participation.MANDATORY_WITH_CHOICE: "CHOS",
}
_PARTICIPATIONS: Final = {code: p for p, code in PARTICIPATION_CODES.items()}

#: Event types DTC's elective dividend instruction profile admits (seev.033, both releases).
INSTRUCTION_EVENT_CODES: Final = frozenset(
    {"CAPD", "CAPG", "CAPI", "DVCA", "DVOP", "DRIP", "INTR", "LIQU", "NOOF", "OTHR", "PRED", "SOFF"}
)
#: Option types the confirmation profile admits, of those this package models.
_CONFIRMATION_OPTION_TYPES: Final = frozenset(
    {OptionType.CASH, OptionType.SECU, OptionType.CASE, OptionType.OTHR}
)
#: The gross distribution rate type a cash dividend's rate is: income.
_INCOME_RATE: Final = "INCO"

#: FIN X character set, DTC's identifier patterns.
_FINX_16: Final = re.compile(
    r"([0-9a-zA-Z\-\?:\(\)\.,'\+ ]([0-9a-zA-Z\-\?:\(\)\.,'\+ ]*(/[0-9a-zA-Z\-\?:\(\)\.,'\+ ])?)*)"
)
_FINX_35: Final = re.compile(r"[0-9a-zA-Z/\-\?:\(\)\.,'\+ ]{1,35}")
_FINX_350: Final = re.compile(r"[0-9a-zA-Z/\-\?:\(\)\.\n\r,'\+ ]{1,350}")
_ISIN: Final = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_OPTION_NUMBER: Final = re.compile(r"[0-9]{3}")

#: (total digits, fraction digits) as DTC's XSDs restrict them.
_RATE_DIGITS: Final = (14, 13)
_AMOUNT_DIGITS: Final = (14, 5)
_QUANTITY_DIGITS: Final = (14, 14)


class MessageProfile(Frozen):
    """One release of one message family, and the XSD it was read from."""

    release: Release
    family: MessageFamily
    message_id: str
    namespace: str
    root: str
    xsd: DtcXsd


PROFILES: Final[dict[tuple[Release, MessageFamily], MessageProfile]] = {
    (x.release, x.family): MessageProfile(
        release=x.release, family=x.family, message_id=x.message_id,
        namespace=_NS_PREFIX + x.message_id, root=_ROOTS[x.family], xsd=x,
    )
    for x in DTC_XSDS
}


class AdapterRefusalReason(StrEnum):
    """Why the adapter would not encode or decode."""

    WRONG_VERSION = "wrong_version"
    """The message is of the right family but another release."""
    WRONG_MESSAGE = "wrong_message"
    """The message is not of the family asked for."""
    NOT_IN_PROFILE = "not_in_profile"
    """DTC's public profile for this message does not admit it."""
    NOT_REPRESENTABLE = "not_representable"
    """The model holds something the message cannot say, or the reverse."""
    EVENT_MISMATCH = "event_mismatch"
    """The message names a different event from the one it is read against."""
    MALFORMED = "malformed"
    """The bytes are not a well-formed message of the expected shape."""


class AdapterRefusalError(ValueError):
    """The adapter refused, with a typed reason."""

    def __init__(self, reason: AdapterRefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


class EncodedMessage(Frozen):
    """One emitted message: its bytes, which profile it follows, and that it is synthetic."""

    release: Release
    family: MessageFamily
    message_id: str
    xml: bytes
    provenance: Literal[Provenance.FACT_SYNTHETIC] = Provenance.FACT_SYNTHETIC
    source: SourceIdentity


# --- values -------------------------------------------------------------------------------


def _refuse(reason: AdapterRefusalReason, detail: str) -> AdapterRefusalError:
    return AdapterRefusalError(reason, detail)


def _checked(value: str, pattern: re.Pattern[str], what: str, maximum: int) -> str:
    if not 1 <= len(value) <= maximum or not pattern.fullmatch(value):
        raise _refuse(
            AdapterRefusalReason.NOT_REPRESENTABLE,
            f"{what} {value!r} is not in DTC's character set or is longer than {maximum}",
        )
    return value


def _event_id(value: str) -> str:
    return _checked(value, _FINX_16, "event identifier", 16)


def _isin(value: str) -> str:
    if not _ISIN.fullmatch(value):
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"security {value!r} is not an ISIN; other schemes are not modeled")
    return value


def _decimal(value: Decimal, digits: tuple[int, int], what: str) -> str:
    """``value`` as DTC writes it, or a refusal where it exceeds the digit limits."""
    if value < 0:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, f"{what} {value} is negative")
    text = format(value, "f")
    whole, _, fraction = text.partition(".")
    whole, fraction = whole.lstrip("0"), fraction.rstrip("0")
    total, places = digits
    if len(whole) + len(fraction) > total or len(fraction) > places:
        raise _refuse(
            AdapterRefusalReason.NOT_REPRESENTABLE,
            f"{what} {value} exceeds {total} digits or {places} decimal places",
        )
    return (whole or "0") + (f".{fraction}" if fraction else "")


def _parse_decimal(text: str, what: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise _refuse(AdapterRefusalReason.MALFORMED, f"{what} {text!r} is not a number") from None
    if not value.is_finite():
        raise _refuse(AdapterRefusalReason.MALFORMED, f"{what} {text!r} is not finite")
    return value


def _parse_date(text: str, what: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _refuse(
            AdapterRefusalReason.MALFORMED,
            f"{what} {text!r} is not an ISO date",
        ) from None


# --- building ------------------------------------------------------------------------------


class _Builder:
    def __init__(self, profile: MessageProfile) -> None:
        self.profile = profile
        self.ns = profile.namespace
        # The namespace is declared once, as the default, and every element is written
        # unqualified beneath it. That is the conventional ISO 20022 form, and the one
        # ElementTree can write with unqualified attributes such as ``Ccy``.
        self.document = ET.Element("Document", {"xmlns": self.ns})
        self.root = self.add(self.document, profile.root)

    def add(self, parent: ET.Element, path: str, text: str | None = None,
            attrs: dict[str, str] | None = None) -> ET.Element:
        node = parent
        for name in path.split("/"):
            node = ET.SubElement(node, name)
        if text is not None:
            node.text = text
        if attrs:
            node.attrib.update(attrs)
        return node

    def date(self, parent: ET.Element, path: str, value: date) -> None:
        self.add(parent, path, value.isoformat())

    def encoded(self) -> EncodedMessage:
        xml = ET.tostring(self.document, encoding="utf-8", xml_declaration=True)
        return EncodedMessage(
            release=self.profile.release, family=self.profile.family,
            message_id=self.profile.message_id, xml=xml,
            source=SourceIdentity(source_id=ADAPTER_SOURCE_ID,
                                  reference=self.profile.message_id),
        )


def _signed_balance(b: _Builder, parent: ET.Element, tag: str, value: Decimal) -> None:
    node = b.add(parent, f"{tag}/Bal")
    b.add(node, "ShrtLngPos", "SHOR" if value < 0 else "LONG")
    b.add(node, "QtyChc/Qty/Unit", _decimal(abs(value), _QUANTITY_DIGITS, tag))


def _eligible_balance(b: _Builder, parent: ET.Element, value: Decimal) -> None:
    node = b.add(parent, "TtlElgblBal/Bal/QtyChc/SgndQty")
    b.add(node, "ShrtLngPos", "SHOR" if value < 0 else "LONG")
    b.add(node, "Qty/Unit", _decimal(abs(value), _QUANTITY_DIGITS, "eligible balance"))


# --- reading -------------------------------------------------------------------------------


class _Reader:
    def __init__(self, xml: bytes, profile: MessageProfile) -> None:
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise _refuse(
                AdapterRefusalReason.MALFORMED,
                "a document type or entity is not accepted",
            )
        try:
            document = ET.fromstring(xml)
        except ET.ParseError as error:
            raise _refuse(AdapterRefusalReason.MALFORMED, f"not well-formed XML: {error}") from None
        namespace, _, local = document.tag[1:].partition("}")
        if local != "Document" or not namespace.startswith(_NS_PREFIX):
            raise _refuse(AdapterRefusalReason.MALFORMED, "not an ISO 20022 Document")
        found = namespace[len(_NS_PREFIX):]
        if found != profile.message_id:
            same_family = found.split(".")[:2] == profile.message_id.split(".")[:2]
            reason = (
                AdapterRefusalReason.WRONG_VERSION if same_family
                else AdapterRefusalReason.WRONG_MESSAGE
            )
            raise _refuse(
                reason,
                f"the message is {found}; {profile.release.value} {profile.family.value} "
                f"is {profile.message_id}",
            )
        self.ns = {"m": namespace}
        root = document.find(f"m:{profile.root}", self.ns)
        if root is None:
            raise _refuse(AdapterRefusalReason.MALFORMED, f"no {profile.root} element")
        self.root = root

    def find(self, parent: ET.Element, path: str) -> ET.Element | None:
        return parent.find("/".join(f"m:{p}" for p in path.split("/")), self.ns)

    def findall(self, parent: ET.Element, path: str) -> list[ET.Element]:
        return parent.findall("/".join(f"m:{p}" for p in path.split("/")), self.ns)

    def text(self, parent: ET.Element, path: str) -> str | None:
        node = self.find(parent, path)
        return None if node is None or node.text is None else node.text.strip()

    def required(self, parent: ET.Element, path: str) -> str:
        value = self.text(parent, path)
        if not value:
            raise _refuse(AdapterRefusalReason.MALFORMED, f"{path} is required")
        return value

    def date(self, parent: ET.Element, path: str) -> date | None:
        value = self.text(parent, path)
        return None if value is None else _parse_date(value, path)

    def signed(self, parent: ET.Element, path: str, *, eligible: bool = False) -> Decimal | None:
        node = self.find(parent, path)
        if node is None:
            return None
        inner = "Bal/QtyChc/SgndQty" if eligible else "Bal"
        quantity = "Qty/Unit" if eligible else "QtyChc/Qty/Unit"
        value = _parse_decimal(self.required(node, f"{inner}/{quantity}"), path)
        short = _one_of(self.required(node, f"{inner}/ShrtLngPos"), _SHORT, "position")
        return -value if short else value


def _one_of(value: str, allowed: dict[str, bool], what: str) -> bool:
    if value not in allowed:
        raise _refuse(
            AdapterRefusalReason.MALFORMED,
            f"{what} {value!r} is not one of {sorted(allowed)}",
        )
    return allowed[value]


_BOOLEAN: Final = {"true": True, "1": True, "false": False, "0": False}
_SHORT: Final = {"SHOR": True, "LONG": False}
_CREDIT: Final = {"CRDT": True, "DBIT": False}


def _source_check(provenance: Provenance) -> None:
    if provenance not in EVENT_FACT_PROVENANCE:
        raise _refuse(
            AdapterRefusalReason.NOT_REPRESENTABLE,
            f"a decoded message is a reported fact: FACT_EXTERNAL or FACT_SYNTHETIC, "
            f"not {provenance}",
        )


def _code(mapping: dict[str, EventType] | dict[str, Participation], code: str, what: str) -> object:
    if code not in mapping:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, f"{what} {code!r} is not modeled")
    return mapping[code]


def _option_type(code: str) -> OptionType:
    try:
        return OptionType(code)
    except ValueError:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"option type {code!r} is not modeled") from None


# --- announcement (seev.031) -----------------------------------------------------------------


def _terms_option(b: _Builder, event: CorporateActionEvent) -> None:
    terms, payable = event.terms, event.dates.payable_date
    if terms == EventTerms():
        return
    if payable is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "terms are carried on an option whose payment date is required")
    option = b.add(b.root, "CorpActnOptnDtls")
    b.add(option, "OptnNb", "001")
    stated_cash = next(
        (
            value
            for value in (
                terms.cash_rate_per_share,
                terms.interest_amount_per_face,
                terms.redemption_price_per_face,
            )
            if value is not None
        ),
        None,
    )
    cash = stated_cash is not None
    b.add(option, "OptnTp/Cd", "CASH" if cash else "SECU")
    b.add(option, "DfltPrcgOrStgInstr/DfltOptnInd", "true")
    if cash:
        assert stated_cash is not None and terms.currency is not None
        if any(t is not None for t in (terms.stock_rate_per_share, terms.split_new)):
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                          "one option carries cash or securities terms, not both")
        movement = b.add(option, "CshMvmntDtls")
        b.add(movement, "CdtDbtInd", "CRDT")
        b.date(movement, "DtDtls/PmtDt/Dt", payable)
        rate = b.add(movement, "RateAndAmtDtls/GrssDstrbtnRate/RateTpAndAmtAndRateSts")
        b.add(rate, "RateTp/Cd", _INCOME_RATE)
        b.add(rate, "Amt", _decimal(stated_cash, _RATE_DIGITS, "cash rate"),
              {"Ccy": terms.currency})
        if terms.reinvestment_price_per_share is not None:
            text = b.add(option, "AddtlInf/AddtlTxt")
            b.add(text, "Lang", "en")
            b.add(
                text,
                "AddtlInf",
                "REINVESTMENT PRICE "
                f"{terms.currency} "
                f"{_decimal(terms.reinvestment_price_per_share, _AMOUNT_DIGITS, 'price')}",
            )
        return
    if terms.stock_rate_per_share is not None and terms.split_new is not None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "one option carries a stock rate or a split ratio, not both")
    movement = b.add(option, "SctiesMvmntDtls")
    b.add(movement, "SctyDtls/FinInstrmId/ISIN", event.security_id)
    b.add(movement, "CdtDbtInd", "CRDT")
    b.date(movement, "DtDtls/PmtDt/Dt", payable)
    if terms.stock_rate_per_share is not None:
        ratio = Fraction(terms.stock_rate_per_share)
        tag, first, second = "AddtlQtyForExstgScties", ratio.numerator, ratio.denominator
    else:
        assert terms.split_new is not None and terms.split_old is not None
        tag, first, second = "NewToOd", terms.split_new, terms.split_old
    quantities = b.add(movement, f"RateDtls/{tag}/QtyToQty")
    b.add(quantities, "Qty1", _decimal(Decimal(first), _QUANTITY_DIGITS, "ratio"))
    b.add(quantities, "Qty2", _decimal(Decimal(second), _QUANTITY_DIGITS, "ratio"))


def _elective_option(b: _Builder, event: CorporateActionEvent, option: ElectionOption) -> None:
    if not _OPTION_NUMBER.fullmatch(option.option_id):
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"option {option.option_id!r} is not a three-digit option number")
    if option.option_type is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"option {option.option_id} states no type, which ISO 20022 requires")
    _checked(option.description, _FINX_350, "option description", 350)
    node = b.add(b.root, "CorpActnOptnDtls")
    b.add(node, "OptnNb", option.option_id)
    b.add(node, "OptnTp/Cd", option.option_type.value)
    b.add(node, "DfltPrcgOrStgInstr/DfltOptnInd",
          "true" if option.option_id == event.default_option_id else "false")
    dates = b.add(node, "DtDtls")
    if event.dates.protect_deadline is not None:
        b.date(dates, "PrtctDdln/Dt/Dt", event.dates.protect_deadline)
    assert event.dates.election_deadline is not None
    b.date(dates, "RspnDdln/Dt/Dt", event.dates.election_deadline)
    text = b.add(node, "AddtlInf/AddtlTxt")
    b.add(text, "Lang", "en")
    b.add(text, "AddtlInf", option.description)


def encode_announcement(event: CorporateActionEvent, release: Release) -> EncodedMessage:
    """``event`` as a DTC seev.031 announcement in ``release``."""
    b = _Builder(PROFILES[(release, MessageFamily.ANNOUNCEMENT)])
    general = b.add(b.root, "NtfctnGnlInf")
    b.add(general, "NtfctnTp", "NEWM")
    status = b.add(general, "PrcgSts/Cd")
    b.add(status, "EvtCmpltnsSts", "COMP")
    b.add(status, "EvtConfSts", "CONF")
    info = b.add(b.root, "CorpActnGnlInf")
    b.add(info, "CorpActnEvtId", _event_id(event.event_id))
    b.add(info, "EvtTp/Cd", EVENT_CODES[event.event_type])
    b.add(info, "MndtryVlntryEvtTp/Cd", PARTICIPATION_CODES[event.participation])
    b.add(info, "UndrlygScty/FinInstrmId/ISIN", _isin(event.security_id))
    b.add(b.root, "AcctDtls/ForAllAccts/IdCd", "GENR")
    dates = b.add(b.root, "CorpActnDtls/DtDtls")
    b.date(dates, "AnncmntDt/Dt/Dt", event.dates.announcement_date)
    if event.dates.record_date is not None:
        b.date(dates, "RcrdDt/Dt", event.dates.record_date)
    if event.dates.payable_date is not None:
        b.date(dates, "PmtDt/Dt", event.dates.payable_date)
    if not event.participation.elective:
        _terms_option(b, event)
        return b.encoded()
    if event.terms != EventTerms():
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "terms on an elective event are not carried; they belong to its options")
    if not event.options:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "an elective event without options cannot carry its election deadline")
    for option in event.options:
        _elective_option(b, event, option)
    return b.encoded()


def _read_terms(r: _Reader, option: ET.Element) -> EventTerms:
    cash = r.find(option, "CshMvmntDtls")
    securities = r.find(option, "SctiesMvmntDtls")
    if cash is not None and securities is None:
        rate = r.find(cash, "RateAndAmtDtls/GrssDstrbtnRate/RateTpAndAmtAndRateSts")
        if rate is None:
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "a cash option states no rate")
        if r.required(rate, "RateTp/Cd") != _INCOME_RATE:
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                          "only a gross income rate is modeled as a cash dividend rate")
        amount = r.find(rate, "Amt")
        assert amount is not None
        result = EventTerms(
            cash_rate_per_share=_parse_decimal(r.required(rate, "Amt"), "cash rate"),
            currency=amount.get("Ccy"),
        )
        text = r.text(option, "AddtlInf/AddtlTxt/AddtlInf")
        if text is not None and text.startswith("REINVESTMENT PRICE "):
            parts = text.split(" ")
            if len(parts) != 4:
                raise _refuse(AdapterRefusalReason.MALFORMED, "malformed reinvestment price")
            result = EventTerms(
                cash_rate_per_share=result.cash_rate_per_share,
                currency=parts[2],
                reinvestment_price_per_share=_parse_decimal(parts[3], "reinvestment price"),
            )
        return result
    if securities is not None and cash is None:
        for tag in ("AddtlQtyForExstgScties", "NewToOd"):
            node = r.find(securities, f"RateDtls/{tag}/QtyToQty")
            if node is None:
                continue
            first = _parse_decimal(r.required(node, "Qty1"), "ratio")
            second = _parse_decimal(r.required(node, "Qty2"), "ratio")
            if second == 0:
                raise _refuse(AdapterRefusalReason.MALFORMED, "a ratio's second quantity is zero")
            if tag == "AddtlQtyForExstgScties":
                return EventTerms(stock_rate_per_share=first / second)
            if first != first.to_integral_value() or second != second.to_integral_value():
                raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                              "a split ratio of fractional quantities is not modeled")
            return EventTerms(split_new=int(first), split_old=int(second))
    raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                  "a mandatory event's option carries exactly one cash or securities movement "
                  "with a rate this adapter models")


def decode_announcement(
    xml: bytes, release: Release, *, provenance: Provenance, source: SourceIdentity
) -> CorporateActionEvent:
    """Read a DTC seev.031 announcement in ``release``. The caller states who it came from."""
    _source_check(provenance)
    r = _Reader(xml, PROFILES[(release, MessageFamily.ANNOUNCEMENT)])
    info = r.find(r.root, "CorpActnGnlInf")
    if info is None:
        raise _refuse(AdapterRefusalReason.MALFORMED, "CorpActnGnlInf is required")
    event_type = _code(_EVENT_TYPES, r.required(info, "EvtTp/Cd"), "event type")
    participation = _code(_PARTICIPATIONS, r.required(info, "MndtryVlntryEvtTp/Cd"),
                          "participation")
    assert isinstance(event_type, EventType) and isinstance(participation, Participation)
    security = r.text(info, "UndrlygScty/FinInstrmId/ISIN")
    if security is None:
        raise _refuse(
            AdapterRefusalReason.NOT_REPRESENTABLE,
            "the underlying security is not an ISIN",
        )
    dates = r.find(r.root, "CorpActnDtls/DtDtls")
    announced = None if dates is None else r.date(dates, "AnncmntDt/Dt/Dt")
    if announced is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "the announcement date is not stated")
    options = r.findall(r.root, "CorpActnOptnDtls")
    terms, modeled_options, default = EventTerms(), [], None
    election_deadlines, protect_deadlines = set(), set()
    if not participation.elective:
        if len(options) > 1:
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                          "a mandatory event with more than one option is not modeled")
        if options:
            terms = _read_terms(r, options[0])
            if event_type is EventType.INTEREST_PAYMENT and terms.cash_rate_per_share is not None:
                terms = EventTerms(
                    interest_amount_per_face=terms.cash_rate_per_share, currency=terms.currency
                )
            elif event_type in {
                EventType.FINAL_MATURITY,
                EventType.PARTIAL_REDEMPTION,
                EventType.FULL_CALL,
                EventType.REDEMPTION_LOTTERY,
            } and terms.cash_rate_per_share is not None:
                terms = EventTerms(
                    redemption_price_per_face=terms.cash_rate_per_share, currency=terms.currency
                )
    else:
        for node in options:
            option_id = r.required(node, "OptnNb")
            text = r.find(node, "AddtlInf/AddtlTxt")
            description = None if text is None else r.text(text, "AddtlInf")
            if not description:
                raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                              f"option {option_id} states no description")
            modeled_options.append(ElectionOption(
                option_id=option_id, description=description,
                option_type=_option_type(r.required(node, "OptnTp/Cd")),
            ))
            if _one_of(r.required(node, "DfltPrcgOrStgInstr/DfltOptnInd"), _BOOLEAN, "default"):
                if default is not None:
                    raise _refuse(
                        AdapterRefusalReason.NOT_REPRESENTABLE,
                        "more than one default option",
                    )
                default = option_id
            election_deadlines.add(r.date(node, "DtDtls/RspnDdln/Dt/Dt"))
            protect_deadlines.add(r.date(node, "DtDtls/PrtctDdln/Dt/Dt"))
        if len(election_deadlines) > 1 or len(protect_deadlines) > 1:
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                          "options with different deadlines are not modeled")
    try:
        return CorporateActionEvent(
            event_id=r.required(info, "CorpActnEvtId"),
            security_id=security,
            event_type=event_type,
            participation=participation,
            dates=EventDates(
                announcement_date=announced,
                record_date=None if dates is None else r.date(dates, "RcrdDt/Dt"),
                election_deadline=next(iter(election_deadlines), None),
                protect_deadline=next(iter(protect_deadlines), None),
                payable_date=None if dates is None else r.date(dates, "PmtDt/Dt"),
            ),
            terms=terms,
            options=tuple(modeled_options),
            default_option_id=default,
            provenance=provenance,
            source=source,
        )
    except ValidationError as error:
        detail = error.errors()[0]["msg"]
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"the announcement is not a valid event: {detail}") from None


# --- instruction (seev.033) ------------------------------------------------------------------


def encode_instruction(
    instruction: ElectionInstruction, event: CorporateActionEvent, release: Release
) -> EncodedMessage:
    """``instruction`` against ``event`` as a DTC seev.033 instruction in ``release``."""
    code = EVENT_CODES[event.event_type]
    if code not in INSTRUCTION_EVENT_CODES:
        raise _refuse(AdapterRefusalReason.NOT_IN_PROFILE,
                      f"DTC's elective dividend instruction profile does not admit {code}")
    if instruction.protect:
        raise _refuse(AdapterRefusalReason.NOT_IN_PROFILE,
                      "DTC's elective dividend instruction profile carries no protect")
    option = next((o for o in event.options if o.option_id == instruction.option_id), None)
    if option is None or option.option_type is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"option {instruction.option_id!r} is not an announced option with a type")
    if not _OPTION_NUMBER.fullmatch(option.option_id):
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"option {option.option_id!r} is not a three-digit option number")
    b = _Builder(PROFILES[(release, MessageFamily.INSTRUCTION)])
    info = b.add(b.root, "CorpActnGnlInf")
    b.add(info, "CorpActnEvtId", _event_id(event.event_id))
    b.add(info, "EvtTp/Cd", code)
    b.add(b.root, "AcctDtls/SfkpgAcct",
          _checked(instruction.account_id, _FINX_35, "account", 35))
    detail = b.add(b.root, "CorpActnInstr")
    b.add(detail, "OptnNb/Nb", option.option_id)
    b.add(detail, "OptnTp/Cd", option.option_type.value)
    quantity_path = (
        "SctiesQtyOrInstdAmt/FaceAmt"
        if instruction.quantity_basis == "face_amount"
        else "SctiesQtyOrInstdAmt/SctiesQty/InstdQty/Qty/Unit"
    )
    b.add(
        detail,
        quantity_path,
        _decimal(instruction.quantity, _QUANTITY_DIGITS, "instructed quantity"),
    )
    return b.encoded()


def decode_instruction(
    xml: bytes,
    release: Release,
    *,
    event: CorporateActionEvent,
    instruction_id: str,
    received_date: date,
    provenance: Provenance,
    source: SourceIdentity,
) -> ElectionInstruction:
    """Read a DTC seev.033 instruction against ``event``.

    The message body carries no instruction identifier and no receipt date, so
    both come from the envelope it arrived in.
    """
    _source_check(provenance)
    r = _Reader(xml, PROFILES[(release, MessageFamily.INSTRUCTION)])
    event_id = r.required(r.root, "CorpActnGnlInf/CorpActnEvtId")
    code = r.required(r.root, "CorpActnGnlInf/EvtTp/Cd")
    if event_id != event.event_id or code != EVENT_CODES[event.event_type]:
        raise _refuse(AdapterRefusalReason.EVENT_MISMATCH,
                      f"the instruction is for {event_id} ({code}), not {event.event_id}")
    account = r.text(r.root, "AcctDtls/SfkpgAcct")
    if account is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "the instruction names no account")
    quantity = r.text(r.root, "CorpActnInstr/SctiesQtyOrInstdAmt/SctiesQty/InstdQty/Qty/Unit")
    face_amount = r.text(r.root, "CorpActnInstr/SctiesQtyOrInstdAmt/FaceAmt")
    if quantity is not None and face_amount is not None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "an instruction carries one quantity choice")
    quantity = quantity if quantity is not None else face_amount
    if quantity is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "only an instructed quantity in units is modeled")
    try:
        return ElectionInstruction(
            instruction_id=instruction_id,
            account_id=account,
            option_id=r.required(r.root, "CorpActnInstr/OptnNb/Nb"),
            quantity=_parse_decimal(quantity, "instructed quantity"),
            quantity_basis="face_amount" if face_amount is not None else "units",
            received_date=received_date,
            provenance=provenance,
            source=source,
        )
    except ValidationError as error:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"the instruction is not valid: {error.errors()[0]['msg']}") from None


# --- movement advice (seev.035) and confirmation (seev.036) -----------------------------------

_STAGES: Final[dict[str, MessageFamily]] = {
    "preliminary_advice": MessageFamily.MOVEMENT_PRELIMINARY_ADVICE,
    "confirmation": MessageFamily.MOVEMENT_CONFIRMATION,
}


def encode_movement(report: MovementReport, release: Release) -> EncodedMessage:
    """``report`` as a DTC seev.035 advice or seev.036 confirmation in ``release``."""
    advice = report.stage == "preliminary_advice"
    if not advice and report.option_type not in _CONFIRMATION_OPTION_TYPES:
        raise _refuse(AdapterRefusalReason.NOT_IN_PROFILE,
                      f"the confirmation profile does not admit option type {report.option_type}")
    b = _Builder(PROFILES[(release, _STAGES[report.stage])])
    if advice:
        general = b.add(b.root, "MvmntPrlimryAdvcGnlInf")
        b.add(general, "Tp", "NEWM")
        b.add(general, "Fctn", "CAPA")
    info = b.add(b.root, "CorpActnGnlInf")
    b.add(info, "CorpActnEvtId", _event_id(report.event_id))
    b.add(info, "EvtTp/Cd", EVENT_CODES[report.event_type])
    if advice:
        assert report.participation is not None
        b.add(info, "MndtryVlntryEvtTp/Cd", PARTICIPATION_CODES[report.participation])
        b.add(info, "UndrlygScty/FinInstrmId/ISIN", report.security_id)
        account = b.add(b.root, "AcctDtls/AcctsListAndBalDtls")
    else:
        b.add(info, "FinInstrmId/ISIN", report.security_id)
        account = b.add(b.root, "AcctDtls")
    b.add(account, "SfkpgAcct", _checked(report.account_id, _FINX_35, "account", 35))
    balances, values = b.add(account, "Bal"), report.balances
    if values.confirmed_balance is not None:
        _signed_balance(b, balances, "ConfdBal", values.confirmed_balance)
    if values.eligible_balance is not None:
        _eligible_balance(b, balances, values.eligible_balance)
    for tag, value in (("PdgDlvryBal", values.pending_delivery_balance),
                       ("PdgRctBal", values.pending_receipt_balance),
                       ("SttlmPosBal", values.settlement_position_balance)):
        if value is not None:
            _signed_balance(b, balances, tag, value)
    detail = b.add(b.root, "CorpActnMvmntDtls" if advice else "CorpActnConfDtls")
    b.add(detail, "OptnNb" if advice else "OptnNb/Nb", report.option_id)
    b.add(detail, "OptnTp/Cd", report.option_type.value)
    if advice:
        b.add(detail, "DfltPrcgOrStgInstr/DfltOptnInd",
              "true" if report.default_option else "false")
    direction = "CRDT" if report.direction == "credit" else "DBIT"
    movement = report.movement
    if isinstance(movement, CashMovement):
        cash = b.add(detail, "CshMvmntDtls")
        b.add(cash, "CdtDbtInd", direction)
        b.add(cash, "AmtDtls/EntitldAmt" if advice else "AmtDtls/PstngAmt",
              _decimal(movement.amount, _AMOUNT_DIGITS, "amount"), {"Ccy": movement.currency})
        b.date(cash, "DtDtls/PmtDt/Dt" if advice else "DtDtls/PstngDt/Dt", report.movement_date)
    else:
        securities = b.add(detail, "SctiesMvmntDtls")
        b.add(securities, "SctyDtls/FinInstrmId/ISIN" if advice else "FinInstrmId/ISIN",
              movement.security_id)
        b.add(securities, "CdtDbtInd", direction)
        b.add(securities, "EntitldQty/Qty/Unit" if advice else "PstngQty/Qty/Unit",
              _decimal(movement.quantity, _QUANTITY_DIGITS, "quantity"))
        b.date(securities, "DtDtls/PmtDt/Dt" if advice else "DtDtls/PstngDt/Dt",
               report.movement_date)
    return b.encoded()


def decode_movement(
    xml: bytes,
    release: Release,
    stage: Literal["preliminary_advice", "confirmation"],
    *,
    provenance: Provenance,
    source: SourceIdentity,
) -> MovementReport:
    """Read a DTC seev.035 advice or seev.036 confirmation in ``release``."""
    _source_check(provenance)
    advice = stage == "preliminary_advice"
    r = _Reader(xml, PROFILES[(release, _STAGES[stage])])
    info = r.find(r.root, "CorpActnGnlInf")
    if info is None:
        raise _refuse(AdapterRefusalReason.MALFORMED, "CorpActnGnlInf is required")
    event_type = _code(_EVENT_TYPES, r.required(info, "EvtTp/Cd"), "event type")
    assert isinstance(event_type, EventType)
    account = r.find(r.root, "AcctDtls/AcctsListAndBalDtls" if advice else "AcctDtls")
    detail = r.find(r.root, "CorpActnMvmntDtls" if advice else "CorpActnConfDtls")
    if account is None or detail is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "one account's balances and one option's movement are modeled")
    account_id = r.text(account, "SfkpgAcct")
    if account_id is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "the message names no account")
    balances = MovementBalances(
        eligible_balance=r.signed(account, "Bal/TtlElgblBal", eligible=True),
        confirmed_balance=r.signed(account, "Bal/ConfdBal"),
        pending_delivery_balance=r.signed(account, "Bal/PdgDlvryBal"),
        pending_receipt_balance=r.signed(account, "Bal/PdgRctBal"),
        settlement_position_balance=r.signed(account, "Bal/SttlmPosBal"),
    )
    cash, securities = r.find(detail, "CshMvmntDtls"), r.find(detail, "SctiesMvmntDtls")
    if (cash is None) == (securities is None):
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      "exactly one cash or one securities movement is modeled")
    movement: CashMovement | SecuritiesMovement
    if cash is not None:
        amount = r.find(cash, "AmtDtls/EntitldAmt" if advice else "AmtDtls/PstngAmt")
        if amount is None or amount.text is None:
            raise _refuse(
                AdapterRefusalReason.NOT_REPRESENTABLE,
                "the cash movement states no amount",
            )
        movement = CashMovement(amount=_parse_decimal(amount.text, "amount"),
                                currency=amount.get("Ccy", ""))
        moving, date_path = cash, "DtDtls/PmtDt/Dt" if advice else "DtDtls/PstngDt/Dt"
    else:
        assert securities is not None
        quantity = r.text(securities, "EntitldQty/Qty/Unit" if advice else "PstngQty/Qty/Unit")
        if quantity is None:
            raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                          "the securities movement states no quantity in units")
        movement = SecuritiesMovement(
            security_id=r.required(
                securities, "SctyDtls/FinInstrmId/ISIN" if advice else "FinInstrmId/ISIN"
            ),
            quantity=_parse_decimal(quantity, "quantity"),
        )
        moving, date_path = securities, "DtDtls/PmtDt/Dt" if advice else "DtDtls/PstngDt/Dt"
    moved = r.date(moving, date_path)
    if moved is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "the movement states no date")
    participation = None
    if advice:
        found = _code(_PARTICIPATIONS, r.required(info, "MndtryVlntryEvtTp/Cd"), "participation")
        assert isinstance(found, Participation)
        participation = found
    security = r.text(info, "UndrlygScty/FinInstrmId/ISIN" if advice else "FinInstrmId/ISIN")
    if security is None:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE, "the security is not an ISIN")
    try:
        return MovementReport(
            stage=stage,
            event_id=r.required(info, "CorpActnEvtId"),
            event_type=event_type,
            participation=participation,
            security_id=security,
            account_id=account_id,
            option_id=r.required(detail, "OptnNb" if advice else "OptnNb/Nb"),
            option_type=_option_type(r.required(detail, "OptnTp/Cd")),
            default_option=(
                _one_of(r.required(detail, "DfltPrcgOrStgInstr/DfltOptnInd"), _BOOLEAN, "default")
                if advice else None
            ),
            balances=balances,
            movement=movement,
            direction=(
                "credit" if _one_of(r.required(moving, "CdtDbtInd"), _CREDIT, "direction")
                else "debit"
            ),
            movement_date=moved,
            provenance=provenance,
            source=source,
        )
    except ValidationError as error:
        raise _refuse(AdapterRefusalReason.NOT_REPRESENTABLE,
                      f"the movement is not valid: {error.errors()[0]['msg']}") from None
