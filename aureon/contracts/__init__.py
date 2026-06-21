"""Aureon custody contracts — typed substrate for custody operations.

Per AUR-CANONICAL-001 v1.6 (Aureon Consolidated Canonical Doctrine)
and AUR-CUSTODY-001 v1.0 (Aureon Custody Operational Doctrine).

This package exports the Pydantic v2 models that encode what custody
operations *are* under Aureon governance. The contracts are the
substrate that subsequent layers (the Aureon Asset-Services Workforce
agents, the quorum ceremony state machine, DSOR record assembly, the
rail integration layer, and the product-specific operational
specifications for Atreides Federate and Atreides Sovereign) implement
against.

See ``doctrine/AUR-CANONICAL-001-v1_6.md`` and
``doctrine/AUR-CUSTODY-001-v1_0.md`` for the source of truth.
"""

from __future__ import annotations

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
from aureon.contracts.dsor_stub import (
    CAOM_MODE_DEFAULT,
    CURRENT_DOCTRINE_VERSION,
    CAOMTier,
    DSORLineageStub,
)
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.inherent_safety import (
    InherentSafetySide,
    InherentSafetySurface,
)
from aureon.contracts.operations import (
    CustodyOperation,
    CustodyOperationUnion,
    DerivativeOperation,
    DerivativeTransactionType,
    EquityOperation,
    EquityTransactionType,
    FixedIncomeOperation,
    FixedIncomeTransactionType,
    FundOperation,
    FundTransactionType,
    FXOperation,
    FXTransactionType,
    LifecycleEventType,
    LifecycleOperation,
    NativeDigitalOperation,
    NativeDigitalTransactionType,
    StructuredOperation,
    StructuredTransactionType,
    TokenizedOperation,
    TokenizedTransactionType,
)
from aureon.contracts.quorum import (
    DEFAULT_THRESHOLD_M,
    DEFAULT_THRESHOLD_N,
    CeremonyState,
    CeremonyStep,
    IndependenceRequirement,
    QuorumAuthority,
    QuorumThreshold,
    Signature,
    SigningAuthority,
)
from aureon.contracts.settlement import (
    AtomicSettlement,
    BilateralSettlement,
    CCPClearedSettlement,
    ConditionalSettlement,
    DvDSettlement,
    DvP1Settlement,
    DvP2Settlement,
    DvP3Settlement,
    FoPSettlement,
    PvPSettlement,
    SettlementMethod,
    SettlementMethodKind,
    TripartySettlement,
)

__all__ = [
    "CAOM_MODE_DEFAULT",
    "CURRENT_DOCTRINE_VERSION",
    "DEFAULT_THRESHOLD_M",
    "DEFAULT_THRESHOLD_N",
    "AssetClass",
    "AtomicSettlement",
    "BilateralSettlement",
    "CAOMTier",
    "CCPClearedSettlement",
    "CeremonyState",
    "CeremonyStep",
    "ConditionalSettlement",
    "CustodyObject",
    "CustodyObjectCategory",
    "CustodyOperation",
    "CustodyOperationUnion",
    "DSORLineageStub",
    "DerivativeOperation",
    "DerivativeTransactionType",
    "DvDSettlement",
    "DvP1Settlement",
    "DvP2Settlement",
    "DvP3Settlement",
    "Encumbrance",
    "EncumbranceType",
    "EquityOperation",
    "EquityTransactionType",
    "FXOperation",
    "FXTransactionType",
    "FailureModeClass",
    "FixedIncomeOperation",
    "FixedIncomeTransactionType",
    "FoPSettlement",
    "FundOperation",
    "FundTransactionType",
    "IndependenceRequirement",
    "InherentSafetySide",
    "InherentSafetySurface",
    "LifecycleEventType",
    "LifecycleOperation",
    "MajorAssetCategory",
    "NativeDigitalAssetObject",
    "NativeDigitalOperation",
    "NativeDigitalTransactionType",
    "OrdinarySafekeepingObject",
    "PledgedAssetObject",
    "PvPSettlement",
    "QuorumAuthority",
    "QuorumThreshold",
    "Representation",
    "SMAObject",
    "SettlementMethod",
    "SettlementMethodKind",
    "Signature",
    "SigningAuthority",
    "StructuredOperation",
    "StructuredTransactionType",
    "TokenizedOperation",
    "TokenizedSecurityObject",
    "TokenizedTransactionType",
    "TripartySettlement",
]
