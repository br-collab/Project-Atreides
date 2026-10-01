"""Acceptance evidence for the rank 14 FICC participant and access model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atreides import clearing
from atreides.clearing import (
    AccessArrangement,
    AccessDetermination,
    AccessPath,
    AccessStatus,
    AuthorityEvidence,
    NovationEvidence,
    PartyRef,
    PartyRole,
    indeterminate_access,
)

DIGEST = "sha256:" + "a" * 64


def party(name: str, role: PartyRole) -> PartyRef:
    return PartyRef(party_id=name, role=role)


def authority(name: str) -> AuthorityEvidence:
    return AuthorityEvidence(
        evidence_id=f"evidence-{name}",
        principal_party_id=name,
        authority_id=f"authority-{name}",
        source="caller-supplied membership or agency record",
        digest=DIGEST,
    )


def novation() -> NovationEvidence:
    return NovationEvidence(
        event_name="caller-supplied rule-defined novation event",
        rule_reference="effective GSD Rulebook provision",
        evidence_id="novation-evidence-1",
    )


def common() -> dict[str, object]:
    return {
        "ficc": party("FICC-GSD", PartyRole.CENTRAL_COUNTERPARTY),
        "novation_evidence": novation(),
        "rule_set_version": "caller-supplied-effective-version",
        "processing_calendar_id": "caller-supplied-calendar",
    }


def test_direct_access_is_typed_and_round_trips() -> None:
    member = party("member-1", PartyRole.DIRECT_NETTING_MEMBER)
    arrangement = AccessArrangement(
        path=AccessPath.FICC_DIRECT,
        acting_party=member,
        clearing_member=member,
        authority_evidence=(authority(member.party_id),),
        **common(),
    )
    restored = AccessArrangement.model_validate_json(arrangement.model_dump_json())
    assert restored == arrangement


@pytest.mark.parametrize(
    ("path", "acting_role", "intermediary_role"),
    [
        (AccessPath.FICC_SPONSORED, PartyRole.SPONSORED_MEMBER, PartyRole.SPONSORING_MEMBER),
        (
            AccessPath.FICC_AGENT,
            PartyRole.EXECUTING_FIRM_CUSTOMER,
            PartyRole.AGENT_CLEARING_MEMBER,
        ),
    ],
)
def test_indirect_paths_name_both_authorities(
    path: AccessPath, acting_role: PartyRole, intermediary_role: PartyRole
) -> None:
    acting = party("customer", acting_role)
    intermediary = party("member", intermediary_role)
    arrangement = AccessArrangement(
        path=path,
        acting_party=acting,
        clearing_member=intermediary,
        intermediary=intermediary,
        authority_evidence=(authority(acting.party_id), authority(intermediary.party_id)),
        **common(),
    )
    determination = AccessDetermination(status=AccessStatus.ESTABLISHED, arrangement=arrangement)
    assert determination.arrangement is not None
    assert {item.principal_party_id for item in arrangement.authority_evidence} == {
        "customer",
        "member",
    }


def test_sponsored_path_cannot_omit_its_sponsoring_member() -> None:
    acting = party("customer", PartyRole.SPONSORED_MEMBER)
    with pytest.raises(ValidationError, match="SPONSORING_MEMBER intermediary"):
        AccessArrangement(
            path=AccessPath.FICC_SPONSORED,
            acting_party=acting,
            clearing_member=acting,
            authority_evidence=(authority(acting.party_id),),
            **common(),
        )


def test_agent_path_cannot_rely_on_unproved_customer_authority() -> None:
    acting = party("customer", PartyRole.EXECUTING_FIRM_CUSTOMER)
    agent = party("agent", PartyRole.AGENT_CLEARING_MEMBER)
    with pytest.raises(ValidationError, match="authority evidence missing"):
        AccessArrangement(
            path=AccessPath.FICC_AGENT,
            acting_party=acting,
            clearing_member=agent,
            intermediary=agent,
            authority_evidence=(authority(agent.party_id),),
            **common(),
        )


def test_ficc_is_not_silently_recast_as_a_member() -> None:
    member = party("member-1", PartyRole.DIRECT_NETTING_MEMBER)
    with pytest.raises(ValidationError, match="CENTRAL_COUNTERPARTY"):
        AccessArrangement(
            path=AccessPath.FICC_DIRECT,
            acting_party=member,
            clearing_member=member,
            ficc=party("FICC-GSD", PartyRole.DIRECT_NETTING_MEMBER),
            authority_evidence=(authority(member.party_id),),
            novation_evidence=novation(),
            rule_set_version="v",
            processing_calendar_id="calendar",
        )


def test_missing_access_is_indeterminate_and_never_defaults_to_direct() -> None:
    result = indeterminate_access("membership and authority evidence were not supplied")
    assert result.status is AccessStatus.INDETERMINATE
    assert result.arrangement is None
    assert result.reason == "membership and authority evidence were not supplied"


def test_indeterminate_status_cannot_carry_an_arrangement() -> None:
    member = party("member-1", PartyRole.DIRECT_NETTING_MEMBER)
    arrangement = AccessArrangement(
        path=AccessPath.FICC_DIRECT,
        acting_party=member,
        clearing_member=member,
        authority_evidence=(authority(member.party_id),),
        **common(),
    )
    with pytest.raises(ValidationError, match="INDETERMINATE requires"):
        AccessDetermination(
            status=AccessStatus.INDETERMINATE,
            arrangement=arrangement,
            reason="contradictory",
        )


def test_public_package_exposes_no_effectful_operation() -> None:
    prohibited = ("authorize", "release", "submit", "settle", "net", "novate")
    assert not any(name.lower().startswith(prohibited) for name in clearing.__all__)
