"""Tests for ``aureon.contracts.inherent_safety``.

Per AUR-CUSTODY-001 v1.0 Section IX (twenty-plus inherent-safety
surfaces in 1:1 FIAT/digital parity).
"""

from __future__ import annotations

import pytest

from aureon.contracts.inherent_safety import (
    InherentSafetySide,
    InherentSafetySurface,
)


class TestSurfaceCoverage:
    """The doctrine declares twenty-plus surfaces in Section IX. The
    enum must enumerate every named surface — adding or removing one is
    a doctrine-modifying change."""

    def test_at_least_twenty_surfaces_declared(self) -> None:
        # Per AUR-CUSTODY-001 v1.0 Section IX wording: "twenty-plus".
        assert len(InherentSafetySurface) >= 20  # noqa: PLR2004

    def test_every_surface_has_a_side(self) -> None:
        # No surface may be undeclared on the FIAT/digital parity axis.
        for surface in InherentSafetySurface:
            assert isinstance(surface.side, InherentSafetySide)


class TestParitySymmetry:
    """1:1 FIAT/digital parity per Section IX — both leg sides must be
    represented in the inherent-safety perimeter, neither privileged."""

    def test_fiat_side_has_at_least_one_surface(self) -> None:
        fiat = [
            s for s in InherentSafetySurface if s.side is InherentSafetySide.FIAT
        ]
        assert len(fiat) >= 1

    def test_digital_side_has_at_least_one_surface(self) -> None:
        digital = [
            s for s in InherentSafetySurface if s.side is InherentSafetySide.DIGITAL
        ]
        assert len(digital) >= 1

    def test_both_sides_represented_in_settlement_inherent_safety(self) -> None:
        # FIAT settlement of material magnitude has its 1:1 partner in
        # native digital asset operations of material magnitude.
        assert (
            InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL.side
            is InherentSafetySide.FIAT
        )
        assert (
            InherentSafetySurface.NATIVE_DIGITAL_ASSET_MATERIAL.side
            is InherentSafetySide.DIGITAL
        )


class TestNamedSurfacesPresent:
    """Specific surfaces named in Section IX must each be declared."""

    @pytest.mark.parametrize(
        "surface",
        [
            InherentSafetySurface.PLEDGED_ASSET_MATERIAL,
            InherentSafetySurface.NATIVE_DIGITAL_ASSET_MATERIAL,
            InherentSafetySurface.TOKENIZED_ASSET_ISSUER,
            InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL,
            InherentSafetySurface.CORRESPONDENT_BANKING_INTEGRITY,
            InherentSafetySurface.DEPOSITORY_MEMBERSHIP,
            InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY,
            InherentSafetySurface.FX_BUNDLED_SETTLEMENT,
            InherentSafetySurface.KEY_CEREMONY,
            InherentSafetySurface.COLD_STORAGE,
            InherentSafetySurface.CUSTODIAN_OF_CUSTODIAN,
            InherentSafetySurface.BENEFICIAL_OWNER_IDENTITY_CHANGE,
            InherentSafetySurface.QUORUM_ENROLLMENT_CHANGE,
            InherentSafetySurface.PHYSICAL_COMMODITY_VAULT_MATERIAL,
            InherentSafetySurface.REAL_ESTATE_TITLE,
            InherentSafetySurface.IP_RIGHTS_MATERIAL,
            InherentSafetySurface.INSURANCE_CONTRACT_MATERIAL,
            InherentSafetySurface.ILS_TRIGGER_DETERMINATION,
            InherentSafetySurface.CARBON_CREDIT_REGISTRY_MATERIAL,
            InherentSafetySurface.PHYSICAL_ASSET_AUTHENTICATION,
        ],
    )
    def test_surface_is_declared(self, surface: InherentSafetySurface) -> None:
        assert surface in InherentSafetySurface


class TestSerializationStability:
    """The string values appear in DSOR records — changes are
    doctrine-modifying."""

    def test_round_trip_through_string(self) -> None:
        for surface in InherentSafetySurface:
            assert InherentSafetySurface(surface.value) is surface

    def test_side_round_trip_through_string(self) -> None:
        for side in InherentSafetySide:
            assert InherentSafetySide(side.value) is side
