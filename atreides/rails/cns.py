"""Continuous net settlement - the equities rail.

Per AUR-CUSTODY-CASH-001 Section IV (deferred-net finality) and
AUR-CUSTODY-001 v1.0 Section V (Equities). Doctrine draft:
AUR-CUSTODY-EQUITY-001.

WHY THIS IS NOT THE TREASURY RAIL WITH DIFFERENT LABELS
-------------------------------------------------------
The Treasury complex settles trade by trade and the framework's models were
built on that shape: an instruction, a rail, a finality class, a funding
question. Equities in a continuous net settlement system break the first
assumption and everything downstream of it.

Two things happen before anything settles. The clearing corporation
**novates**, becoming the counterparty to both sides, and it **nets**, so
what settles is one position per security per member rather than a queue of
trades. By the time settlement runs, the trades are gone as settlement
objects.

The consequence is the load-bearing claim of this module: **a trade that
fails in a netted system did not fail as a trade.** The net position failed.
Which underlying trade "caused" it is not observable from the participant
seat, because the netting destroyed the correspondence and the allocation of
whatever shares were available is the clearing corporation's algorithm
rather than the member's. A framework that reports a per-trade fail is
reporting an inference, and it should say so or say nothing.

This module says nothing, loudly. There is no ``attribute_fail_to_trade``
function, and :func:`absent_trade_attribution` exists to answer why in one
auditable place. That is a refusal of the same kind as the margin engine
this framework also declines to build.

PARTIAL IS NORMAL
-----------------
A netted settlement delivers what is available. Partial allocation is the
ordinary case rather than an exception path, and a model whose success state
is all-or-nothing will classify a normal day as a failure. So the
disposition set separates full settlement from partial allocation from a
true fail, and partial allocation carries the residual rather than being
folded into either neighbour.

CORPORATE ACTIONS: THE CONDITION IS PUBLISHED, THE TREATMENT IS NOT
-------------------------------------------------------------------
Depository corporate-action usage guidance describes the open-position
problem in detail. It separates an eligible position from a settlement
position, states that the two diverge where position moved after record-date
capture, and carries pending-delivery and pending-receipt balances - fails
short and fails long - on the movement advice and the movement confirmation.
Lottery events get an obligated balance; voluntary events get an uncovered
protect balance.

It does not state the entitlement treatment. No rule for how an entitlement
is allocated when delivery has not occurred by the record date, and no
mention of due bills or claims at all.

So :class:`RecordDatePosition` adopts that vocabulary exactly and
:func:`absent_entitlement_treatment` refuses to go further. Computing an
outcome here would be inventing market practice and presenting it as
governance, which is the same error as reverse-engineering an undisclosed
margin methodology and worse, because it would produce a number somebody
might act on.

DIRECTION IS NOT SYMMETRIC
--------------------------
A fail to deliver and a fail to receive are the same event from opposite
sides with different remedies and different regulatory consequences. They
are recorded as different dispositions, not as one disposition with a sign,
for the same reason the margin model records direction separately from
disposition.

Architectural contract: PURE, NO I/O, NO CLOCK. Every offset and every date
arrives as a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from atreides.rails.finality import FinalityClass

__all__ = [
    "DOCTRINE_VERSION",
    "NO_ENTITLEMENT_COMPUTATION_API",
    "NO_TRADE_LEVEL_FAIL_API",
    "CNSDisposition",
    "CloseOutRegime",
    "FailPosition",
    "MarketProfile",
    "NetPosition",
    "NetSettlementResult",
    "ProcessingDateRule",
    "RecordDatePosition",
    "SecuritiesBreak",
    "SecuritiesBreakCode",
    "absent_entitlement_treatment",
    "absent_market_profile",
    "absent_processing_date",
    "absent_trade_attribution",
    "close_out_deadline",
    "net_positions",
    "processing_date_offset",
    "settle_net_position",
]

DOCTRINE_VERSION: Final[str] = "AUR-CUSTODY-EQUITY-001-draft-v0.1"

#: The finality class every position on this rail carries. Stated as a
#: constant rather than passed in, because a continuous net settlement
#: system has exactly one, and a caller who could override it could assert a
#: gross-final equity settlement that does not occur.
CNS_FINALITY: Final[FinalityClass] = FinalityClass.DEFERRED_NET


class CloseOutRegime(StrEnum):
    """How, and on what clock, an open fail must be closed out.

    Read from the market's own rules. The framework holds the structure and
    refuses to hold a number it has not read, on the same discipline as
    every other registry here.
    """

    NOT_ASSESSED = "not_assessed"
    """Nobody has read this market's close-out rules. NOT the same as "this
    market has none"; the remedy is research."""

    NONE_PUBLISHED = "none_published"
    """Read, and the market publishes no mandatory close-out."""

    MANDATORY_DEADLINE = "mandatory_deadline"
    """Read, and the market imposes a deadline. The deadline itself is
    carried on the profile, in the market's own units."""


