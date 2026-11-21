"""PS-3C Part 3 stored Know Your Customer decision-chain tests."""

from datetime import UTC, datetime, timedelta

from atreides.account_lifecycle import AccountType, record_kyc_decision
from simulator.golden_path import Variant, run_golden_path
from simulator.synthetic_attestation_fixture import KYC_KEY_ID, KYC_PRIVATE_KEY


def test_golden_path_refuses_a_chain_stored_for_another_kyc_record() -> None:
    result = run_golden_path(Variant.KYC_CHAIN_SWAP)

    assert result.refusal == "KYC_CHAIN_INVALID", "stored KYC chain binding control did not fail"


def test_two_kyc_decisions_never_share_an_event_identifier() -> None:
    decided_at = datetime(2026, 11, 13, 14, tzinfo=UTC)
    first = record_kyc_decision(
        record_id="SYN-KYC-PS3C-A",
        account_id="SYN-ACCOUNT-PS3C-A",
        account_type=AccountType.NATURAL_PERSON,
        person_id="SYN-PERSON-PS3C-A",
        path_id="KYC_ELIGIBLE_CLEAR",
        decided_at=decided_at,
        maximum_age_seconds=300,
        key_id=KYC_KEY_ID,
        private_key=KYC_PRIVATE_KEY,
    )
    second = record_kyc_decision(
        record_id="SYN-KYC-PS3C-B",
        account_id="SYN-ACCOUNT-PS3C-B",
        account_type=AccountType.NATURAL_PERSON,
        person_id="SYN-PERSON-PS3C-B",
        path_id="KYC_ELIGIBLE_CLEAR",
        decided_at=decided_at + timedelta(seconds=1),
        maximum_age_seconds=300,
        key_id=KYC_KEY_ID,
        private_key=KYC_PRIVATE_KEY,
    )

    assert first.event_chain[0].event_id != second.event_chain[0].event_id
