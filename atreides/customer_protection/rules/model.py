"""Rule table model: every regulatory figure, with where it came from.

EXPERIMENTAL (charter section 18.6). A rule item is a figure read from a pinned
copy of rule text, never a figure from anybody's memory. Each item names the
paragraph it came from, the exact words it was read from (``quote``), the part
of those words that states the figure (``figure``), and the SHA-256 (Secure
Hash Algorithm, 256 bit) of the source file it was read from. The loader
refuses an item whose quote is not in that file, whose figure does not parse to
its value, or whose source hash has changed since the item was written.

Categorical items (an Exhibit A line, a control location) carry no value. Their
``quote`` is the rule's own wording for the category, and the loader checks it
the same way.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from cannae_kernel.canonical import Digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CLAIM_LABEL",
    "RejectedItem",
    "RuleItem",
    "RuleItemSpec",
    "RuleKind",
    "RuleSource",
    "RuleTable",
    "RuleVersion",
    "SourceLabel",
]

#: Charter section 18.6 claim label carried by every artifact in this package.
CLAIM_LABEL: Literal["EXPERIMENTAL"] = "EXPERIMENTAL"

DTG_PATTERN = r"^\d{12}$"


class SourceLabel(StrEnum):
    """What kind of text a source is."""

    #: Regulation text, read from the electronic Code of Federal Regulations (eCFR).
    RULE = "RULE"
    #: Staff guidance. Recorded and cited, never read as a figure an engine computes from.
    GUIDANCE = "GUIDANCE"


class RuleKind(StrEnum):
    """How an item's figure is read, and whether it has a value at all."""

    #: A percentage, stored as a ratio: "2 percent" is ``0.02``.
    PERCENT = "PERCENT"
    #: An amount in United States dollars.
    USD = "USD"
    #: A duration in months. "2 years" is stored as ``24``.
    MONTHS = "MONTHS"
    #: A count of calendar days.
    CALENDAR_DAYS = "CALENDAR_DAYS"
    #: A count of business days.
    BUSINESS_DAYS = "BUSINESS_DAYS"
    #: A credit line of Exhibit A to Rule 15c3-3. No value.
    EXHIBIT_A_CREDIT = "EXHIBIT_A_CREDIT"
    #: A debit line of Exhibit A to Rule 15c3-3. No value.
    EXHIBIT_A_DEBIT = "EXHIBIT_A_DEBIT"
    #: A location Rule 15c3-3(c) deems to be under the broker-dealer's control. No value.
    CONTROL_LOCATION = "CONTROL_LOCATION"
    #: A noncontrol location Rule 15c3-3(d) names. No value.
    NONCONTROL_LOCATION = "NONCONTROL_LOCATION"
    #: A provision an engine's arithmetic depends on, such as "Note E(3) does not apply
    #: to the PAB computation". No value: the quote is the provision.
    PROVISION = "PROVISION"

    @property
    def has_value(self) -> bool:
        return self in _VALUED


_VALUED = frozenset(
    {
        RuleKind.PERCENT,
        RuleKind.USD,
        RuleKind.MONTHS,
        RuleKind.CALENDAR_DAYS,
        RuleKind.BUSINESS_DAYS,
    }
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleItemSpec(_Frozen):
    """One row of the committed table, before the loader has checked it."""

    id: str = Field(min_length=1)
    kind: RuleKind
    citation: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    #: SHA-256 hex of the source file the item was written against.
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: Exact words from the normalized source text.
    quote: str = Field(min_length=1)
    #: The part of ``quote`` that states the figure. Required when the kind has a value.
    figure: str | None = None
    #: The figure as a decimal string. Required when the kind has a value.
    value: Decimal | None = Field(default=None, allow_inf_nan=False)
    #: When compliance with this item began, if a source states it.
    compliance_date: date | None = None
    compliance_source_id: str | None = None
    compliance_quote: str | None = None

    @model_validator(mode="after")
    def _value_matches_kind(self) -> Self:
        if self.kind.has_value and (self.value is None or self.figure is None):
            raise ValueError(f"{self.id}: a {self.kind} item needs a figure and a value")
        if not self.kind.has_value and (self.value is not None or self.figure is not None):
            raise ValueError(f"{self.id}: a {self.kind} item carries no figure or value")
        if self.figure is not None and self.figure not in self.quote:
            raise ValueError(f"{self.id}: figure {self.figure!r} is not inside its quote")
        compliance = (self.compliance_date, self.compliance_source_id, self.compliance_quote)
        if any(c is not None for c in compliance) and any(c is None for c in compliance):
            raise ValueError(f"{self.id}: a compliance date needs its source and quote")
        return self


class RuleSource(_Frozen):
    """A pinned source file, as its sidecars describe it."""

    source_id: str
    citation: str
    label: SourceLabel
    filename: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: Retrieval date-time group (DTG), UTC, ``YYYYMMDDHHMM``.
    retrieval_dtg: str = Field(pattern=DTG_PATTERN)
    ecfr_up_to_date_as_of: date | None
    latest_amendment_date: date | None


class RuleItem(_Frozen):
    """A rule item the loader has checked against its source. Engines read only these."""

    id: str
    kind: RuleKind
    citation: str
    source_id: str
    source_file: str
    source_label: SourceLabel
    sha256: str
    retrieval_dtg: str = Field(pattern=DTG_PATTERN)
    #: The amendment date of the source section's current text, per the eCFR versioner.
    effective_date: date | None
    compliance_date: date | None
    quote: str
    value: Decimal | None


class RejectedItem(_Frozen):
    """An item the loader refused, and why. Its id resolves to nothing."""

    id: str
    reason: str


class RuleVersion(_Frozen):
    """The identity of one source an engine read from."""

    source_id: str
    citation: str
    sha256: str
    retrieval_dtg: str = Field(pattern=DTG_PATTERN)


class RuleTable(_Frozen):
    """Loaded, checked rule items. Built only by :func:`~.loader.load_rule_table`."""

    table_version: str
    #: SHA-256 over the committed table file, as ``sha256:<hex>``.
    table_digest: Digest
    sources: tuple[RuleSource, ...]
    items: tuple[RuleItem, ...]
    rejected: tuple[RejectedItem, ...]

    def get(self, rule_id: str) -> RuleItem | None:
        """The item, or ``None`` when it was never written or was refused."""
        return next((item for item in self.items if item.id == rule_id), None)

    def of_kind(self, kind: RuleKind) -> tuple[RuleItem, ...]:
        return tuple(item for item in self.items if item.kind is kind)

    def version_of(self, source_id: str) -> RuleVersion | None:
        source = next((s for s in self.sources if s.source_id == source_id), None)
        if source is None:
            return None
        return RuleVersion(
            source_id=source.source_id,
            citation=source.citation,
            sha256=source.sha256,
            retrieval_dtg=source.retrieval_dtg,
        )