class ProcessingDateRule(StrEnum):
    """How a market fixes the business date a trade is processed for.

    A settlement cycle is an integer of business days. That integer answers
    "how long after the processing date does this settle", and it silently
    assumes the answer to a prior question: **which business date is the
    processing date.** In a market that trades within one session per day,
    the two questions collapse into one and the assumption is free.

    Extended-hours US equities separated them. The SEC order approving
    NSCC's 24x5 clearing defines a Trade Processing Date - the business date
    a trade is expected to clear for - and fixes its boundary with a Good
    Night Message sent by each market around midnight. Trades submitted
    before it are processed for that business date; trades after it roll to
    the next.

    So a trade at 11:58 PM and a trade at 12:02 AM can carry different
    processing dates, and which one applies is **not derivable from the
    timestamp**. It depends on when the market sent its message. An integer
    cycle cannot express that, and a framework that stores only the integer
    will compute a settlement date that is right most nights and wrong on
    the nights that matter.

    This enumeration therefore records how the boundary is fixed, and the
    cycle integer becomes meaningful only once the processing date is known.
    """

    NOT_ASSESSED = "not_assessed"
    """Nobody has read how this market fixes its processing date. NOT the
    same as a fixed cycle, and defaulting to a fixed cycle is the specific
    error this member exists to prevent."""

    FIXED_CYCLE_FROM_TRADE_DATE = "fixed_cycle_from_trade_date"
    """Read, and the processing date is the trade date. The settlement cycle
    counts from the trade date directly and a timestamp is sufficient."""

    SESSION_CLOSURE_MESSAGE = "session_closure_message"
    """Read, and the processing date is fixed by a message the market sends
    at the close of a session rather than by a clock. A timestamp alone does
    not establish which business date a trade clears for."""


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """One securities market's settlement characteristics.

    Parallel in construction and discipline to ``DepositoryProfile``, the
    venue margin profile and the determination profile. Unpopulated entries
    are flagged, never inferred, and never defaulted to the US convention
    because the US convention is the one most likely to be assumed and
    therefore the one most dangerous to default to.
    """

    market_id: str

    #: Settlement cycle in business days **from the processing date**.
    #: ``None`` where unread. Recorded rather than assumed: markets have
    #: moved cycles recently and in different years, and a hardcoded value
    #: would be silently wrong for whichever market moved last.
    #:
    #: Read this together with ``processing_date_rule``. On a market that
    #: fixes its processing date by a session-closure message, this integer
    #: does not on its own yield a settlement date - see
    #: :func:`absent_processing_date`.
    settlement_cycle_days: int | None = None

    #: How this market fixes the business date a trade is processed for.
    #: Separate from the cycle because the cycle counts *from* that date and
    #: cannot establish it.
    processing_date_rule: ProcessingDateRule = ProcessingDateRule.NOT_ASSESSED
    #: Under SESSION_CLOSURE_MESSAGE, the market's own name for the message
    #: that closes the session - "Good Night Message" at NSCC. Carried in
    #: the market's language rather than normalised, because an operator
    #: chasing a rolled processing date searches for the market's term.
    session_closure_message: str | None = None

    close_out_regime: CloseOutRegime = CloseOutRegime.NOT_ASSESSED
    #: Business days from the settlement date by which an open fail must be
    #: closed out. Only meaningful under MANDATORY_DEADLINE.
    close_out_deadline_days: int | None = None

    #: Whether the clearing corporation publishes how it allocates available
    #: shares among members with open receives. Where it does not, the
    #: framework cannot explain why a member received what it received, and
    #: says so rather than modelling a plausible rule.
    allocation_rule_published: bool = False

    provenance: str | None = None

    def __post_init__(self) -> None:
        # Coerce at the boundary - see DeterminationProfile for the reasoning.
        # An exported profile that cannot be read back in is not portable.
        if not isinstance(self.close_out_regime, CloseOutRegime):
            object.__setattr__(
                self, "close_out_regime", CloseOutRegime(self.close_out_regime)
            )
        if not isinstance(self.processing_date_rule, ProcessingDateRule):
            object.__setattr__(
                self,
                "processing_date_rule",
                ProcessingDateRule(self.processing_date_rule),
            )

        if not self.market_id:
            raise ValueError("market_id is required")
        assessed = self.close_out_regime is not CloseOutRegime.NOT_ASSESSED
        if assessed and not self.provenance:
            raise ValueError(
                "an assessed market profile requires provenance; an "
                "unattributed profile is indistinguishable from a guess"
            )
        if not assessed and (
            self.close_out_deadline_days is not None
            or self.settlement_cycle_days is not None
            or self.processing_date_rule is not ProcessingDateRule.NOT_ASSESSED
        ):
            raise ValueError(
                "a NOT_ASSESSED profile may not state a settlement cycle, a "
                "close-out deadline or a processing-date rule; you cannot "
                "record a rule you have not read"
            )
        if (
            self.close_out_regime is CloseOutRegime.MANDATORY_DEADLINE
            and self.close_out_deadline_days is None
        ):
            raise ValueError(
                "MANDATORY_DEADLINE requires close_out_deadline_days; asserting "
                "a deadline without stating it is not a rule anybody can meet"
            )
        if (
            self.close_out_regime is not CloseOutRegime.MANDATORY_DEADLINE
            and self.close_out_deadline_days is not None
        ):
            raise ValueError(
                "close_out_deadline_days is meaningful only under "
                "MANDATORY_DEADLINE"
            )
        message_determined = (
            self.processing_date_rule is ProcessingDateRule.SESSION_CLOSURE_MESSAGE
        )
        if message_determined and not self.session_closure_message:
            raise ValueError(
                "SESSION_CLOSURE_MESSAGE requires the message to be named; an "
                "operator reconciling a rolled processing date needs the "
                "market's own term for it, not a flag"
            )
        if self.session_closure_message and not message_determined:
            raise ValueError(
                "session_closure_message is meaningful only under "
                "SESSION_CLOSURE_MESSAGE"
            )


    @property
    def settlement_date_follows_from_trade_date(self) -> bool:
        """True only where a trade timestamp is sufficient to date settlement.

        False under NOT_ASSESSED as well as under SESSION_CLOSURE_MESSAGE,
        and deliberately so: "we have not read how this market fixes its
        processing date" must not read the same as "the trade date is the
        processing date". That collapse is the whole defect this field was
        added to close.
        """
        return (
            self.processing_date_rule
            is ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE
            and self.settlement_cycle_days is not None
        )


