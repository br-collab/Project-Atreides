"""Every registry entry must be exportable, losslessly, without this package.

WHY THIS IS A TEST AND NOT A README SENTENCE
-------------------------------------------
A licensee that populates ten thousand venue profiles inside this framework
has accumulated ten thousand framework-specific assets, and the semantic
layer is the highest-switching-cost layer in any stack. "We sit above the
platform" is not an answer to that; it is the same lock-in one level up, and
a chief data officer will say so.

The only honest answer is a portability commitment, and a commitment nobody
can check is marketing. So it is asserted here: every registry model
round-trips through plain JSON, and the exported form is readable by anything
that can read JSON. Populating a profile creates data the licensee owns and
can take with them, not an asset this framework holds hostage.

Doctrine: AUR-REGISTRY-PORTABILITY-001 (draft).
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

from atreides.contracts.margin_impact import (
    IndeterminacyReason,
    MarginDirection,
    MarginDisposition,
    MarginImpact,
    Observability,
)
from atreides.contracts.margin_profile import (
    CollateralEligibility,
    DeterminabilityRegime,
    ProfileStatus,
    ResponsivenessObservation,
    VenueMarginProfile,
)
from atreides.rails.cns import CloseOutRegime, MarketProfile
from atreides.rails.determination import DeterminationProfile, RevocationForm

CITATION = "portability test"


def _pydantic_registries() -> list[object]:
    return [
        VenueMarginProfile(
            venue_id="V1",
            status=ProfileStatus.POPULATED,
            determinability=DeterminabilityRegime.PUBLISHED_PARAMETER,
            eligible_collateral=(
                CollateralEligibility(
                    asset_identifier="USD_CASH",
                    haircut_pct=Decimal("0"),
                    source="VENUE_PUBLISHED",
                ),
            ),
            responsiveness=(
                ResponsivenessObservation(
                    period_label="2026Q2",
                    margin_rate_of_change=Decimal("0.18"),
                    source="VENUE_PUBLISHED",
                ),
            ),
            provenance=CITATION,
        ),
        MarginImpact(
            disposition=MarginDisposition.INDETERMINATE,
            direction=MarginDirection.UNKNOWN,
            observability=Observability.UNOBSERVABLE,
            collateral_observability=Observability.UNOBSERVABLE,
            indeterminacy=IndeterminacyReason.UNREAD_VENUE_PROFILE,
            basis=CITATION,
        ),
    ]


def _dataclass_registries() -> list[object]:
    return [
        DeterminationProfile(
            venue_id="V1",
            revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
            qualification_window_seconds=86_400,
            provenance=CITATION,
        ),
        MarketProfile(
            market_id="XCLR",
            settlement_cycle_days=1,
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            close_out_deadline_days=3,
            allocation_rule_published=True,
            provenance=CITATION,
        ),
    ]


def test_every_pydantic_registry_round_trips_through_json() -> None:
    for original in _pydantic_registries():
        payload = original.model_dump_json()  # type: ignore[attr-defined]
        restored = type(original).model_validate_json(payload)  # type: ignore[attr-defined]
        assert restored == original
        assert restored.model_dump_json() == payload  # type: ignore[attr-defined]


def test_every_dataclass_registry_round_trips_through_json() -> None:
    for original in _dataclass_registries():
        payload = json.dumps(dataclasses.asdict(original), default=str)  # type: ignore[arg-type]
        restored = type(original)(**json.loads(payload))
        assert restored == original


def test_the_exported_form_needs_nothing_from_this_package() -> None:
    """The commitment in its operative form: what comes out is plain JSON
    with plain scalars, readable by anything, with no framework types
    embedded in it."""
    for original in _pydantic_registries():
        decoded = json.loads(original.model_dump_json())  # type: ignore[attr-defined]
        assert isinstance(decoded, dict)
        rendered = json.dumps(decoded)
        assert "atreides" not in rendered
        assert "object at 0x" not in rendered


def test_provenance_survives_export() -> None:
    """The citation is the reason a populated profile is worth anything.
    An export that dropped it would hand back numbers with no attribution -
    which this framework treats as indistinguishable from guesses."""
    for original in _pydantic_registries() + _dataclass_registries():
        rendered = (
            original.model_dump_json()  # type: ignore[attr-defined]
            if hasattr(original, "model_dump_json")
            else json.dumps(dataclasses.asdict(original), default=str)  # type: ignore[arg-type]
        )
        assert CITATION in rendered


def test_no_registry_holds_an_unexportable_field() -> None:
    """A field that cannot be serialised is a field that cannot leave, and
    one is enough to break the commitment."""
    for original in _pydantic_registries():
        json.loads(original.model_dump_json())  # type: ignore[attr-defined]
    for original in _dataclass_registries():
        json.dumps(dataclasses.asdict(original), default=str)  # type: ignore[arg-type]
