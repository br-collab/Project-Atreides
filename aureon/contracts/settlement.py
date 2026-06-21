"""Settlement-method taxonomy and per-method typed structures.

Per AUR-CUSTODY-001 v1.0 Section V (Settlement Methods Taxonomy).

The doctrine frames settlement methods as the *variable operational
layer* beneath the durable asset-class architecture (Section III). The
enumeration here is comprehensive for current operational reality but
explicitly non-binding on future settlement evolution: when a new method
emerges (atomic on a new chain, PORTS-aligned wholesale tokenized, an
entirely novel rail), the doctrine absorbs it through configuration —
operational specifications detail per-method handling without
architectural rebuild.

This module defines the eleven canonical methods enumerated in Section V
plus a discriminated-union ``SettlementMethod`` type that operations
carry. Per-method models hold method-specific fields where the doctrine
calls them out (triparty agent identity, conditional-settlement
condition, CCP identifier, atomic rail, etc.). Asset-class /
transaction-type compatibility (the "settlement method on a custody
operation must be valid for the operation's asset class and transaction
type" rule) is enforced at the operation level in
``aureon.contracts.operations``, not on the settlement method itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SettlementMethodKind(StrEnum):
    """The eleven canonical settlement methods enumerated in
    AUR-CUSTODY-001 v1.0 Section V.

    BIS classification governs the DvP variants. The doctrine commits
    custody operations under Aureon governance to handle every method;
    operational specifications detail per-method mechanics per
    deployment.
    """

    DVP_1 = "DvP-1"
    """Delivery versus Payment, gross/gross. Each securities transfer
    settled gross against a corresponding cash transfer. Highest
    settlement-risk-mitigation profile because the linkage between
    securities and cash legs is per-trade. BIS classification."""

    DVP_2 = "DvP-2"
    """Gross securities, net cash. Securities transfers gross, cash
    settlements netted across multiple trades. Reduces cash settlement
    volume while maintaining per-trade securities settlement integrity.
    BIS classification."""

    DVP_3 = "DvP-3"
    """Multilateral net. Both securities and cash netted multilaterally.
    Highest operational efficiency but greatest exposure to settlement
    failure. Used in CCP-settled markets and some triparty arrangements.
    BIS classification."""

    DVD = "DvD"
    """Delivery versus Delivery — security-for-security exchange without
    cash. Used in tokenized swaps, in-kind operations, and some
    securities-lending arrangements."""

    PVP = "PvP"
    """Payment versus Payment. Two cash legs settled simultaneously to
    eliminate Herstatt risk. CLS is the dominant PvP mechanism for
    major currency pairs."""

    FOP = "FoP"
    """Free of Payment — securities transfer without cash component.
    Used for in-kind transfers, gifts, error corrections, and some
    collateral movements. Highest settlement-risk profile because no
    per-trade cash settlement; counterparty trust required."""

    ATOMIC = "atomic"
    """Single irreversible operation, typically on-chain. Securities and
    cash legs settle simultaneously through smart-contract execution.
    Eliminates settlement-risk window structurally. Available today on
    tokenized rails (Ethereum L1, Base, Arbitrum, Solana per Cato);
    anticipated for wholesale infrastructure (PORTS-aligned)."""

    CONDITIONAL = "conditional"
    """Settlement contingent on a future event (when-issued, subject-to,
    contingent). Custody operations track the conditional state and
    execute settlement when condition is satisfied or unwind when
    condition fails."""

    TRIPARTY = "triparty"
    """Custodian or specialised agent (BNY Mellon TriParty, JPMorgan
    Collateral Management, Euroclear Triparty, Clearstream Triparty)
    intermediates between principals to manage collateral selection,
    substitution, valuation, and operational mechanics. Used extensively
    for repo, securities lending, and OTC derivative collateral."""

    BILATERAL = "bilateral"
    """Direct settlement between two principals without an intermediary.
    Used for some repo, securities lending, and OTC operations where
    the principals have direct relationships and operational
    capability."""

    CCP_CLEARED = "CCP-cleared"
    """Settlement through a central counterparty that becomes the buyer
    to every seller and seller to every buyer. Eliminates bilateral
    counterparty risk. Used for listed derivatives, some OTC
    derivatives (post-Dodd-Frank clearing mandates), and an increasing
    share of repo (FICC sponsored membership and agent clearing)."""


class _SettlementMethodBase(BaseModel):
    """Shared configuration for all settlement-method models."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class DvP1Settlement(_SettlementMethodBase):
    """DvP-1 (gross/gross) settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.DVP_1] = SettlementMethodKind.DVP_1


class DvP2Settlement(_SettlementMethodBase):
    """DvP-2 (gross securities, net cash) settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.DVP_2] = SettlementMethodKind.DVP_2


