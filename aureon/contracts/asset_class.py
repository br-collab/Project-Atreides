"""Asset-class identity — the durable architectural axis.

Per AUR-CUSTODY-001 v1.0 Section III, custody under Aureon governance
is bounded only by the legal definition of custodiable assets, not by
current operational practice or any incumbent platform's coverage.
Asset-class breadth is the durable architectural axis; settlement
methods are the variable operational layer beneath (Section V).

The model:

- ``MajorAssetCategory`` — the ten major categories the doctrine
  enumerates plus an ``EMERGING`` extensible category for asset
  categories that emerge during the doctrine's operational life.
- ``Representation`` — the FIAT / TOKENIZED / NATIVE_DIGITAL distinction
  that the doctrine commits the framework to handle natively (a single
  beneficial owner may hold the same underlying asset in multiple
  representations under one custody account, Section X "Selective FIAT
  and/or Tokenized Custody").
- ``AssetClass`` — a typed structure carrying major category,
  representation, sub-category text (operational sub-classification per
  the asset class, e.g., "Treasury", "Corporate IG", "ETH",
  "PAXG"), the underlying-category pointer for tokenized
  representations, and an optional asset identifier (CUSIP, ISIN,
  ticker, contract address, vault location, etc.).

The cross-field validators encode three doctrinal rules:

1. Per Section III: tokenized representations of an underlying asset are
   classified under ``MajorAssetCategory.TOKENIZED_REPRESENTATIONS``
   with ``representation == TOKENIZED`` and ``underlying_category`` set
   to the underlying FIAT category.
2. Per Section III: native digital assets are classified under
   ``MajorAssetCategory.NATIVE_DIGITAL_ASSETS`` with
   ``representation == NATIVE_DIGITAL``. They have no FIAT underlying;
   ``underlying_category`` must be ``None``.
3. Per Section III: categories #1-7 and #10 are FIAT representations.
   ``representation == FIAT`` only; ``underlying_category`` must be
   ``None``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MajorAssetCategory(StrEnum):
    """The ten major categories enumerated in AUR-CUSTODY-001 v1.0
    Section III, plus an extensible ``EMERGING`` category for future
    asset categories.

    The categories are:

    - #1 Traditional Financial Securities (equities, fixed income, FX,
      listed derivatives, OTC derivatives)
    - #2 Funds and Pooled Investment Vehicles (mutual, ETF, hedge,
      private equity, private credit, real estate funds, other
      alternatives)
    - #3 Physical and Financial Commodities (precious metals, base
      metals, energy, agricultural, carbon and environmental)
    - #4 Real Estate and Real Assets (direct interests, infrastructure,
      natural resources)
    - #5 Insurance and Reinsurance (ILS, insurance contracts in
      custody, reinsurance interests)
    - #6 Intellectual Property and Royalty Streams (music, patent,
      other IP)
    - #7 Trade Finance and Receivables (trade receivables, trade
      finance instruments, loans)
    - #8 Tokenized Representations (tokenized traditional securities,
      funds, commodities, real assets, cash)
    - #9 Native Digital Assets (cryptocurrencies, staking, DeFi, NFTs)
    - #10 Alternative and Specialty Assets (art, wine, litigation
      finance, sports and entertainment)
    - ``EMERGING`` — extensible per Section III "Emerging and Future
      Asset Categories"
    """

    TRADITIONAL_FINANCIAL_SECURITIES = "traditional_financial_securities"
    FUNDS_AND_POOLED_VEHICLES = "funds_and_pooled_vehicles"
    PHYSICAL_AND_FINANCIAL_COMMODITIES = "physical_and_financial_commodities"
    REAL_ESTATE_AND_REAL_ASSETS = "real_estate_and_real_assets"
    INSURANCE_AND_REINSURANCE = "insurance_and_reinsurance"
    INTELLECTUAL_PROPERTY_AND_ROYALTIES = "intellectual_property_and_royalties"
    TRADE_FINANCE_AND_RECEIVABLES = "trade_finance_and_receivables"
    TOKENIZED_REPRESENTATIONS = "tokenized_representations"
    NATIVE_DIGITAL_ASSETS = "native_digital_assets"
    ALTERNATIVE_AND_SPECIALTY_ASSETS = "alternative_and_specialty_assets"
    EMERGING = "emerging"


class Representation(StrEnum):
    """The representation axis: FIAT, TOKENIZED, or NATIVE_DIGITAL.

    Per AUR-CUSTODY-001 v1.0 Section X "Selective FIAT and/or Tokenized
    Custody", custody under Aureon governance offers beneficial owners
    the choice of holding assets in FIAT, tokenized, or both
    representations per asset class. The ``Representation`` enum is the
    machine-checkable encoding of that distinction.
    """

    FIAT = "FIAT"
    """Traditional, non-tokenized representation. Held via traditional
    custodian rails (depository, sub-custodian, vault, title trust)."""

    TOKENIZED = "TOKENIZED"
    """Tokenized representation of an underlying FIAT-class asset.
    Held on a blockchain or distributed ledger; the token represents a
    beneficial interest in the off-chain underlying."""

    NATIVE_DIGITAL = "NATIVE_DIGITAL"
    """Wholly on-chain asset with no FIAT underlying. Cryptocurrencies,
    native protocol tokens, NFTs, DeFi protocol positions."""


# Categories whose representation must be FIAT (no tokenized variant
# under this category — tokenized variants are classified under
# TOKENIZED_REPRESENTATIONS with the FIAT category as the underlying).
# Per AUR-CUSTODY-001 v1.0 Section III enumeration.
_FIAT_ONLY_CATEGORIES: frozenset[MajorAssetCategory] = frozenset(
    {
        MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        MajorAssetCategory.FUNDS_AND_POOLED_VEHICLES,
        MajorAssetCategory.PHYSICAL_AND_FINANCIAL_COMMODITIES,
        MajorAssetCategory.REAL_ESTATE_AND_REAL_ASSETS,
        MajorAssetCategory.INSURANCE_AND_REINSURANCE,
        MajorAssetCategory.INTELLECTUAL_PROPERTY_AND_ROYALTIES,
        MajorAssetCategory.TRADE_FINANCE_AND_RECEIVABLES,
        MajorAssetCategory.ALTERNATIVE_AND_SPECIALTY_ASSETS,
    }
)


class AssetClass(BaseModel):
    """Typed asset-class identity for a custody object.

    Carries the doctrinal asset-class information that downstream
    operations, reporting, reconciliation, and concentration agents
    need to apply asset-class-aware logic per AUR-CUSTODY-001 v1.0
    Section III "Architectural Implications of Asset-Class Breadth".
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    major_category: MajorAssetCategory = Field(
        description=(
            "One of the ten major asset-class categories enumerated in "
            "AUR-CUSTODY-001 v1.0 Section III, or EMERGING for future "
            "categories."
        )
    )
    representation: Representation = Field(
        description=(
            "FIAT / TOKENIZED / NATIVE_DIGITAL per Section X 'Selective "
            "FIAT and/or Tokenized Custody'."
        )
    )
    sub_category: str = Field(
        min_length=1,
        description=(
            "Operational sub-classification per the asset class, e.g., "
            "'Treasury', 'Corporate IG', 'MBS Agency', 'Gold LBMA', "
            "'ETH', 'Tokenized Treasury BUIDL', 'Music Royalty "
            "Catalog'. The doctrine commits the framework to "
            "comprehensive sub-coverage but does not enumerate "
            "sub-categories prescriptively (Section III)."
        ),
    )
    underlying_category: MajorAssetCategory | None = Field(
        default=None,
        description=(
            "The FIAT-class category that underlies a tokenized "
            "representation. Required when major_category is "
            "TOKENIZED_REPRESENTATIONS; must be None for FIAT-only and "
            "native-digital categories."
        ),
    )
    asset_identifier: str | None = Field(
        default=None,
        description=(
            "Optional asset identifier — CUSIP, ISIN, ticker, contract "
            "address, vault location, registry identifier. The doctrine "
            "does not mandate a single identifier scheme; operational "
            "specifications detail per-asset-class identifier policy."
        ),
    )

    @model_validator(mode="after")
    def _enforce_representation_alignment(self) -> Self:
        """Enforce the representation/category alignment from Section III.

        Three rules:

        - FIAT-only categories (#1-7, #10) require ``representation ==
          FIAT`` and ``underlying_category is None``. Tokenized variants
          of these categories are classified under
          ``TOKENIZED_REPRESENTATIONS``.
        - ``TOKENIZED_REPRESENTATIONS`` requires
          ``representation == TOKENIZED`` and ``underlying_category``
          set to a FIAT-class category (tokenized representations of
          ``TOKENIZED_REPRESENTATIONS``, ``NATIVE_DIGITAL_ASSETS``, or
          itself are not coherent under the doctrine).
        - ``NATIVE_DIGITAL_ASSETS`` requires
          ``representation == NATIVE_DIGITAL`` and
          ``underlying_category is None`` (native digital assets have no
          FIAT underlying by definition, Section III).
        - ``EMERGING`` is unconstrained on representation — emerging
          asset categories may use any representation, including
          combinations not anticipated today.
        """
        if self.major_category in _FIAT_ONLY_CATEGORIES:
            if self.representation is not Representation.FIAT:
                raise ValueError(
                    f"Per AUR-CUSTODY-001 v1.0 Section III, "
                    f"major_category={self.major_category.value!r} is "
                    f"FIAT-only; tokenized variants must use "
                    f"major_category=TOKENIZED_REPRESENTATIONS with "
                    f"underlying_category="
                    f"{self.major_category.value!r}."
                )
            if self.underlying_category is not None:
                raise ValueError(
                    f"Per AUR-CUSTODY-001 v1.0 Section III, "
                    f"underlying_category must be None for FIAT-only "
                    f"category {self.major_category.value!r} (used "
                    f"only for TOKENIZED_REPRESENTATIONS)."
                )
        elif self.major_category is MajorAssetCategory.TOKENIZED_REPRESENTATIONS:
            if self.representation is not Representation.TOKENIZED:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section III, "
                    "major_category=TOKENIZED_REPRESENTATIONS requires "
                    "representation=TOKENIZED."
                )
            if self.underlying_category is None:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section III, "
                    "major_category=TOKENIZED_REPRESENTATIONS requires "
                    "underlying_category to identify the FIAT-class "
                    "category that the tokenized asset represents."
                )
            if self.underlying_category in {
                MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
                MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
            }:
                raise ValueError(
                    f"Per AUR-CUSTODY-001 v1.0 Section III, "
                    f"underlying_category={self.underlying_category.value!r} "
                    f"is not a coherent underlying for a tokenized "
                    f"representation (recursive tokenization and "
                    f"native-digital underlyings are not in the "
                    f"doctrine)."
                )
        elif self.major_category is MajorAssetCategory.NATIVE_DIGITAL_ASSETS:
            if self.representation is not Representation.NATIVE_DIGITAL:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section III, "
                    "major_category=NATIVE_DIGITAL_ASSETS requires "
                    "representation=NATIVE_DIGITAL."
                )
            if self.underlying_category is not None:
                raise ValueError(
                    "Per AUR-CUSTODY-001 v1.0 Section III, native "
                    "digital assets have no FIAT underlying; "
                    "underlying_category must be None."
                )
        # MajorAssetCategory.EMERGING is intentionally unconstrained —
        # the doctrine commits to absorbing emerging categories through
        # configuration rather than rebuild (Section III "Emerging and
        # Future Asset Categories").
        return self


__all__ = ["AssetClass", "MajorAssetCategory", "Representation"]
