"""Shared fixtures for Settlement Operations Analyst integration tests.

Each fixture creates an independent DSORLineageStub (with a fresh uuid4
operation_id) so that tests can append multiple outputs to the same store
without triggering the DSOR append-only constraint.
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from aureon.agents.tier1.outputs import (
    GCFPoolCustodian,
    SettlementKind,
    SettlementRail,
    SettlementTaskingRecord,
)
from aureon.contracts import CAOMTier, DSORLineageStub
from aureon.dsor import DSORStore


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _lineage(dtg: datetime, authority_id: str) -> DSORLineageStub:
    """Build a fresh DSORLineageStub with a unique operation_id."""
    return DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id=authority_id,
        initiated_at=dtg,
        pre_operation_state_hash=_sha(f"pre-state-{authority_id}"),
    )


@pytest.fixture
def dtg() -> datetime:
    return datetime(2026, 6, 20, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def mem_store() -> Generator[DSORStore, None, None]:
    """In-memory DSORStore — fast, no cleanup needed."""
    with DSORStore(":memory:") as store:
        yield store


# ---------------------------------------------------------------------------
# Tasking record fixtures — FICC GSD repo (UST T-bill collateral)
# ---------------------------------------------------------------------------


@pytest.fixture
def ficc_gsd_repo_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC GSD DVP repo — net delivery of T-note/bond collateral, receipt of cash.

    CUSIP 91282CCR7 uses the 91282C prefix, which is the note/bond format
    (not the 912796 T-bill prefix). Fixture represents a repo backed by
    T-notes/bonds as collateral.
    """
    lineage = _lineage(dtg, "soa-repo-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="91282CCR7",
        net_delivery_quantity=Decimal("10000000"),
        net_payment_amount=Decimal("9975000"),
        ficc_published_net_delivery=Decimal("10000000"),
        ficc_clearing_fund_compliant=True,
        intraday_credit_limit=Decimal("1000000000"),
        intraday_credit_current_usage=Decimal("250000000"),
    )


# ---------------------------------------------------------------------------
# Tasking record fixtures — FICC GSD cash UST (December 2026 mandate)
# ---------------------------------------------------------------------------


@pytest.fixture
def cash_ust_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC GSD DVP cash UST — buy-side net settlement."""
    lineage = _lineage(dtg, "soa-ust-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=15, minute=30),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="912828R69",
        net_delivery_quantity=Decimal("50000000"),
        net_payment_amount=Decimal("49850000"),
        ficc_published_net_delivery=Decimal("50000000"),
        ficc_clearing_fund_compliant=True,
        intraday_credit_limit=Decimal("2000000000"),
        intraday_credit_current_usage=Decimal("300000000"),
    )


# ---------------------------------------------------------------------------
# Tasking record fixtures — FICC Sponsored DVP
# ---------------------------------------------------------------------------


@pytest.fixture
def sponsored_dvp_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC Sponsored DVP — Sponsored Member via JPM as Sponsoring Member."""
    lineage = _lineage(dtg, "soa-sponsored-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_SPONSORED_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="91282CCR7",
        net_delivery_quantity=Decimal("5000000"),
        net_payment_amount=Decimal("4990000"),
        ficc_published_net_delivery=Decimal("5000000"),
        ficc_clearing_fund_compliant=True,
        sponsoring_member_id="JPM-SPONSOR-001",
    )


# ---------------------------------------------------------------------------
# Tasking record fixtures — FICC GCF Repo
# ---------------------------------------------------------------------------


@pytest.fixture
def gcf_repo_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC GCF Repo — BNY Mellon pool custodian."""
    lineage = _lineage(dtg, "soa-gcf-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GCF_REPO,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GCF",
        deadline=dtg.replace(hour=22, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="GC-POOL-BNY",
        net_delivery_quantity=Decimal("20000000"),
        net_payment_amount=Decimal("19990000"),
        ficc_clearing_fund_compliant=True,
        gcf_pool_custodian=GCFPoolCustodian.BNY_MELLON,
    )


# ---------------------------------------------------------------------------
# Tasking record fixtures — FICC intraday MTM margin call (Fedwire Funds)
# ---------------------------------------------------------------------------


@pytest.fixture
def mtm_call_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC intraday MTM call — Fedwire Funds to FICC's Federal Reserve account."""
    lineage = _lineage(dtg, "soa-mtm-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FEDWIRE_FUNDS,
        settlement_kind=SettlementKind.MTM_MARGIN_CALL,
        counterparty_id="FICC-MTM",
        deadline=dtg.replace(hour=17, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        ficc_clearing_fund_compliant=True,
        ficc_mtm_call_amount=Decimal("2500000"),
        ficc_mtm_call_deadline=dtg.replace(hour=17, minute=0),
        intraday_credit_limit=Decimal("500000000"),
        intraday_credit_current_usage=Decimal("100000000"),
    )


# ---------------------------------------------------------------------------
# Escalation-path fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clearing_fund_deficiency_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """FICC clearing fund deficiency — pre-routing hold."""
    lineage = _lineage(dtg, "soa-cf-deficiency-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="91282CCR7",
        ficc_clearing_fund_compliant=False,
    )


@pytest.fixture
def intraday_credit_threshold_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """Intraday credit at limit — pre-routing hold."""
    lineage = _lineage(dtg, "soa-credit-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        intraday_credit_limit=Decimal("500000000"),
        intraday_credit_current_usage=Decimal("500000000"),
    )


@pytest.fixture
def net_obligation_mismatch_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """Net delivery quantity diverges from FICC published figure."""
    lineage = _lineage(dtg, "soa-netmismatch-001")
    return SettlementTaskingRecord(
        operation_id=lineage.operation_id,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        net_cusip="91282CCR7",
        net_delivery_quantity=Decimal("10000000"),
        ficc_published_net_delivery=Decimal("10500000"),
        ficc_clearing_fund_compliant=True,
    )


@pytest.fixture
def dsor_mismatch_tasking(dtg: datetime) -> SettlementTaskingRecord:
    """operation_id deliberately mismatched from lineage_stub.operation_id."""
    lineage = _lineage(dtg, "soa-dsormismatch-001")
    return SettlementTaskingRecord(
        operation_id=uuid4(),
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="FICC-GSD",
        deadline=dtg.replace(hour=23, minute=0),
        dsor_pre_trade_record_id=uuid4(),
        lineage_stub=lineage,
        ficc_clearing_fund_compliant=True,
    )