def absent_market_profile(market_id: str) -> MarketProfile:
    """Return the profile for a market with no registry entry.

    Named and exported so "what happens when no profile exists" is answered
    in one auditable place. Mirrors ``absent_gate_decision()``,
    ``absent_margin_profile()`` and ``absent_determination_profile()``.
    """
    return MarketProfile(market_id=market_id)


def close_out_deadline(
    profile: MarketProfile, settlement_date_offset_days: int
) -> int | None:
    """Business-day offset by which an open fail must be closed out.

    Returns ``None`` where the market publishes no deadline **and** where
    nobody has read its rules. Those are different states and the caller
    distinguishes them by reading ``close_out_regime`` - this function
    deliberately does not encode a difference in its return value, because a
    caller that treats "no deadline" and "unread" the same way has a bug the
    profile is designed to surface, not to hide.
    """
    if profile.close_out_regime is not CloseOutRegime.MANDATORY_DEADLINE:
        return None
    assert profile.close_out_deadline_days is not None  # enforced in __post_init__
    return settlement_date_offset_days + profile.close_out_deadline_days


def processing_date_offset(
    profile: MarketProfile, position: NetPosition
) -> int | None:
    """Business-date offset, from trade date, this position clears for.

    Returns ``0`` on a market whose processing date is the trade date, the
    offset the market assigned on a market that fixes the date by message,
    and ``None`` wherever the date is not established - including where
    nobody has read the market's rule.

    ``None`` is returned for two different reasons and the function does not
    distinguish them, on the same discipline as :func:`close_out_deadline`:
    a caller that treats "the market has not sent its message yet" and "we
    never read how this market works" as the same condition has a bug the
    profile exists to surface rather than to smooth over.
    """
    if profile.processing_date_rule is ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE:
        return 0
    if profile.processing_date_rule is ProcessingDateRule.SESSION_CLOSURE_MESSAGE:
        return position.assigned_processing_date_offset_days
    return None


