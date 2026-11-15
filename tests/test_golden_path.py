import json

from simulator.golden_path import (
    Variant,
    replay_evidence_digest,
    run_golden_path,
    write_golden_path_publication,
)


def test_clean_golden_path_closes_with_every_invariant_true() -> None:
    result = run_golden_path()

    assert result.disposition == "PASS"
    assert result.account_status == "ACTIVE"
    assert result.dsor_records == 1
    assert result.close_report == "NORMAL_CLOSE"
    assert result.invariants
    assert all(result.invariants.values())


def test_evidence_pack_is_linked_and_replays_to_same_digest() -> None:
    result = run_golden_path()

    assert result.evidence[0].cause_event_id is None
    assert all(
        event.cause_event_id == result.evidence[index - 1].event_id
        for index, event in enumerate(result.evidence[1:], 1)
    )
    assert replay_evidence_digest(result) == result.evidence_digest


def test_fail_closed_variants_have_owned_exceptions_and_no_close() -> None:
    expected = {
        Variant.CIP_UNABLE: "CIP_UNABLE_TO_VERIFY",
        Variant.PROFILE_INCOMPLETE: "RECOMMENDATION_PROFILE_INCOMPLETE",
        Variant.ACCOUNT_RESTRICTED: "ACCOUNT_NOT_ACTIVE:RESTRICTED",
        Variant.CREDIT_LIMIT: "ACCOUNT_CREDIT_LIMIT",
        Variant.FORGED_STATUS: "RECOMMENDATION_ACCOUNT_STATUS_UNREADABLE",
    }
    for variant, refusal in expected.items():
        result = run_golden_path(variant)
        assert result.disposition == "HOLD"
        assert result.refusal == refusal
        assert result.exception_owner
        assert "Atreides: daily close completed" not in result.stages


def test_settlement_fail_ages_and_close_reports_it() -> None:
    result = run_golden_path(Variant.SETTLEMENT_FAIL)

    assert result.refusal == "CNS_SETTLEMENT_FAIL"
    assert result.exception_owner == "MVP3_SETTLEMENT_OPERATIONS"
    assert result.exception_age_seconds == 86400
    assert result.close_report == "FAIL_AGED_1_DAY"
    assert "Atreides: daily close completed" not in result.stages


def test_stale_caller_time_cannot_make_kyc_fresh() -> None:
    result = run_golden_path(Variant.STALE_CALLER_TIME)

    assert result.refusal == "KYC_EVIDENCE_STALE"
    assert result.account_status == "APPLIED"
    assert "Atreides: account moved to FUNDED" not in result.stages


def test_publication_writes_a_new_linked_pack(tmp_path) -> None:
    evidence, summary = write_golden_path_publication(tmp_path / "mvp3")

    document = json.loads(evidence.read_text())
    assert all(document["invariants"].values())
    assert "declared-synthetic" in summary.read_text()
