"""Tokenized security custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Tokenized Securities" — mint
(issuance), burn (retirement), on-chain transfer, atomic swap, smart
contract execution, programmable distribution.

Mint and burn operations on tokenized representations are tokenized
asset issuer operations and are inherent-safety surfaces per Section
IX (severe by category, not by per-operation magnitude — over-issuance,
unauthorised burn, or supply manipulation affects all beneficial
owners of the tokenized asset class). The base ``CustodyOperation``
cross-validators enforce the quorum requirement automatically when
the inherent-safety surface is declared on a mint or burn operation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from aureon.contracts.operations.base import CustodyOperation


class TokenizedTransactionType(StrEnum):
    """Tokenized security transaction types per AUR-CUSTODY-001 v1.0
    Section V."""

    MINT = "mint"
    """Per Section V: 'New tokenized securities created on-chain.'
    Tokenized issuer operation per Section IX — inherent-safety
    surface."""
    BURN = "burn"
    """Per Section V: 'Tokenized securities destroyed on-chain.'
    Tokenized issuer operation per Section IX — inherent-safety
    surface."""
    ON_CHAIN_TRANSFER = "on_chain_transfer"
    """Per Section V: 'Tokenized security transferred between addresses
    on-chain.'"""
    ATOMIC_SWAP = "atomic_swap"
    """Per Section V: 'Simultaneous on-chain exchange of two tokens or
    token-versus-cash via smart contract.' Routed through Cato
    governance gate per Section II of the canonical."""
    SMART_CONTRACT_EXECUTION = "smart_contract_execution"
    """Per Section V: 'Tokenized security operations executed through
    smart contract logic.' Doctrine-over-code per Axiom 5: smart
    contract action that conflicts with doctrine triggers Thifur-J
    hold and escalation."""
    PROGRAMMABLE_DISTRIBUTION = "programmable_distribution"
    """Per Section V: 'Smart contract executes scheduled or
    event-triggered distributions.'"""


class TokenizedOperation(CustodyOperation):
    """Tokenized security custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["tokenized"] = "tokenized"
    transaction_type: TokenizedTransactionType = Field(
        description="Tokenized security transaction type per Section V.",
    )
    smart_contract_address: str | None = Field(
        default=None,
        description=(
            "Smart contract address invoked for SMART_CONTRACT_EXECUTION "
            "and PROGRAMMABLE_DISTRIBUTION. The doctrine commits to "
            "doctrine-over-code per Axiom 5; the contract address is "
            "carried so DSOR replay can identify which contract logic "
            "executed."
        ),
    )


__all__ = ["TokenizedOperation", "TokenizedTransactionType"]
