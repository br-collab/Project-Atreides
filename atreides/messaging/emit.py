"""ISO 20022 emit path — canonical model to network-native XML.

Per AUR-CUSTODY-CASH-001 v0.2 Section VIII. Two rules govern this module:

1. **The emitted package must be schema-valid without modification.** The
   member drops it into their own connection unchanged. Any requirement
   for the member to edit it before submission is a defect here.
2. **It is never a submission.** Atreides prepares, governs and reconciles;
   the entitled member submits (`AUR-CUSTODY-FED-001 §III`,
   `AUR-COCKPIT-001 §XI`). :class:`InstructionArtifact` pins
   ``is_submission`` to ``Literal[False]`` — the same control the cockpit
   uses to make a submission object unconstructible at the type layer.

No network calls, no clock, no I/O. Timestamps arrive on the instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from xml.etree import ElementTree as ET

from atreides.messaging.canonical import CashLegInstruction, FinancialInstitution
from atreides.messaging.profile import BASE_ISO_20022, DepositoryProfile

__all__ = [
    "InstructionArtifact",
    "emit_business_application_header",
    "emit_fi_credit_transfer",
    "emit_instruction_artifact",
]

def _iso_datetime(value: datetime) -> str:
    """Render as xs:dateTime.

    NOT ``strftime("%z")`` — that emits ``+0000``, which xs:dateTime
    rejects; it requires ``+00:00`` or ``Z``. This was caught by schema
    validation, not by review, and it is exactly the class of defect a
    hand-rolled assertion would have waved through and a depository would
    have bounced.
    """
    return value.isoformat()

_NS = "urn:iso:std:iso:20022:tech:xsd:{}"


@dataclass(frozen=True, slots=True)
class InstructionArtifact:
    """A prepared, schema-valid instruction package for human submission.

    Carries the header and document separately because venues differ on
    whether they want them wrapped in one envelope or delivered as a pair;
    that choice belongs to the member's connection, not to us.
    """

    header_xml: bytes
    document_xml: bytes
    message_definition: str
    profile_name: str
    profile_verified: bool
    dsor_lineage_uri: str | None
    #: Structural guarantee, not a comment. This artifact is prepared for
    #: the entitled member to submit; nothing in Atreides submits it.
    is_submission: Literal[False] = False


def _fmt_amount(amount: Decimal) -> str:
    """Render as ISO 20022 decimal — plain notation, no exponent.

    ``Decimal('1E+6')`` stringifies to scientific notation, which the
    schema's decimal type rejects. Plain formatting avoids that WITHOUT
    ``normalize()``, which would strip monetary scale — turning
    ``1000000.00`` into ``1000000``.
    """
    return format(amount, "f")


def _fi_element(parent: ET.Element, tag: str, fi: FinancialInstitution) -> None:
    """Render a BranchAndFinancialInstitutionIdentification8."""
    node = ET.SubElement(parent, tag)
    fin = ET.SubElement(node, "FinInstnId")
    ET.SubElement(fin, "BICFI").text = fi.bicfi
    if fi.name is not None:
        ET.SubElement(fin, "Nm").text = fi.name


def emit_business_application_header(
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
) -> bytes:
    """Emit head.001 ``AppHdr``.

    Mandatory children per the schema: ``Fr``, ``To``, ``BizMsgIdr``,
    ``MsgDefIdr``, ``CreDt``. Everything else is optional and omitted
    unless the profile supplies it — emitting optional fields the venue
    does not expect is how a technically-valid message gets rejected.
    """
    ns = _NS.format(profile.business_application_header)
    ET.register_namespace("", ns)
    hdr = ET.Element(f"{{{ns}}}AppHdr")

    for tag, party in (("Fr", instruction.sender), ("To", instruction.receiver)):
        node = ET.SubElement(hdr, tag)
        fiid = ET.SubElement(node, "FIId")
        fin = ET.SubElement(fiid, "FinInstnId")
        ET.SubElement(fin, "BICFI").text = party.bicfi

    ET.SubElement(hdr, "BizMsgIdr").text = instruction.message_id
    ET.SubElement(hdr, "MsgDefIdr").text = profile.fi_credit_transfer
    if profile.business_service is not None:
        ET.SubElement(hdr, "BizSvc").text = profile.business_service
    ET.SubElement(hdr, "CreDt").text = _iso_datetime(instruction.created_at)
    return ET.tostring(hdr, encoding="utf-8", xml_declaration=True)


def emit_fi_credit_transfer(
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
) -> bytes:
    """Emit pacs.009 ``Document`` — financial institution credit transfer.

    This is the cash leg between institutions. Mandatory path per the
    schema: ``GrpHdr`` (MsgId, CreDtTm, NbOfTxs, SttlmInf/SttlmMtd) and
    ``CdtTrfTxInf`` (PmtId/EndToEndId, IntrBkSttlmAmt, Dbtr, Cdtr).

    One transaction per message. Batching is a venue-profile decision and
    the base standard does not constrain it, so we do not assume it.
    """
    ns = _NS.format(profile.fi_credit_transfer)
    ET.register_namespace("", ns)
    doc = ET.Element(f"{{{ns}}}Document")
    body = ET.SubElement(doc, "FICdtTrf")

    grp = ET.SubElement(body, "GrpHdr")
    ET.SubElement(grp, "MsgId").text = instruction.message_id
    ET.SubElement(grp, "CreDtTm").text = _iso_datetime(instruction.created_at)
    ET.SubElement(grp, "NbOfTxs").text = "1"
    sttlm = ET.SubElement(grp, "SttlmInf")
    ET.SubElement(sttlm, "SttlmMtd").text = instruction.settlement_method.value

    tx = ET.SubElement(body, "CdtTrfTxInf")
    pmt = ET.SubElement(tx, "PmtId")
    ET.SubElement(pmt, "EndToEndId").text = instruction.end_to_end_id
    amt = ET.SubElement(tx, "IntrBkSttlmAmt")
    amt.set("Ccy", instruction.currency)
    amt.text = _fmt_amount(instruction.amount)
    _fi_element(tx, "Dbtr", instruction.debtor)
    _fi_element(tx, "Cdtr", instruction.creditor)

    return ET.tostring(doc, encoding="utf-8", xml_declaration=True)


def emit_instruction_artifact(
    instruction: CashLegInstruction,
    profile: DepositoryProfile = BASE_ISO_20022,
) -> InstructionArtifact:
    """Emit the full instruction package: header plus document.

    The returned artifact is what the cockpit's ``emit_instruction_package``
    hands the operator. It is a prepared artifact for human entry, never a
    submission.
    """
    return InstructionArtifact(
        header_xml=emit_business_application_header(instruction, profile),
        document_xml=emit_fi_credit_transfer(instruction, profile),
        message_definition=profile.fi_credit_transfer,
        profile_name=profile.name,
        profile_verified=profile.verified_against_published_spec,
        dsor_lineage_uri=instruction.dsor_lineage_uri,
    )
