"""Tests for ``aureon.contracts.operations.tokenized``.

Per AUR-CUSTODY-001 v1.0 Section V Tokenized Securities and Section IX
(tokenized asset issuer operations are inherent-safety surfaces).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import TokenizedSecurityObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.inherent_safety import InherentSafetySurface
from aureon.contracts.operations.tokenized import (
    TokenizedOperation,
    TokenizedTransactionType,
)
from aureon.contracts.quorum import QuorumAuthority
from aureon.contracts.settlement import AtomicSettlement


class TestTokenizedTransactionTypeCoverage:
    def test_six_types_enumerated(self) -> None:
        # Per Section V: mint, burn, on-chain transfer, atomic swap,
        # smart contract execution, programmable distribution.
        assert {t.value for t in TokenizedTransactionType} == {
            "mint",
            "burn",
            "on_chain_transfer",
            "atomic_swap",
            "smart_contract_execution",
            "programmable_distribution",
        }


class TestTokenizedConstruction:
    def test_on_chain_transfer(
        self,
        lineage_t1: DSORLineageStub,
        tokenized_treasury_object: TokenizedSecurityObject,
    ) -> None:
        op = TokenizedOperation(
            lineage=lineage_t1,
            custody_object=tokenized_treasury_object,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=TokenizedTransactionType.ON_CHAIN_TRANSFER,
            settlement_method=AtomicSettlement(rail="ethereum_l1"),
        )
        assert op.kind == "tokenized"

    def test_atomic_swap_with_atomic_settlement(
        self,
        lineage_t1: DSORLineageStub,
        tokenized_treasury_object: TokenizedSecurityObject,
    ) -> None:
        op = TokenizedOperation(
            lineage=lineage_t1,
            custody_object=tokenized_treasury_object,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=TokenizedTransactionType.ATOMIC_SWAP,
            settlement_method=AtomicSettlement(rail="base"),
        )
        assert op.transaction_type is TokenizedTransactionType.ATOMIC_SWAP


class TestMintAsInherentSafetySurface:
    """Per AUR-CUSTODY-001 v1.0 Section IX, tokenized asset issuer
    operations (mint, burn, supply control) are inherent-safety
    surfaces. The base CustodyOperation cross-validators enforce
    quorum routing when the inherent-safety surface is declared."""

    def test_mint_on_inherent_safety_surface_with_quorum(
        self,
        lineage_quorum: DSORLineageStub,
        tokenized_treasury_object: TokenizedSecurityObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        op = TokenizedOperation(
            lineage=lineage_quorum,
            custody_object=tokenized_treasury_object,
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=(
                InherentSafetySurface.TOKENIZED_ASSET_ISSUER
            ),
            quorum_authority=quorum_3_of_5_completed,
            transaction_type=TokenizedTransactionType.MINT,
        )
        assert (
            op.inherent_safety_surface
            is InherentSafetySurface.TOKENIZED_ASSET_ISSUER
        )

    def test_mint_without_quorum_rejected(
        self,
        lineage_t1: DSORLineageStub,
        tokenized_treasury_object: TokenizedSecurityObject,
    ) -> None:
        # Mint on inherent-safety surface but with single-tier authority
        # — must be rejected by the inherent-safety→quorum cross-
        # validator on the base.
        with pytest.raises(
            ValidationError,
            match=r"require quorum_authority routing",
        ):
            TokenizedOperation(
                lineage=lineage_t1,
                custody_object=tokenized_treasury_object,
                failure_mode_class=FailureModeClass.UR_F,
                inherent_safety_surface=(
                    InherentSafetySurface.TOKENIZED_ASSET_ISSUER
                ),
                transaction_type=TokenizedTransactionType.MINT,
            )
