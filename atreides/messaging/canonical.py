"""Canonical cash-leg settlement model — rail-agnostic, message-agnostic.

Per AUR-CUSTODY-CASH-001 v0.2 Section VIII. The framework maintains one
internal settlement model that serialises OUT to network-native ISO 20022
and validates IN on readback. This module is that model.

WHY A CANONICAL MODEL RATHER THAN BUILDING XML DIRECTLY
-------------------------------------------------------
Depositories constrain the base ISO 20022 schemas differently, and message
variants change on their own release cadence (DTCC's Settlement Release
carries UAT V5 and V6 concurrently; Fedwire has a November 2026 release).
A model that renders to a *profile* survives those changes; code that
builds one depository's XML directly does not.

So the rule this module encodes: **the domain speaks canonical, the wire
speaks ISO 20022, and the profile is the only thing that knows the
difference.**

WHAT THIS MODEL IS NOT
----------------------
It is not a submission and cannot become one. Per
`AUR-CUSTODY-FED-001 §III` and `AUR-COCKPIT-001 §XI`, Atreides prepares,
governs and reconciles; the entitled member submits. The emitted artifact
is a validated instruction package for the member to send under their own
credentials — the same boundary the cockpit enforces by making an
`InstructionPackage` with `is_submission=True` unconstructible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from atreides.rails.cato_f import CashRail

__all__ = [
    "BICFI_PATTERN",
    "CashLegInstruction",
    "FinancialInstitution",
    "RAIL_SETTLEMENT_METHOD",
    "SettlementMethod",
    "settlement_method_for_rail",
]

#: Straight from `BICFIDec2014Identifier` in pacs.009.001.13. Encoded here
#: rather than approximated, so an invalid BIC fails in the domain model
#: instead of at the depository.
BICFI_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Z0-9]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$"
)

_MAX35 = 35


class SettlementMethod(StrEnum):
    """The four values of ISO 20022 ``SettlementMethod1Code``.

    Not an Aureon invention — this is the complete enumeration from the
    schema, and the emitter cannot produce anything outside it.
    """

    INSTRUCTED_AGENT = "INDA"
    INSTRUCTING_AGENT = "INGA"
    COVER = "COVE"
    CLEARING_SYSTEM = "CLRG"


#: Maps CATO-F's rail selection onto the settlement method the message must
#: declare. This is the join between the gate (CASH-001 §V) and the wire
#: (§VIII): the gate chooses a rail, and the rail determines how the
#: settlement is expressed on the network.
#:
#: RTGS and netted clearing systems settle through a clearing system (CLRG).
#: Correspondent chains settle on the books of an agent — which agent
#: depends on whether a cover payment is in play, so correspondent legs
#: default to COVE and are overridden per-instruction where the member
#: settles serially instead.
RAIL_SETTLEMENT_METHOD: Final[dict[CashRail, SettlementMethod]] = {
    CashRail.FEDWIRE: SettlementMethod.CLEARING_SYSTEM,
    CashRail.FEDNOW: SettlementMethod.CLEARING_SYSTEM,
    CashRail.CHIPS: SettlementMethod.CLEARING_SYSTEM,
    CashRail.NSS_DTC_NSCC: SettlementMethod.CLEARING_SYSTEM,
    CashRail.FICC_GSD_FUNDS_ONLY: SettlementMethod.CLEARING_SYSTEM,
    CashRail.CORRESPONDENT: SettlementMethod.COVER,
}


def settlement_method_for_rail(rail: CashRail) -> SettlementMethod:
    """Resolve the settlement method for a CATO-F-selected rail.

    Raises for rails with no ISO 20022 credit-transfer expression. That is
    deliberate: tokenized-deposit, stablecoin and the reserved
    ``ports_wholesale`` slot do not settle via `pacs` messages, and
    silently defaulting them to CLRG would emit a message asserting a
    clearing-system settlement that never happens.
    """
    try:
        return RAIL_SETTLEMENT_METHOD[rail]
    except KeyError:
        raise ValueError(
            f"rail {rail.value!r} has no ISO 20022 credit-transfer "
            f"expression; it does not settle through the pacs family. "
            f"Emitting a pacs message for it would assert a settlement "
            f"mechanism that does not occur (CASH-001 §III, §VIII)."
        ) from None


@dataclass(frozen=True, slots=True)
class FinancialInstitution:
    """A party to the cash leg, identified as the schema requires.

    ``FinancialInstitutionIdentification23`` makes every identifier
    optional individually, which means a schema-valid message can identify
    nobody. That is a schema permitting something the business cannot use,
    so this model requires a BICFI.
    """

    bicfi: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not BICFI_PATTERN.match(self.bicfi):
            raise ValueError(
                f"invalid BICFI {self.bicfi!r} — must match "
                f"{BICFI_PATTERN.pattern} per BICFIDec2014Identifier"
            )
        if self.name is not None and not (1 <= len(self.name) <= 140):
            raise ValueError("name must be 1..140 characters (Max140Text)")


@dataclass(frozen=True, slots=True)
class CashLegInstruction:
    """One cash-leg settlement instruction, canonical form.

    Carries exactly what the mandatory ISO 20022 path needs, plus the
    governance context that makes it replayable. Rendering to a specific
    message and variant is the emitter's job, not this model's.
    """

    message_id: str
    end_to_end_id: str
    created_at: datetime
    amount: Decimal
    currency: str
    debtor: FinancialInstitution
    creditor: FinancialInstitution
    settlement_method: SettlementMethod
    #: BAH Fr/To — the member sending and the party receiving. Distinct
    #: from debtor/creditor, which are the parties to the *payment*.
    sender: FinancialInstitution
    receiver: FinancialInstitution
    #: DSOR lineage this instruction package belongs to. Optional only so
    #: the model is testable standalone; the cockpit always supplies it.
    dsor_lineage_uri: str | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("message_id", self.message_id),
            ("end_to_end_id", self.end_to_end_id),
        ):
            if not (1 <= len(value) <= _MAX35):
                raise ValueError(
                    f"{field} must be 1..{_MAX35} characters (Max35Text); "
                    f"got {len(value)}"
                )
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        if not re.match(r"^[A-Z]{3}$", self.currency):
            raise ValueError(
                f"currency {self.currency!r} must be a 3-letter "
                f"ActiveCurrencyCode"
            )
        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware — ISODateTime on the "
                "wire is unambiguous and a naive timestamp silently "
                "asserts the emitter's local zone"
            )