class DvP3Settlement(_SettlementMethodBase):
    """DvP-3 (multilateral net) settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.DVP_3] = SettlementMethodKind.DVP_3


class DvDSettlement(_SettlementMethodBase):
    """DvD (Delivery versus Delivery) settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.DVD] = SettlementMethodKind.DVD


class PvPSettlement(_SettlementMethodBase):
    """PvP (Payment versus Payment) settlement. Per Section V.

    The CLS field captures whether the legs are settling through CLS
    (the dominant PvP mechanism for major currency pairs). Non-CLS PvP
    arrangements exist for currencies outside CLS coverage.
    """

    kind: Literal[SettlementMethodKind.PVP] = SettlementMethodKind.PVP
    via_cls: bool = Field(
        default=False,
        description=(
            "True if PvP settles through CLS (Continuous Linked "
            "Settlement). False for non-CLS PvP arrangements such as "
            "on-us settlement at a single bank or bilateral PvP for "
            "non-CLS currency pairs."
        ),
    )


class FoPSettlement(_SettlementMethodBase):
    """FoP (Free of Payment) settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.FOP] = SettlementMethodKind.FOP


class AtomicSettlement(_SettlementMethodBase):
    """Atomic on-chain settlement. Per Section V and Section X
    (forward-state framework — atomic settlement governance).

    The ``rail`` field carries the Cato-validated rail identifier. Rail
    selection is governed by the Cato gate (canonical Section II); this
    contract carries the rail decision rather than evaluating it.
    """

    kind: Literal[SettlementMethodKind.ATOMIC] = SettlementMethodKind.ATOMIC
    rail: str = Field(
        min_length=1,
        description=(
            "Cato-validated atomic rail (e.g., 'ethereum_l1', 'base', "
            "'arbitrum', 'solana', 'fed_l1' when PORTS-aligned wholesale "
            "infrastructure is operational)."
        ),
    )


class ConditionalSettlement(_SettlementMethodBase):
    """Conditional settlement (when-issued, subject-to, contingent).
    Per Section V."""

    kind: Literal[SettlementMethodKind.CONDITIONAL] = SettlementMethodKind.CONDITIONAL
    condition: str = Field(
        min_length=1,
        description=(
            "Free-text description of the settlement condition (e.g., "
            "'when-issued: contingent on actual issuance', 'subject-to: "
            "regulatory approval', 'contingent: knockout barrier "
            "breach'). Operational specifications detail the structured "
            "condition vocabulary per asset class."
        ),
    )


class TripartySettlement(_SettlementMethodBase):
    """Triparty settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.TRIPARTY] = SettlementMethodKind.TRIPARTY
    agent: str = Field(
        min_length=1,
        description=(
            "Triparty agent identifier (e.g., 'BNY_MELLON_TRIPARTY', "
            "'JPM_COLLATERAL_MGMT', 'EUROCLEAR_TRIPARTY', "
            "'CLEARSTREAM_TRIPARTY')."
        ),
    )


class BilateralSettlement(_SettlementMethodBase):
    """Bilateral settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.BILATERAL] = SettlementMethodKind.BILATERAL


class CCPClearedSettlement(_SettlementMethodBase):
    """CCP-cleared settlement. Per Section V."""

    kind: Literal[SettlementMethodKind.CCP_CLEARED] = SettlementMethodKind.CCP_CLEARED
    ccp: str = Field(
        min_length=1,
        description=(
            "Central counterparty identifier (e.g., 'FICC_GSD', "
            "'CME_CLEARING', 'LCH_CLEARNET', 'EUREX_CLEARING')."
        ),
    )


SettlementMethod = Annotated[
    DvP1Settlement
    | DvP2Settlement
    | DvP3Settlement
    | DvDSettlement
    | PvPSettlement
    | FoPSettlement
    | AtomicSettlement
    | ConditionalSettlement
    | TripartySettlement
    | BilateralSettlement
    | CCPClearedSettlement,
    Field(discriminator="kind"),
]
"""Discriminated union of all settlement methods enumerated in
AUR-CUSTODY-001 v1.0 Section V. The ``kind`` field is the
discriminator."""


__all__ = [
    "AtomicSettlement",
    "BilateralSettlement",
    "CCPClearedSettlement",
    "ConditionalSettlement",
    "DvDSettlement",
    "DvP1Settlement",
    "DvP2Settlement",
    "DvP3Settlement",
    "FoPSettlement",
    "PvPSettlement",
    "SettlementMethod",
    "SettlementMethodKind",
    "TripartySettlement",
]
