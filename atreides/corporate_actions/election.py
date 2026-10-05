"""The election workflow for elective corporate actions (ORDER SC-1, WP-3).

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence, and
nothing here transmits an instruction. Atreides records what it was asked and
what it did with it; an entitled member instructs the depository.

THE FIRM'S DEADLINE
-------------------
The depository's election deadline is event data. The firm's own deadline is
earlier by a policy parameter (:class:`ElectionPolicy`), so the firm has time
to instruct the depository after its last client instruction. Days are
calendar days: no business-day calendar is modeled, and a firm that needs one
sets the lead accordingly.

WHAT A SUBMISSION CAN DO
------------------------
Two kinds of submission, each journaled with what happened to it:

- an :class:`ElectionInstruction` elects a quantity into one announced option,
  optionally under protect (a promise to deliver the shares later);
- a :class:`ProtectCover` delivers against an accepted protect instruction.

A late submission is refused, not queued. An instruction is late after the
firm's deadline; a cover is late after the event's protect deadline.

Every submission carries a caller-chosen identifier. Submitting the same
identifier again with the same content changes nothing and is journaled as a
duplicate of the original, which is what makes a retry safe. The same
identifier with different content is refused: it is either an error or an
attempt to amend, and an amendment needs its own identifier.

PROTECT, IN THE DEPOSITORY'S WORDS
----------------------------------
The quantity elected under protect and not yet covered is the
``uncovered_protect_balance``, the term depository guidance uses and that
:class:`~atreides.rails.cns.RecordDatePosition` carries.

THE DEFAULT
-----------
A holder who does not elect, or elects less than the whole position, receives
the event's default option on the remainder, and the default is the one the
announcement states (``CorporateActionEvent.default_option_id``). Where the
announcement states none, no default is applied. The default is assigned only
after the firm's deadline, when no further instruction can be accepted.

NOT AN ADVISORY DISPOSITION
---------------------------
Acceptance, refusal and default assignment are domain outcomes with typed
reasons. There is no PASS, HOLD or INDETERMINATE here (order section 8).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from cannae_kernel.provenance import Provenance
from pydantic import Field, model_validator

from atreides.corporate_actions.entitlement import HolderPosition
from atreides.corporate_actions.events import (
    CorporateActionEvent,
    Participation,
    SourceIdentity,
)
from atreides.corporate_actions.lifecycle import JournalMismatchError
from atreides.customer_protection.common import Frozen, NonNegativeMoney

__all__ = [
    "AccountDefault",
    "DefaultAssignment",
    "DefaultRefusal",
    "ElectionBook",
    "ElectionEntry",
    "ElectionInstruction",
    "ElectionPolicy",
    "ElectionRefusal",
    "ProtectCover",
    "Submission",
    "assign_defaults",
    "firm_deadline",
    "rebuild_elections",
]

ZERO = Decimal(0)


class ElectionPolicy(Frozen):
    """The firm's parameters for one event's elections."""

    #: How many calendar days before the depository's election deadline the firm stops
    #: accepting instructions. At least one: the firm's deadline is earlier, not equal.
    firm_lead_days: int = Field(ge=1)


def firm_deadline(event: CorporateActionEvent, policy: ElectionPolicy) -> date | None:
    """The last day the firm accepts an instruction, or ``None`` for a mandatory event."""
    depository = event.dates.election_deadline
    if depository is None:
        return None
    return depository - timedelta(days=policy.firm_lead_days)


#: An elected or covered quantity of shares: exact and positive.
Quantity = Annotated[NonNegativeMoney, Field(gt=0)]


class ElectionInstruction(Frozen):
    """A holder's instruction to elect a quantity into one announced option."""

    submission_type: Literal["instruction"] = "instruction"
    #: Chosen by the caller and unique per event. A retry reuses it.
    instruction_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    quantity: Quantity
    received_date: date
    #: Elected under protect: the shares are promised and delivered later by a cover.
    protect: bool = False
    #: What kind of claim the instruction is, for example ``FACT_EXTERNAL`` for one
    #: received from the holder's system, or ``HUMAN_JUDGMENT`` for one keyed by an operator.
    provenance: Provenance
    source: SourceIdentity

    @property
    def submission_id(self) -> str:
        return self.instruction_id


class ProtectCover(Frozen):
    """Delivery of shares against an accepted protect instruction."""

    submission_type: Literal["protect_cover"] = "protect_cover"
    cover_id: str = Field(min_length=1)
    #: The protect instruction this cover delivers against.
    instruction_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    quantity: Quantity
    received_date: date
    provenance: Provenance
    source: SourceIdentity

    @property
    def submission_id(self) -> str:
        return self.cover_id


Submission = Annotated[ElectionInstruction | ProtectCover, Field(discriminator="submission_type")]


