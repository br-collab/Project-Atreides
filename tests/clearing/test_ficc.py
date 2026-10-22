"""R15 evidence for the distinct FICC GSD Treasury path."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from cannae_kernel.canonical import digest_bytes
from pydantic import ValidationError

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
from atreides.clearing.ficc import (
    ClearingAgency,
    ClearingStatus,
    EvidenceFact,
    EvidenceStage,
    FactStatus,
    FiccGsdNettingDocument,
    FiccGsdNettingRequest,
    FiccGsdResult,
    NovatedObligation,
    ObservationSeat,
    produce_ficc_gsd_result,
)

DIGEST = "sha256:" + "a" * 64
SETTLEMENT_DATE = date(2026, 10, 22)


def _party(party_id: str, role: PartyRole) -> PartyRef:
    return PartyRef(party_id=party_id, role=role)


def _authority(party_id: str) -> AuthorityEvidence:
    return AuthorityEvidence(
        evidence_id=f"authority-evidence-{party_id}",
        principal_party_id=party_id,
        authority_id=f"authority-{party_id}",
        source="caller-supplied membership or agency record",
        digest=DIGEST,
    )


def _arrangement(path: AccessPath) -> AccessArrangement:
    ficc = _party("FICC-GSD", PartyRole.CENTRAL_COUNTERPARTY)
    common = {
        "ficc": ficc,
        "novation_evidence": NovationEvidence(
            event_name="rule-defined comparison-system novation",
            rule_reference="caller-supplied effective GSD Rulebook provision",
            evidence_id="arrangement-novation-evidence",
        ),
        "rule_set_version": "caller-supplied-effective-rule-set",
        "processing_calendar_id": "caller-supplied-processing-calendar",
    }
    if path is AccessPath.FICC_DIRECT:
        member = _party("member-a", PartyRole.DIRECT_NETTING_MEMBER)
        return AccessArrangement(
            path=path,
            acting_party=member,
            clearing_member=member,
            authority_evidence=(_authority(member.party_id),),
            **common,
        )
    if path is AccessPath.FICC_SPONSORED:
        customer = _party("customer-a", PartyRole.SPONSORED_MEMBER)
        sponsor = _party("member-a", PartyRole.SPONSORING_MEMBER)
        return AccessArrangement(
            path=path,
            acting_party=customer,
            clearing_member=sponsor,
            intermediary=sponsor,
            authority_evidence=(_authority(customer.party_id), _authority(sponsor.party_id)),
            **common,
        )
    customer = _party("customer-a", PartyRole.EXECUTING_FIRM_CUSTOMER)
    agent = _party("member-a", PartyRole.AGENT_CLEARING_MEMBER)
    return AccessArrangement(
        path=path,
        acting_party=customer,
        clearing_member=agent,
        intermediary=agent,
        authority_evidence=(_authority(customer.party_id), _authority(agent.party_id)),
        **common,
    )


def _obligation(
    obligation_id: str,
    trade_id: str,
    member_id: str,
    quantity: str,
    settlement_amount: str,
    *,
    cusip: str = "91282CJL6",
    settlement_date: date = SETTLEMENT_DATE,
) -> NovatedObligation:
    return NovatedObligation(
        obligation_id=obligation_id,
        trade_ids=(trade_id,),
        member_id=member_id,
        cusip=cusip,
        settlement_date=settlement_date,
        signed_quantity=Decimal(quantity),
        signed_settlement_amount=Decimal(settlement_amount),
        settlement_currency="USD",
        novation_evidence_id=f"novation-{obligation_id}",
    )


def _request(
    *,
    path: AccessPath = AccessPath.FICC_DIRECT,
    agency: ClearingAgency = ClearingAgency.FICC_GSD,
    access: AccessDetermination | None = None,
    instruction: str | None = None,
    finality: str | None = None,
) -> FiccGsdNettingRequest:
    determination = access or AccessDetermination(
        status=AccessStatus.ESTABLISHED, arrangement=_arrangement(path)
    )
    return FiccGsdNettingRequest(
        clearing_agency=agency,
        access=determination,
        obligations=(
            _obligation("obligation-1", "trade-1", "member-a", "100", "-99.00"),
            _obligation("obligation-2", "trade-2", "member-a", "-35", "34.65"),
        ),
        clearing_acceptance_evidence_id="acceptance-1",
        netting_evidence_id="netting-1",
        settlement_instruction_evidence_id=instruction,
        settlement_finality_evidence_id=finality,
    )


@pytest.mark.parametrize("path", list(AccessPath))
def test_direct_sponsored_and_agent_access_each_produce_a_result(path: AccessPath) -> None:
    result = produce_ficc_gsd_result(_request(path=path))
    assert result.status is ClearingStatus.ESTABLISHED
    assert result.payload is not None
    document = FiccGsdNettingDocument.model_validate_json(result.payload)
    assert document.access_path == path.value


def test_incomplete_access_is_reasoned_indeterminate_and_never_defaults() -> None:
    result = produce_ficc_gsd_result(
        _request(access=indeterminate_access("sponsoring-member authority evidence is absent"))
    )
    assert result.status is ClearingStatus.INDETERMINATE
    assert result.reason == (
        "FICC GSD access is indeterminate: sponsoring-member authority evidence is absent"
    )
    assert result.payload is None


def test_cme_is_declared_but_its_rules_are_not_built() -> None:
    result = produce_ficc_gsd_result(_request(agency=ClearingAgency.CME_SECURITIES_CLEARING))
    assert result.status is ClearingStatus.INDETERMINATE
    assert result.reason == "clearing agency declared, rules not built"


def test_member_seat_conserves_both_legs_with_full_lineage() -> None:
    result = produce_ficc_gsd_result(_request())
    assert result.payload is not None
    document = FiccGsdNettingDocument.model_validate_json(result.payload)
    assert document.observation_seat is ObservationSeat.FICC_MEMBER
    assert document.observed_member_id == "member-a"
    assert len(document.net_settlement_obligations) == 1
    position = document.net_settlement_obligations[0]
    assert position.net_quantity == Decimal("65")
    assert position.net_settlement_amount == Decimal("-64.35")
    assert position.settlement_currency == "USD"
    assert position.net_quantity == sum(
        (item.signed_quantity for item in document.novated_obligations), Decimal(0)
    )
    assert position.net_settlement_amount == sum(
        (item.signed_settlement_amount for item in document.novated_obligations), Decimal(0)
    )
    assert position.source_obligation_ids == ("obligation-1", "obligation-2")
    assert position.source_trade_ids == ("trade-1", "trade-2")


def test_member_seat_refuses_a_mixed_member_request() -> None:
    request = _request().model_copy(
        update={
            "obligations": (
                *_request().obligations,
                _obligation("obligation-3", "trade-3", "member-b", "-65", "64.35"),
            )
        }
    )
    result = produce_ficc_gsd_result(request)
    assert result.status is ClearingStatus.INDETERMINATE
    assert result.reason is not None
    assert "member-seat result" in result.reason


def test_each_fact_has_its_own_evidence_and_no_stage_implies_the_next() -> None:
    result = produce_ficc_gsd_result(_request())
    assert result.payload is not None
    document = FiccGsdNettingDocument.model_validate_json(result.payload)
    facts = {fact.stage: fact for fact in document.facts}

    assert facts[EvidenceStage.CLEARING_ACCEPTANCE].evidence_id == "acceptance-1"
    assert facts[EvidenceStage.NOVATION].evidence_id == (
        "novation-obligation-1,novation-obligation-2"
    )
    assert facts[EvidenceStage.NETTING].evidence_id == "netting-1"
    assert facts[EvidenceStage.SETTLEMENT_INSTRUCTION].status is FactStatus.NOT_RECORDED
    assert facts[EvidenceStage.SETTLEMENT_FINALITY].status is FactStatus.NOT_RECORDED


def test_instruction_and_finality_are_separate_recorded_facts() -> None:
    result = produce_ficc_gsd_result(_request(instruction="instruction-1", finality="finality-1"))
    assert result.payload is not None
    document = FiccGsdNettingDocument.model_validate_json(result.payload)
    facts = {fact.stage: fact for fact in document.facts}
    assert facts[EvidenceStage.SETTLEMENT_INSTRUCTION].evidence_id == "instruction-1"
    assert facts[EvidenceStage.SETTLEMENT_FINALITY].evidence_id == "finality-1"


def test_finality_cannot_exist_without_instruction() -> None:
    with pytest.raises(ValidationError, match="without instruction evidence"):
        _request(finality="finality-1")


def test_attestation_binds_the_exact_payload_bytes() -> None:
    result = produce_ficc_gsd_result(_request())
    assert result.header is not None and result.payload is not None
    assert result.header.payload_digest == digest_bytes(result.payload)
    assert result.header.clearing_agency is ClearingAgency.FICC_GSD
    assert result.header.clearing_method == "FICC_GSD_NOVATED_NETTED"


def test_grouping_never_crosses_cusip_or_settlement_date() -> None:
    request = _request().model_copy(
        update={
            "obligations": (
                _obligation("a", "trade-a", "member-a", "10", "-9.90"),
                _obligation("b", "trade-b", "member-a", "20", "-19.80", cusip="91282CJM4"),
                _obligation(
                    "c",
                    "trade-c",
                    "member-a",
                    "30",
                    "-29.70",
                    settlement_date=date(2026, 10, 23),
                ),
            )
        }
    )
    result = produce_ficc_gsd_result(request)
    assert result.payload is not None
    document = FiccGsdNettingDocument.model_validate_json(result.payload)
    positions = document.net_settlement_obligations
    assert len(positions) == 3


@pytest.mark.parametrize(
    ("status", "evidence_id", "reason", "message"),
    [
        (FactStatus.RECORDED, None, None, "RECORDED requires evidence_id"),
        (FactStatus.RECORDED, "evidence", "contradiction", "RECORDED requires evidence_id"),
        (FactStatus.NOT_RECORDED, "evidence", None, "NOT_RECORDED requires a reason"),
        (FactStatus.NOT_RECORDED, None, None, "NOT_RECORDED requires a reason"),
    ],
)
def test_evidence_fact_refusals_name_the_reason(status, evidence_id, reason, message) -> None:
    with pytest.raises(ValidationError, match=message):
        EvidenceFact(
            stage=EvidenceStage.NOVATION,
            status=status,
            evidence_id=evidence_id,
            reason=reason,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"signed_quantity": "0"}, "cannot have zero quantity"),
        ({"signed_settlement_amount": "0"}, "cannot have zero settlement amount"),
        ({"signed_settlement_amount": "99"}, "opposite signs"),
        ({"trade_ids": ("trade-1", "trade-1")}, "trade_ids must be unique"),
    ],
)
def test_novated_obligation_refusals_name_the_reason(changes, message) -> None:
    values = {
        "obligation_id": "obligation-1",
        "trade_ids": ("trade-1",),
        "member_id": "member-a",
        "cusip": "91282CJL6",
        "settlement_date": SETTLEMENT_DATE,
        "signed_quantity": "100",
        "signed_settlement_amount": "-99",
        "settlement_currency": "USD",
        "novation_evidence_id": "novation-1",
    }
    values.update(changes)
    with pytest.raises(ValidationError, match=message):
        NovatedObligation(**values)


def test_request_refuses_duplicate_obligation_ids() -> None:
    first = _request().obligations[0]
    duplicate = first.model_copy(update={"trade_ids": ("trade-2",)})
    values = _request().model_dump()
    values["obligations"] = (first, duplicate)
    with pytest.raises(ValidationError, match="obligation_id must be unique"):
        FiccGsdNettingRequest.model_validate(values)


def test_result_shape_refusals_name_the_reason() -> None:
    with pytest.raises(ValidationError, match="ESTABLISHED requires header and payload"):
        FiccGsdResult(status=ClearingStatus.ESTABLISHED)
    with pytest.raises(ValidationError, match="INDETERMINATE requires only a reason"):
        FiccGsdResult(status=ClearingStatus.INDETERMINATE)


def test_defensive_absent_arrangement_is_reasoned_indeterminate() -> None:
    invalid_access = AccessDetermination.model_construct(
        status=AccessStatus.ESTABLISHED, arrangement=None, reason=None
    )
    result = produce_ficc_gsd_result(_request().model_copy(update={"access": invalid_access}))
    assert result.status is ClearingStatus.INDETERMINATE
    assert result.reason == "access is absent"


def test_one_net_position_cannot_mix_currencies() -> None:
    first, second = _request().obligations
    euro = second.model_copy(update={"settlement_currency": "EUR"})
    result = produce_ficc_gsd_result(
        _request().model_copy(update={"obligations": (first, euro)})
    )
    assert result.status is ClearingStatus.INDETERMINATE
    assert result.reason == (
        "one member/CUSIP/settlement-date position cannot mix settlement currencies"
    )
