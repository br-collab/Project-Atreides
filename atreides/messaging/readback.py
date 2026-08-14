"""Readback ingest - the venue's answer, brought back in by hand.

Per SPEC-READBACK-INGEST v0.1 and AUR-CUSTODY-CASH-001 Section VIII.

THE GAP THIS CLOSES
-------------------
Atreides prepares an instruction package and a human being submits it.
Nothing here calls a venue, holds a credential, or presses send, and that
constraint is permanent. The consequence is that the framework has emitted
and then gone blind: the decision-of-record carries what was decided and
what was prepared, and nothing about what happened.

This module closes the loop from the only direction available to a
participant that does not submit - the venue's own ``pacs.002`` status
report, carried back in by the same operator who took the instruction out.

It is the first point in the framework where reality is allowed to
contradict the record, and most of the code below is about what happens
when it does.

THE RULE THAT GOVERNS EVERYTHING ELSE
-------------------------------------
**Silence is not rejection.**

The funding model already holds that a queued payment is not a failed
payment, because classifying a queue as a failure and re-issuing produces a
duplicate payment which on a gross-final rail cannot be reversed. This
module is where that doctrine meets the operational moment at which the
mistake is actually made: the instruction went out, nothing has come back,
and somebody has to decide what that means.

It means nothing has been established. :func:`absent_readback` answers that
in one auditable place, as ``absent_gate_decision()``,
``absent_margin_assessment()`` and ``absent_determination_profile()`` answer
theirs. Four instances now, and the pattern is the framework's most-repeated
structural claim: **the absence of evidence is a state with a name, never a
default that reads as benign.**

SCHEMA VALIDITY IS A FLOOR
--------------------------
Every child of ``PaymentTransaction177`` is optional, so a schema-valid
status report can identify no original message, no original transaction, and
carry no status code at all. This is the same defect the canonical model
already names in ``FinancialInstitutionIdentification23``, and the answer is
the same: require what the business requires and refuse the rest, so an
unusable message fails at the boundary rather than three layers in.

Architectural contract: PURE, NO I/O, NO CLOCK, AND NO SUBMISSION. Bytes
arrive as an argument. Nothing here resubmits on any status - that is the
duplicate-payment interlock and it is the reason this module exists at all.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from atreides.messaging.canonical import CashLegInstruction

__all__ = [
    "DOCTRINE_VERSION",
    "MATCHED_STATUS_ORDER",
    "RECOGNISED_STATUS_CODES",
    "ReadbackBreak",
    "ReadbackBreakCode",
    "ReadbackMatch",
    "ReadbackParseError",
    "SettlementStatus",
    "StatusEntry",
    "StatusReport",
    "absent_readback",
    "classify_status_code",
    "ingest_readback",
    "parse_status_report",
    "reconcile",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-CASH-001-v0.2-SVIII-RB"

_PACS002_NS = re.compile(r"^urn:iso:std:iso:20022:tech:xsd:pacs\.002\.\d{3}\.\d{2}$")
_ROOT_ELEMENT: Final[str] = "FIToFIPmtStsRpt"


class ReadbackParseError(ValueError):
    """The bytes are not a usable status report.

    Raised rather than returned because a document that cannot be parsed is
    not a finding about a payment; it is a finding about the file, and the
    operator who supplied it is the one who can fix it.
    """


class SettlementStatus(StrEnum):
    """What a status code means for settlement.

    The ISO status field is an externalised code set and this framework does
    not claim to hold all of it. It recognises a deliberately small set and
    classifies the rest as UNRECOGNIZED, which is a break rather than a
    shrug.
    """

    RECEIVED = "received"
    """The venue has the instruction. Nothing further is established."""

    IN_PROGRESS = "in_progress"
    """Accepted and not settled."""

    ACCEPTED_NOT_POSTED = "accepted_not_posted"
    """Accepted and not posted to the account. Kept out of both neighbours
    on the same reasoning that produced WILL_QUEUE and FUNDED_QUALIFIED: it
    looks settled and is not, and an operator who reads "accepted" and acts
    as though the money moved has taken a position the record does not
    support."""

    ACCEPTED_WITH_CHANGE = "accepted_with_change"
    """Accepted on terms other than instructed. Always a break."""

    SETTLED = "settled"
    """Settlement completed."""

    REJECTED = "rejected"
    """Not settled, and the venue says why."""

    CANCELLED = "cancelled"
    """Withdrawn."""

    UNRECOGNIZED = "unrecognized"
    """Outside the recognised set. A code the framework does not understand
    is a code it cannot act on, and treating it as benign is the same
    failure as treating silence as success."""


#: The recognised codes, one venue's evidence at a time. Deliberately short.
#: Growth here should follow a message actually seen from a venue, not a
#: reading of the external code list.
RECOGNISED_STATUS_CODES: Final[dict[str, SettlementStatus]] = {
    "RCVD": SettlementStatus.RECEIVED,
    "ACTC": SettlementStatus.IN_PROGRESS,
    "ACCP": SettlementStatus.IN_PROGRESS,
    "ACSP": SettlementStatus.IN_PROGRESS,
    "PDNG": SettlementStatus.IN_PROGRESS,
    "ACWP": SettlementStatus.ACCEPTED_NOT_POSTED,
    "ACWC": SettlementStatus.ACCEPTED_WITH_CHANGE,
    "ACSC": SettlementStatus.SETTLED,
    "RJCT": SettlementStatus.REJECTED,
    "CANC": SettlementStatus.CANCELLED,
}


#: Progression order. Higher is further along. Terminal states share the top
#: rank because they are alternatives to each other rather than steps past
#: one another, which is what makes the conflict-versus-regression
#: distinction below computable.
MATCHED_STATUS_ORDER: Final[dict[SettlementStatus, int]] = {
    SettlementStatus.UNRECOGNIZED: 0,
    SettlementStatus.RECEIVED: 1,
    SettlementStatus.IN_PROGRESS: 2,
    SettlementStatus.ACCEPTED_NOT_POSTED: 3,
    SettlementStatus.ACCEPTED_WITH_CHANGE: 4,
    SettlementStatus.SETTLED: 4,
    SettlementStatus.REJECTED: 4,
    SettlementStatus.CANCELLED: 4,
}


def classify_status_code(code: str) -> SettlementStatus:
    """Map a raw ISO status code onto a settlement meaning.

    Unknown codes classify rather than raise, because an unknown code is a
    finding about a payment and the payment still needs a record.
    """
    return RECOGNISED_STATUS_CODES.get(code.strip().upper(), SettlementStatus.UNRECOGNIZED)


class ReadbackBreakCode(StrEnum):
    """Why a readback did not reconcile cleanly."""

    UNSOLICITED_STATUS = "unsolicited_status"
    """Status for an instruction this framework never prepared. The most
    interesting class here: Atreides never submits, so either the venue
    misrouted a message or a payment left the firm outside the governed
    path. The second is a governance failure no other surface can detect,
    and it is detectable here as a direct consequence of the no-submission
    constraint rather than in spite of it."""

    IDENTIFIER_DISAGREEMENT = "identifier_disagreement"
    """Message and end-to-end identifiers resolve to different prepared
    instructions. The framework does not pick; silently preferring one key
    is how a system acknowledges the wrong payment."""

    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    ACCEPTED_WITH_CHANGE = "accepted_with_change"

    STATUS_REGRESSION = "status_regression"
    """A terminal settled status followed by a non-settled one. Severe: a
    settlement the record shows as complete is being reported as not
    complete."""

    STATUS_CONFLICT = "status_conflict"
    """Two different statuses at the same progression level. Distinguished
    from a regression because the remedy differs - a conflict is usually a
    duplicate or crossed message, a regression is usually real."""

    UNRECOGNIZED_STATUS_CODE = "unrecognized_status_code"

    REJECTED = "rejected"
    """An instruction that passed every gate, was prepared and submitted,
    and did not settle. Needs no investigation and is still an event the
    decision-of-record must carry rather than a quiet terminal state."""

    MALFORMED_STATUS_ENTRY = "malformed_status_entry"

    NO_READBACK = "no_readback"
    """Nothing came back. Not a defect in a message - the absence of one.
    Distinct from every other code here because there is no venue assertion
    to disagree with, and because the wrong response to it is the one that
    produces duplicate payments."""


@dataclass(frozen=True, slots=True)
class ReadbackBreak:
    """One finding from a readback, with the evidence behind it."""

    code: ReadbackBreakCode
    detail: str
    end_to_end_id: str | None = None
    original_message_id: str | None = None
    status_code: str | None = None

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("a break with no detail is not a finding")


@dataclass(frozen=True, slots=True)
class StatusEntry:
    """One transaction-level status, as the venue reported it.

    Holds what was on the wire. Every field the venue did not populate stays
    None; nothing here is filled in from what the instruction said, because
    the whole purpose of the object is to be comparable against that
    instruction.
    """

    status_code: str
    status: SettlementStatus
    end_to_end_id: str | None = None
    original_transaction_id: str | None = None
    original_uetr: str | None = None
    reason_codes: tuple[str, ...] = ()
    echoed_amount: Decimal | None = None
    echoed_currency: str | None = None
    acceptance_datetime: str | None = None


@dataclass(frozen=True, slots=True)
class StatusReport:
    """A parsed ``pacs.002``.

    ``original_message_id`` is the group-level key. It is optional because a
    venue may report transaction statuses with no group block at all, and
    refusing that would refuse messages that are usable.
    """

    message_id: str
    created_at: str
    namespace: str
    original_message_id: str | None
    original_message_name_id: str | None
    group_status_code: str | None
    entries: tuple[StatusEntry, ...]


@dataclass(frozen=True, slots=True)
class ReadbackMatch:
    """The outcome of reconciling one status report against prepared work."""

    report: StatusReport
    #: end-to-end id -> the status the venue reported for it.
    matched: dict[str, SettlementStatus] = field(default_factory=dict)
    breaks: tuple[ReadbackBreak, ...] = ()
    #: True where nothing came back at all. See :func:`absent_readback`.
    is_absent: bool = False

    @property
    def clean(self) -> bool:
        """True where every entry matched and nothing broke."""
        return not self.breaks and not self.is_absent

    @property
    def settled_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(k for k, v in self.matched.items() if v is SettlementStatus.SETTLED)
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _localname(child.tag) == name:
            return child
    return None


def _findall(parent: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in parent if _localname(c.tag) == name]


def _text(parent: ET.Element | None, name: str) -> str | None:
    if parent is None:
        return None
    el = _find(parent, name)
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None


def parse_status_report(xml_bytes: bytes) -> StatusReport:
    """Parse a ``pacs.002`` status report.

    Requires, over and above schema validity:

    - The document root is the expected message. A ``pacs.008`` in a
      ``pacs.002`` slot is refused rather than parsed for whatever happens
      to match.
    - The namespace is read from the document rather than assumed, so a
      venue on a different minor version is a parse question rather than a
      silent zero-match.
    - Every status entry carries a code and at least one identifier. An
      entry with neither is not a status report about anything.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ReadbackParseError(f"not well-formed XML: {exc}") from exc

    if _localname(root.tag) != "Document":
        raise ReadbackParseError(
            f"expected a Document root, got {_localname(root.tag)!r}"
        )

    namespace = root.tag[1:].rsplit("}", 1)[0] if root.tag.startswith("{") else ""
    if not _PACS002_NS.match(namespace):
        raise ReadbackParseError(
            f"namespace {namespace!r} is not a pacs.002 namespace; refusing to "
            f"parse a message of one definition as another"
        )

    report_el = _find(root, _ROOT_ELEMENT)
    if report_el is None:
        raise ReadbackParseError(
            f"no {_ROOT_ELEMENT} element; the namespace says pacs.002 and the "
            f"body does not"
        )

    grp_hdr = _find(report_el, "GrpHdr")
    message_id = _text(grp_hdr, "MsgId")
    created_at = _text(grp_hdr, "CreDtTm")
    if message_id is None or created_at is None:
        raise ReadbackParseError("GrpHdr must carry MsgId and CreDtTm")

    grp_info = _find(report_el, "OrgnlGrpInfAndSts")

    entries: list[StatusEntry] = []
    for tx in _findall(report_el, "TxInfAndSts"):
        code = _text(tx, "TxSts")
        e2e = _text(tx, "OrgnlEndToEndId")
        tx_id = _text(tx, "OrgnlTxId")
        uetr = _text(tx, "OrgnlUETR")

        if code is None:
            raise ReadbackParseError(
                "a status entry carries no TxSts. The schema permits this and "
                "the business cannot use it: a status report with no status is "
                "not a report about anything"
            )
        if e2e is None and tx_id is None and uetr is None:
            raise ReadbackParseError(
                "a status entry carries no original identifier. Schema-valid "
                "and unusable: it reports a status about nothing identifiable"
            )

        amount, currency = _echoed_amount(tx)
        entries.append(
            StatusEntry(
                status_code=code,
                status=classify_status_code(code),
                end_to_end_id=e2e,
                original_transaction_id=tx_id,
                original_uetr=uetr,
                reason_codes=_reason_codes(tx),
                echoed_amount=amount,
                echoed_currency=currency,
                acceptance_datetime=_text(tx, "AccptncDtTm"),
            )
        )

    return StatusReport(
        message_id=message_id,
        created_at=created_at,
        namespace=namespace,
        original_message_id=_text(grp_info, "OrgnlMsgId"),
        original_message_name_id=_text(grp_info, "OrgnlMsgNmId"),
        group_status_code=_text(grp_info, "GrpSts"),
        entries=tuple(entries),
    )