class CNSDisposition(StrEnum):
    """What happened to one net position at settlement."""

    SETTLED_IN_FULL = "settled_in_full"
    """The whole net position moved."""

    PARTIAL_ALLOCATION = "partial_allocation"
    """Some of the position moved. The ordinary case in a netted system, not
    an exception path, and kept out of both neighbours because a model whose
    success state is all-or-nothing classifies a normal day as a failure."""

    FAILED_TO_DELIVER = "failed_to_deliver"
    """The member owes securities it did not deliver. Carries a close-out
    obligation where the market imposes one."""

    FAILED_TO_RECEIVE = "failed_to_receive"
    """The member is owed securities it did not receive. Same event from the
    other side, different remedy, and not the negative of the above."""

    FLAT = "flat"
    """The net position is zero. Nothing settles and nothing failed; the
    trades netted out against each other."""

    NOT_NOVATED = "not_novated"
    """The trade did not enter the netting system - ex-clearing, a locked-in
    away-settlement, or a rejected submission. It settles bilaterally and
    this model does not govern it."""

    INDETERMINATE = "indeterminate"
    """The settlement outcome is not observable. The fail-safe default: a
    position with no reported outcome is not a settled position."""


@dataclass(frozen=True, slots=True)
class NetPosition:
    """One member's net obligation in one security after novation and netting.

    ``quantity`` is signed: positive is a net receive, negative is a net
    deliver. Signed rather than split into two fields because the netting
    itself produces one number, and splitting it here would invite a caller
    to populate both.
    """

    security_id: str
    quantity: Decimal
    settlement_date_offset_days: int
    market_id: str
    #: How many underlying trades netted into this position. Recorded for
    #: the record's sake and NEVER used to attribute an outcome back to any
    #: of them - see :func:`absent_trade_attribution`.
    constituent_trade_count: int = 0

    #: On a market that fixes its processing date by a session-closure
    #: message, the business-date offset the market actually assigned this
    #: position, as reported by the market. ``None`` means the market has
    #: not told us - which on such a market is a live unknown, not a
    #: default - and ``None`` is also the correct value on a fixed-cycle
    #: market, where the trade date is the processing date and nothing needs
    #: to be assigned. The profile distinguishes those two cases; this field
    #: deliberately does not, because a field that encoded the difference
    #: would let a caller answer the question without reading the profile.
    assigned_processing_date_offset_days: int | None = None

    @property
    def is_receive(self) -> bool:
        return self.quantity > 0

    @property
    def is_deliver(self) -> bool:
        return self.quantity < 0

    @property
    def finality_class(self) -> FinalityClass:
        return CNS_FINALITY


@dataclass(frozen=True, slots=True)
class FailPosition:
    """An open fail carried forward, in the units it is actually owed in."""

    security_id: str
    quantity: Decimal
    aged_days: int
    close_out_deadline_offset_days: int | None
    #: True where a corporate action has restated this quantity. Recorded so
    #: an operator can tell a restated fail from an original one; the two
    #: reconcile against different source records.
    restated_by_corporate_action: bool = False


@dataclass(frozen=True, slots=True)
class RecordDatePosition:
    """Balances at a corporate-action record date, in the published vocabulary.

    Every field name here traces to a term used in depository corporate-action
    usage guidance rather than to one this framework invented. That is the
    seam rule: adopt the standard's language where the standard speaks, and
    keep this framework's language for the decision layer, which the guidance
    does not address.

    The object holds balances and asserts no outcome. There is no
    ``entitlement`` field and there will not be one - see
    :func:`absent_entitlement_treatment`.
    """

    security_id: str

    #: The balance the event is calculated against.
    eligible_balance: Decimal
    #: The balance actually settled. Normally equal to eligible, and not
    #: equal where position moved after record-date capture.
    settlement_balance: Decimal

    #: Fails short. Carried on the movement advice and confirmation.
    pending_delivery_balance: Decimal = Decimal(0)
    #: Fails long. Same.
    pending_receipt_balance: Decimal = Decimal(0)

    #: Lottery and partial-call events: the called quantity that exceeds the
    #: settled position and must be returned.
    obligated_balance: Decimal = Decimal(0)
    #: Voluntary events: protect instructions not covered by delivery.
    uncovered_protect_balance: Decimal = Decimal(0)

    #: Provenance for the guidance this profile of balances was populated
    #: against. Same discipline as every other registry here.
    provenance: str | None = None

    @property
    def diverges(self) -> bool:
        """True where the eligible and settled balances are not the same.

        The condition the guidance names. Not itself a finding about who is
        owed what.
        """
        return self.eligible_balance != self.settlement_balance

    @property
    def divergence(self) -> Decimal:
        return self.eligible_balance - self.settlement_balance


