import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import emulators.venue
import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.effects import OperationEffects
from cannae_kernel.envelopes import ApprovedIntentEnvelope
from cannae_kernel.ids import ActorId, IntentId, LifecycleId
from cannae_kernel.provenance import Provenance
from cannae_kernel.session import BusinessDate, MarketSession, SessionContext

from atreides.account_lifecycle import AccountTransitionRefusedError, RefusalReason
from atreides.books.ledger import EquitiesBooks
from simulator.calibration import load_calibration_pack
from simulator.estate import (
    exercise_simulator_market_access,
    seed_customer_cash,
    validate_approval_provenance,
)
from simulator.golden_path import (
    Variant,
    replay_evidence_digest,
    run_golden_path,
    verify_evidence_artifacts,
    verify_first_trade_record,
    verify_published_pack,
    write_golden_path_publication,
)
from simulator.model import Print


def test_clean_golden_path_closes_with_every_invariant_true() -> None:
    result = run_golden_path()

    assert result.disposition == "PASS"
    assert result.account_status == "ACTIVE"
    assert result.dsor_records == 1
    assert result.close_report == "NORMAL_CLOSE"
    assert result.invariants
    assert all(result.invariants.values())
    assert result.trade_date_statement is not None
    assert result.statement is not None
    assert result.trade_date_statement.period_end.isoformat() == "2026-11-13"
    assert set(result.trade_date_statement.settlement_status.values()) == {"UNSETTLED"}
    assert result.statement.period_end.isoformat() == "2026-11-16"
    assert set(result.statement.settlement_status.values()) == {"SETTLED"}
    assert len(result.reconciliation_calendar) == 6
    assert {str(row["status"]) for row in result.reconciliation_calendar} == {"RAN"}
    assert all(row["sources_read"] for row in result.reconciliation_calendar)


def test_cash_statement_short_by_one_cent_fails_its_golden_row() -> None:
    result = run_golden_path(bank_statement_delta=Decimal("-0.01"))
    row = next(
        item for item in result.reconciliation_calendar if item["item_id"] == "cash-to-bank"
    )

    assert row["status"] == "FAILED", "cash-to-bank control must publish its own failure"
    assert row["break_count"] == 1
    assert row["sources_read"] == (
        "Atreides equities books",
        "synthetic firm bank statement",
    )


