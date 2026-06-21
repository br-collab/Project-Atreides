"""Tests for ``aureon.contracts.dsor_stub``.

Per AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan), Axiom 1, Axiom 3, Axiom 4.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aureon.contracts.dsor_stub import (
    CAOM_MODE_DEFAULT,
    CURRENT_DOCTRINE_VERSION,
    CAOMTier,
    DSORLineageStub,
)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


_PRE_HASH = _hash("pre-state")
_POST_HASH = _hash("post-state")


class TestDoctrineVersion:
    def test_default_doctrine_version_matches_canonical(self) -> None:
        # AUR-CANONICAL-001 v1.6 — the constant is the source of truth
        # for the active doctrine version.
        assert CURRENT_DOCTRINE_VERSION == "1.6"

    def test_default_caom_mode(self) -> None:
        assert CAOM_MODE_DEFAULT == "CAOM-001"


class TestCAOMTierCoverage:
    def test_five_tiers_enumerated(self) -> None:
        # T0 + T1 + T2 + T3 + QUORUM (post-CAOM).
        assert {tier.value for tier in CAOMTier} == {
            "T0",
            "T1",
            "T2",
            "T3",
            "QUORUM",
        }


class TestStubConstruction:
    def test_minimal_valid_construction(self) -> None:
        stub = DSORLineageStub(
            authority_tier=CAOMTier.T1,
            authority_id="operator-bill",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
        )
        assert stub.doctrine_version == CURRENT_DOCTRINE_VERSION
        assert stub.caom_mode == CAOM_MODE_DEFAULT
        assert stub.post_operation_state_hash is None
        assert stub.c2_handoff_id is None
        assert isinstance(stub.operation_id, UUID)

    def test_explicit_post_hash_accepted(self) -> None:
        stub = DSORLineageStub(
            authority_tier=CAOMTier.T1,
            authority_id="operator-bill",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
            post_operation_state_hash=_POST_HASH,
        )
        assert stub.post_operation_state_hash == _POST_HASH


class TestDoctrineVersionValidation:
    @pytest.mark.parametrize(
        "version", ["1.6", "1.6.0", "2.0", "10.20.300"]
    )
    def test_valid_versions_accepted(self, version: str) -> None:
        stub = DSORLineageStub(
            doctrine_version=version,
            authority_tier=CAOMTier.T1,
            authority_id="operator-bill",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
        )
        assert stub.doctrine_version == version

    @pytest.mark.parametrize(
        "version",
        ["", "1", "v1.6", "1.6-beta", "1.6.0.0", "abc"],
    )
    def test_invalid_versions_rejected(self, version: str) -> None:
        with pytest.raises(ValidationError):
            DSORLineageStub(
                doctrine_version=version,
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash=_PRE_HASH,
            )


class TestStateHashValidation:
    def test_invalid_pre_hash_rejected(self) -> None:
        with pytest.raises(
            ValidationError,
            match="pre_operation_state_hash must be a 64-character",
        ):
            DSORLineageStub(
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash="not-a-hash",
            )

    def test_uppercase_hash_rejected(self) -> None:
        # Lowercase is canonical to keep parity bit-for-bit comparable.
        with pytest.raises(ValidationError):
            DSORLineageStub(
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash=_PRE_HASH.upper(),
            )

    def test_invalid_post_hash_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="post_operation_state_hash"
        ):
            DSORLineageStub(
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash=_PRE_HASH,
                post_operation_state_hash="too-short",
            )

    def test_pre_hash_is_required(self) -> None:
        with pytest.raises(ValidationError):
            DSORLineageStub(  # type: ignore[call-arg]
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
            )


class TestAuthorityTierAndId:
    @pytest.mark.parametrize("tier", list(CAOMTier))
    def test_every_tier_acceptable(self, tier: CAOMTier) -> None:
        stub = DSORLineageStub(
            authority_tier=tier,
            authority_id=f"id-{tier.value}",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
        )
        assert stub.authority_tier is tier

    def test_empty_authority_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DSORLineageStub(
                authority_tier=CAOMTier.T1,
                authority_id="",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash=_PRE_HASH,
            )


class TestImmutability:
    def test_frozen(self) -> None:
        stub = DSORLineageStub(
            authority_tier=CAOMTier.T1,
            authority_id="operator-bill",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
        )
        with pytest.raises(ValidationError):
            stub.authority_tier = CAOMTier.T3  # type: ignore[misc]


class TestExtraFieldRejection:
    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DSORLineageStub(  # type: ignore[call-arg]
                authority_tier=CAOMTier.T1,
                authority_id="operator-bill",
                initiated_at=datetime.now(UTC),
                pre_operation_state_hash=_PRE_HASH,
                spurious_field="unexpected",
            )


class TestUUIDDefault:
    def test_each_stub_gets_unique_operation_id(self) -> None:
        kwargs = {
            "authority_tier": CAOMTier.T1,
            "authority_id": "operator-bill",
            "initiated_at": datetime.now(UTC),
            "pre_operation_state_hash": _PRE_HASH,
        }
        stub_a = DSORLineageStub(**kwargs)
        stub_b = DSORLineageStub(**kwargs)
        assert stub_a.operation_id != stub_b.operation_id

    def test_explicit_operation_id_accepted(self) -> None:
        explicit = uuid4()
        stub = DSORLineageStub(
            operation_id=explicit,
            authority_tier=CAOMTier.T1,
            authority_id="operator-bill",
            initiated_at=datetime.now(UTC),
            pre_operation_state_hash=_PRE_HASH,
        )
        assert stub.operation_id == explicit