class SecuritiesBreakCode(StrEnum):
    """Break taxonomy for the equities rail."""

    FAIL_TO_DELIVER = "fail_to_deliver"
    """The member owes securities it did not deliver."""
    FAIL_TO_RECEIVE = "fail_to_receive"
    """The member is owed securities it did not receive."""

    PARTIAL_WITH_UNEXPLAINED_ALLOCATION = "partial_with_unexplained_allocation"
    """A partial allocation on a market that does not publish its allocation
    rule. The member cannot explain why it received what it received, and
    the framework will not manufacture an explanation."""

    CLOSE_OUT_DEADLINE_UNREADABLE = "close_out_deadline_unreadable"
    """An open fail on a market whose close-out rules have not been read.
    Closed by populating the registry, not by any market action."""

    CLOSE_OUT_DEADLINE_PASSED = "close_out_deadline_passed"
    """An open fail is past the market's published close-out deadline."""

    ELIGIBLE_SETTLED_DIVERGENCE = "eligible_settled_divergence"
    """An open position at a corporate-action record date, so the eligible
    balance and the settled balance are not the same number.

    This is the condition published depository guidance names and carries -
    as an eligible-versus-settlement position distinction, and as pending
    delivery and pending receipt balances riding on the entitlement and
    confirmation messages. What that guidance does NOT state is the
    entitlement treatment: which side ends up owed what. So the framework
    records the divergence and refuses to compute the outcome. See
    :func:`absent_entitlement_treatment`."""

    QUANTITY_NOT_RESTATED = "quantity_not_restated"
    """A ratio-changing corporate action occurred and the open quantity was
    not restated. The fail is now denominated in shares that no longer
    exist in that form."""

    PROCESSING_DATE_NOT_ESTABLISHED = "processing_date_not_established"
    """The market fixes its processing date by a session-closure message and
    no processing date has been reported for this position.

    The settlement offset the position carries was derived from a trade
    timestamp, and on this market a timestamp does not establish a business
    date. The offset is therefore an assumption wearing the shape of a
    record. Closed by the market reporting the date, not by anything the
    member can do. See :func:`absent_processing_date`."""

    OUTCOME_NOT_REPORTED = "outcome_not_reported"
    """No settlement outcome was reported for the position. Fail-safe: not
    a settled position."""


@dataclass(frozen=True, slots=True)
class SecuritiesBreak:
    code: SecuritiesBreakCode
    detail: str
    security_id: str | None = None

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("a break with no detail is not a finding")


@dataclass(frozen=True, slots=True)
class NetSettlementResult:
    """The outcome for one net position, with the evidence behind it."""

    disposition: CNSDisposition
    position: NetPosition
    allocated_quantity: Decimal
    residual: FailPosition | None
    breaks: tuple[SecuritiesBreak, ...] = ()
    rationale: str = ""
    doctrine_version: str = DOCTRINE_VERSION

    @property
    def is_fail(self) -> bool:
        return self.disposition in {
            CNSDisposition.FAILED_TO_DELIVER,
            CNSDisposition.FAILED_TO_RECEIVE,
        }

    @property
    def completed(self) -> bool:
        """True only for a full settlement or a flat position.

        A partial allocation is deliberately excluded even though something
        moved, because the residual is a live obligation and treating the
        day as done is how a residual gets dropped.
        """
        return self.disposition in {
            CNSDisposition.SETTLED_IN_FULL,
            CNSDisposition.FLAT,
        }


