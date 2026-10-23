from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

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
    assert close.signed_money == Decimal("99.10")
    assert start.signed_money + close.signed_money == Decimal("0.10")
    assert start.facts[-1].status.value == "RECORDED"
    assert close.facts[-1].status.value == "NOT_RECORDED"
    assert doc.member_margin_method == "SYNTHETIC_APPROXIMATION_NOT_FICC_VAR"


def test_dvp_repo_nets_with_cash_by_member_cusip_and_date():
    repo = produce_repo_result(
        trade=trade(term=RepoTerm.OVERNIGHT, close_date=date(2026, 10, 23)), access=access()
    )
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


def test_repo_term_matches_business_days_and_friday_to_monday_is_overnight():
    friday = date(2026, 10, 23)
    monday = date(2026, 10, 26)
    overnight = trade(term=RepoTerm.OVERNIGHT, start_date=friday, close_date=monday)
    assert overnight.term is RepoTerm.OVERNIGHT
    with pytest.raises(ValidationError, match="TERM repo must close more than one business day"):
        trade(term=RepoTerm.TERM, start_date=friday, close_date=monday)
    with pytest.raises(ValidationError, match="OVERNIGHT repo must close exactly one business day"):
        trade(term=RepoTerm.OVERNIGHT, close_date=date(2026, 10, 26))
    assert trade(term=RepoTerm.TERM, close_date=date(2026, 10, 26)).term is RepoTerm.TERM


def test_repo_term_calendar_excludes_declared_holidays_and_nonbusiness_closes():
    assert (
        trade(
            term=RepoTerm.OVERNIGHT,
            start_date=date(2026, 6, 18),
            close_date=date(2026, 6, 22),
        ).term
        is RepoTerm.OVERNIGHT
    )
    with pytest.raises(ValidationError, match="government securities business day"):
        trade(term=RepoTerm.OVERNIGHT, close_date=date(2026, 10, 24))
    with pytest.raises(ValidationError, match="start date"):
        trade(start_date=date(2027, 1, 1), close_date=date(2027, 1, 4))


def test_half_cent_close_money_rounds_up_and_document_keeps_unrounded_amount():
    repo = trade(
        term=RepoTerm.OVERNIGHT, start_money=Decimal("1.80"),
        repo_rate_percent=Decimal("100"), start_date=date(2026, 10, 22),
        close_date=date(2026, 10, 23),
    )
    assert repo.unrounded_close_money() == Decimal("1.805")
    assert repo.close_money() == Decimal("1.81")
    doc = document(produce_repo_result(trade=repo, access=access()))
    assert doc.legs[-1].unrounded_signed_money == Decimal("1.805")
    assert doc.cash_rounding_convention == "ROUND_HALF_UP_TO_CENT"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"term": RepoTerm.OPEN, "close_date": date(2026, 10, 23)}, "OPEN repo"),
        ({"close_date": date(2026, 10, 22)}, "later close date"),
        ({"cusip": None}, "DVP requires CUSIP"),
        (
            {"service": RepoService.GCF, "cusip": "91282CJL6"},
            "GCF requires CUSIP-less",
        ),
    ],
)
def test_trade_shape_refusals_name_the_reason(changes, reason):
    with pytest.raises(ValidationError, match=reason):
        trade(**changes)


def test_open_repo_has_one_leg_and_no_close_money():
    open_trade = trade(term=RepoTerm.OPEN, close_date=None)
    assert open_trade.close_money() is None
    doc = document(produce_repo_result(trade=open_trade, access=access()))
    assert len(doc.legs) == 1
    assert doc.gcf_allocation is None


def test_repo_result_refusals_name_each_reason():
    absent = AccessDetermination(status=AccessStatus.INDETERMINATE, reason="membership absent")
    cases = (
        (
            produce_repo_result(trade=trade(), access=absent),
            "repo access is indeterminate: membership absent",
        ),
        (
            produce_repo_result(trade=trade(member_id="member-b"), access=access()),
            "trade is not observed from the relied-on FICC member seat",
        ),
        (
            produce_repo_result(trade=trade(), access=access(AccessPath.FICC_SPONSORED)),
            "sponsored repo requires done-with or done-away evidence",
        ),
        (
            produce_repo_result(
                trade=trade(), access=access(), agency=ClearingAgency.CME_SECURITIES_CLEARING
            ),
            "CME Securities Clearing repo rules are declared but not built",
        ),
    )
    for result, reason in cases:
        assert result.status is ClearingStatus.INDETERMINATE
        assert result.reason == reason


def test_non_established_repo_has_no_dvp_legs_and_malformed_dvp_is_refused():
    assert (
        dvp_legs_for_netting(
            produce_repo_result(
                trade=trade(), access=access(), agency=ClearingAgency.CME_SECURITIES_CLEARING
            )
        )
        == ()
    )
    malformed = RepoDocument.model_construct(
        clearing_agency=ClearingAgency.FICC_GSD,
        clearing_method=RepoService.DVP,
        observed_member_id="member-a",
        access_path="FICC_DIRECT",
        sponsored_execution=None,
        repo_rate_percent=Decimal("5"),
        day_count_basis=360,
        term=RepoTerm.OPEN,
        haircut_percent=Decimal("0"),
        member_margin_approximation=Decimal("0"),
        legs=(
            document(produce_repo_result(trade=trade(), access=access()))
            .legs[0]
            .model_copy(update={"settlement_date": None}),
        ),
    )
    result = produce_repo_result(trade=trade(), access=access()).model_copy(
        update={"payload": malformed.model_dump_json().encode()}
    )
    with pytest.raises(ValueError, match="dated cash obligations"):
        dvp_legs_for_netting(result)
    assert (
        produce_repo_result(
            trade=trade(), access=access(), agency=ClearingAgency.CME_SECURITIES_CLEARING
        ).status
        is ClearingStatus.INDETERMINATE
    )