class ElectionRefusal(StrEnum):
    """Why a submission was refused. Each names the rule it broke."""

    NOT_ELECTIVE = "not_elective"
    """The event is mandatory. There is nothing to elect."""
    LATE = "late"
    """Received after the firm's deadline. Refused, not queued."""
    BEFORE_ANNOUNCEMENT = "before_announcement"
    """Received before the event was announced."""
    OPTIONS_NOT_STATED = "options_not_stated"
    """The event states no options, so no option can be elected."""
    UNKNOWN_OPTION = "unknown_option"
    """The option is not one the event announced."""
    PROTECT_NOT_OFFERED = "protect_not_offered"
    """Protect needs a voluntary event that states a protect deadline."""
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    """The identifier was used before with different content. An amendment needs its own."""
    UNKNOWN_PROTECT = "unknown_protect"
    """The cover names no accepted protect instruction for this account."""
    LATE_COVER = "late_cover"
    """Received after the event's protect deadline. Refused, not queued."""
    OVER_COVER = "over_cover"
    """The cover exceeds what remains uncovered on its protect instruction."""


class ElectionEntry(Frozen):
    """One submission and what the workflow did with it."""

    event_id: str
    #: Position in the journal, from zero, counting every submission.
    sequence: int = Field(ge=0)
    submission: Submission
    outcome: Literal["accepted", "refused", "duplicate"]
    refusal: ElectionRefusal | None = None
    #: For a duplicate: the sequence of the submission it repeats.
    duplicate_of: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ElectionEntry:
        if (self.outcome == "refused") != (self.refusal is not None):
            raise ValueError("a refused submission names its reason, and only a refused one")
        if (self.outcome == "duplicate") != (self.duplicate_of is not None):
            raise ValueError("a duplicate names the submission it repeats, and only a duplicate")
        return self


class ElectionBook(Frozen):
    """One event's elections: the policy, and every submission made. Immutable."""

    event: CorporateActionEvent
    policy: ElectionPolicy
    journal: tuple[ElectionEntry, ...] = ()

    @property
    def firm_deadline(self) -> date | None:
        return firm_deadline(self.event, self.policy)

    def _first(self, submission_id: str) -> ElectionEntry | None:
        return next(
            (e for e in self.journal
             if e.outcome != "duplicate" and e.submission.submission_id == submission_id),
            None,
        )

    def accepted_instructions(self) -> tuple[ElectionInstruction, ...]:
        return tuple(
            e.submission for e in self.journal
            if e.outcome == "accepted" and isinstance(e.submission, ElectionInstruction)
        )

    def accepted_covers(self) -> tuple[ProtectCover, ...]:
        return tuple(
            e.submission for e in self.journal
            if e.outcome == "accepted" and isinstance(e.submission, ProtectCover)
        )

    def elected_quantity(self, account_id: str) -> Decimal:
        """Everything the account elected, into any option, protect included."""
        return sum(
            (i.quantity for i in self.accepted_instructions() if i.account_id == account_id),
            ZERO,
        )

    def _uncovered(self, instruction: ElectionInstruction) -> Decimal:
        covered = sum(
            (c.quantity for c in self.accepted_covers()
             if c.instruction_id == instruction.instruction_id),
            ZERO,
        )
        return instruction.quantity - covered

    def uncovered_protect_balance(self, account_id: str) -> Decimal:
        """Elected under protect and not yet covered, in the depository's term."""
        return sum(
            (self._uncovered(i) for i in self.accepted_instructions()
             if i.protect and i.account_id == account_id),
            ZERO,
        )

    def _refusal(self, submission: ElectionInstruction | ProtectCover) -> ElectionRefusal | None:
        event = self.event
        if not event.participation.elective:
            return ElectionRefusal.NOT_ELECTIVE
        if submission.received_date < event.dates.announcement_date:
            return ElectionRefusal.BEFORE_ANNOUNCEMENT
        if isinstance(submission, ProtectCover):
            protect = next(
                (i for i in self.accepted_instructions()
                 if i.instruction_id == submission.instruction_id and i.protect
                 and i.account_id == submission.account_id),
                None,
            )
            if protect is None:
                return ElectionRefusal.UNKNOWN_PROTECT
            protect_deadline = event.dates.protect_deadline
            if protect_deadline is not None and submission.received_date > protect_deadline:
                return ElectionRefusal.LATE_COVER
            if submission.quantity > self._uncovered(protect):
                return ElectionRefusal.OVER_COVER
            return None
        deadline = self.firm_deadline
        if deadline is not None and submission.received_date > deadline:
            return ElectionRefusal.LATE
        if not event.options:
            return ElectionRefusal.OPTIONS_NOT_STATED
        if submission.option_id not in {o.option_id for o in event.options}:
            return ElectionRefusal.UNKNOWN_OPTION
        if submission.protect and (
            event.participation is not Participation.VOLUNTARY
            or event.dates.protect_deadline is None
        ):
            return ElectionRefusal.PROTECT_NOT_OFFERED
        return None

    def submit(
        self, submission: ElectionInstruction | ProtectCover
    ) -> tuple[ElectionBook, ElectionEntry]:
        """Accept, refuse, or recognise as a duplicate. Returns the new book and the entry."""
        sequence = len(self.journal)
        first = self._first(submission.submission_id)
        if first is not None and first.submission == submission:
            entry = ElectionEntry(
                event_id=self.event.event_id, sequence=sequence, submission=submission,
                outcome="duplicate", duplicate_of=first.sequence,
            )
        else:
            refusal = (
                ElectionRefusal.CONFLICTING_DUPLICATE if first is not None
                else self._refusal(submission)
            )
            entry = ElectionEntry(
                event_id=self.event.event_id, sequence=sequence, submission=submission,
                outcome="accepted" if refusal is None else "refused", refusal=refusal,
            )
        book = ElectionBook(event=self.event, policy=self.policy, journal=(*self.journal, entry))
        return book, entry


