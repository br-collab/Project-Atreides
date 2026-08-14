"""Venue margin profile registry.

Structured home for venue margin characteristics that this framework consumes
and does not compute. Parallels ``DepositoryProfile``: the registry ships with
the shape defined and the entries flagged, never populated by inference.

Doctrine: AUR-CUSTODY-MARGIN-001 (draft). See also SPEC-MARGIN-AWARE-BREAKS v0.2
sections 2 (determinism boundary), 3 (standards posture) and 4 (this registry).

NOTE on RevocationAuthority. NONE_DISCLOSED conflates "we read the rulebook and
it grants no such power" with "we have not read it". The determination registry
in ``atreides.rails.determination`` corrects that by separating NOT_ASSESSED from
NONE_DISCLOSED, and this enum should be brought into line - tracked as an open
item in AUR-CUSTODY-CASH-AMD-002 section 4.3. Today the disambiguator is
``status``: an UNVERIFIED profile means nobody looked.

Implements SPEC-MARGIN-AWARE-BREAKS v0.2 section 4 (registry prerequisite).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileStatus(StrEnum):
    """Population state of a registry entry.

    ``UNVERIFIED`` is the default and the safe state. A profile is never
    inferred: an entry that has not been populated from an entitled source
    stays UNVERIFIED, and consumers must treat its fields as absent rather
    than as defaults. AUR-CUSTODY-MARGIN-001 sec. 4.
    """

    UNVERIFIED = "UNVERIFIED"
    POPULATED = "POPULATED"
    SUPERSEDED = "SUPERSEDED"


class DeterminabilityRegime(StrEnum):
    """How knowable a venue's margin figure is from outside the venue.

    Determinability is a property of the venue and product, not of the
    framework. It governs how much weight an operator may place on any
    supplied figure. AUR-CUSTODY-MARGIN-001 sec. 2.
    """

    FULLY_COLLATERALIZED = "FULLY_COLLATERALIZED"
    """Margin is maximum loss, known at execution. Deterministic."""

    PUBLISHED_PARAMETER = "PUBLISHED_PARAMETER"
    """Risk model with disclosed parameters and no discretionary add-ons.
    Closely derivable; a supplied figure can be sanity-checked."""

    DISCRETIONARY = "DISCRETIONARY"
    """Risk model with judgment add-ons or intraday discretion. Not derivable;
    a supplied figure must be taken as given or refused."""

    UNDISCLOSED = "UNDISCLOSED"
    """Venue publishes no methodology on any standard basis. The correct
    downstream disposition is INDETERMINATE."""


class CollectionModel(StrEnum):
    """When the venue can actually call and collect margin.

    Taxonomy follows the three clearing models named in the CFTC staff
    advisory on 24/7 trading and clearing (Letter 26-16, 29 May 2026).
    Continuous trading against periodic collection is the condition that
    produces the CALL_WINDOW_CLOSED disposition.
    """

    TRADITIONAL_HOURS_ONLY = "TRADITIONAL_HOURS_ONLY"
    OPTIONAL_WEEKEND_POSTING = "OPTIONAL_WEEKEND_POSTING"
    REQUIRED_WEEKEND_POSTING = "REQUIRED_WEEKEND_POSTING"
    UNKNOWN = "UNKNOWN"


class RevocationAuthority(StrEnum):
    """Whether and how the venue may alter an outcome after determination.

    Cross-venue research (14 Aug 2026) established that broad emergency
    authority exists at every DCM examined, so revocability is a venue
    attribute rather than a defining property of any finality class. The
    forms differ materially and the difference is what matters here.
    """

    NONE_DISCLOSED = "NONE_DISCLOSED"

    LIQUIDATION_AT_ADMINISTERED_PRICE = "LIQUIDATION_AT_ADMINISTERED_PRICE"
    """Exchange may liquidate positions and establish the settlement price.
    Settlement still occurs and finality holds; the value was administered."""

    CANCELLATION_AND_RETURN_OF_FUNDS = "CANCELLATION_AND_RETURN_OF_FUNDS"
    """Exchange may cancel the contract and return funds. Finality itself is
    reversed rather than the value being set."""


class CollateralEligibility(BaseModel):
    """One eligible collateral type and its disclosed haircut."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_identifier: str = Field(min_length=1)
    haircut_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    source: Literal["VENUE_PUBLISHED", "ENTITLED_DOCUMENT", "UNVERIFIED"] = "UNVERIFIED"

    @model_validator(mode="after")
    def _haircut_requires_source(self) -> CollateralEligibility:
        if self.haircut_pct is not None and self.source == "UNVERIFIED":
            raise ValueError(
                "haircut_pct may not be set on an UNVERIFIED source; a number "
                "without provenance is an inference (AUR-CUSTODY-MARGIN-001 sec. 4)"
            )
        return self


