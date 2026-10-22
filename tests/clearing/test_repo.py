from datetime import date
from decimal import Decimal

import pytest

from atreides.clearing.access import AccessDetermination, AccessPath, AccessStatus
from atreides.clearing.ficc import (
    ClearingAgency,
    ClearingStatus,
    FiccGsdNettingDocument,
    FiccGsdNettingRequest,
    NovatedObligation,
    produce_ficc_gsd_result,
)
from atreides.clearing.repo import (
    RepoDocument,
    RepoLeg,
    RepoService,
    RepoTerm,
    RepoTrade,
    SponsoredExecution,
    dvp_legs_for_netting,
    produce_repo_result,
)
from tests.clearing.test_ficc import _arrangement


def access(path=AccessPath.FICC_DIRECT):
    return AccessDetermination(status=AccessStatus.ESTABLISHED, arrangement=_arrangement(path))


def trade(service=RepoService.DVP, **changes):
    values = dict(
        trade_id="repo-1",
        member_id="member-a",
        service=service,
        term=RepoTerm.TERM,
        start_date=date(2026, 10, 22),
        close_date=date(2026, 10, 29),
        collateral_par=Decimal("100"),
        start_money=Decimal("99"),
        repo_rate_percent=Decimal("5"),
        haircut_percent=Decimal("1"),
        member_margin_approximation=Decimal("0.25"),
        cusip="91282CJL6",
    )
    if service is RepoService.GCF:
        values.update(
            cusip=None, collateral_class="US_TREASURY_GENERAL", clearing_bank="synthetic-bank"
        )
    values.update(changes)
    return RepoTrade(**values)


def document(result):
    assert result.payload is not None
    return RepoDocument.model_validate_json(result.payload)


def test_two_legs_conserve_par_and_close_money_includes_interest():
    doc = document(
        produce_repo_result(trade=trade(), access=access(), settled_legs=(RepoLeg.START,))
    )
    start, close = doc.legs
    assert start.signed_par + close.signed_par == 0
    assert close.signed_money == Decimal("99.09625")
    assert start.signed_money + close.signed_money == Decimal("0.09625")
    assert start.facts[-1].status.value == "RECORDED"
    assert close.facts[-1].status.value == "NOT_RECORDED"
    assert doc.member_margin_method == "SYNTHETIC_APPROXIMATION_NOT_FICC_VAR"


def test_dvp_repo_nets_with_cash_by_member_cusip_and_date():
    repo = produce_repo_result(trade=trade(close_date=date(2026, 10, 23)), access=access())
    repo_start = dvp_legs_for_netting(repo)[0]
    cash = NovatedObligation(
        obligation_id="cash-1",
        trade_ids=("cash-trade",),
        member_id="member-a",
        cusip="91282CJL6",
        settlement_date=date(2026, 10, 22),
        signed_quantity=Decimal("-40"),
        signed_settlement_amount=Decimal("39.5"),
        settlement_currency="USD",
        novation_evidence_id="cash-nov",
    )
    result = produce_ficc_gsd_result(
        FiccGsdNettingRequest(
            clearing_agency=ClearingAgency.FICC_GSD,
            access=access(),
            obligations=(cash, repo_start),
            clearing_acceptance_evidence_id="accept",
            netting_evidence_id="net",
        )
    )
    net = FiccGsdNettingDocument.model_validate_json(result.payload).net_settlement_obligations[0]
    assert net.net_quantity == Decimal("60")
    assert net.net_settlement_amount == Decimal("-59.5")
    assert net.source_trade_ids == ("cash-trade", "repo-1")


def test_gcf_is_cusipless_balanced_and_uses_distinct_triparty_path():
    doc = document(produce_repo_result(trade=trade(RepoService.GCF), access=access()))
    assert doc.gcf_allocation.allocated_par == doc.gcf_allocation.returned_par
    assert {leg.settlement_path for leg in doc.legs} == {"GCF_TRIPARTY"}
    assert (
        dvp_legs_for_netting(produce_repo_result(trade=trade(RepoService.GCF), access=access()))
        == ()
    )


@pytest.mark.parametrize("style", list(SponsoredExecution))
def test_both_sponsored_execution_styles_are_explicit(style):
    result = produce_repo_result(
        trade=trade(sponsored_execution=style), access=access(AccessPath.FICC_SPONSORED)
    )
    assert result.status is ClearingStatus.ESTABLISHED


def test_missing_sponsored_detail_and_cme_are_indeterminate():
    assert (
        produce_repo_result(trade=trade(), access=access(AccessPath.FICC_SPONSORED)).status
        is ClearingStatus.INDETERMINATE
    )
    assert (
        produce_repo_result(
            trade=trade(), access=access(), agency=ClearingAgency.CME_SECURITIES_CLEARING
        ).status
        is ClearingStatus.INDETERMINATE
    )
