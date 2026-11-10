import hashlib
import inspect
import tomllib

from atreides.account_lifecycle import AuthoritativeEvidenceResolver
from atreides.trust_anchors import TRUST_ANCHOR_PATH, resolve_pinned_anchor

EXPECTED_CHECKSUM = "866284222a943756a821478d3c6f1c6392a189970d6caf5598a19713ee87731f"


def test_trust_anchor_file_checksum() -> None:
    assert hashlib.sha256(TRUST_ANCHOR_PATH.read_bytes()).hexdigest() == EXPECTED_CHECKSUM
    with (TRUST_ANCHOR_PATH.parents[1] / "pyproject.toml").open("rb") as handle:
        package_data = tomllib.load(handle)["tool"]["setuptools"]["package-data"]["atreides"]
    assert TRUST_ANCHOR_PATH.name in package_data


def test_public_verifiers_accept_no_registry_argument() -> None:
    public_entries = (AuthoritativeEvidenceResolver, resolve_pinned_anchor)
    for entry in public_entries:
        assert all("registry" not in name for name in inspect.signature(entry).parameters)
