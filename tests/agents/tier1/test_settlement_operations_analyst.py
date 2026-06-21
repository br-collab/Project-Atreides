"""Integration tests for SettlementOperationsAnalyst — Phase 3.

Tests the full six-primitive workflow across FICC GSD repo and cash UST
paths, pre-routing gate escalations, and DSOR integration (persistence and
replay determinism).

FICC GSD repo path: repos clearing through FICC GSD, net delivery of UST
    collateral, receipt of cash. June 2027 eligible repo mandate context.
Cash UST path: UST buys/sells clearing through FICC GSD. December 2026
    cash UST mandate context.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from aureon.agents.tier1.outputs import (
    DiscrepancyCode,
    GCFPoolCustodian,
    SettlementEscalation,
    SettlementKind,
    SettlementRail,
    SettlementTaskingRecord,
    SettlementTelemetry,
)
from aureon.agents.tier1.settlement_operations_analyst import SettlementOperationsAnalyst
from aureon.dsor import DSORAppendOnlyError, DSORStore

# ===========================================================================
# FICC GSD Repo Path (June 2027 eligible repo mandate)
# ===========================================================================


class TestFICCGSDRepoPath:
    def test_repo_returns_settlement_telemetry(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)

    def test_repo_telemetry_rail(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.rail == SettlementRail.FICC_GSD_DVP

    def test_repo_telemetry_net_obligation_preserved(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.net_cusip == "91282CCR7"
        assert output.net_delivery_quantity == Decimal("10000000")
        assert output.net_payment_amount == Decimal("9975000")

    def test_repo_telemetry_clearing_fund_compliant(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.clearing_fund_compliant is True

    def test_repo_telemetry_stored_and_replayable(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, record = SettlementOperationsAnalyst().run(
            ficc_gsd_repo_tasking, mem_store, now=dtg
        )
        replayed = mem_store.replay(record.record_id)
        assert isinstance(replayed, SettlementTelemetry)
        assert replayed.model_dump_json() == output.model_dump_json()

    def test_repo_instruction_reference_format(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.instruction_reference.startswith("FICC_GSD_DVP-")


# ===========================================================================
# Cash UST Path (December 2026 mandate)
# ===========================================================================


class TestCashUSTPath:
    def test_cash_ust_returns_settlement_telemetry(
        self,
        mem_store: DSORStore,
        cash_ust_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(cash_ust_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)

    def test_cash_ust_telemetry_cusip(
        self,
        mem_store: DSORStore,
        cash_ust_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(cash_ust_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.net_cusip == "912828R69"
        assert output.net_delivery_quantity == Decimal("50000000")

    def test_cash_ust_telemetry_stored_and_replayable(
        self,
        mem_store: DSORStore,
        cash_ust_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, record = SettlementOperationsAnalyst().run(cash_ust_tasking, mem_store, now=dtg)
        replayed = mem_store.replay(record.record_id)
        assert replayed.model_dump_json() == output.model_dump_json()

    def test_cash_ust_replay_byte_identical(
        self,
        mem_store: DSORStore,
        cash_ust_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        _, record = SettlementOperationsAnalyst().run(cash_ust_tasking, mem_store, now=dtg)
        r1 = mem_store.replay(record.record_id)
        r2 = mem_store.replay(record.record_id)
        assert r1.model_dump_json() == r2.model_dump_json()


# ===========================================================================
# FICC Sponsored DVP and GCF Repo
# ===========================================================================


class TestFICCSponsoredAndGCF:
    def test_sponsored_dvp_returns_telemetry(
        self,
        mem_store: DSORStore,
        sponsored_dvp_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(sponsored_dvp_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.rail == SettlementRail.FICC_SPONSORED_DVP

    def test_sponsored_dvp_member_id_in_telemetry(
        self,
        mem_store: DSORStore,
        sponsored_dvp_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(sponsored_dvp_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.sponsoring_member_id == "JPM-SPONSOR-001"

    def test_gcf_repo_returns_telemetry(
        self,
        mem_store: DSORStore,
        gcf_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(gcf_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.rail == SettlementRail.FICC_GCF_REPO

    def test_gcf_repo_custodian_in_telemetry(
        self,
        mem_store: DSORStore,
        gcf_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(gcf_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.gcf_pool_custodian == GCFPoolCustodian.BNY_MELLON

    def test_mtm_call_fedwire_funds_path(
        self,
        mem_store: DSORStore,
        mtm_call_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(mtm_call_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)
        assert output.rail == SettlementRail.FEDWIRE_FUNDS
        assert output.settlement_kind == SettlementKind.MTM_MARGIN_CALL


# ===========================================================================
# Pre-routing gate checks — all six paths
# ===========================================================================


class TestPreRoutingGates:
    def test_intraday_credit_at_limit_escalates(
        self,
        mem_store: DSORStore,
        intraday_credit_threshold_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            intraday_credit_threshold_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.discrepancy_code == DiscrepancyCode.INTRADAY_CREDIT_THRESHOLD

    def test_intraday_credit_below_limit_passes(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        # repo tasking has usage=250M vs limit=1B — should not trigger gate
        output, _ = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        assert isinstance(output, SettlementTelemetry)

    def test_clearing_fund_deficiency_escalates(
        self,
        mem_store: DSORStore,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            clearing_fund_deficiency_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.discrepancy_code == DiscrepancyCode.CLEARING_FUND_DEFICIENCY

    def test_clearing_fund_deficiency_flag_set(
        self,
        mem_store: DSORStore,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            clearing_fund_deficiency_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.clearing_fund_deficiency is True

    def test_net_obligation_mismatch_escalates(
        self,
        mem_store: DSORStore,
        net_obligation_mismatch_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            net_obligation_mismatch_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.discrepancy_code == DiscrepancyCode.NET_OBLIGATION_MISMATCH

    def test_net_obligation_mismatch_discrepancy_detail(
        self,
        mem_store: DSORStore,
        net_obligation_mismatch_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            net_obligation_mismatch_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.net_obligation_discrepancy is not None
        assert "10000000" in output.net_obligation_discrepancy
        assert "10500000" in output.net_obligation_discrepancy

    def test_dsor_lineage_mismatch_escalates(
        self,
        mem_store: DSORStore,
        dsor_mismatch_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            dsor_mismatch_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.discrepancy_code == DiscrepancyCode.DSOR_MISMATCH

    def test_escalation_pre_routing_has_no_rail(
        self,
        mem_store: DSORStore,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, _ = SettlementOperationsAnalyst().run(
            clearing_fund_deficiency_tasking, mem_store, now=dtg
        )
        assert isinstance(output, SettlementEscalation)
        assert output.rail is None

    def test_escalation_stored_and_replayable(
        self,
        mem_store: DSORStore,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        output, record = SettlementOperationsAnalyst().run(
            clearing_fund_deficiency_tasking, mem_store, now=dtg
        )
        replayed = mem_store.replay(record.record_id)
        assert isinstance(replayed, SettlementEscalation)
        assert replayed.model_dump_json() == output.model_dump_json()


# ===========================================================================
# DSOR integration — persistence and append-only enforcement
# ===========================================================================


class TestDSORIntegration:
    def test_append_only_on_same_operation_id(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        analyst = SettlementOperationsAnalyst()
        analyst.run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        with pytest.raises(DSORAppendOnlyError):
            analyst.run(ficc_gsd_repo_tasking, mem_store, now=dtg)

    def test_repo_and_ust_same_store_both_replayable(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        cash_ust_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        analyst = SettlementOperationsAnalyst()
        repo_out, repo_rec = analyst.run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        ust_out, ust_rec = analyst.run(cash_ust_tasking, mem_store, now=dtg)
        assert mem_store.replay(repo_rec.record_id).model_dump_json() == repo_out.model_dump_json()
        assert mem_store.replay(ust_rec.record_id).model_dump_json() == ust_out.model_dump_json()

    def test_telemetry_replay_byte_identical(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        _, record = SettlementOperationsAnalyst().run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        r1 = mem_store.replay(record.record_id)
        r2 = mem_store.replay(record.record_id)
        assert r1.model_dump_json() == r2.model_dump_json()

    def test_escalation_replay_byte_identical(
        self,
        mem_store: DSORStore,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        _, record = SettlementOperationsAnalyst().run(
            clearing_fund_deficiency_tasking, mem_store, now=dtg
        )
        r1 = mem_store.replay(record.record_id)
        r2 = mem_store.replay(record.record_id)
        assert r1.model_dump_json() == r2.model_dump_json()

    def test_telemetry_and_escalation_different_kinds_in_same_store(
        self,
        mem_store: DSORStore,
        ficc_gsd_repo_tasking: SettlementTaskingRecord,
        clearing_fund_deficiency_tasking: SettlementTaskingRecord,
        dtg: datetime,
    ) -> None:
        analyst = SettlementOperationsAnalyst()
        telemetry, tel_rec = analyst.run(ficc_gsd_repo_tasking, mem_store, now=dtg)
        escalation, esc_rec = analyst.run(clearing_fund_deficiency_tasking, mem_store, now=dtg)
        assert isinstance(telemetry, SettlementTelemetry)
        assert isinstance(escalation, SettlementEscalation)
        assert tel_rec.record_id != esc_rec.record_id
        assert isinstance(mem_store.replay(tel_rec.record_id), SettlementTelemetry)
        assert isinstance(mem_store.replay(esc_rec.record_id), SettlementEscalation)
