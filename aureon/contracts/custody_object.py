"""Custody object identity — the five categories.

Per AUR-CUSTODY-001 v1.0 Section IV (Custody Object Inventory Applied
to Operations). The five categories are restated in Section IV from
the source inventory in `AUR-CUSTODY-OBJ-001 v1.0` (which is not
authoritative for this build per the build prompt — the categorization
as restated in the custody doctrine governs):

1. **Ordinary safekeeping** — baseline custody object with no specific
   encumbrance, restriction, or specialised governance overlay.
2. **Pledged assets** — custody objects with active encumbrance
   (collateral pledged for repo, securities lending, derivative
   margin, credit facility, or other secured arrangement). Per
   Section IV: pledged-asset operations of material magnitude are
   quorum authority operations under Axiom 10.
3. **Separately Managed Accounts (SMAs)** — custody objects held in
   named beneficial owner accounts (rather than in omnibus
   structures). Defining characteristic: title clarity per
   beneficial owner at all times.
4. **Tokenized securities** — custody objects represented as digital
   tokens on a blockchain or distributed ledger, where the token
   represents a beneficial interest in an underlying security.
5. **Native digital assets** — custody objects whose existence is
   wholly on-chain (cryptocurrencies, native protocol tokens, NFTs,
   DeFi protocol positions). Per Section IV: all material native
   digital asset operations are quorum authority operations.

The model uses a discriminated union so each category carries its own
required fields:

- pledged: ``encumbrance`` (lien holder, encumbrance type, priority)
- SMA: ``account_id`` (the per-account beneficial-owner identification)
- tokenized: ``rail`` and ``contract_address`` (the tokenization rail)
- native digital: ``chain`` and ``custody_address`` (the on-chain
  custody location)

Cross-validators enforce that the object's ``asset_class`` is coherent
with the category — tokenized objects must reference a
``MajorAssetCategory.TOKENIZED_REPRESENTATIONS`` asset class, native
digital objects must reference a ``MajorAssetCategory.NATIVE_DIGITAL_ASSETS``
asset class.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.contracts.asset_class import AssetClass, MajorAssetCategory


class CustodyObjectCategory(StrEnum):
    """The five custody object categories per AUR-CUSTODY-001 v1.0
    Section IV."""

    ORDINARY_SAFEKEEPING = "ordinary_safekeeping"
    PLEDGED_ASSET = "pledged_asset"
    SEPARATELY_MANAGED_ACCOUNT = "separately_managed_account"
    TOKENIZED_SECURITY = "tokenized_security"
    NATIVE_DIGITAL_ASSET = "native_digital_asset"


class EncumbranceType(StrEnum):
    """Types of encumbrance on a pledged asset.

    Per AUR-CUSTODY-001 v1.0 Section V "Pledged-Asset Transaction
    Variety" enumeration — the encumbrance categories the doctrine
    commits the framework to handle.
    """

    REPO = "repo"
    SECURITIES_LENDING = "securities_lending"
    DERIVATIVE_MARGIN = "derivative_margin"
    CREDIT_FACILITY = "credit_facility"
    PRIME_BROKERAGE_MARGIN = "prime_brokerage_margin"
    CCP_MARGIN = "ccp_margin"
    CENTRAL_BANK_FACILITY = "central_bank_facility"
    OTHER_SECURED_ARRANGEMENT = "other_secured_arrangement"


class Encumbrance(BaseModel):
    """Encumbrance details required on pledged-asset custody objects.

    Per AUR-CUSTODY-001 v1.0 Section IV: pledged objects must carry
    encumbrance details that allow the framework to track the
    third-party interest, respect it through the asset's lifecycle, and
    discharge it appropriately when the underlying obligation is
    satisfied.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    encumbrance_type: EncumbranceType = Field(
        description=(
            "Category of encumbrance per AUR-CUSTODY-001 v1.0 Section V "
            "'Pledged-Asset Transaction Variety'."
        ),
    )
    lien_holder_id: str = Field(
        min_length=1,
        description=(
            "Identifier of the counterparty holding the lien — the "
            "party to whom the asset is pledged."
        ),
    )
    lien_priority: int = Field(
        ge=1,
        description=(
            "Lien priority (1 = senior, 2+ = junior). Per Section V "
            "'Lien upgrade' / 'Lien subordination' transaction "
            "variety; cross-collateralisation may produce multiple "
            "encumbrances per asset."
        ),
    )
    rehypothecation_permitted: bool = Field(
        default=False,
        description=(
            "Whether the pledgee may re-pledge the assets to a third "
            "party (Reg T limits in US, Client Money Rules in UK). "
            "Per Section V 'Rehypothecation' transaction variety."
        ),
    )