def net_positions(
    trades: tuple[tuple[str, Decimal], ...],
    *,
    market_id: str,
    settlement_date_offset_days: int,
    novated: bool = True,
    assigned_processing_date_offset_days: int | None = None,
) -> tuple[NetPosition, ...]:
    """Net a set of ``(security_id, signed_quantity)`` trades into positions.

    Deterministic: output is ordered by security identifier, so the same
    trades in any order produce the same positions byte for byte.

    ``novated=False`` produces no positions at all rather than positions
    flagged as un-novated. A trade that did not enter the netting system has
    no net position by definition, and manufacturing one so the shape looks
    familiar would assert a settlement mechanism that does not occur.

    ``assigned_processing_date_offset_days`` is passed through unchanged to
    every position produced. It is a value the market reported, so it is
    supplied rather than derived; leaving it ``None`` on a market that fixes
    its processing date by message is a live unknown and
    :func:`settle_net_position` says so.
    """
    if not novated:
        return ()

    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for security_id, quantity in trades:
        totals[security_id] = totals.get(security_id, Decimal(0)) + quantity
        counts[security_id] = counts.get(security_id, 0) + 1

    return tuple(
        NetPosition(
            security_id=security_id,
            quantity=totals[security_id],
            settlement_date_offset_days=settlement_date_offset_days,
            market_id=market_id,
            constituent_trade_count=counts[security_id],
            assigned_processing_date_offset_days=(
                assigned_processing_date_offset_days
            ),
        )
        for security_id in sorted(totals)
    )


def settle_net_position(
    position: NetPosition,
    profile: MarketProfile,
    *,
    allocated_quantity: Decimal | None = None,
    aged_days: int = 0,
    current_offset_days: int | None = None,
    spans_record_date: bool = False,
    corporate_action_ratio_applied: bool = False,
    quantity_restated: bool = False,
) -> NetSettlementResult:
    """Classify the settlement outcome for one net position.

    ``allocated_quantity`` is what the clearing corporation actually moved,
    signed the same way as the position. ``None`` means no outcome was
    reported, which resolves to INDETERMINATE - **a position with no
    reported outcome is not a settled position.**

    Check order is doctrine, not optimisation.
    """
    breaks: list[SecuritiesBreak] = []

    # 0. Is the date this position clears for even established? Asked before
    #    anything about allocation, and attached to every outcome including
    #    a full settlement, because "it settled" and "it settled on the date
    #    we assumed" are different assertions and only the first is
    #    observable here. A fully settled position on the wrong side of a
    #    session-closure boundary is still a reconciliation break the next
    #    morning.
    if (
        profile.processing_date_rule is ProcessingDateRule.SESSION_CLOSURE_MESSAGE
        and position.assigned_processing_date_offset_days is None
    ):
        breaks.append(
            SecuritiesBreak(
                SecuritiesBreakCode.PROCESSING_DATE_NOT_ESTABLISHED,
                f"{position.security_id}: market {profile.market_id} fixes its "
                f"processing date by "
                f"{profile.session_closure_message or 'a session-closure message'} "
                f"and has reported none for this position. The "
                f"{position.settlement_date_offset_days}-day settlement offset "
                f"carried here was derived from a timestamp, which on this "
                f"market does not establish a business date",
                position.security_id,
            )
        )

    def build(
        disposition: CNSDisposition,
        allocated: Decimal,
        residual: FailPosition | None,
        rationale: str,
    ) -> NetSettlementResult:
        return NetSettlementResult(
            disposition=disposition,
            position=position,
            allocated_quantity=allocated,
            residual=residual,
            breaks=tuple(breaks),
            rationale=rationale,
        )

    # 1. Nothing reported. Fail-safe, and the first check for that reason.
    if allocated_quantity is None:
        breaks.append(
            SecuritiesBreak(
                SecuritiesBreakCode.OUTCOME_NOT_REPORTED,
                "no settlement outcome was reported for this net position; "
                "the framework does not infer settlement from silence",
                position.security_id,
            )
        )
        return build(
            CNSDisposition.INDETERMINATE,
            Decimal(0),
            None,
            "No reported outcome. INDETERMINATE, never settled.",
        )

    # 2. Flat. Trades netted out; nothing settles and nothing failed.
    if position.quantity == 0:
        return build(
            CNSDisposition.FLAT,
            Decimal(0),
            None,
            f"Net position in {position.security_id} is zero across "
            f"{position.constituent_trade_count} trades. Netted out.",
        )

    outstanding = position.quantity - allocated_quantity
    fully_settled = outstanding == 0
    nothing_moved = allocated_quantity == 0

    residual: FailPosition | None = None
    if not fully_settled:
        residual = FailPosition(
            security_id=position.security_id,
            quantity=outstanding,
            aged_days=aged_days,
            close_out_deadline_offset_days=close_out_deadline(
                profile, position.settlement_date_offset_days
            ),
            restated_by_corporate_action=quantity_restated,
        )
        breaks.extend(
            _open_fail_breaks(
                position=position,
                profile=profile,
                residual=residual,
                current_offset_days=current_offset_days,
                spans_record_date=spans_record_date,
                corporate_action_ratio_applied=corporate_action_ratio_applied,
                quantity_restated=quantity_restated,
            )
        )

    if fully_settled:
        return build(
            CNSDisposition.SETTLED_IN_FULL,
            allocated_quantity,
            None,
            f"Net position in {position.security_id} settled in full on a "
            f"{CNS_FINALITY.value} basis.",
        )

    if not nothing_moved:
        if not profile.allocation_rule_published:
            breaks.append(
                SecuritiesBreak(
                    SecuritiesBreakCode.PARTIAL_WITH_UNEXPLAINED_ALLOCATION,
                    f"{position.security_id} allocated {allocated_quantity} of "
                    f"{position.quantity} on a market that does not publish "
                    f"its allocation rule. The member cannot explain why it "
                    f"received what it received, and this framework will not "
                    f"manufacture an explanation",
                    position.security_id,
                )
            )
        return build(
            CNSDisposition.PARTIAL_ALLOCATION,
            allocated_quantity,
            residual,
            f"Partial allocation: {allocated_quantity} of {position.quantity} "
            f"in {position.security_id}. The residual is a live obligation, "
            f"not a rounding remainder.",
        )

    disposition = (
        CNSDisposition.FAILED_TO_RECEIVE
        if position.is_receive
        else CNSDisposition.FAILED_TO_DELIVER
    )
    breaks.append(
        SecuritiesBreak(
            SecuritiesBreakCode.FAIL_TO_RECEIVE
            if position.is_receive
            else SecuritiesBreakCode.FAIL_TO_DELIVER,
            f"{position.security_id}: nothing allocated against a net "
            f"position of {position.quantity}",
            position.security_id,
        )
    )
    return build(
        disposition,
        Decimal(0),
        residual,
        f"Nothing allocated. {disposition.value} on the net position, which "
        f"is the only unit that settles here - no underlying trade failed, "
        f"because no underlying trade was the settlement object.",
    )


