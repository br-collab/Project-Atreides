"""Tests for ``aureon.contracts.custody_object``.

Per AUR-CUSTODY-001 v1.0 Section IV (Custody Object Inventory Applied
to Operations).
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from aureon.contracts.asset_class import (
    AssetClass,
    MajorAssetCategory,
    Representation,
)
from aureon.contracts.custody_object import (
    CustodyObject,
    CustodyObjectCategory,
    Encumbrance,
    EncumbranceType,
    NativeDigitalAssetObject,
    OrdinarySafekeepingObject,
    PledgedAssetObject,
    SMAObject,
    TokenizedSecurityObject,
)

_ADAPTER: TypeAdapter[CustodyObject] = TypeAdapter(CustodyObject)


def _treasury_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="Treasury",
        asset_identifier="912828YV6",
    )


def _tokenized_treasury_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
        representation=Representation.TOKENIZED,
        sub_category="BUIDL",
        underlying_category=(
            MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
        ),
    )


def _eth_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
        representation=Representation.NATIVE_DIGITAL,
        sub_category="ETH",
    )


class TestCategoryCoverage:
    def test_five_categories_enumerated(self) -> None:
        # Per AUR-CUSTODY-001 v1.0 Section IV — five categories.
        assert len(CustodyObjectCategory) == 5  # noqa: PLR2004


class TestOrdinarySafekeeping:
    def test_construction(self) -> None:
        obj = OrdinarySafekeepingObject(
            beneficial_owner_id="bo-pension-fund-x",
            asset_class=_treasury_asset(),
        )
        assert obj.category is CustodyObjectCategory.ORDINARY_SAFEKEEPING

    def test_beneficial_owner_required(self) -> None:
        with pytest.raises(ValidationError):
            OrdinarySafekeepingObject(  # type: ignore[call-arg]
                asset_class=_treasury_asset(),
            )


class TestPledgedAsset:
    def _encumbrance(self) -> Encumbrance:
        return Encumbrance(
            encumbrance_type=EncumbranceType.REPO,
            lien_holder_id="cp-jpmorgan-prime",
            lien_priority=1,
        )

    def test_construction(self) -> None:
        obj = PledgedAssetObject(
            beneficial_owner_id="bo-pension-fund-x",
            asset_class=_treasury_asset(),
            encumbrance=self._encumbrance(),
        )
        assert obj.encumbrance.encumbrance_type is EncumbranceType.REPO

    def test_encumbrance_required(self) -> None:
        with pytest.raises(ValidationError):
            PledgedAssetObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-pension-fund-x",
                asset_class=_treasury_asset(),
            )


class TestEncumbrance:
    def test_lien_priority_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Encumbrance(
                encumbrance_type=EncumbranceType.REPO,
                lien_holder_id="cp-x",
                lien_priority=0,
            )

    def test_default_rehypothecation_is_false(self) -> None:
        encumbrance = Encumbrance(
            encumbrance_type=EncumbranceType.REPO,
            lien_holder_id="cp-x",
            lien_priority=1,
        )
        assert encumbrance.rehypothecation_permitted is False


class TestSMA:
    def test_construction_with_account_id(self) -> None:
        obj = SMAObject(
            beneficial_owner_id="bo-endowment-y",
            asset_class=_treasury_asset(),
            account_id="SMA-2026-001",
        )
        assert obj.account_id == "SMA-2026-001"

    def test_account_id_required(self) -> None:
        with pytest.raises(ValidationError):
            SMAObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-endowment-y",
                asset_class=_treasury_asset(),
            )

    def test_empty_account_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SMAObject(
                beneficial_owner_id="bo-endowment-y",
                asset_class=_treasury_asset(),
                account_id="",
            )


class TestTokenizedSecurity:
    def test_construction(self) -> None:
        obj = TokenizedSecurityObject(
            beneficial_owner_id="bo-treasury-mgmt-z",
            asset_class=_tokenized_treasury_asset(),
            rail="ethereum_l1",
            contract_address="0xabc...",
        )
        assert obj.rail == "ethereum_l1"

    def test_rail_required(self) -> None:
        with pytest.raises(ValidationError):
            TokenizedSecurityObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-treasury-mgmt-z",
                asset_class=_tokenized_treasury_asset(),
                contract_address="0xabc...",
            )

    def test_contract_address_required(self) -> None:
        with pytest.raises(ValidationError):
            TokenizedSecurityObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-treasury-mgmt-z",
                asset_class=_tokenized_treasury_asset(),
                rail="ethereum_l1",
            )

    def test_non_tokenized_asset_class_rejected(self) -> None:
        # Constructing with a FIAT-class asset (e.g., raw Treasury)
        # should fail — the object claims tokenization but the asset
        # class doesn't reflect it.
        with pytest.raises(
            ValidationError,
            match=r"major_category=TOKENIZED_REPRESENTATIONS",
        ):
            TokenizedSecurityObject(
                beneficial_owner_id="bo-treasury-mgmt-z",
                asset_class=_treasury_asset(),
                rail="ethereum_l1",
                contract_address="0xabc...",
            )


class TestNativeDigitalAsset:
    def test_construction(self) -> None:
        obj = NativeDigitalAssetObject(
            beneficial_owner_id="bo-crypto-fund",
            asset_class=_eth_asset(),
            chain="ethereum",
            custody_address="0xfeed...",
        )
        assert obj.chain == "ethereum"

    def test_chain_required(self) -> None:
        with pytest.raises(ValidationError):
            NativeDigitalAssetObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-crypto-fund",
                asset_class=_eth_asset(),
                custody_address="0xfeed...",
            )

    def test_custody_address_required(self) -> None:
        with pytest.raises(ValidationError):
            NativeDigitalAssetObject(  # type: ignore[call-arg]
                beneficial_owner_id="bo-crypto-fund",
                asset_class=_eth_asset(),
                chain="ethereum",
            )

    def test_non_native_digital_asset_class_rejected(self) -> None:
        with pytest.raises(
            ValidationError,
            match=r"major_category=NATIVE_DIGITAL_ASSETS",
        ):
            NativeDigitalAssetObject(
                beneficial_owner_id="bo-crypto-fund",
                asset_class=_treasury_asset(),
                chain="ethereum",
                custody_address="0xfeed...",
            )


class TestDiscriminatedUnion:
    """The CustodyObject TypeAdapter dispatches on the ``category``
    field — the way operations and DSOR replay reconstruct objects."""

    def test_ordinary_from_dict(self) -> None:
        obj = _ADAPTER.validate_python(
            {
                "category": "ordinary_safekeeping",
                "beneficial_owner_id": "bo-x",
                "asset_class": _treasury_asset().model_dump(),
            }
        )
        assert isinstance(obj, OrdinarySafekeepingObject)

    def test_pledged_from_dict(self) -> None:
        obj = _ADAPTER.validate_python(
            {
                "category": "pledged_asset",
                "beneficial_owner_id": "bo-x",
                "asset_class": _treasury_asset().model_dump(),
                "encumbrance": {
                    "encumbrance_type": "repo",
                    "lien_holder_id": "cp-x",
                    "lien_priority": 1,
                    "rehypothecation_permitted": False,
                },
            }
        )
        assert isinstance(obj, PledgedAssetObject)

    def test_native_digital_from_dict(self) -> None:
        obj = _ADAPTER.validate_python(
            {
                "category": "native_digital_asset",
                "beneficial_owner_id": "bo-x",
                "asset_class": _eth_asset().model_dump(),
                "chain": "ethereum",
                "custody_address": "0xfeed",
            }
        )
        assert isinstance(obj, NativeDigitalAssetObject)

    def test_unknown_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "category": "fictional-category",
                    "beneficial_owner_id": "bo-x",
                    "asset_class": _treasury_asset().model_dump(),
                }
            )

    def test_pledged_without_encumbrance_rejected_via_union(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "category": "pledged_asset",
                    "beneficial_owner_id": "bo-x",
                    "asset_class": _treasury_asset().model_dump(),
                }
            )
