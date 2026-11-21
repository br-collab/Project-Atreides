"""The firm run fails closed, by name, when an intent is refused, and installs its own trust.

Gate G3 finding on PS-3C Part 4B (#214, 21 Nov 2026): run_firm ignored a REFUSED outcome from
L.C. accept_intent and went on to authorize, split and allocate the order, then crashed with a
bare KeyError inside L.C. It also relied on pytest's conftest to install the synthetic keys, so
run_firm called on its own refused every intent.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from simulator import firm
from simulator.calibration import load_calibration_pack
from simulator.firm import load_firm_profile, run_firm

CONTROL = "firm run refused-intent control"
ROOT = Path(__file__).resolve().parents[2]


def _profile() -> firm.FirmProfile:
    return load_firm_profile(load_calibration_pack("firm-synthetic/6"), "small")


def test_a_volume_approval_signed_by_an_uninstalled_key_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(firm, "HUMAN_APPROVAL_PRIVATE_KEY", Ed25519PrivateKey.generate())
    with pytest.raises(ValueError, match="FIRM_INTENT_REFUSED"):
        run_firm(_profile(), days=1, verify_replay=False)


def _fresh_process(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def test_run_firm_installs_its_own_trust_outside_pytest() -> None:
    result = _fresh_process(
        "from simulator.calibration import load_calibration_pack\n"
        "from simulator.firm import load_firm_profile, run_firm\n"
        "run = run_firm(load_firm_profile(load_calibration_pack('firm-synthetic/6'), 'small'),"
        " days=1, verify_replay=False)\n"
        "print('breaks', [len(day.control_breaks) for day in run.days])\n"
    )
    assert result.returncode == 0, (CONTROL, result.stderr[-2000:])
    assert "breaks [0]" in result.stdout, CONTROL


def test_a_partial_synthetic_trust_set_is_refused() -> None:
    result = _fresh_process(
        "from datetime import UTC, datetime\n"
        "from atreides.trust_anchors import TrustAnchor, install_runtime_trust_anchor\n"
        "from simulator.synthetic_attestation_fixture import (\n"
        "    KYC_KEY_ID, KYC_PRIVATE_KEY, ensure_synthetic_trust)\n"
        "from atreides.account_lifecycle import KYC_PRODUCER\n"
        "install_runtime_trust_anchor(TrustAnchor(key_id=KYC_KEY_ID, producer=KYC_PRODUCER,"
        " public_key=KYC_PRIVATE_KEY.public_key(), valid_from=datetime(2026, 1, 1, tzinfo=UTC),"
        " valid_to=datetime(2035, 1, 1, tzinfo=UTC), revoked=False))\n"
        "ensure_synthetic_trust()\n"
    )
    assert result.returncode != 0, CONTROL
    assert "SYNTHETIC_TRUST_PARTIAL" in result.stderr, CONTROL
