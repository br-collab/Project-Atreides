"""Process-local Ed25519 identity for offline synthetic simulator evidence."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from cannae_kernel.signed_attestation import sign_attestation
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lc import trust_anchors as lc_trust_anchors
from lc.trust_anchors import TrustAnchor as LCTrustAnchor
from lc.trust_anchors import install_runtime_trust_anchor as install_lc_anchor

from atreides.account_lifecycle import KYC_PRODUCER
from atreides.approval_attestations import HUMAN_APPROVAL_PRODUCER
from atreides.supervision.aml import AML_OFFICER_PRODUCER
from atreides.trust_anchors import (
    TrustAnchor,
    install_runtime_trust_anchor,
    runtime_anchor_installed,
)

LC_KEY_ID = "synthetic-lc-run-key-1"
LC_PRIVATE_KEY = Ed25519PrivateKey.generate()
LC_STATUS_KEY_ID = "synthetic-atreides-status-key-1"
LC_STATUS_PRIVATE_KEY = Ed25519PrivateKey.generate()
KYC_KEY_ID = "synthetic-kyc-run-key-1"
KYC_PRIVATE_KEY = Ed25519PrivateKey.generate()
HUMAN_APPROVAL_KEY_ID = "synthetic-human-approval-run-key-1"
AML_OFFICER_KEY_ID = "synthetic-aml-officer-run-key-1"
# Generated per process: no repository bytes can reproduce this officer's signature.
AML_OFFICER_PRIVATE_KEY = Ed25519PrivateKey.generate()
HUMAN_APPROVAL_PRIVATE_KEY = Ed25519PrivateKey.generate()


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
    install_runtime_trust_anchor(
        TrustAnchor(
            key_id=KYC_KEY_ID,
            producer=KYC_PRODUCER,
            public_key=KYC_PRIVATE_KEY.public_key(),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC),
            revoked=False,
        )
    )
    install_runtime_trust_anchor(
        TrustAnchor(
            key_id=HUMAN_APPROVAL_KEY_ID,
            producer=HUMAN_APPROVAL_PRODUCER,
            public_key=HUMAN_APPROVAL_PRIVATE_KEY.public_key(),
            valid_from=datetime(2000, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC),
            revoked=False,
        )
    )
    install_lc_anchor(
        LCTrustAnchor(
            key_id=HUMAN_APPROVAL_KEY_ID,
            producer=HUMAN_APPROVAL_PRODUCER,
            public_key=HUMAN_APPROVAL_PRIVATE_KEY.public_key(),
            valid_from=datetime(2000, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC),
            revoked=False,
        )
    )
    _install_lc_status_anchor()
    install_runtime_trust_anchor(
        TrustAnchor(
            key_id=AML_OFFICER_KEY_ID,
            producer=AML_OFFICER_PRODUCER,
            public_key=AML_OFFICER_PRIVATE_KEY.public_key(),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC),
            revoked=False,
        )
    )


ATREIDES_SIDE_KEYS = (LC_KEY_ID, KYC_KEY_ID, HUMAN_APPROVAL_KEY_ID, AML_OFFICER_KEY_ID)
LC_SIDE_KEYS = (HUMAN_APPROVAL_KEY_ID, LC_STATUS_KEY_ID)


def _lc_anchor_installed(key_id: str) -> bool:
    """Whether L.C.'s process-local registry holds ``key_id``.

    The pinned L.C. commit exposes no public query, so this reads its runtime state under
    its own lock. If that state is ever renamed this raises, and the run stops: it never
    assumes the L.C. side is installed.
    """

    lock = lc_trust_anchors._runtime_lock  # private: no public query at the L.C. pin
    state = lc_trust_anchors._runtime_state
    with lock:
        return key_id in state.anchors


def _installed_synthetic_keys() -> tuple[list[str], list[str]]:
    expected = [f"atreides:{key}" for key in ATREIDES_SIDE_KEYS] + [
        f"lc:{key}" for key in LC_SIDE_KEYS
    ]
    present = {f"atreides:{key}" for key in ATREIDES_SIDE_KEYS if runtime_anchor_installed(key)}
    present |= {f"lc:{key}" for key in LC_SIDE_KEYS if _lc_anchor_installed(key)}
    installed = [label for label in expected if label in present]
    missing = [label for label in expected if label not in present]
    return installed, missing


def ensure_synthetic_trust() -> None:
    """Install this process's synthetic keys once, from any composition root.

    A run may start under pytest (whose conftest already installed the keys) or on its own.
    All six installs present (four Atreides anchors and the two L.C.-side anchors) is a
    no-op; none present installs them all; anything in between is refused, so a run never
    proceeds on a partial trust set.
    """

    installed, missing = _installed_synthetic_keys()
    if not missing:
        return
    if installed:
        raise RuntimeError(f"SYNTHETIC_TRUST_PARTIAL: installed {installed}, missing {missing}")
    configure_synthetic_trust()


def sign_aml_officer_attestation(payload: Mapping[str, str]) -> bytes:
    """Sign a synthetic AML officer payload with this process's generated officer key.

    This is the simulator's stand-in for a named human officer. It lives in the composition
    root, not in ``atreides``: the decision functions accept only a verified wire.
    """

    body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sign_attestation(
        body,
        producer=AML_OFFICER_PRODUCER,
        key_id=AML_OFFICER_KEY_ID,
        private_key=AML_OFFICER_PRIVATE_KEY,
    )


def _install_lc_status_anchor() -> None:
    install_lc_anchor(
        LCTrustAnchor(
            key_id=LC_STATUS_KEY_ID,
            producer="atreides",
            public_key=LC_STATUS_PRIVATE_KEY.public_key(),
            valid_from=datetime(2000, 1, 1, tzinfo=UTC),
            valid_to=datetime(2035, 1, 1, tzinfo=UTC),
            revoked=False,
        )
    )


def configure_lc_status_trust() -> None:
    """Install the one process-local Atreides status key consumed by L.C., once.

    ``configure_synthetic_trust`` already installs it, so a repeat call is a no-op rather
    than an error that callers had to swallow.
    """

    if _lc_anchor_installed(LC_STATUS_KEY_ID):
        return
    _install_lc_status_anchor()