def test_service_approver_cannot_claim_human_judgment() -> None:
    actor = ActorRef(
        actor_id=ActorId("act_00000000000000000000000001"),
        actor_kind=ActorKind.DETERMINISTIC_SERVICE,
        role="synthetic service",
        entitlement_refs=("SIM-1B",),
        authenticated=True,
    )
    envelope = ApprovedIntentEnvelope(
        envelope_id=IntentId("int_00000000000000000000000001"),
        lifecycle_id=LifecycleId("lif_00000000000000000000000001"),
        revision=1,
        prior_digest=None,
        session=SessionContext(
            session=MarketSession.REGULAR,
            business_date=BusinessDate(
                value=date(2026, 11, 18), calendar="SIFMA-US", established_by="test"
            ),
        ),
        approved_by=actor,
        provenance=Provenance.HUMAN_JUDGMENT,
        effects=OperationEffects(operation="test", effects=(), note="synthetic only"),
        payload_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(ValueError, match="HUMAN_JUDGMENT requires an authenticated HUMAN"):
        validate_approval_provenance(envelope)


def test_duplicate_evidence_id_fails_pack_check() -> None:
    result = run_golden_path()
    duplicate = result.model_copy(update={"evidence": (*result.evidence, result.evidence[-1])})
    assert not verify_evidence_artifacts(duplicate)


def test_venue_fill_is_caused_by_market_access_gate() -> None:
    result = run_golden_path()
    fill = next(item for item in result.evidence if item.summary == "venue fill")
    gate = next(item for item in result.evidence if item.summary == "MARKET_ACCESS_PASSED")
    assert fill.cause_event_id == gate.event_id


def test_supersession_register_names_every_older_pack_and_corrected_figures() -> None:
    text = (Path(__file__).parents[1] / "simulator/publication/SUPERSEDED.md").read_text()
    for pack in (
        "mvp3-golden-path-2026-11-15",
        "mvp3-golden-path-2026-11-15-v2",
        "mvp3b-golden-path-2026-11-15",
        "mvp4-client-reporting-2026-11-15",
        "mvp4-client-reporting-2026-11-15-v2",
    ):
        assert f"`{pack}`" in text
    assert "customer cash 9,000.00" in text
    assert "customer credits 9,000.00" in text
    assert "requirement of 9,000.00" in text


def test_simulator_market_access_refuses_above_declared_notional_limit() -> None:
    pack = load_calibration_pack()
    books = EquitiesBooks(break_owner="TEST")
    business_date = date(2026, 12, 28)
    seed_customer_cash(
        books,
        run_number=1,
        business_date=business_date,
        accounts=("ACCOUNT-1",),
        account_weights=(1,),
        balance=Decimal("10000"),
    )
    at = datetime(2026, 12, 28, 14, 30, tzinfo=UTC)
    report = Print(
        print_id="OVER-LIMIT",
        order_id="ORDER-OVER-LIMIT",
        issue="SYN-EQ-LIMIT",
        quantity=int(pack.value("generator", "quantity_max")),
        price=Decimal(str(pack.value("market", "cns_prior_close"))) * 2,
        matched_at=at,
        reported_at=at,
    )

    with pytest.raises(ValueError, match="SIM-1B market access refused: MAXIMUM_NOTIONAL"):
        exercise_simulator_market_access(
            run_number=1,
            business_date=business_date,
            issue=report.issue,
            reports=(report,),
            account_weights=(1,),
            prior_close=report.price,
            pack=pack,
            books=books,
        )


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
    assert result.refusal_state_before is not None
    assert result.refusal_state_before == result.refusal_state_after


def test_first_trade_activates_only_after_cns_books_posting() -> None:
    result = run_golden_path()
    books = next(item for item in result.evidence if item.event_id == "SIM-1B-1")
    active = next(item for item in result.evidence if item.summary == "account active")
    close = next(item for item in result.evidence if item.summary == "NORMAL_CLOSE")

    assert books.recorded_at < active.recorded_at < close.recorded_at


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
    assert result.evidence[0].cause_event_id is None
    assert all(item.cause_event_id is not None for item in result.evidence[1:])


def test_tampered_stored_artifact_fails_evidence_check() -> None:
    result = run_golden_path()
    tampered = dict(result.stored_artifacts)
    assert "00000000-0000-0000-0000-000000000301" in tampered
    tampered["00000000-0000-0000-0000-000000000301"] = b"tampered DSOR payload".hex()

    assert not verify_evidence_artifacts(result.model_copy(update={"stored_artifacts": tampered}))
    unchanged = {
        event_id: artifact
        for event_id, artifact in tampered.items()
        if event_id != "00000000-0000-0000-0000-000000000301"
    }
    assert unchanged == {
        event_id: artifact
        for event_id, artifact in result.stored_artifacts.items()
        if event_id != "00000000-0000-0000-0000-000000000301"
    }


def test_first_trade_verifier_can_report_failed_status() -> None:
    class RefusingResolver:
        def resolve_first_trade(self, record_id: str, *, evaluated_at: datetime) -> None:
            del record_id, evaluated_at
            raise AccountTransitionRefusedError(RefusalReason.FIRST_TRADE_SIGNATURE_INVALID)

    result = verify_first_trade_record(  # type: ignore[arg-type]
        RefusingResolver(), "SYN-TAMPERED", evaluated_at=datetime(2026, 11, 17, tzinfo=UTC)
    )
    assert result.status == "FAILED"
    assert result.reason == "FIRST_TRADE_SIGNATURE_INVALID"


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


def test_daily_close_i3_fails_when_only_depository_side_moves() -> None:
    result = run_golden_path(depository_quantity_delta=Decimal(1))
    assert result.i3_computed is False


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
    anchor = evidence.parent / "pack-digest-dsor.json"
    assert verify_published_pack(evidence, anchor)
    evidence.write_text(evidence.read_text() + " ", encoding="utf-8")
    assert not verify_published_pack(evidence, anchor)
