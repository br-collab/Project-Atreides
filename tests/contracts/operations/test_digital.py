"""Tests for ``aureon.contracts.operations.digital``.

Per AUR-CUSTODY-001 v1.0 Section V Native Digital Assets and Section
IX (native digital asset, key ceremony, cold storage are inherent-
safety surfaces).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import NativeDigitalAssetObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.inherent_safety import InherentSafetySurface
from aureon.contracts.operations.digital import (
    NativeDigitalOperation,
    NativeDigitalTransactionType,
)
from aureon.contracts.quorum import QuorumAuthority


class TestNativeDigitalTransactionTypeCoverage:
    @pytest.mark.parametrize(
        "txn_type",
        [
            NativeDigitalTransactionType.OUTRIGHT_TRANSFER,
            NativeDigitalTransactionType.STAKING,
            NativeDigitalTransactionType.UNSTAKING,
            NativeDigitalTransactionType.SLASHING_EVENT,
            NativeDigitalTransactionType.VALIDATOR_REWARD,
            NativeDigitalTransactionType.DEFI_INTERACTION,
            NativeDigitalTransactionType.NFT_MINT,
            NativeDigitalTransactionType.NFT_TRANSFER,
            NativeDigitalTransactionType.NFT_SALE,
            NativeDigitalTransactionType.NFT_BURN,
            NativeDigitalTransactionType.AIRDROP_RECEIPT,
            NativeDigitalTransactionType.GOVERNANCE_VOTE,
            NativeDigitalTransactionType.KEY_GENERATION,
            NativeDigitalTransactionType.KEY_ROTATION,
            NativeDigitalTransactionType.KEY_RECOVERY,
            NativeDigitalTransactionType.COLD_STORAGE_DEPOSIT,
            NativeDigitalTransactionType.COLD_STORAGE_WITHDRAWAL,
        ],
    )
    def test_doctrinal_types_present(
        self, txn_type: NativeDigitalTransactionType
    ) -> None:
        assert txn_type in NativeDigitalTransactionType


class TestNativeDigitalConstruction:
    def test_staking(
        self,
        lineage_t1: DSORLineageStub,
        native_eth_object: NativeDigitalAssetObject,
    ) -> None:
        op = NativeDigitalOperation(
            lineage=lineage_t1,
            custody_object=native_eth_object,
            failure_mode_class=FailureModeClass.RM,
            transaction_type=NativeDigitalTransactionType.STAKING,
            protocol_identifier="eth-beacon",
        )
        assert op.kind == "native_digital"
        assert op.protocol_identifier == "eth-beacon"


class TestKeyCeremonyAsInherentSafety:
    """Per AUR-CUSTODY-001 v1.0 Section IX, key ceremonies are
    inherent-safety surfaces required by category regardless of
    asset magnitude."""

    def test_key_generation_with_quorum_accepted(
        self,
        lineage_quorum: DSORLineageStub,
        native_eth_object: NativeDigitalAssetObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        op = NativeDigitalOperation(
            lineage=lineage_quorum,
            custody_object=native_eth_object,
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=InherentSafetySurface.KEY_CEREMONY,
            quorum_authority=quorum_3_of_5_completed,
            transaction_type=NativeDigitalTransactionType.KEY_GENERATION,
        )
        assert op.transaction_type is NativeDigitalTransactionType.KEY_GENERATION

    def test_key_generation_without_inherent_safety_at_ur_f_rejected(
        self,
        lineage_t1: DSORLineageStub,
        native_eth_object: NativeDigitalAssetObject,
    ) -> None:
        # UR-F without inherent-safety surface — base validator rejects.
        with pytest.raises(
            ValidationError,
            match=r"UR-F must declare an inherent-safety surface",
        ):
            NativeDigitalOperation(
                lineage=lineage_t1,
                custody_object=native_eth_object,
                failure_mode_class=FailureModeClass.UR_F,
                transaction_type=(
                    NativeDigitalTransactionType.KEY_GENERATION
                ),
            )


class TestColdStorageAsInherentSafety:
    def test_cold_storage_deposit_with_quorum(
        self,
        lineage_quorum: DSORLineageStub,
        native_eth_object: NativeDigitalAssetObject,
        quorum_3_of_5_completed: QuorumAuthority,
    ) -> None:
        op = NativeDigitalOperation(
            lineage=lineage_quorum,
            custody_object=native_eth_object,
            failure_mode_class=FailureModeClass.UR_F,
            inherent_safety_surface=InherentSafetySurface.COLD_STORAGE,
            quorum_authority=quorum_3_of_5_completed,
            transaction_type=(
                NativeDigitalTransactionType.COLD_STORAGE_DEPOSIT
            ),
        )
        assert (
            op.inherent_safety_surface is InherentSafetySurface.COLD_STORAGE
        )