class ResponsivenessObservation(BaseModel):
    """One period's disclosed margin responsiveness measure.

    Consumes the standardised measure of margin responsiveness alongside its
    associated volatility measure. Backward-looking by construction: this is a
    characterisation of past venue behaviour, never a forecast.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    period_label: str = Field(min_length=1)
    margin_rate_of_change: Decimal | None = None
    market_rate_of_change: Decimal | None = None
    source: Literal["VENUE_PUBLISHED", "UNVERIFIED"] = "UNVERIFIED"

    @model_validator(mode="after")
    def _values_require_source(self) -> ResponsivenessObservation:
        has_value = (
            self.margin_rate_of_change is not None
            or self.market_rate_of_change is not None
        )
        if has_value and self.source == "UNVERIFIED":
            raise ValueError(
                "responsiveness values may not be recorded against an UNVERIFIED "
                "source (AUR-CUSTODY-MARGIN-001 sec. 4)"
            )
        return self


class VenueMarginProfile(BaseModel):
    """Margin characteristics of one venue, as disclosed by that venue.

    This object holds nothing the framework computed. Every populated field
    traces to a venue publication or an entitled document. Absent that, the
    profile stays UNVERIFIED and consumers treat its fields as unavailable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue_id: str = Field(min_length=1)
    status: ProfileStatus = ProfileStatus.UNVERIFIED

    model_type: str | None = None
    calibration_notes: str | None = None
    addon_logic: str | None = None

    determinability: DeterminabilityRegime = DeterminabilityRegime.UNDISCLOSED
    collection_model: CollectionModel = CollectionModel.UNKNOWN
    revocation_authority: RevocationAuthority = RevocationAuthority.NONE_DISCLOSED

    eligible_collateral: tuple[CollateralEligibility, ...] = ()
    responsiveness: tuple[ResponsivenessObservation, ...] = ()

    provenance: str | None = Field(
        default=None,
        description="Citation for the disclosure this profile was populated from.",
    )

    @model_validator(mode="after")
    def _populated_requires_provenance(self) -> VenueMarginProfile:
        if self.status is ProfileStatus.POPULATED and not self.provenance:
            raise ValueError(
                "a POPULATED profile requires provenance; an unattributed profile "
                "is indistinguishable from a guess (AUR-CUSTODY-MARGIN-001 sec. 4)"
            )
        return self

    @model_validator(mode="after")
    def _unverified_carries_no_assertions(self) -> VenueMarginProfile:
        if self.status is ProfileStatus.UNVERIFIED:
            asserted = (
                self.model_type,
                self.calibration_notes,
                self.addon_logic,
            )
            if any(field is not None for field in asserted):
                raise ValueError(
                    "an UNVERIFIED profile may not assert model characteristics; "
                    "populate and cite, or leave absent (AUR-CUSTODY-MARGIN-001 sec. 4)"
                )
            if self.determinability is not DeterminabilityRegime.UNDISCLOSED:
                raise ValueError(
                    "an UNVERIFIED profile may not assert a determinability regime "
                    "(AUR-CUSTODY-MARGIN-001 sec. 4)"
                )
        return self

    @property
    def figure_may_be_trusted_absolutely(self) -> bool:
        """True only where margin is deterministic at the venue.

        Deliberately narrow. Anything other than full collateralisation
        against a cited disclosure returns False, because the framework does
        not distinguish degrees of trust below that bar.
        """
        return (
            self.status is ProfileStatus.POPULATED
            and self.determinability is DeterminabilityRegime.FULLY_COLLATERALIZED
        )


def absent_margin_profile(venue_id: str) -> VenueMarginProfile:
    """Return the profile for a venue with no registry entry.

    Named and exported so that "what happens when no profile exists" is
    answered in one auditable place rather than implicitly at each call site.
    The answer is always an UNVERIFIED profile asserting nothing - never a
    default-populated one. Mirrors ``absent_gate_decision()``.
    """
    return VenueMarginProfile(venue_id=venue_id, status=ProfileStatus.UNVERIFIED)


__all__ = [
    "CollateralEligibility",
    "CollectionModel",
    "DeterminabilityRegime",
    "ProfileStatus",
    "ResponsivenessObservation",
    "RevocationAuthority",
    "VenueMarginProfile",
    "absent_margin_profile",
]
