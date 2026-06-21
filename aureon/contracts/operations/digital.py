"""Native digital asset custody operations.

Per AUR-CUSTODY-001 v1.0 Section V "Native Digital Assets" — outright
on-chain transfer, staking, unstaking, slashing, validator rewards,
DeFi protocol interaction, NFT operations, airdrops and token
distributions, governance voting, plus the inherent-safety operation
categories (key ceremonies, cold-storage operations).

Material on-chain transfers, key ceremonies, cold-storage operations,
and DeFi protocol interactions are inherent-safety surfaces per
Section IX. The base ``CustodyOperation`` cross-validators enforce the
quorum requirement automatically when the inherent-safety surface is
declared on these operations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from aureon.contracts.operations.base import CustodyOperation


class NativeDigitalTransactionType(StrEnum):
    """Native digital asset transaction types per AUR-CUSTODY-001 v1.0
    Section V."""

    OUTRIGHT_TRANSFER = "outright_transfer"
    """Per Section V: 'Native digital asset moved between addresses.'
    Material magnitude is an inherent-safety surface per Section IX
    (NATIVE_DIGITAL_ASSET_MATERIAL)."""
    STAKING = "staking"
    """Per Section V: 'Native digital asset committed to consensus
    protocol in exchange for staking rewards.'"""
    UNSTAKING = "unstaking"
    """Reversal of staking — withdrawal of staked assets, often subject
    to network-level lock-up periods."""
    SLASHING_EVENT = "slashing_event"
    """Per Section V: 'Penalty applied to staked assets due to validator
    misbehaviour or downtime.' Custody operations: slashing event
    detection, position reduction, beneficial owner notification."""
    VALIDATOR_REWARD = "validator_reward"
    """Periodic distributions to staked positions."""
    DEFI_INTERACTION = "defi_interaction"
    """Per Section V: 'Native digital assets deployed into decentralised
    finance protocols (lending, liquidity provision, yield farming).'
    Doctrine-over-code per Axiom 5; protocol-level actions that
    conflict with doctrine trigger Thifur-J hold."""
    NFT_MINT = "nft_mint"
    NFT_TRANSFER = "nft_transfer"
    NFT_SALE = "nft_sale"
    NFT_BURN = "nft_burn"
    AIRDROP_RECEIPT = "airdrop_receipt"
    """Per Section V: 'Receipt of tokens distributed by protocol or
    project.' Custody operations: airdrop receipt monitoring, position
    recording, evaluation of distributed asset."""
    GOVERNANCE_VOTE = "governance_vote"
    """Per Section V: 'Token-holders vote on protocol governance
    proposals.' Voting instruction processing under beneficial owner
    direction."""
    KEY_GENERATION = "key_generation"
    """Per Section IX KEY_CEREMONY surface — generation of new private
    keys."""
    KEY_ROTATION = "key_rotation"
    """Per Section IX KEY_CEREMONY surface — rotation of existing
    keys."""
    KEY_RECOVERY = "key_recovery"
    """Per Section IX KEY_CEREMONY surface — recovery operations
    involving direct key material handling."""
    COLD_STORAGE_DEPOSIT = "cold_storage_deposit"
    """Per Section IX COLD_STORAGE surface — movement of assets into
    cold storage."""
    COLD_STORAGE_WITHDRAWAL = "cold_storage_withdrawal"
    """Per Section IX COLD_STORAGE surface — movement of assets out of
    cold storage."""


class NativeDigitalOperation(CustodyOperation):
    """Native digital asset custody operation per AUR-CUSTODY-001 v1.0
    Section V."""

    kind: Literal["native_digital"] = "native_digital"
    transaction_type: NativeDigitalTransactionType = Field(
        description=(
            "Native digital asset transaction type per Section V."
        ),
    )
    on_chain_transaction_hash: str | None = Field(
        default=None,
        description=(
            "Hash of the on-chain transaction that effected the "
            "operation. None until the transaction is broadcast and "
            "confirmed; populated post-execution as part of DSOR "
            "lineage."
        ),
    )
    target_address: str | None = Field(
        default=None,
        description=(
            "Target on-chain address for transfers, NFT operations, "
            "and DeFi interactions. None for staking/unstaking (which "
            "interact with protocol contracts identified separately) "
            "and for key ceremonies."
        ),
    )
    protocol_identifier: str | None = Field(
        default=None,
        description=(
            "Protocol identifier for STAKING / UNSTAKING / "
            "DEFI_INTERACTION / GOVERNANCE_VOTE (e.g., 'eth-beacon', "
            "'aave-v3', 'lido', 'uniswap-v4', 'compound-v3')."
        ),
    )


__all__ = ["NativeDigitalOperation", "NativeDigitalTransactionType"]
