"""Tests for ``aureon.contracts.asset_class``.

Per AUR-CUSTODY-001 v1.0 Section III (asset-class universe).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.asset_class import (
    AssetClass,
    MajorAssetCategory,
    Representation,
)


class TestMajorCategoryCoverage:
    def test_eleven_categories_total(self) -> None:
        # Ten doctrinal categories + EMERGING = eleven enum members per
        # AUR-CUSTODY-001 v1.0 Section III.
        assert len(MajorAssetCategory) == 11  # noqa: PLR2004

    def test_emerging_category_present(self) -> None:
        # Per Section III "Emerging and Future Asset Categories" — the
        # framework must absorb future categories without rebuild.
        assert MajorAssetCategory.EMERGING in MajorAssetCategory


class TestRepresentationCoverage:
    def test_three_representations(self) -> None:
        assert {r.value for r in Representation} == {
            "FIAT",
            "TOKENIZED",
            "NATIVE_DIGITAL",
        }


class TestFiatCategoryConstruction:
    """FIAT-only categories require representation=FIAT and no
    underlying_category. Per Section III."""

    @pytest.mark.parametrize(
        "category",
        [
            MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
            MajorAssetCategory.FUNDS_AND_POOLED_VEHICLES,
            MajorAssetCategory.PHYSICAL_AND_FINANCIAL_COMMODITIES,
            MajorAssetCategory.REAL_ESTATE_AND_REAL_ASSETS,
            MajorAssetCategory.INSURANCE_AND_REINSURANCE,
            MajorAssetCategory.INTELLECTUAL_PROPERTY_AND_ROYALTIES,
            MajorAssetCategory.TRADE_FINANCE_AND_RECEIVABLES,
            MajorAssetCategory.ALTERNATIVE_AND_SPECIALTY_ASSETS,
        ],
    )
    def test_fiat_category_with_fiat_representation_accepted(
        self, category: MajorAssetCategory
    ) -> None:
        asset = AssetClass(
            major_category=category,
            representation=Representation.FIAT,
            sub_category="Treasury",
        )
        assert asset.major_category is category
        assert asset.representation is Representation.FIAT

    def test_fiat_category_with_tokenized_representation_rejected(self) -> None:
        # Tokenized variants of FIAT-only categories must be classified
        # under TOKENIZED_REPRESENTATIONS, not under the FIAT category.
        with pytest.raises(ValidationError, match="FIAT-only"):
            AssetClass(
                major_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
                representation=Representation.TOKENIZED,
                sub_category="Treasury",
            )

    def test_fiat_category_with_native_digital_representation_rejected(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match="FIAT-only"):
            AssetClass(
                major_category=(
                    MajorAssetCategory.PHYSICAL_AND_FINANCIAL_COMMODITIES
                ),
                representation=Representation.NATIVE_DIGITAL,
                sub_category="Gold",
            )

    def test_fiat_category_with_underlying_rejected(self) -> None:
        with pytest.raises(ValidationError, match="underlying_category"):
            AssetClass(
                major_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
                representation=Representation.FIAT,
                sub_category="Treasury",
                underlying_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
            )


class TestTokenizedRepresentationConstruction:
    """TOKENIZED_REPRESENTATIONS requires representation=TOKENIZED and
    a valid (FIAT-class) underlying_category. Per Section III."""

    def test_tokenized_treasury_accepted(self) -> None:
        asset = AssetClass(
            major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
            representation=Representation.TOKENIZED,
            sub_category="Tokenized Treasury BUIDL",
            underlying_category=(
                MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
            ),
        )
        assert (
            asset.underlying_category
            is MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
        )

    def test_tokenized_gold_accepted(self) -> None:
        asset = AssetClass(
            major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
            representation=Representation.TOKENIZED,
            sub_category="PAXG",
            underlying_category=(
                MajorAssetCategory.PHYSICAL_AND_FINANCIAL_COMMODITIES
            ),
        )
        assert (
            asset.underlying_category
            is MajorAssetCategory.PHYSICAL_AND_FINANCIAL_COMMODITIES
        )

    def test_tokenized_with_fiat_representation_rejected(self) -> None:
        with pytest.raises(ValidationError, match="representation=TOKENIZED"):
            AssetClass(
                major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
                representation=Representation.FIAT,
                sub_category="BUIDL",
                underlying_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
            )

    def test_tokenized_without_underlying_rejected(self) -> None:
        with pytest.raises(ValidationError, match="underlying_category"):
            AssetClass(
                major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
                representation=Representation.TOKENIZED,
                sub_category="BUIDL",
            )

    def test_tokenized_with_tokenized_underlying_rejected(self) -> None:
        # No recursive tokenization in the doctrine.
        with pytest.raises(ValidationError, match="not a coherent underlying"):
            AssetClass(
                major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
                representation=Representation.TOKENIZED,
                sub_category="recursive",
                underlying_category=(
                    MajorAssetCategory.TOKENIZED_REPRESENTATIONS
                ),
            )

    def test_tokenized_with_native_digital_underlying_rejected(self) -> None:
        # Native digital assets have no FIAT underlying — they cannot be
        # the underlying of a tokenized representation in the doctrine.
        with pytest.raises(ValidationError, match="not a coherent underlying"):
            AssetClass(
                major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
                representation=Representation.TOKENIZED,
                sub_category="tokenized-eth",
                underlying_category=(
                    MajorAssetCategory.NATIVE_DIGITAL_ASSETS
                ),
            )


class TestNativeDigitalConstruction:
    """NATIVE_DIGITAL_ASSETS requires representation=NATIVE_DIGITAL and
    no underlying_category. Per Section III."""

    def test_eth_accepted(self) -> None:
        asset = AssetClass(
            major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
            representation=Representation.NATIVE_DIGITAL,
            sub_category="ETH",
        )
        assert asset.representation is Representation.NATIVE_DIGITAL

    def test_native_digital_with_fiat_representation_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="representation=NATIVE_DIGITAL"
        ):
            AssetClass(
                major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
                representation=Representation.FIAT,
                sub_category="ETH",
            )

    def test_native_digital_with_tokenized_representation_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValidationError, match="representation=NATIVE_DIGITAL"
        ):
            AssetClass(
                major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
                representation=Representation.TOKENIZED,
                sub_category="ETH",
            )

    def test_native_digital_with_underlying_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="no FIAT underlying"
        ):
            AssetClass(
                major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
                representation=Representation.NATIVE_DIGITAL,
                sub_category="ETH",
                underlying_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
            )


class TestEmergingCategory:
    """EMERGING is intentionally unconstrained — Section III commits to
    absorbing future categories through configuration rather than
    rebuild."""

    @pytest.mark.parametrize(
        "representation",
        [
            Representation.FIAT,
            Representation.TOKENIZED,
            Representation.NATIVE_DIGITAL,
        ],
    )
    def test_emerging_accepts_any_representation(
        self, representation: Representation
    ) -> None:
        asset = AssetClass(
            major_category=MajorAssetCategory.EMERGING,
            representation=representation,
            sub_category="future-asset",
        )
        assert asset.major_category is MajorAssetCategory.EMERGING


class TestSubCategoryValidation:
    def test_sub_category_required(self) -> None:
        with pytest.raises(ValidationError):
            AssetClass(  # type: ignore[call-arg]
                major_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
                representation=Representation.FIAT,
            )

    def test_empty_sub_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AssetClass(
                major_category=(
                    MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
                ),
                representation=Representation.FIAT,
                sub_category="",
            )


class TestImmutability:
    def test_frozen(self) -> None:
        asset = AssetClass(
            major_category=(
                MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
            ),
            representation=Representation.FIAT,
            sub_category="Treasury",
        )
        with pytest.raises(ValidationError):
            asset.sub_category = "Corporate"  # type: ignore[misc]
