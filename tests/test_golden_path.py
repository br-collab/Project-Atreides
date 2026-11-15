import json
from decimal import Decimal

import emulators.venue

from simulator.golden_path import (
    Variant,
    replay_evidence_digest,
    run_golden_path,
    verify_evidence_artifacts,
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


def test_lc_venue_is_importable_in_atreides_environment() -> None:
    assert emulators.venue.VenueEmulator.__module__ == "emulators.venue"


def test_sealed_quantity_changes_venue_fill_and_books() -> None:
    ten = run_golden_path(order_quantity=Decimal(10))
    twenty = run_golden_path(order_quantity=Decimal(20))

    assert (ten.fill_quantity, ten.customer_position) == (Decimal(10), Decimal(10))
    assert (twenty.fill_quantity, twenty.customer_position) == (Decimal(20), Decimal(20))
    assert ten.books_digest != twenty.books_digest


def test_books_projected_capacity_refuses_underfunded_order() -> None:
    result = run_golden_path(funding_cash=Decimal(400))

    assert result.disposition == "HOLD"
    assert result.refusal == "ACCOUNT_CREDIT_LIMIT"
    assert result.fill_quantity is None


def test_first_trade_activates_only_after_cns_books_posting() -> None:
    stages = run_golden_path().stages

    assert stages.index("Atreides: CNS settlement posted to books") < stages.index(
        "Atreides: L.C. signed first-trade evidence moved account to ACTIVE"
    ) < stages.index("Atreides: daily close completed")


def test_evidence_pack_is_linked_and_replays_to_same_digest() -> None:
    result = run_golden_path()

    by_id = {event.event_id: event for event in result.evidence}
    cursor = by_id["SIM-1B-1"]
    walked = [cursor.event_id]
    while cursor.cause_event_id is not None:
        cursor = by_id[cursor.cause_event_id]
        walked.append(cursor.event_id)
    assert walked[-1] == "MVP3-APPLICATION"
    assert replay_evidence_digest(result) == result.evidence_digest
    assert verify_evidence_artifacts(result)


def test_tampered_stored_artifact_fails_evidence_check() -> None:
    result = run_golden_path()
    tampered = dict(result.stored_artifacts)
    tampered["00000000-0000-0000-0000-000000000301"] = b"tampered DSOR payload".hex()

    assert not verify_evidence_artifacts(
        result.model_copy(update={"stored_artifacts": tampered})
    )


def test_empty_or_partial_artifact_store_fails_evidence_check() -> None:
    result = run_golden_path()

    assert not verify_evidence_artifacts(result.model_copy(update={"stored_artifacts": {}}))
    first = next(iter(result.stored_artifacts.items()))
    assert not verify_evidence_artifacts(
        result.model_copy(update={"stored_artifacts": {first[0]: first[1]}})
    )


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
        assert result.refusal_state_before == result.refusal_state_after
        assert result.evidence[-1].event_id == f"REFUSAL:{refusal}"
        assert not any(item.event_id.startswith("MVP3-0") for item in result.evidence)
        assert verify_evidence_artifacts(result)


def test_settlement_fail_ages_and_close_reports_it() -> None:
    result = run_golden_path(Variant.SETTLEMENT_FAIL)

    assert result.refusal == "CNS_SETTLEMENT_FAIL"
    assert result.exception_owner == "MVP3_SETTLEMENT_OPERATIONS"
    assert result.exception_age_seconds == 86400
    assert result.close_report == "FAIL_AGED_1_BUSINESS_DAY"
    assert result.fail_id
    assert result.i3_computed is True
    assert "Atreides: daily close completed" in result.stages
    assert result.refusal_state_before == result.refusal_state_after
    assert result.evidence[-1].event_id == "REFUSAL:CNS_SETTLEMENT_FAIL"
    assert verify_evidence_artifacts(result)


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
