"""Synthetic Ed25519 fixture for offline simulator evidence."""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

LC_KEY_ID = "synthetic-lc-simulator-key-1"
LC_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
