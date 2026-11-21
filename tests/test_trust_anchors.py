import hashlib
import inspect
import subprocess
import sys
import tomllib

from atreides.account_lifecycle import AuthoritativeEvidenceResolver
from atreides.trust_anchors import TRUST_ANCHOR_PATH, resolve_pinned_anchor

EXPECTED_CHECKSUM = "5e5823e983848187e36617c20f246744b584b45d932244e04fd48da342fa681a"


def test_trust_anchor_file_checksum() -> None:
    assert hashlib.sha256(TRUST_ANCHOR_PATH.read_bytes()).hexdigest() == EXPECTED_CHECKSUM
    with (TRUST_ANCHOR_PATH.parents[1] / "pyproject.toml").open("rb") as handle:
        package_data = tomllib.load(handle)["tool"]["setuptools"]["package-data"]["atreides"]
    assert TRUST_ANCHOR_PATH.name in package_data


def test_public_verifiers_accept_no_registry_argument() -> None:
    public_entries = (AuthoritativeEvidenceResolver, resolve_pinned_anchor)
    for entry in public_entries:
        assert all("registry" not in name for name in inspect.signature(entry).parameters)


def test_runtime_anchor_refuses_second_install() -> None:
    from datetime import UTC, datetime

    import pytest
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from atreides.trust_anchors import TrustAnchor, install_runtime_trust_anchor

    key = Ed25519PrivateKey.generate()
    with pytest.raises(RuntimeError, match="set once"):
        install_runtime_trust_anchor(
            TrustAnchor(
                key_id="second",
                producer="legiones-cannenses",
                public_key=key.public_key(),
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                valid_to=datetime(2027, 1, 1, tzinfo=UTC),
                revoked=False,
            )
        )


def test_runtime_anchor_refuses_install_after_verification() -> None:
    code = """
from datetime import UTC, datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from atreides.trust_anchors import (
    TrustAnchor,
    TrustAnchorError,
    install_runtime_trust_anchor,
    resolve_pinned_anchor,
)
try:
    resolve_pinned_anchor(b'{}', expected_producer='legiones-cannenses')
except TrustAnchorError:
    pass
key = Ed25519PrivateKey.generate()
try:
    install_runtime_trust_anchor(
        TrustAnchor(
            'late',
            'legiones-cannenses',
            key.public_key(),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
            False,
        )
    )
except RuntimeError as exc:
    assert 'after verification' in str(exc)
else:
    raise AssertionError('late install was accepted')
"""
    subprocess.run([sys.executable, "-c", code], check=True)
