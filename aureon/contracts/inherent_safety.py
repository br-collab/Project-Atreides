"""Inherent-safety surface declarations for custody operations.

Per AUR-CUSTODY-001 v1.0 Section IX (Inherent-Safety Architecture for
Custody) and AUR-CANONICAL-001 v1.6 Axiom 10 (Inherent-Safety Surfaces
Require Architectural Impossibility of Single-Point Failure).

Inherent-safety, per AUR-CANONICAL-001 v1.6 Section III ("Doctrinal
Term: Inherent-Safety"), is *not* a colloquial zero-fail claim. It
means the failure surface requires multiple independent simultaneous
failures to produce loss, each independently bounded under stated
assumptions. No single authority, no single component, no single
signature, no single key, no single jurisdiction, and no single
counterparty may sit on the loss path.

This module declares the surfaces. The architectural enforcement (UR-F
operations require an inherent-safety surface; inherent-safety
operations require quorum authority routing) lives on operation
models in ``aureon.contracts.operations``.
"""

from __future__ import annotations

from enum import StrEnum


class InherentSafetySide(StrEnum):
    """The 1:1 FIAT/digital parity classification.

    Per AUR-CUSTODY-001 v1.0 Section IX, the inherent-safety perimeter
    extends across both FIAT and digital legs in explicit 1:1 parity —
    the doctrine does not privilege one leg over the other. Some
    surfaces are structurally on one side (key ceremonies are digital;
    correspondent banking is FIAT); others span both (beneficial owner
    identity changes apply across the asset-class universe).
    """

    FIAT = "FIAT"
    DIGITAL = "DIGITAL"
    COMMON = "COMMON"


class InherentSafetySurface(StrEnum):
    """Inherent-safety surfaces declared in AUR-CUSTODY-001 v1.0 Section IX.

    Operations placed on these surfaces inherit Axiom 10's architectural
    requirements automatically. Adding or removing a surface is a
    doctrine-modifying change and must flow through the propose/approve
    workflow per AUR-CANONICAL-001 v1.6 Section VII.
    """

    PLEDGED_ASSET_MATERIAL = "pledged_asset_material_magnitude"
    """Pledged-asset operations of material magnitude (Section IX).

    Spans all asset classes — pledged equities, fixed income,
    commodities (physical and financial), real estate interests, digital
    assets, tokenized assets, IP and royalty streams used as collateral.
    """

    NATIVE_DIGITAL_ASSET_MATERIAL = "native_digital_asset_material_magnitude"
    """Native digital asset operations of material magnitude (Section IX)."""

    TOKENIZED_ASSET_ISSUER = "tokenized_asset_issuer"
    """Tokenized asset issuer operations — mint, burn, supply control
    (Section IX). Severe by category, not by per-operation magnitude:
    over-issuance, unauthorized burn, or supply manipulation affects all
    beneficial owners of the tokenized asset class."""

    FIAT_SETTLEMENT_MATERIAL = "fiat_settlement_material_magnitude"
    """Material-magnitude FIAT settlement operations (Section IX). Large-
    value FIAT transfers above operational-specification thresholds
    across Fedwire, CHIPS, Target2, CHAPS, SWIFT MT202, and analogous
    large-value systems. 1:1 parity with native digital asset material-
    magnitude operations."""

    CORRESPONDENT_BANKING_INTEGRITY = "correspondent_banking_integrity"
    """Operations establishing, modifying, or terminating correspondent
    banking relationships affecting custody settlement routing
    (Section IX)."""

    DEPOSITORY_MEMBERSHIP = "depository_membership"
    """Operations affecting Aureon-governed entities' membership status
    at central securities depositories — DTCC, Euroclear, Clearstream,
    JASDEC, and analogous (Section IX)."""

    LARGE_VALUE_PAYMENT_FINALITY = "large_value_payment_finality"
    """Operations producing settlement finality in real-time gross
    settlement systems (Fedwire, Target2, CHAPS) or end-of-day net
    settlement systems (CHIPS, ACH at Federal Reserve closing) at
    material magnitude (Section IX)."""

    FX_BUNDLED_SETTLEMENT = "fx_bundled_settlement"
    """FX bundled settlement operations and PvP-through-CLS-dependent
    operations of material magnitude (Section IX). Herstatt risk if PvP
    fails."""

    KEY_CEREMONY = "key_ceremony"
    """Generation, rotation, recovery, and any direct key material
    handling operations across all cryptographic infrastructure
    (Section IX). Required by category regardless of asset magnitude."""

    COLD_STORAGE = "cold_storage"
    """Movement of assets into or out of cold storage. Applies to digital
    asset cold storage (hardware wallets, air-gapped systems) and to
    physical asset cold storage equivalents (vault entry for precious
    metals, warehouse access for high-value commodities, secured storage
    for art and collectibles). Per Section IX."""

    CUSTODIAN_OF_CUSTODIAN = "custodian_of_custodian"
    """Federate-specific: operations where Aureon directs an underlying
    custodian to take action affecting beneficial owner assets
    (Section IX)."""

    BENEFICIAL_OWNER_IDENTITY_CHANGE = "beneficial_owner_identity_change"
    """Operations changing the beneficial owner of record on a custody
    account — transfers, beneficiary changes on trusts, account
    ownership changes, real-estate title changes, royalty stream
    beneficial-ownership changes (Section IX)."""

    QUORUM_ENROLLMENT_CHANGE = "quorum_enrollment_change"
    """Operations adding, removing, or modifying signing authorities in
    the quorum structure itself (Section IX). The meta-architectural
    rule: the inherent-safety mechanism's own integrity must be
    inherent-safety-protected."""

    PHYSICAL_COMMODITY_VAULT_MATERIAL = "physical_commodity_vault_material"
    """Movements of precious metals between LBMA-approved vaults, base
    metal allocation changes at LME warehouse locations, large-scale
    physical commodity title transfers (Section IX)."""

    REAL_ESTATE_TITLE = "real_estate_title"
    """Title transfer, lien recording, encumbrance changes affecting
    recorded title to real property (Section IX)."""

    IP_RIGHTS_MATERIAL = "ip_rights_material"
    """Patent assignments, trademark transfers, copyright registrations,
    royalty stream beneficial ownership changes for material IP
    portfolios (Section IX)."""

    INSURANCE_CONTRACT_MATERIAL = "insurance_contract_material"
    """Policy ownership transfers, beneficiary changes, policy
    assignments for material insurance contracts (life settlements,
    structured settlements, longevity contracts) — Section IX."""

    ILS_TRIGGER_DETERMINATION = "ils_trigger_determination"
    """Catastrophe bond, longevity bond, and other ILS trigger event
    classifications (Section IX). Incorrect trigger determination
    affects payment obligations to beneficial owners."""

    CARBON_CREDIT_REGISTRY_MATERIAL = "carbon_credit_registry_material"
    """Registry-level operations on voluntary carbon market credits,
    compliance market allowances, RECs at material magnitude
    (Section IX). Double-counting, unauthorized retirement, registry
    fraud are unrecoverable failure modes."""

    PHYSICAL_ASSET_AUTHENTICATION = "physical_asset_authentication"
    """Authentication, provenance verification, and material custody
    changes for art, wine, rare collectibles, and other authenticated
    alternative assets (Section IX)."""

    @property
    def side(self) -> InherentSafetySide:
        """The 1:1 parity side: FIAT, DIGITAL, or COMMON.

        Per AUR-CUSTODY-001 v1.0 Section IX, the inherent-safety
        perimeter is structurally symmetric between FIAT and digital
        legs. This property exposes the structural side for surfaces
        whose inherent-safety failure modes are leg-specific.

        Surfaces returning ``COMMON`` apply across the asset-class
        universe and are not leg-specific (e.g., beneficial-owner
        identity changes, quorum-enrollment changes).
        """
        return _SIDE_BY_SURFACE[self]