def _open_fail_breaks(
    *,
    position: NetPosition,
    profile: MarketProfile,
    residual: FailPosition,
    current_offset_days: int | None,
    spans_record_date: bool,
    corporate_action_ratio_applied: bool,
    quantity_restated: bool,
) -> list[SecuritiesBreak]:
    """Findings that attach to an open fail. Order is stable for replay."""
    out: list[SecuritiesBreak] = []

    if profile.close_out_regime is CloseOutRegime.NOT_ASSESSED:
        out.append(
            SecuritiesBreak(
                SecuritiesBreakCode.CLOSE_OUT_DEADLINE_UNREADABLE,
                f"open fail in {position.security_id} on market "
                f"{profile.market_id}, whose close-out rules have not been "
                f"read. Whether a deadline is running is unknown rather than "
                f"absent; closed by populating the registry",
                position.security_id,
            )
        )
    elif (
        residual.close_out_deadline_offset_days is not None
        and current_offset_days is not None
        and current_offset_days > residual.close_out_deadline_offset_days
    ):
        out.append(
            SecuritiesBreak(
                SecuritiesBreakCode.CLOSE_OUT_DEADLINE_PASSED,
                f"open fail in {position.security_id} is past the market's "
                f"close-out deadline at day "
                f"{residual.close_out_deadline_offset_days}",
                position.security_id,
            )
        )

    if spans_record_date:
        side = "pending receipt (fail long)" if position.is_receive else (
            "pending delivery (fail short)"
        )
        out.append(
            SecuritiesBreak(
                SecuritiesBreakCode.ELIGIBLE_SETTLED_DIVERGENCE,
                f"{position.security_id} was open across a corporate action "
                f"record date, so the eligible balance and the settled "
                f"balance diverge by {residual.quantity} on the {side} side. "
                f"The entitlement treatment is not computed here - published "
                f"depository guidance carries this condition and does not "
                f"state the outcome",
                position.security_id,
            )
        )

    if corporate_action_ratio_applied and not quantity_restated:
        out.append(
            SecuritiesBreak(
                SecuritiesBreakCode.QUANTITY_NOT_RESTATED,
                f"a ratio-changing corporate action applied to "
                f"{position.security_id} and the open quantity was not "
                f"restated; the fail is denominated in shares that no longer "
                f"exist in that form",
                position.security_id,
            )
        )

    return out


