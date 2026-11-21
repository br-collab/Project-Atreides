"""PS-3C Part 4 run-level approval and KYC provenance controls."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from simulator.golden_path import Variant, run_golden_path


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        (Variant.KYC_WRONG_ACTOR, "KYC_SEALER_INVALID"),
        (Variant.KYC_UNSIGNED, "KYC_SIGNATURE_MISSING"),
        (Variant.KYC_BAD_SIGNATURE, "KYC_SIGNATURE_INVALID"),
    ],
)
def test_golden_path_refuses_untrusted_kyc_provenance(
    variant: Variant, reason: str
) -> None:
    result = run_golden_path(variant)

    assert result.refusal == reason, "KYC signer provenance control did not fail"


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        (Variant.PRINCIPAL_APPROVAL_MISSING, "PRINCIPAL_ACCEPTANCE_NOT_FOUND"),
        (Variant.PRINCIPAL_SELF_APPROVAL, "PRINCIPAL_ROLE_CONFLICT"),
    ],
)
def test_golden_path_refuses_missing_or_self_principal_approval(
    variant: Variant, reason: str
) -> None:
    result = run_golden_path(variant)

    assert result.refusal == reason, "principal approval control did not fail"


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        (Variant.INTENT_SERVICE_HUMAN_JUDGMENT, "signed approval attestation is required"),
        (Variant.INTENT_HUMAN_NO_ATTESTATION, "signed approval attestation is required"),
        (Variant.INTENT_HUMAN_BAD_SIGNATURE, "APPROVAL_ATTESTATION_INVALID"),
    ],
)
def test_golden_path_refuses_unattested_approved_intent(
    variant: Variant, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        run_golden_path(variant)


def test_golden_path_pack_has_one_attested_human_decision() -> None:
    result = run_golden_path()
    human = tuple(item for item in result.evidence if item.actor_kind == "HUMAN")

    assert len(human) == 1, "golden path must publish exactly one human decision"
    assert human[0].attestation_id == "MVP3-HUMAN-APPROVAL"
    assert human[0].signature_status == "VERIFIED"


def test_repository_seed_cannot_forge_kyc_or_human_approval() -> None:
    forged_kyc = Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32)
    forged_approval = Ed25519PrivateKey.from_private_bytes(bytes([23]) * 32)

    assert run_golden_path(kyc_private_key=forged_kyc).refusal == "KYC_SIGNATURE_INVALID"
    with pytest.raises(ValueError, match="APPROVAL_ATTESTATION_INVALID"):
        run_golden_path(human_approval_private_key=forged_approval)


def test_golden_path_refuses_approver_absent_from_principal_register() -> None:
    with pytest.raises(ValueError, match="HUMAN_APPROVER_NOT_REGISTERED"):
        run_golden_path(Variant.INTENT_APPROVER_UNREGISTERED)