# Side classification per AUR-CUSTODY-001 v1.0 Section IX:
# - FIAT-leg surfaces: FIAT settlement, correspondent banking,
#   depository membership, large-value payment finality, FX bundled.
# - Digital-leg surfaces: native digital asset, key ceremony, tokenized
#   issuer.
# - Cold storage spans both (digital cold storage and physical vault
#   cold storage are both in scope per Section IX). Marked COMMON.
# - Pledged-asset, beneficial-owner-identity, quorum-enrollment,
#   physical-commodity-vault, real-estate-title, IP-rights, insurance,
#   ILS trigger, carbon credit, and physical-asset authentication apply
#   across the asset-class universe and are marked COMMON.
# - Custodian-of-custodian (Federate) is COMMON because it can route
#   through any underlying custodian's asset-class coverage.
_SIDE_BY_SURFACE: dict[InherentSafetySurface, InherentSafetySide] = {
    InherentSafetySurface.FIAT_SETTLEMENT_MATERIAL: InherentSafetySide.FIAT,
    InherentSafetySurface.CORRESPONDENT_BANKING_INTEGRITY: InherentSafetySide.FIAT,
    InherentSafetySurface.DEPOSITORY_MEMBERSHIP: InherentSafetySide.FIAT,
    InherentSafetySurface.LARGE_VALUE_PAYMENT_FINALITY: InherentSafetySide.FIAT,
    InherentSafetySurface.FX_BUNDLED_SETTLEMENT: InherentSafetySide.FIAT,
    InherentSafetySurface.NATIVE_DIGITAL_ASSET_MATERIAL: InherentSafetySide.DIGITAL,
    InherentSafetySurface.KEY_CEREMONY: InherentSafetySide.DIGITAL,
    InherentSafetySurface.TOKENIZED_ASSET_ISSUER: InherentSafetySide.DIGITAL,
    InherentSafetySurface.COLD_STORAGE: InherentSafetySide.COMMON,
    InherentSafetySurface.PLEDGED_ASSET_MATERIAL: InherentSafetySide.COMMON,
    InherentSafetySurface.CUSTODIAN_OF_CUSTODIAN: InherentSafetySide.COMMON,
    InherentSafetySurface.BENEFICIAL_OWNER_IDENTITY_CHANGE: InherentSafetySide.COMMON,
    InherentSafetySurface.QUORUM_ENROLLMENT_CHANGE: InherentSafetySide.COMMON,
    InherentSafetySurface.PHYSICAL_COMMODITY_VAULT_MATERIAL: InherentSafetySide.COMMON,
    InherentSafetySurface.REAL_ESTATE_TITLE: InherentSafetySide.COMMON,
    InherentSafetySurface.IP_RIGHTS_MATERIAL: InherentSafetySide.COMMON,
    InherentSafetySurface.INSURANCE_CONTRACT_MATERIAL: InherentSafetySide.COMMON,
    InherentSafetySurface.ILS_TRIGGER_DETERMINATION: InherentSafetySide.COMMON,
    InherentSafetySurface.CARBON_CREDIT_REGISTRY_MATERIAL: InherentSafetySide.COMMON,
    InherentSafetySurface.PHYSICAL_ASSET_AUTHENTICATION: InherentSafetySide.COMMON,
}


__all__ = ["InherentSafetySide", "InherentSafetySurface"]
