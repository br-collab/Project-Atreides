"""Depository profile — the only thing that knows what a venue constrains.

Per AUR-CUSTODY-CASH-001 v0.2 Section VIII:

    "exact message variants and profiles are implementation-determined
    against the depository's published specifications, not asserted in
    doctrine — depositories constrain the base ISO schemas, and a doctrine
    document that hardcodes variant numbers will be wrong before it is
    approved."

This module is where that determination lives. A profile is data, not
code, so adopting a depository's constraints is a fixture change under the
propose/approve discipline (`AUR-J-PATHSET-COMP-001 §IV`) rather than a
code change.

THE VARIANT PROBLEM, CONCRETELY
-------------------------------
ISO 20022 names messages ``<area>.<number>.<variant>.<version>``. The
``sese`` settlement triplet ships as BOTH variant 001 (base registered) and
variant 002 (a separately registered restricted variant) — they are not
interchangeable, and choosing wrong produces messages that validate against
the wrong schema and are rejected downstream. Which applies is stated in
the depository's own mapping document, which is behind participant access.

So the variant is a profile field with a documented default, never a
constant in the emitter.

STATUS
------
``BASE_ISO_20022`` is the only profile that can be asserted today. DTCC and
Fedwire profiles require their published specifications:

- DTCC — "ISO 20022 Message Specification UAT V6" and "Settlement Client
  Interface ISO 20022 Mapping", both behind MyDTCC participant login.
- Fedwire — implementation guide, and note the **November 2026 release**
  lands between now and the 2026-12-31 cash-clearing mandate date, so
  current-state formats are not the ones to build against for go-live.

Both are stubbed below with their gaps named rather than guessed. A profile
populated by inference would be worse than no profile: it would look
authoritative and be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "BASE_ISO_20022",
    "DTCC_SETTLEMENT_PENDING",
    "DepositoryProfile",
    "FEDWIRE_PENDING",
]


@dataclass(frozen=True, slots=True)
class DepositoryProfile:
    """Venue-specific constraints applied on top of the base schemas."""

    name: str
    #: Message identifiers, variant included. These become the BAH
    #: ``MsgDefIdr`` and select the schema the emitter renders against.
    fi_credit_transfer: str = "pacs.009.001.13"
    customer_credit_transfer: str = "pacs.008.001.14"
    payment_status_report: str = "pacs.002.001.16"
    business_application_header: str = "head.001.001.04"
    #: BAH ``BizSvc`` — venues use this to route by service. Absent in the
    #: base profile because the base standard does not define values.
    business_service: str | None = None
    #: Fields the venue makes mandatory that the base schema leaves
    #: optional. Empty until a published specification says otherwise.
    additional_mandatory_fields: frozenset[str] = frozenset()
    #: Code values the venue restricts below the schema enumeration.
    restricted_code_values: dict[str, frozenset[str]] = field(
        default_factory=dict
    )
    #: True once the profile reflects a published venue specification
    #: rather than the bare standard. Emitters may warn on False; nothing
    #: silently treats an unverified profile as authoritative.
    verified_against_published_spec: bool = False

    @property
    def is_base_standard(self) -> bool:
        return not self.verified_against_published_spec


#: The base ISO 20022 standard, exactly as published. Every field
#: identifier here is taken from the XSDs in `tests/fixtures/iso20022/`,
#: not from memory.
BASE_ISO_20022: Final[DepositoryProfile] = DepositoryProfile(
    name="base-iso20022",
    verified_against_published_spec=True,  # it IS the published standard
)

#: Placeholder. Do not use to emit — the fields below are unknown, not empty.
DTCC_SETTLEMENT_PENDING: Final[DepositoryProfile] = DepositoryProfile(
    name="dtcc-settlement-UNVERIFIED",
    verified_against_published_spec=False,
)

#: Placeholder. See the November 2026 release note in the module docstring.
FEDWIRE_PENDING: Final[DepositoryProfile] = DepositoryProfile(
    name="fedwire-UNVERIFIED",
    verified_against_published_spec=False,
)
