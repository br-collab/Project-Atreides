"""Synthetic Ed25519 fixture for offline simulator evidence."""

from cannae_kernel.signed_attestation import PublicKeyRecord, pinned_public_key_registry
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

LC_KEY_ID = "synthetic-lc-simulator-key-1"
LC_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
LC_PUBLIC_KEYS = pinned_public_key_registry(
    {LC_KEY_ID: PublicKeyRecord("legiones-cannenses", LC_PRIVATE_KEY.public_key())}
)