def rebuild_elections(
    event: CorporateActionEvent,
    policy: ElectionPolicy,
    journal: Sequence[ElectionEntry],
) -> ElectionBook:
    """Replay ``journal`` and return the book it produces, or say which entry does not."""
    book = ElectionBook(event=event, policy=policy)
    for expected, recorded in enumerate(journal):
        if recorded.event_id != event.event_id or recorded.sequence != expected:
            raise JournalMismatchError(
                f"entry {recorded.sequence} of event {recorded.event_id!r} is not entry "
                f"{expected} of {event.event_id!r}"
            )
        book, recomputed = book.submit(recorded.submission)
        if recomputed != recorded:
            raise JournalMismatchError(
                f"entry {recorded.sequence} records {recorded.outcome}, and its submission "
                f"gives {recomputed.outcome}"
            )
    return book


class DefaultRefusal(StrEnum):
    """Why no default was assigned."""

    NOT_ELECTIVE = "not_elective"
    """A mandatory event has no default to assign."""
    DEADLINE_NOT_PASSED = "deadline_not_passed"
    """The firm's deadline has not passed, so an instruction may still arrive."""
    DEFAULT_NOT_STATED = "default_not_stated"
    """The announcement states no default option."""
    OVER_INSTRUCTED = "over_instructed"
    """The account elected more than its eligible balance."""
    INSTRUCTED_WITHOUT_POSITION = "instructed_without_position"
    """The account elected but holds no eligible balance in the holdings given."""


class AccountDefault(Frozen):
    """One account's default, or why it has none."""

    account_id: str
    eligible_balance: Decimal | None
    elected_quantity: Decimal
    #: The quantity the default option applies to. ``None`` where refused.
    default_quantity: Decimal | None
    refusal: DefaultRefusal | None = None

    @model_validator(mode="after")
    def _a_quantity_or_a_reason(self) -> AccountDefault:
        if (self.default_quantity is None) == (self.refusal is None):
            raise ValueError("an account has a default quantity or a reason, never both")
        return self


class DefaultAssignment(Frozen):
    """The default applied to every account's uninstructed balance, as of one day."""

    event_id: str
    as_of: date
    firm_deadline: date | None
    #: The option the default quantities go to. ``None`` where the default was refused.
    default_option_id: str | None
    #: Why no account received a default, where that is so.
    refusal: DefaultRefusal | None = None
    accounts: tuple[AccountDefault, ...] = ()


def assign_defaults(
    book: ElectionBook, holdings: Sequence[HolderPosition], as_of: date
) -> DefaultAssignment:
    """Assign the event's default option to every uninstructed balance. Pure and order-free."""
    event, deadline = book.event, book.firm_deadline

    def refused(reason: DefaultRefusal) -> DefaultAssignment:
        return DefaultAssignment(event_id=event.event_id, as_of=as_of, firm_deadline=deadline,
                                 default_option_id=None, refusal=reason)

    if deadline is None:
        return refused(DefaultRefusal.NOT_ELECTIVE)
    if as_of <= deadline:
        return refused(DefaultRefusal.DEADLINE_NOT_PASSED)
    if event.default_option_id is None:
        return refused(DefaultRefusal.DEFAULT_NOT_STATED)

    eligible = {h.account_id: h.position.eligible_balance for h in holdings}
    if len(eligible) != len(holdings):
        raise ValueError("an account appears more than once")
    instructed = {i.account_id for i in book.accepted_instructions()}
    accounts = []
    for account_id in sorted(set(eligible) | instructed):
        elected = book.elected_quantity(account_id)
        balance = eligible.get(account_id)
        if balance is None:
            accounts.append(AccountDefault(
                account_id=account_id, eligible_balance=None, elected_quantity=elected,
                default_quantity=None, refusal=DefaultRefusal.INSTRUCTED_WITHOUT_POSITION,
            ))
        elif elected > balance:
            accounts.append(AccountDefault(
                account_id=account_id, eligible_balance=balance, elected_quantity=elected,
                default_quantity=None, refusal=DefaultRefusal.OVER_INSTRUCTED,
            ))
        else:
            accounts.append(AccountDefault(
                account_id=account_id, eligible_balance=balance, elected_quantity=elected,
                default_quantity=balance - elected,
            ))
    return DefaultAssignment(
        event_id=event.event_id, as_of=as_of, firm_deadline=deadline,
        default_option_id=event.default_option_id, accounts=tuple(accounts),
    )