def absent_processing_date(market_id: str, message_name: str | None = None) -> str:
    """Why this module will not date a settlement it cannot date.

    On a market that fixes its processing date with a session-closure
    message, the business date a trade clears for is established by the
    arrival of that message and not by the trade's own timestamp. Two trades
    four minutes apart across midnight can clear for different business
    dates, and no amount of arithmetic on the timestamps recovers which.

    A settlement cycle expressed as an integer of business days answers the
    question *after* this one. Applying it to an unestablished processing
    date produces a settlement date that looks computed, carries no
    qualification, and is wrong on exactly the trades an extended session
    was introduced to enable.

    Named and exported, and returning a sentence rather than a date, for the
    same reason as :func:`absent_trade_attribution`: the answer is a refusal
    and a refusal belongs in one auditable place.
    """
    named = message_name or "a session-closure message"
    return (
        f"No processing date for market {market_id}. This market fixes the "
        f"business date a trade clears for by {named} rather than by a clock, "
        f"and none has been reported. The settlement cycle counts from that "
        f"date and cannot establish it, so no settlement date is derived "
        f"here. This is an unknown with a name, not a missing field "
        f"(AUR-CUSTODY-EQUITY-001 draft)."
    )


def absent_trade_attribution(security_id: str) -> str:
    """Why this module will not say which trade failed.

    Novation and netting destroy the correspondence between a trade and a
    settlement obligation. What settles is one position per security, and
    the allocation of whatever shares were available is the clearing
    corporation's algorithm rather than the member's. From the participant
    seat, per-trade fail attribution is an inference dressed as an
    observation.

    Named and exported, and returning a sentence rather than a value,
    because the answer to "which trade failed" is a refusal and refusals
    belong in one auditable place - the same reason
    ``absent_gate_decision()`` exists.
    """
    return (
        f"No trade failed in {security_id}. The net position failed. Novation "
        f"and netting destroyed the trade-to-obligation correspondence before "
        f"settlement ran, and the allocation of available shares is the "
        f"clearing corporation's rule, not the member's. Any per-trade "
        f"attribution here would be an inference presented as an observation "
        f"(AUR-CUSTODY-EQUITY-001 draft)."
    )


def absent_entitlement_treatment(security_id: str) -> str:
    """Why this module will not compute who is owed what across a record date.

    Published depository usage guidance for corporate actions carries the
    *condition* in detail. It distinguishes an eligible position from a
    settlement position, states plainly that the two can diverge where
    position moved after record-date capture, and rides pending-delivery and
    pending-receipt balances - fails short and fails long - on the movement
    preliminary advice and the movement confirmation. For lottery events it
    carries an obligated balance for the case where the called quantity
    exceeds the settled one, and for voluntary events an uncovered protect
    balance.

    What that guidance does not state is the **treatment**: no rule for how
    an entitlement is allocated when delivery has not occurred by the record
    date. Due bills and claims are not mentioned at all. The material
    describes the shape of the problem and leaves the adjustment to
    processes outside the messages.

    So this framework records the divergence, names both sides, and stops.
    Computing an entitlement outcome here would be inventing market practice
    and presenting it as governance - the same error as reverse-engineering
    an undisclosed margin methodology, and worse, because it would produce a
    number somebody might act on.

    Named and exported, and returning a sentence rather than a value, for
    the same reason as :func:`absent_trade_attribution`.
    """
    return (
        f"Entitlement treatment for the open position in {security_id} is not "
        f"computed. The eligible-versus-settled divergence is recorded and "
        f"both sides are named; the allocation rule is not published in the "
        f"depository usage guidance this framework consumes, and inventing "
        f"one would present market practice as governance "
        f"(AUR-CUSTODY-EQUITY-001 draft)."
    )


#: Kept as module-level markers so a reader searching for trade-level fail
#: handling or for entitlement computation finds the refusal rather than an
#: absence.
NO_TRADE_LEVEL_FAIL_API: Final[bool] = True
NO_ENTITLEMENT_COMPUTATION_API: Final[bool] = True
