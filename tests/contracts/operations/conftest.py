"""Shared fixtures for custody operation tests.

These fixtures are reused across all per-asset-class operation test
modules to keep the test code focused on the asset-class-specific
behaviours.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from aureon.contracts.asset_class import (
    AssetClass,
    MajorAssetCategory,
    Representation,
)
from aureon.contracts.custody_object import (
    Encumbrance,
    EncumbranceType,
    NativeDigitalAssetObject,
    OrdinarySafekeepingObject,
    PledgedAssetObject,
    TokenizedSecurityObject,
)
from aureon.contracts.dsor_stub import CAOMTier, DSORLineageStub
from aureon.contracts.quorum import (
    CeremonyState,
    CeremonyStep,
    IndependenceRequirement,
    QuorumAuthority,
    QuorumThreshold,
    Signature,
    SigningAuthority,
)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture
def pre_hash() -> str:
    return _hash("pre-state")


@pytest.fixture
def lineage_t1(pre_hash: str) -> DSORLineageStub:
    """A standard CAOM-001 T1 operator lineage stub."""
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="operator-bill",
        initiated_at=datetime.now(UTC),
        pre_operation_state_hash=pre_hash,
    )


@pytest.fixture
def lineage_quorum(pre_hash: str) -> DSORLineageStub:
    """A quorum-tier lineage stub (post-CAOM authority structure)."""
    return DSORLineageStub(
        authority_tier=CAOMTier.QUORUM,
        authority_id="ceremony-2026-001",
        initiated_at=datetime.now(UTC),
        pre_operation_state_hash=_hash("pre-state-quorum"),
    )


@pytest.fixture
def treasury_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="Treasury",
        asset_identifier="912828YV6",
    )


@pytest.fixture
def tokenized_treasury_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TOKENIZED_REPRESENTATIONS,
        representation=Representation.TOKENIZED,
        sub_category="BUIDL",
        underlying_category=(
            MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES
        ),
    )


@pytest.fixture
def eth_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.NATIVE_DIGITAL_ASSETS,
        representation=Representation.NATIVE_DIGITAL,
        sub_category="ETH",
    )


@pytest.fixture
def equity_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="Common Stock",
        asset_identifier="AAPL",
    )


@pytest.fixture
def fund_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.FUNDS_AND_POOLED_VEHICLES,
        representation=Representation.FIAT,
        sub_category="Hedge Fund",
    )


@pytest.fixture
def fx_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="FX EUR/USD",
    )


@pytest.fixture
def derivative_asset() -> AssetClass:
    return AssetClass(
        major_category=MajorAssetCategory.TRADITIONAL_FINANCIAL_SECURITIES,
        representation=Representation.FIAT,
        sub_category="Interest Rate Swap",
    )


@pytest.fixture
def ordinary_treasury(treasury_asset: AssetClass) -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=treasury_asset,
    )


@pytest.fixture
def ordinary_equity(equity_asset: AssetClass) -> OrdinarySafekeepingObject:
    return OrdinarySafekeepingObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=equity_asset,
    )


@pytest.fixture
def pledged_treasury(treasury_asset: AssetClass) -> PledgedAssetObject:
    return PledgedAssetObject(
        beneficial_owner_id="bo-pension-fund-x",
        asset_class=treasury_asset,
        encumbrance=Encumbrance(
            encumbrance_type=EncumbranceType.REPO,
            lien_holder_id="cp-jpmorgan-prime",
            lien_priority=1,
        ),
    )


@pytest.fixture
def tokenized_treasury_object(
    tokenized_treasury_asset: AssetClass,
) -> TokenizedSecurityObject:
    return TokenizedSecurityObject(
        beneficial_owner_id="bo-treasury-mgmt",
        asset_class=tokenized_treasury_asset,
        rail="ethereum_l1",
        contract_address="0xBUIDL...",
    )


@pytest.fixture
def native_eth_object(eth_asset: AssetClass) -> NativeDigitalAssetObject:
    return NativeDigitalAssetObject(
        beneficial_owner_id="bo-crypto-fund",
        asset_class=eth_asset,
        chain="ethereum",
        custody_address="0xfeed...",
    )


@pytest.fixture
def quorum_3_of_5_completed() -> QuorumAuthority:
    """A completed 3-of-5 quorum ceremony with all five independence
    requirements satisfied at the pool composition level."""
    pool = tuple(
        SigningAuthority(
            authority_id=f"auth-{i}",
            identity_id=f"person-{i}",
            organizational_unit=org,
            jurisdiction=jur,
            signing_system=f"hsm-{i}",
        )
        for i, (org, jur) in enumerate(
            [
                ("operations", "US"),
                ("risk", "UK"),
                ("compliance", "US"),
                ("treasury", "UK"),
                ("audit", "US"),
            ]
        )
    )
    now = datetime.now(UTC)
    signatures = tuple(
        Signature(
            authority_id=f"auth-{i}",
            signed_at=now + timedelta(hours=i),
        )
        for i in range(3)
    )
    return QuorumAuthority(
        threshold=QuorumThreshold(n=3, m=5),
        independence_requirements=frozenset(
            {
                IndependenceRequirement.IDENTITY,
                IndependenceRequirement.ORGANIZATIONAL,
                IndependenceRequirement.GEOGRAPHIC,
                IndependenceRequirement.SYSTEM,
            }
        ),
        signing_pool=pool,
        collected_signatures=signatures,
        ceremony_step=CeremonyStep.OPERATION_EXECUTION,
        ceremony_state=CeremonyState.COMPLETED,
        session_id="ceremony-2026-001",
    )
