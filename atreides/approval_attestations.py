"""Pinned signed attestations for synthetic human approval decisions."""

from datetime import datetime

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.canonical import canonical_bytes
from cannae_kernel.signed_attestation import (
    AttestationVerificationError,
    SigningKey,
    sign_attestation,
    verify_attestation,
)
from pydantic import BaseModel, ConfigDict, Field

from atreides.trust_anchors import (
    TrustAnchorError,
    require_anchor_valid_at,
    resolve_pinned_anchor,
)


class HumanApproval(BaseModel):
    """Facts authenticated by one verified synthetic human approver."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    approval_id: str = Field(min_length=1)
    decision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approver: ActorRef
    approved_at: datetime


def attest_human_approval(
    approval: HumanApproval,
    *,
    key_id: str,
    private_key: SigningKey,
) -> bytes:
    """Sign one human decision under the pinned Atreides producer identity."""
    return sign_attestation(
        canonical_bytes(approval),
        producer="atreides",
        key_id=key_id,
        private_key=private_key,
    )


def verify_human_approval(
    wire: bytes,
    *,
    decision_digest: str,
    approver: ActorRef,
    evaluated_at: datetime,
) -> HumanApproval:
    """Resolve pinned trust and bind a signed decision to its envelope."""
    try:
        anchor, registry = resolve_pinned_anchor(wire, expected_producer="atreides")
        payload = verify_attestation(wire, expected_producer="atreides", registry=registry)
        approval = HumanApproval.model_validate_json(payload)
        require_anchor_valid_at(anchor, evaluated_at)
    except (TrustAnchorError, AttestationVerificationError, ValueError) as exc:
        raise ValueError("HUMAN_APPROVAL_SIGNATURE_INVALID") from exc
    if approval.approver != approver or approval.decision_digest != decision_digest:
        raise ValueError("HUMAN_APPROVAL_BINDING_INVALID")
    if approval.approver.actor_kind is not ActorKind.HUMAN or not approval.approver.authenticated:
        raise ValueError("HUMAN_APPROVER_REQUIRED")
    return approval
