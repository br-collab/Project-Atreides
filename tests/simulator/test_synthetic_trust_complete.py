"""H3-inv: the synthetic trust set is all six installs or none.

Each case runs in a fresh interpreter because runtime trust anchors are process-local and
set once. The conftest of this suite installs the full set in the pytest process itself, so
an in-process test could never observe a partial set.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(body: str) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


ATREIDES_ONLY = """
from datetime import UTC, datetime

from atreides.account_lifecycle import KYC_PRODUCER
from atreides.approval_attestations import HUMAN_APPROVAL_PRODUCER
from atreides.supervision.aml import AML_OFFICER_PRODUCER
from atreides.trust_anchors import TrustAnchor, install_runtime_trust_anchor
from simulator import synthetic_attestation_fixture as fx

start = datetime(2000, 1, 1, tzinfo=UTC)
end = datetime(2035, 12, 31, tzinfo=UTC)
for key_id, producer, private_key in (
    (fx.LC_KEY_ID, "legiones-cannenses", fx.LC_PRIVATE_KEY),
    (fx.KYC_KEY_ID, KYC_PRODUCER, fx.KYC_PRIVATE_KEY),
    (fx.HUMAN_APPROVAL_KEY_ID, HUMAN_APPROVAL_PRODUCER, fx.HUMAN_APPROVAL_PRIVATE_KEY),
    (fx.AML_OFFICER_KEY_ID, AML_OFFICER_PRODUCER, fx.AML_OFFICER_PRIVATE_KEY),
):
    install_runtime_trust_anchor(
        TrustAnchor(
            key_id=key_id,
            producer=producer,
            public_key=private_key.public_key(),
            valid_from=start,
            valid_to=end,
            revoked=False,
        )
    )
try:
    fx.ensure_synthetic_trust()
except RuntimeError as exc:
    print(exc)
else:
    print("ACCEPTED")
"""


def test_four_atreides_keys_without_the_lc_side_is_partial() -> None:
    result = _run(ATREIDES_ONLY)
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    assert out.startswith("SYNTHETIC_TRUST_PARTIAL"), out
    assert "lc:synthetic-atreides-status-key-1" in out, out
    assert "lc:synthetic-human-approval-run-key-1" in out, out


def test_fresh_process_installs_all_six_and_repeats_are_no_ops() -> None:
    result = _run(
        """
        from lc import trust_anchors as lc_anchors
        from atreides.trust_anchors import runtime_anchor_installed
        from simulator import synthetic_attestation_fixture as fx

        fx.ensure_synthetic_trust()
        fx.ensure_synthetic_trust()
        fx.configure_lc_status_trust()
        atreides = [
            runtime_anchor_installed(k)
            for k in (fx.LC_KEY_ID, fx.KYC_KEY_ID, fx.HUMAN_APPROVAL_KEY_ID,
                      fx.AML_OFFICER_KEY_ID)
        ]
        lc = sorted(lc_anchors._runtime_state.anchors)
        print(all(atreides), lc)
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "True ['synthetic-atreides-status-key-1', 'synthetic-human-approval-run-key-1']"
    )


def test_lc_status_key_alone_is_partial() -> None:
    result = _run(
        """
        from simulator import synthetic_attestation_fixture as fx

        fx.configure_lc_status_trust()
        try:
            fx.ensure_synthetic_trust()
        except RuntimeError as exc:
            print(exc)
        else:
            print("ACCEPTED")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("SYNTHETIC_TRUST_PARTIAL"), result.stdout
