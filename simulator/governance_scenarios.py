"""Synthetic governance failures executed inside SIM-1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from cannae_kernel.account import AccountStatus
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.governance import ActionClass, AutonomyLevel
from cannae_kernel.ids import ActorId
from cannae_kernel.journal import ChainReport

from atreides.account_lifecycle import (
    AccountLifecycleStore,
    AccountTransitionRefusedError,
    ActorRegistryApproverVerifier,
    AuthoritativeEvidenceResolver,
    EligibilityResultRecord,
    KYCDecisionRecord,
)
from atreides.agents.tier2.eligibility import (
    EligibilityInputs,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from atreides.dsor.governance_scenario import GovernanceScenarioEvidence
from atreides.dsor.store import DSORStore

_NOW = datetime(2026, 11, 7, 17, 0, tzinfo=UTC)
_EXIT_PLAN_LABEL = "simulated, not a tested exit plan"
_WALKTHROUGH_LABEL = (
    "scenario walkthrough; the control is simulated inside the scenario and is not a "
    "production control"
)
_G3_SERVICE_ACTOR = ActorRef(
    actor_id=ActorId("act_01K00000000000000000000000"),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="synthetic account agent",
    entitlement_refs=("SIM-1-G3",),
    authenticated=True,
)
_C2_G3_ACTOR_REGISTRY = {str(_G3_SERVICE_ACTOR.actor_id): _G3_SERVICE_ACTOR}


class _PermissiveApproverVerifier:
    def is_verified_human(self, actor: ActorRef, approval_ref: str) -> bool:
        del actor, approval_ref
        return True


def _evidence_resolver() -> AuthoritativeEvidenceResolver:
    verification = verify_eligibility(
        EligibilityInputs(
            check_time=_NOW,
            kyc=KYCEvidence(
                beneficial_owner_id="SYN-G3-OWNER",
                kyc_reference_id="SIM-1-G3-KYC",
                verified_at=_NOW,
                expires_at=datetime(2026, 12, 7, 17, tzinfo=UTC),
            ),
            requires_kyb=False,
            ofac_screenings=(
                OFACScreeningEvidence(
                    subject_id="SYN-G3-OWNER",
                    screening_id="SIM-1-G3-OFAC",
                    matched=False,
                    screened_at=_NOW,
                ),
            ),
            sanctions_screenings=(
                SanctionsScreeningEvidence(
                    subject_id="SYN-G3-OWNER",
                    screening_id="SIM-1-G3-SANCTIONS",
                    matched=False,
                    screened_at=_NOW,
                ),
            ),
        )
    )
    return AuthoritativeEvidenceResolver(
        kyc_dsor_records={
            "SIM-1-G3-KYC": KYCDecisionRecord(
                record_id="SIM-1-G3-KYC",
                account_id="SYN-G3",
                path_id="KYC_ELIGIBLE_CLEAR",
                decided_at=_NOW,
                maximum_age_seconds=300,
            )
        },
        kyc_chain_reports={
            "SIM-1-G3-KYC": ChainReport(
                ok=True,
                event_count=1,
                head_digest="sha256:" + "11" * 32,
                issues=(),
            )
        },
        eligibility_records={
            "SIM-1-G3-ELIGIBILITY": EligibilityResultRecord(
                record_id="SIM-1-G3-ELIGIBILITY",
                account_id="SYN-G3",
                verified_at=_NOW,
                result=verification,
            )
        },
        transfer_records={},
        first_trade_attestations={},
    )


def _evidence(
    number: int,
    scenario: Literal["G1", "G2", "G3"],
    stage: str,
    result: str,
    detail: str,
    action_class: ActionClass,
    *,
    model_version: str | None = None,
) -> GovernanceScenarioEvidence:
    return GovernanceScenarioEvidence(
        operation_id=UUID(int=number),
        scenario=scenario,
        stage=stage,
        observed_at=_NOW,
        autonomy_level=AutonomyLevel.DECISION_SUPPORT,
        action_class=action_class,
        result=result,
        detail=detail,
        model_version=model_version,
    )


def _trail(
    outputs: tuple[GovernanceScenarioEvidence, ...],
) -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    replay_identical = True
    with DSORStore(":memory:") as store:
        for output in outputs:
            record = store.append(output, dtg=_NOW)
            replayed = store.replay(record.record_id)
            replay_identical = (
                replay_identical and replayed.model_dump_json() == output.model_dump_json()
            )
            rows.append(output.model_dump(mode="json"))
    return rows, replay_identical


def run_vendor_model_regression(*, control_enabled: bool = True) -> dict[str, object]:
    """Detect drift, quarantine version 2.0.0, and roll back to pinned 1.4.2."""
    if not control_enabled:
        return {
            "scenario": "G1",
            "control_enabled": False,
            "failed_as_expected": True,
            "failure": "drift went undetected",
        }
    drift, tolerance = 0.18, 0.05
    outputs = (
        _evidence(
            101,
            "G1",
            "detection",
            "DRIFT_DETECTED",
            f"output drift {drift} exceeded tolerance {tolerance}",
            ActionClass.CHANGE_LIMIT_OR_CONTROL,
            model_version="2.0.0",
        ),
        _evidence(
            102,
            "G1",
            "quarantine",
            "VERSION_QUARANTINED",
            "vendor model excluded from advisory service",
            ActionClass.CHANGE_LIMIT_OR_CONTROL,
            model_version="2.0.0",
        ),
        _evidence(
            103,
            "G1",
            "rollback",
            "PIN_RESTORED",
            "last good pinned model restored",
            ActionClass.CHANGE_LIMIT_OR_CONTROL,
            model_version="1.4.2",
        ),
    )
    records, replay_identical = _trail(outputs)
    return {
        "scenario": "G1",
        "control_enabled": True,
        "records": records,
        "label": _WALKTHROUGH_LABEL,
        "replay_identical": replay_identical,
    }


def run_hosting_provider_loss(*, control_enabled: bool = True) -> dict[str, object]:
    """Execute the declared synthetic exit plan after human approval."""
    if not control_enabled:
        return {
            "scenario": "G2",
            "control_enabled": False,
            "failed_as_expected": True,
            "failure": "no exit was executed",
        }
    plan = (
        "failover target synthetic-secondary; recovery point objective 5 minutes; "
        "recovery time objective 30 minutes; " + _EXIT_PLAN_LABEL
    )
    outputs = (
        _evidence(
            201, "G2", "detection", "PRIMARY_UNAVAILABLE", plan, ActionClass.CHANGE_LIMIT_OR_CONTROL
        ),
        _evidence(
            202, "G2", "exit_decision", "HUMAN_APPROVED", plan, ActionClass.CHANGE_LIMIT_OR_CONTROL
        ),
        _evidence(
            203, "G2", "restore", "SECONDARY_RESTORED", plan, ActionClass.CHANGE_LIMIT_OR_CONTROL
        ),
    )
    records, replay_identical = _trail(outputs)
    return {
        "scenario": "G2",
        "control_enabled": True,
        "records": records,
        "label": f"{_EXIT_PLAN_LABEL}; {_WALKTHROUGH_LABEL}",
        "replay_identical": replay_identical,
    }


def run_unauthorized_core_write(*, control_enabled: bool = True) -> dict[str, object]:
    """Exercise the ONB-1 human approval gate for a core lifecycle write."""
    actor = _G3_SERVICE_ACTOR
    verifier = (
        ActorRegistryApproverVerifier(_C2_G3_ACTOR_REGISTRY)
        if control_enabled
        else _PermissiveApproverVerifier()
    )
    lifecycle = AccountLifecycleStore(verifier, _evidence_resolver())
    lifecycle.apply("SYN-G3")
    if not control_enabled:
        lifecycle.transition(
            "SYN-G3",
            AccountStatus.APPROVED,
            actor=actor,
            timestamp=_NOW,
            reason="synthetic unauthorized transition attempt",
            evidence_refs=("SIM-1-G3",),
            kyc_record_id="SIM-1-G3-KYC",
            eligibility_record_id="SIM-1-G3-ELIGIBILITY",
            human_approval_ref="SYN-CLAIMED-APPROVAL",
        )
        return {
            "scenario": "G3",
            "control_enabled": False,
            "failed_as_expected": True,
            "failure": "unauthorized write was accepted",
            "accepted_status": lifecycle.status("SYN-G3").value,
        }
    try:
        lifecycle.transition(
            "SYN-G3",
            AccountStatus.APPROVED,
            actor=actor,
            timestamp=_NOW,
            reason="synthetic unauthorized transition attempt",
            evidence_refs=("SIM-1-G3",),
            kyc_record_id="SIM-1-G3-KYC",
            eligibility_record_id="SIM-1-G3-ELIGIBILITY",
            human_approval_ref="SYN-CLAIMED-APPROVAL",
        )
    except AccountTransitionRefusedError as exc:
        refusal = exc.reason.value
    else:
        raise AssertionError("ONB-1 account lifecycle gate accepted an agent approval")
    outputs = (
        _evidence(
            301,
            "G3",
            "refused_write",
            refusal,
            "APPLIED to APPROVED core-record write refused",
            ActionClass.WRITE_CORE_RECORD,
        ),
        _evidence(
            302,
            "G3",
            "escalation",
            "HUMAN_REVIEW_REQUIRED",
            f"escalated after named refusal {refusal}",
            ActionClass.WRITE_CORE_RECORD,
        ),
    )
    records, replay_identical = _trail(outputs)
    return {
        "scenario": "G3",
        "control_enabled": True,
        "records": records,
        "named_refusal": refusal,
        "replay_identical": replay_identical,
    }


def run_governance_scenarios() -> dict[str, object]:
    """Run controlled cases and their deliberately disabled controls."""
    controlled = {
        "G1": run_vendor_model_regression(),
        "G2": run_hosting_provider_loss(),
        "G3": run_unauthorized_core_write(),
    }
    negative_controls = {
        "G1": run_vendor_model_regression(control_enabled=False),
        "G2": run_hosting_provider_loss(control_enabled=False),
        "G3": run_unauthorized_core_write(control_enabled=False),
    }
    assert all(result["failed_as_expected"] for result in negative_controls.values())
    assert all(result["replay_identical"] for result in controlled.values())
    return {"controlled": controlled, "negative_controls": negative_controls}


__all__ = [
    "run_governance_scenarios",
    "run_hosting_provider_loss",
    "run_unauthorized_core_write",
    "run_vendor_model_regression",
]
