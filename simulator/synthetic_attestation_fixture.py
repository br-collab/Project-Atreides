"""Process-local Ed25519 identity for offline synthetic simulator evidence."""

from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atreides.trust_anchors import TrustAnchor, install_runtime_trust_anchor

LC_KEY_ID = "synthetic-lc-run-key-1"
LC_PRIVATE_KEY = Ed25519PrivateKey.generate()


def configure_synthetic_trust() -> None:
    """Composition-root wiring for this process's generated L.C. identity."""

    install_runtime_trust_anchor(
        TrustAnchor(
            key_id=LC_KEY_ID,
            producer="legiones-cannenses",
            public_key=LC_PRIVATE_KEY.public_key(),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC),
            revoked=False,
        )
    )