class _CustodyObjectBase(BaseModel):
    """Shared configuration and core fields for all custody object
    categories."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    beneficial_owner_id: str = Field(
        min_length=1,
        description=(
            "Identifier of the beneficial owner per AUR-CUSTODY-001 "
            "v1.0 Section II operational definition: 'Custody "
            "operations are always agency operations'."
        ),
    )
    asset_class: AssetClass = Field(
        description=(
            "The asset-class identity of the custodied asset. See "
            "``aureon.contracts.asset_class``."
        ),
    )


class OrdinarySafekeepingObject(_CustodyObjectBase):
    """Ordinary safekeeping — baseline custody object.

    Per AUR-CUSTODY-001 v1.0 Section IV: 'the largest custody category
    by volume and value across the institutional custody industry'.
    No specific encumbrance, restriction, or specialised governance
    overlay beyond standard custodian operations.
    """

    category: Literal[CustodyObjectCategory.ORDINARY_SAFEKEEPING] = (
        CustodyObjectCategory.ORDINARY_SAFEKEEPING
    )


class PledgedAssetObject(_CustodyObjectBase):
    """Pledged asset — custody object with active encumbrance.

    Per AUR-CUSTODY-001 v1.0 Section IV: 'pledged-asset operations of
    material magnitude are quorum authority operations under Axiom 10
    and the canonical v1.5 quorum primitive'. The encumbrance details
    are required at the object level so that downstream operations can
    inherit the encumbrance context.
    """

    category: Literal[CustodyObjectCategory.PLEDGED_ASSET] = (
        CustodyObjectCategory.PLEDGED_ASSET
    )
    encumbrance: Encumbrance = Field(
        description=(
            "Required encumbrance details. Per Section IV: pledged "
            "objects must carry encumbrance details (lien holder, "
            "priority, type)."
        ),
    )


class SMAObject(_CustodyObjectBase):
    """Separately Managed Account (SMA) — title-clear, per-account
    custody object.

    Per AUR-CUSTODY-001 v1.0 Section IV: 'the defining characteristic
    is title clarity: every asset in an SMA is identifiable to a
    specific beneficial owner at all times'. The ``account_id`` is the
    per-account identifier that distinguishes SMA structure from
    omnibus structure.
    """

    category: Literal[CustodyObjectCategory.SEPARATELY_MANAGED_ACCOUNT] = (
        CustodyObjectCategory.SEPARATELY_MANAGED_ACCOUNT
    )
    account_id: str = Field(
        min_length=1,
        description=(
            "Per-account identifier. Per Section IV: SMA-specific "
            "reporting (per-account positions, per-account performance "
            "attribution, per-account tax treatment, per-account "
            "corporate-action elections) requires every operation on "
            "an SMA object to carry the account identifier."
        ),
    )


class TokenizedSecurityObject(_CustodyObjectBase):
    """Tokenized security — on-chain representation of an underlying
    security.

    Per AUR-CUSTODY-001 v1.0 Section IV: 'the token-to-security mapping
    is established by the token issuer (typically the security issuer
    or an authorised custodian) and is enforced by the smart-contract
    logic governing the token'. The ``rail`` identifies which
    blockchain/ledger holds the tokenized representation; the
    ``contract_address`` identifies the token contract on that rail.
    """

    category: Literal[CustodyObjectCategory.TOKENIZED_SECURITY] = (
        CustodyObjectCategory.TOKENIZED_SECURITY
    )
    rail: str = Field(
        min_length=1,
        description=(
            "Tokenization rail identifier (e.g., 'ethereum_l1', 'base', "
            "'arbitrum', 'solana', 'fed_l1' for PORTS-aligned wholesale "
            "infrastructure)."
        ),
    )
    contract_address: str = Field(
        min_length=1,
        description=(
            "Smart contract address of the token issuer on the rail."
        ),
    )

    @model_validator(mode="after")
    def _enforce_asset_class_alignment(self) -> Self:
        """Tokenized security objects must reference a tokenized asset
        class.

        Per AUR-CUSTODY-001 v1.0 Section III: tokenized representations
        of underlying assets are classified under
        ``MajorAssetCategory.TOKENIZED_REPRESENTATIONS``. The
        ``AssetClass`` validators already enforce that
        ``TOKENIZED_REPRESENTATIONS`` implies ``representation =
        TOKENIZED``, so the major-category check below is sufficient.
        """
        if (
            self.asset_class.major_category
            is not MajorAssetCategory.TOKENIZED_REPRESENTATIONS
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section III, "
                f"TokenizedSecurityObject requires asset_class."
                f"major_category=TOKENIZED_REPRESENTATIONS, got "
                f"{self.asset_class.major_category.value!r}."
            )
        return self


class NativeDigitalAssetObject(_CustodyObjectBase):
    """Native digital asset — wholly on-chain custody object.

    Per AUR-CUSTODY-001 v1.0 Section IV: 'custody of native digital
    assets is fundamentally different from custody of tokenized
    securities because there is no off-chain underlying to reconcile
    against'. All material operations are quorum authority operations.
    """

    category: Literal[CustodyObjectCategory.NATIVE_DIGITAL_ASSET] = (
        CustodyObjectCategory.NATIVE_DIGITAL_ASSET
    )
    chain: str = Field(
        min_length=1,
        description=(
            "Chain identifier (e.g., 'bitcoin', 'ethereum', 'solana', "
            "'cosmos')."
        ),
    )
    custody_address: str = Field(
        min_length=1,
        description=(
            "On-chain custody address (or identifier of the custody "
            "key/vault — for cold storage the address may be a vault "
            "reference rather than a hot wallet)."
        ),
    )

    @model_validator(mode="after")
    def _enforce_asset_class_alignment(self) -> Self:
        """Native digital asset objects must reference a native-digital
        asset class.

        Per AUR-CUSTODY-001 v1.0 Section III: native digital assets are
        classified under ``MajorAssetCategory.NATIVE_DIGITAL_ASSETS``.
        The ``AssetClass`` validators already enforce that
        ``NATIVE_DIGITAL_ASSETS`` implies ``representation =
        NATIVE_DIGITAL``, so the major-category check below is
        sufficient.
        """
        if (
            self.asset_class.major_category
            is not MajorAssetCategory.NATIVE_DIGITAL_ASSETS
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section III, "
                f"NativeDigitalAssetObject requires asset_class."
                f"major_category=NATIVE_DIGITAL_ASSETS, got "
                f"{self.asset_class.major_category.value!r}."
            )
        return self


CustodyObject = Annotated[
    OrdinarySafekeepingObject
    | PledgedAssetObject
    | SMAObject
    | TokenizedSecurityObject
    | NativeDigitalAssetObject,
    Field(discriminator="category"),
]
"""Discriminated union of the five custody object categories per
AUR-CUSTODY-001 v1.0 Section IV. The ``category`` field is the
discriminator."""


__all__ = [
    "CustodyObject",
    "CustodyObjectCategory",
    "Encumbrance",
    "EncumbranceType",
    "NativeDigitalAssetObject",
    "OrdinarySafekeepingObject",
    "PledgedAssetObject",
    "SMAObject",
    "TokenizedSecurityObject",
]
