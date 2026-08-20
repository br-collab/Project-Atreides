"""Tests for the venue margin profile registry.

House convention: every validator carries a positive and a negative test.
The negative tests are the point - each one asserts that the registry refuses
to record something it cannot attribute.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from atreides.contracts.margin_profile import (
    CollateralEligibility,
    CollectionModel,
    DeterminabilityRegime,
    MonitoringModel,
    ProfileStatus,
    ResponsivenessObservation,
    RevocationAuthority,
    VenueMarginProfile,
    absent_margin_profile,
)

CITATION = "Venue public disclosure, Q3 2026"


# --------------------------------------------------------------------------
# Default posture
# --------------------------------------------------------------------------


def test_default_profile_is_unverified_and_asserts_nothing() -> None:
    profile = VenueMarginProfile(venue_id="VENUE_A")
    assert profile.status is ProfileStatus.UNVERIFIED
    assert profile.determinability is DeterminabilityRegime.UNDISCLOSED
    assert profile.collection_model is CollectionModel.UNKNOWN
    assert profile.revocation_authority is RevocationAuthority.NONE_DISCLOSED
    assert profile.model_type is None


def test_absent_profile_returns_unverified_never_populated() -> None:
    """The fail-safe default. A missing profile is not an empty profile."""
    profile = absent_margin_profile("VENUE_UNKNOWN")
    assert profile.status is ProfileStatus.UNVERIFIED
    assert profile.status is not ProfileStatus.POPULATED
    assert profile.figure_may_be_trusted_absolutely is False


# --------------------------------------------------------------------------
# Provenance is required to populate
# --------------------------------------------------------------------------


def test_populated_profile_with_provenance_is_accepted() -> None:
    profile = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        model_type="Full collateralisation to maximum loss",
        determinability=DeterminabilityRegime.FULLY_COLLATERALIZED,
        collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
        provenance=CITATION,
    )
    assert profile.status is ProfileStatus.POPULATED
    assert profile.provenance == CITATION


def test_populated_profile_without_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires provenance"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            status=ProfileStatus.POPULATED,
            model_type="Some model",
        )


# --------------------------------------------------------------------------
# An unverified profile may not assert
# --------------------------------------------------------------------------


def test_unverified_profile_rejects_model_assertion() -> None:
    with pytest.raises(ValidationError, match="may not assert model characteristics"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            status=ProfileStatus.UNVERIFIED,
            model_type="VaR, two-day close-out",
        )


def test_unverified_profile_rejects_determinability_assertion() -> None:
    with pytest.raises(ValidationError, match="may not assert a determinability regime"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            status=ProfileStatus.UNVERIFIED,
            determinability=DeterminabilityRegime.PUBLISHED_PARAMETER,
        )


def test_unverified_profile_may_still_record_collection_model() -> None:
    """Collection windows are observable operationally without a margin
    disclosure, so they are deliberately not gated behind population."""
    profile = VenueMarginProfile(
        venue_id="VENUE_A",
        collection_model=CollectionModel.REQUIRED_WEEKEND_POSTING,
    )
    assert profile.collection_model is CollectionModel.REQUIRED_WEEKEND_POSTING


# --------------------------------------------------------------------------
# Collateral eligibility
# --------------------------------------------------------------------------


def test_collateral_with_haircut_and_source_is_accepted() -> None:
    item = CollateralEligibility(
        asset_identifier="USD_CASH",
        haircut_pct=Decimal("0"),
        source="VENUE_PUBLISHED",
    )
    assert item.haircut_pct == Decimal("0")


def test_collateral_haircut_without_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="without provenance is an inference"):
        CollateralEligibility(
            asset_identifier="TOKENIZED_MMF",
            haircut_pct=Decimal("5"),
            source="UNVERIFIED",
        )


def test_collateral_may_be_listed_without_a_haircut() -> None:
    """Knowing an asset is eligible is useful even where the haircut is not
    published. The registry records the eligibility and stays silent on the
    number."""
    item = CollateralEligibility(asset_identifier="TOKENIZED_TREASURY")
    assert item.haircut_pct is None
    assert item.source == "UNVERIFIED"


def test_collateral_haircut_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CollateralEligibility(
            asset_identifier="USD_CASH",
            haircut_pct=Decimal("101"),
            source="VENUE_PUBLISHED",
        )


# --------------------------------------------------------------------------
# Responsiveness observations
# --------------------------------------------------------------------------


def test_responsiveness_with_source_is_accepted() -> None:
    obs = ResponsivenessObservation(
        period_label="2026Q2",
        margin_rate_of_change=Decimal("0.18"),
        market_rate_of_change=Decimal("0.11"),
        source="VENUE_PUBLISHED",
    )
    assert obs.period_label == "2026Q2"


def test_responsiveness_without_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="UNVERIFIED"):
        ResponsivenessObservation(
            period_label="2026Q2",
            margin_rate_of_change=Decimal("0.18"),
        )


def test_empty_responsiveness_period_is_permitted() -> None:
    """A period with no published figure is recorded as a gap rather than
    omitted, so the absence is visible in the series."""
    obs = ResponsivenessObservation(period_label="2026Q1")
    assert obs.margin_rate_of_change is None


# --------------------------------------------------------------------------
# Trust property
# --------------------------------------------------------------------------


def test_trust_is_true_only_for_populated_full_collateralisation() -> None:
    trusted = VenueMarginProfile(
        venue_id="VENUE_FC",
        status=ProfileStatus.POPULATED,
        determinability=DeterminabilityRegime.FULLY_COLLATERALIZED,
        provenance=CITATION,
    )
    assert trusted.figure_may_be_trusted_absolutely is True


def test_trust_is_false_for_published_parameter_regime() -> None:
    """Derivable is not the same as deterministic. The bar is deliberately
    high and there is no middle rating."""
    derivable = VenueMarginProfile(
        venue_id="VENUE_PP",
        status=ProfileStatus.POPULATED,
        determinability=DeterminabilityRegime.PUBLISHED_PARAMETER,
        provenance=CITATION,
    )
    assert derivable.figure_may_be_trusted_absolutely is False


def test_trust_is_false_when_unpopulated_even_if_regime_would_qualify() -> None:
    assert absent_margin_profile("VENUE_X").figure_may_be_trusted_absolutely is False


# --------------------------------------------------------------------------
# Revocation authority is recorded, not judged
# --------------------------------------------------------------------------


def test_both_revocation_forms_are_representable() -> None:
    """Cross-venue research established that emergency authority exists
    everywhere and differs in form. The registry records which form; it does
    not rank them."""
    administered = VenueMarginProfile(
        venue_id="VENUE_ADMIN",
        status=ProfileStatus.POPULATED,
        revocation_authority=RevocationAuthority.LIQUIDATION_AT_ADMINISTERED_PRICE,
        provenance=CITATION,
    )
    cancelled = VenueMarginProfile(
        venue_id="VENUE_CANCEL",
        status=ProfileStatus.POPULATED,
        revocation_authority=RevocationAuthority.CANCELLATION_AND_RETURN_OF_FUNDS,
        provenance=CITATION,
    )
    assert administered.revocation_authority is not cancelled.revocation_authority


# --------------------------------------------------------------------------
# Immutability and determinism
# --------------------------------------------------------------------------


def test_profile_is_frozen() -> None:
    profile = absent_margin_profile("VENUE_A")
    with pytest.raises(ValidationError):
        profile.venue_id = "VENUE_B"  # type: ignore[misc]


def test_identical_inputs_produce_identical_profiles() -> None:
    a = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        determinability=DeterminabilityRegime.DISCRETIONARY,
        provenance=CITATION,
    )
    b = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        determinability=DeterminabilityRegime.DISCRETIONARY,
        provenance=CITATION,
    )
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VenueMarginProfile(venue_id="VENUE_A", predicted_margin=Decimal("1000"))  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Monitoring: when the venue can SEE, as distinct from when it can collect
# --------------------------------------------------------------------------


def test_monitoring_is_unassessed_by_default() -> None:
    """The safe state, and NOT the same as a venue that watches
    continuously. Defaulting to CONTINUOUS would let every unread venue read
    as one that observes everything."""
    assert absent_margin_profile("VENUE_A").monitoring_model is (
        MonitoringModel.NOT_ASSESSED
    )
    assert absent_margin_profile("VENUE_A").monitoring_window is None


def test_a_bounded_window_may_be_recorded_with_its_hours() -> None:
    profile = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        monitoring_model=MonitoringModel.BOUNDED_WINDOW,
        monitoring_window="15-minute cycle, 06:00-23:00 venue local time",
        provenance=CITATION,
    )
    assert profile.monitoring_window is not None


def test_a_bounded_window_without_its_hours_is_refused() -> None:
    """The gap between the monitoring window and the trading session IS the
    finding. A bare flag cannot produce it."""
    with pytest.raises(ValidationError, match="must state the window"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            status=ProfileStatus.POPULATED,
            monitoring_model=MonitoringModel.BOUNDED_WINDOW,
            provenance=CITATION,
        )


def test_hours_may_not_be_recorded_against_an_unbounded_model() -> None:
    with pytest.raises(ValidationError, match="meaningful only under BOUNDED_WINDOW"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            status=ProfileStatus.POPULATED,
            monitoring_model=MonitoringModel.CONTINUOUS,
            monitoring_window="06:00-23:00",
            provenance=CITATION,
        )


def test_an_unverified_profile_may_not_assert_a_monitoring_model() -> None:
    """Same discipline as every other field here: an entry nobody populated
    cannot carry a claim about the venue."""
    with pytest.raises(ValidationError, match="UNVERIFIED profile"):
        VenueMarginProfile(
            venue_id="VENUE_A",
            monitoring_model=MonitoringModel.CONTINUOUS,
        )


def test_monitoring_and_collection_are_separate_axes() -> None:
    """The condition the extended-hours signal memo turned up: a venue can
    collect on traditional hours only and still monitor on a bounded cycle,
    and those two facts answer different questions. Collapsing them would
    have the framework report an uncollectable exposure where the position
    rolls into a start-of-day call that will be made."""
    profile = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
        monitoring_model=MonitoringModel.BOUNDED_WINDOW,
        monitoring_window="15-minute cycle, 06:00-23:00 venue local time",
        provenance=CITATION,
    )
    assert profile.collection_model is CollectionModel.TRADITIONAL_HOURS_ONLY
    assert profile.monitoring_model is MonitoringModel.BOUNDED_WINDOW


def test_nothing_published_is_distinct_from_nothing_read() -> None:
    """The distinction this framework draws everywhere. A venue that
    publishes no monitoring arrangement was read; a NOT_ASSESSED one was
    not, and the remedies are different."""
    assert MonitoringModel.NONE_PUBLISHED is not MonitoringModel.NOT_ASSESSED
    read = VenueMarginProfile(
        venue_id="VENUE_A",
        status=ProfileStatus.POPULATED,
        monitoring_model=MonitoringModel.NONE_PUBLISHED,
        provenance=CITATION,
    )
    assert read.monitoring_window is None


# --------------------------------------------------------------------------
# Deliberate absence
# --------------------------------------------------------------------------


def test_no_test_asserts_a_predicted_margin_figure() -> None:
    """Placeholder marking a deliberate absence.

    There is no forecast in this module and no test of one. A reader looking
    for predictive coverage should find this note instead of a gap.
    Doctrine: AUR-CUSTODY-MARGIN-001 sec. 2.
    """
    assert not hasattr(VenueMarginProfile, "predict_margin")