def _reason_codes(tx: ET.Element) -> tuple[str, ...]:
    codes: list[str] = []
    for sts_rsn in _findall(tx, "StsRsnInf"):
        rsn = _find(sts_rsn, "Rsn")
        code = _text(rsn, "Cd") if rsn is not None else None
        if code:
            codes.append(code)
    return tuple(codes)


def _echoed_amount(tx: ET.Element) -> tuple[Decimal | None, str | None]:
    """Read the venue's echoed settlement amount, if it echoed one.

    A malformed amount is recorded as absent rather than raising. The
    document is otherwise usable and the mismatch checks downstream will
    simply have nothing to compare - which is honest, where refusing the
    whole message over one unparseable field would not be.
    """
    ref = _find(tx, "OrgnlTxRef")
    if ref is None:
        return None, None
    amt_el = _find(ref, "IntrBkSttlmAmt")
    if amt_el is None or amt_el.text is None:
        return None, None
    try:
        amount = Decimal(amt_el.text.strip())
    except (InvalidOperation, ArithmeticError):
        return None, None
    return amount, amt_el.get("Ccy")


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile(
    report: StatusReport,
    prepared: tuple[CashLegInstruction, ...],
    known_statuses: dict[str, SettlementStatus] | None = None,
) -> ReadbackMatch:
    """Reconcile a parsed report against what this framework prepared.

    ``known_statuses`` carries what was already established for each
    end-to-end identifier, so progression and regression are computable
    without this module holding state or consulting a clock.

    **Agreement is the match. Disagreement is a break.** Where the
    end-to-end identifier resolves to one instruction and the message
    identifier to another, the framework does not choose between them.
    """
    by_e2e = {i.end_to_end_id: i for i in prepared}
    by_msg = {i.message_id: i for i in prepared}
    prior = dict(known_statuses or {})

    matched: dict[str, SettlementStatus] = {}
    breaks: list[ReadbackBreak] = []

    msg_instruction = (
        by_msg.get(report.original_message_id)
        if report.original_message_id is not None
        else None
    )

    for entry in report.entries:
        e2e = entry.end_to_end_id
        if e2e is None:
            breaks.append(
                ReadbackBreak(
                    ReadbackBreakCode.MALFORMED_STATUS_ENTRY,
                    "status entry identifies a transaction but carries no "
                    "OrgnlEndToEndId; this revision matches on the end-to-end "
                    "identifier only",
                    original_message_id=report.original_message_id,
                    status_code=entry.status_code,
                )
            )
            continue

        instruction = by_e2e.get(e2e)
        if instruction is None:
            breaks.append(
                ReadbackBreak(
                    ReadbackBreakCode.UNSOLICITED_STATUS,
                    f"status reported for end-to-end id {e2e!r}, which this "
                    f"framework never prepared. Atreides does not submit, so "
                    f"this is either a venue misroute or a payment that left "
                    f"the firm outside the governed path",
                    end_to_end_id=e2e,
                    original_message_id=report.original_message_id,
                    status_code=entry.status_code,
                )
            )
            continue

        if msg_instruction is not None and msg_instruction is not instruction:
            breaks.append(
                ReadbackBreak(
                    ReadbackBreakCode.IDENTIFIER_DISAGREEMENT,
                    f"OrgnlEndToEndId {e2e!r} resolves to the instruction with "
                    f"message id {instruction.message_id!r}, while OrgnlMsgId "
                    f"{report.original_message_id!r} resolves to a different "
                    f"prepared instruction. The framework does not choose "
                    f"between them",
                    end_to_end_id=e2e,
                    original_message_id=report.original_message_id,
                    status_code=entry.status_code,
                )
            )
            continue

        breaks.extend(_entry_breaks(entry, instruction, prior.get(e2e)))
        matched[e2e] = entry.status

    return ReadbackMatch(report=report, matched=matched, breaks=tuple(breaks))


