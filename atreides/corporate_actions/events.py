"""The corporate action event: what was announced, when, and on whose word.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

An event is data. It carries the dates and terms an announcement states and
nothing this module infers. Where a date or a term is not stated it is
``None``, and the code that needs it says so rather than assuming a value.

WHO SAID SO
-----------
Every event names the kind of claim it is and where it came from, as two
separate fields. ``provenance`` is the shared kernel vocabulary
(:class:`cannae_kernel.provenance.Provenance`): an event reported by an
external authority such as DTC (the Depository Trust Company) is
``FACT_EXTERNAL``, and one produced by a synthetic adapter is
``FACT_SYNTHETIC``. ``source`` says which authority or adapter, and which
message or document. There is no second provenance taxonomy here.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from cannae_kernel.provenance import Provenance
from pydantic import Field, field_validator, model_validator

from atreides.customer_protection.common import Frozen, NonNegativeMoney

__all__ = [
    "EVENT_FACT_PROVENANCE",
    "CorporateActionEvent",
    "ElectionOption",
    "EventDates",
    "EventTerms",
    "EventType",
    "OptionType",
    "Participation",
    "SourceIdentity",
]


#: A per-share rate: exact, never a binary float, never negative. The same validation
#: as non-negative money, which is what it is checked against.
Rate = NonNegativeMoney

#: The two provenance values an event's facts may carry: reported, or emulated.
EVENT_FACT_PROVENANCE: frozenset[Provenance] = frozenset(
    {Provenance.FACT_EXTERNAL, Provenance.FACT_SYNTHETIC}
)


class EventType(StrEnum):
    """The corporate action classes this package models."""

    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    MERGER = "merger"
    TENDER_OFFER = "tender_offer"
    RIGHTS = "rights"
    #: A partial redemption allocated by lottery.
    REDEMPTION_LOTTERY = "redemption_lottery"
    INTEREST_PAYMENT = "interest_payment"
    FINAL_MATURITY = "final_maturity"
    PARTIAL_REDEMPTION = "partial_redemption"
    FULL_CALL = "full_call"
    CAPITAL_GAINS_DISTRIBUTION = "capital_gains_distribution"
    CAPITAL_DISTRIBUTION = "capital_distribution"
    REINVESTMENT = "reinvestment"


class Participation(StrEnum):
    """Whether the holder acts, and whether acting is optional."""

    #: Happens to every holder. No election.
    MANDATORY = "mandatory"
    #: Happens only to holders who elect.
    VOLUNTARY = "voluntary"
    #: Happens to every holder, who may elect among options or take the default.
    MANDATORY_WITH_CHOICE = "mandatory_with_choice"

    @property
    def elective(self) -> bool:
        return self is not Participation.MANDATORY


class SourceIdentity(Frozen):
    """Which authority or adapter reported a fact, and in which message or document."""

    #: The reporting authority or adapter, for example ``"DTC"`` or ``"synthetic-dtc-adapter"``.
    source_id: str = Field(min_length=1)
    #: The message, notice or document the fact was read from, where one exists.
    reference: str | None = None


class EventDates(Frozen):
    """The dates an announcement states. ``None`` means the announcement does not state it."""

    announcement_date: date
    #: The date that fixes who is entitled.
    record_date: date | None = None
    #: The depository's deadline for elections. Elective events only.
    election_deadline: date | None = None
    #: The deadline for covering a protect instruction. Voluntary events only.
    protect_deadline: date | None = None
    payable_date: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> EventDates:
        for name in ("record_date", "election_deadline", "protect_deadline", "payable_date"):
            value = getattr(self, name)
            if value is not None and value < self.announcement_date:
                raise ValueError(f"{name} {value} precedes the announcement date")
        if (
            self.protect_deadline is not None
            and self.election_deadline is not None
            and self.protect_deadline < self.election_deadline
        ):
            raise ValueError("a protect deadline cannot precede the election deadline it covers")
        if (
            self.payable_date is not None
            and self.record_date is not None
            and self.payable_date < self.record_date
        ):
            raise ValueError("a payable date cannot precede the record date")
        return self


class EventTerms(Frozen):
    """The terms an announcement states. Data only: nothing here is computed.

    ``None`` means not stated. Arithmetic over these terms lives in the
    entitlement module, which refuses to compute from a term that is absent.
    """

    #: Cash dividend: the amount per share, in ``currency``.
    cash_rate_per_share: NonNegativeMoney | None = None
    #: ISO 4217 currency code of ``cash_rate_per_share``.
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    #: Stock dividend: additional shares distributed per share held.
    stock_rate_per_share: Rate | None = None
    #: Split ratio as announced, ``split_new`` for ``split_old`` (a 3-for-2 split is 3 and 2).
    split_new: int | None = Field(default=None, gt=0)
    split_old: int | None = Field(default=None, gt=0)
    #: Fixed income interest amount per unit of face amount.
    interest_amount_per_face: NonNegativeMoney | None = None
    #: Fixed income redemption price per unit of face amount.
    redemption_price_per_face: NonNegativeMoney | None = None
    #: Reinvestment price per fund share. No price means no share computation.
    reinvestment_price_per_share: NonNegativeMoney | None = None

    @model_validator(mode="after")
    def _paired(self) -> EventTerms:
        if (self.split_new is None) != (self.split_old is None):
            raise ValueError("a split ratio states both sides or neither")
        if (self.cash_rate_per_share is None) != (self.currency is None):
            other_cash = any(
                value is not None
                for value in (
                    self.interest_amount_per_face,
                    self.redemption_price_per_face,
                    self.reinvestment_price_per_share,
                )
            )
            if not other_cash:
                raise ValueError("a cash rate is stated with its currency, and only then")
        if self.currency is None and any(
            value is not None
            for value in (
                self.interest_amount_per_face,
                self.redemption_price_per_face,
                self.reinvestment_price_per_share,
            )
        ):
            raise ValueError("a stated monetary term requires its currency")
        return self


class OptionType(StrEnum):
    """What an option delivers, in the ISO 20022 option type codes the announcement uses."""

    CASH = "CASH"
    SECU = "SECU"
    #: Cash and securities.
    CASE = "CASE"
    #: No action.
    NOAC = "NOAC"
    OTHR = "OTHR"


class ElectionOption(Frozen):
    """One option an elective event offers, as the announcement numbers and describes it."""

    #: The option's identifier as announced, for example ``"001"``.
    option_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    #: What the option delivers, where the announcement states it. ``None`` means not
    #: stated; such an option cannot be expressed in ISO 20022, which requires a type.
    option_type: OptionType | None = None


class CorporateActionEvent(Frozen):
    """One announced corporate action on one security."""

    event_id: str = Field(min_length=1)
    security_id: str = Field(min_length=1)
    event_type: EventType
    participation: Participation
    dates: EventDates
    terms: EventTerms = EventTerms()
    #: Elective events only: the options as announced. Empty means not stated.
    options: tuple[ElectionOption, ...] = ()
    #: Elective events only: the option a holder who does not elect receives, as the
    #: announcement states it. ``None`` means not stated, and no default is applied.
    default_option_id: str | None = None
    provenance: Provenance
    source: SourceIdentity

    @field_validator("provenance")
    @classmethod
    def _a_fact(cls, value: Provenance) -> Provenance:
        if value not in EVENT_FACT_PROVENANCE:
            raise ValueError(
                f"an event is a reported fact: FACT_EXTERNAL or FACT_SYNTHETIC, not {value}"
            )
        return value

    @model_validator(mode="after")
    def _dates_fit_participation(self) -> CorporateActionEvent:
        if self.participation.elective and self.dates.election_deadline is None:
            raise ValueError(f"a {self.participation.value} event states an election deadline")
        if not self.participation.elective and self.dates.election_deadline is not None:
            raise ValueError("a mandatory event has no election deadline")
        if (
            self.dates.protect_deadline is not None
            and self.participation is not Participation.VOLUNTARY
        ):
            raise ValueError("a protect deadline belongs to a voluntary event")
        if not self.participation.elective and (self.options or self.default_option_id):
            raise ValueError("a mandatory event offers no election options")
        ids = [option.option_id for option in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("an option identifier appears more than once")
        if self.default_option_id is not None and self.default_option_id not in ids:
            raise ValueError(f"the default option {self.default_option_id!r} is not an option")
        return self