def _entry_breaks(
    entry: StatusEntry,
    instruction: CashLegInstruction,
    prior_status: SettlementStatus | None,
) -> list[ReadbackBreak]:
    """Findings about a matched entry. Order is stable for replay."""
    out: list[ReadbackBreak] = []
    e2e = entry.end_to_end_id

    if entry.status is SettlementStatus.UNRECOGNIZED:
        out.append(
            ReadbackBreak(
                ReadbackBreakCode.UNRECOGNIZED_STATUS_CODE,
                f"status code {entry.status_code!r} is not in the recognised "
                f"set. A code the framework does not understand is a code it "
                f"cannot act on",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        )

    if entry.status is SettlementStatus.ACCEPTED_WITH_CHANGE:
        out.append(
            ReadbackBreak(
                ReadbackBreakCode.ACCEPTED_WITH_CHANGE,
                f"venue accepted {e2e!r} on terms other than instructed",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        )

    if entry.status is SettlementStatus.REJECTED:
        reasons = ", ".join(entry.reason_codes) or "no reason code supplied"
        out.append(
            ReadbackBreak(
                ReadbackBreakCode.REJECTED,
                f"venue rejected {e2e!r} ({reasons}). Governed, prepared, "
                f"submitted, and did not settle",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        )

    if entry.echoed_amount is not None and entry.echoed_amount != instruction.amount:
        out.append(
            ReadbackBreak(
                ReadbackBreakCode.AMOUNT_MISMATCH,
                f"venue echoed {entry.echoed_amount} against an instructed "
                f"{instruction.amount}",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        )

    if (
        entry.echoed_currency is not None
        and entry.echoed_currency != instruction.currency
    ):
        out.append(
            ReadbackBreak(
                ReadbackBreakCode.CURRENCY_MISMATCH,
                f"venue echoed {entry.echoed_currency} against an instructed "
                f"{instruction.currency}",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        )

    out.extend(_progression_break(entry, prior_status))
    return out


def _progression_break(
    entry: StatusEntry, prior_status: SettlementStatus | None
) -> list[ReadbackBreak]:
    """Forward movement is normal. Backward from settled is severe."""
    if prior_status is None or prior_status is entry.status:
        # Venues resend. An identical status arriving twice is idempotent.
        return []

    e2e = entry.end_to_end_id
    prior_rank = MATCHED_STATUS_ORDER[prior_status]
    new_rank = MATCHED_STATUS_ORDER[entry.status]

    if prior_status is SettlementStatus.SETTLED:
        return [
            ReadbackBreak(
                ReadbackBreakCode.STATUS_REGRESSION,
                f"{e2e!r} was reported SETTLED and is now reported "
                f"{entry.status.value}. A settlement the record shows as "
                f"complete is being reported as not complete",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        ]

    if new_rank < prior_rank:
        return [
            ReadbackBreak(
                ReadbackBreakCode.STATUS_REGRESSION,
                f"{e2e!r} moved backward from {prior_status.value} to "
                f"{entry.status.value}",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        ]

    if new_rank == prior_rank:
        return [
            ReadbackBreak(
                ReadbackBreakCode.STATUS_CONFLICT,
                f"{e2e!r} carries two different statuses at the same "
                f"progression level: {prior_status.value} and "
                f"{entry.status.value}. Usually a duplicate or crossed message "
                f"rather than a real reversal",
                end_to_end_id=e2e,
                status_code=entry.status_code,
            )
        ]

    return []


# ---------------------------------------------------------------------------
# Ingest and the absent default
# ---------------------------------------------------------------------------


def ingest_readback(
    xml_bytes: bytes,
    prepared: tuple[CashLegInstruction, ...],
    known_statuses: dict[str, SettlementStatus] | None = None,
) -> ReadbackMatch:
    """Parse and reconcile in one call. Deterministic, pure, replayable.

    Nothing here resubmits on any status. That is the duplicate-payment
    interlock, and it is the reason this module exists.
    """
    return reconcile(parse_status_report(xml_bytes), prepared, known_statuses)


def absent_readback(reason: str = "no status report has been received") -> ReadbackMatch:
    """The absent-readback default: nothing established, never a failure.

    **Silence is not rejection.** An instruction with no status report is not
    an instruction that failed, and treating it as one is precisely the
    mechanism that produces duplicate payments on a gross-final rail.

    Named and exported so that "what happens when nothing came back" is
    answered in one auditable place rather than implicitly at every call
    site. Mirrors ``absent_gate_decision()``,
    ``absent_margin_assessment()`` and ``absent_determination_profile()``.
    """
    return ReadbackMatch(
        report=StatusReport(
            message_id="",
            created_at="",
            namespace="",
            original_message_id=None,
            original_message_name_id=None,
            group_status_code=None,
            entries=(),
        ),
        matched={},
        breaks=(
            ReadbackBreak(
                ReadbackBreakCode.NO_READBACK,
                f"{reason}. Nothing is established: not settlement, not "
                f"rejection. Re-issuing on this basis produces a duplicate "
                f"payment (CASH-001 SVII, SVIII).",
            ),
        ),
        is_absent=True,
    )
