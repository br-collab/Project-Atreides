"""MVP-2 firm FOCUS tie-out and synthetic early-warning workflow acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.account_lifecycle import ActorRegistryApproverVerifier
from atreides.customer_protection.control import ControlInputs, Holding, IssueRequirement
from simulator.calibration import load_calibration_pack
from simulator.early_warning import DEADLINE_QUOTE, PARAGRAPH_QUOTES, EarlyWarningQueue
from simulator.firm import _pab_requirement_from_book_lines, load_firm_profile, run_firm
from simulator.focus import _books_control_shortfall


def _profile():  # type: ignore[no-untyped-def]
    return load_firm_profile(load_calibration_pack("firm-synthetic/5"), "small")


def test_i13_ties_every_real_firm_close_and_book_shape() -> None:
    run = run_firm(_profile(), days=2, verify_replay=False)
    for day in run.days:
        assert day.invariants["I13_FOCUS_TIE_OUT"]
        assert day.focus_tie_out.differences == ()
        assert day.focus_tie_out.book_shape["customer_accounts"] > 0
        assert day.focus_tie_out.book_shape["ownership_lines"] > 0
    assert run.days[1].focus_tie_out.book_shape["fail_lines"] > 0
    assert run.days[1].focus_tie_out.book_shape["stock_loan_lines"] > 0


def test_focus_control_filter_uses_projected_rule_identifiers() -> None:
    control = ControlInputs(
        as_of=datetime(2027, 1, 4, tzinfo=UTC).date(),
        issues=(
            IssueRequirement(
                issue="SYN-ISSUE",
                fully_paid=10,
                excess_margin=0,
                books_total=10,
                holdings=(Holding(location="15c3-3.control.c1", quantity=10),),
            ),
        ),
    )
    assert _books_control_shortfall(control) == 0


@seed(20261115)
@settings(max_examples=200, deadline=None)
@given(
    customer_credit_cents=st.integers(min_value=0, max_value=10**12),
    customer_debit_cents=st.integers(min_value=0, max_value=10**12),
    pab_credit_cents=st.integers(min_value=0, max_value=10**12),
    pab_debit_cents=st.integers(min_value=0, max_value=10**12),
    reduction_basis_points=st.integers(min_value=0, max_value=10_000),
)
def test_pab_tie_out_conserves_requirement_to_the_cent(
    customer_credit_cents: int,
    customer_debit_cents: int,
    pab_credit_cents: int,
    pab_debit_cents: int,
    reduction_basis_points: int,
) -> None:
    cents = Decimal(100)
    customer_credits = Decimal(customer_credit_cents) / cents
    customer_debits = Decimal(customer_debit_cents) / cents
    pab_credits = Decimal(pab_credit_cents) / cents
    pab_debits = Decimal(pab_debit_cents) / cents
    rate = Decimal(reduction_basis_points) / Decimal(10_000)
    result = _pab_requirement_from_book_lines(
        customer_credits, customer_debits, pab_credits, pab_debits, rate
    )
    customer_excess = max(
        customer_debits - rate * customer_debits - customer_credits, Decimal()
    )
    raw_pab = max(pab_credits - pab_debits, Decimal())
    assert result + min(raw_pab, customer_excess) == raw_pab


@pytest.mark.parametrize(
    "mutation, difference",
    [
        ("FOCUS_WRONG_NET_CAPITAL", "net_capital"),
        ("FOCUS_WRONG_RESERVE_CREDIT", "reserve_total_credits"),
        ("FOCUS_WRONG_CONTROL_QUANTITY", "control_shortfall_by_issue"),
        ("FOCUS_DROP_CUSTOMER_ACCOUNT", "customer_accounts"),
    ],
)
def test_each_focus_mutation_turns_i13_false(mutation: str, difference: str) -> None:
    day = run_firm(_profile(), days=1, mutation=mutation, verify_replay=False).days[0]
    assert not day.invariants["I13_FOCUS_TIE_OUT"]
    assert difference in day.focus_tie_out.differences


def test_fired_warning_always_creates_owned_unfiled_draft() -> None:
    day = run_firm(
        _profile(), days=1, verify_replay=False, early_warning_stress=True
    ).days[0]
    assert day.invariants["I16_EARLY_WARNING_DRAFT_OWNED"]
    assert day.early_warning_notices
    for notice in day.early_warning_notices:
        assert notice.owner_role == "FINOP"
        assert notice.label == "synthetic draft, not filed"
        assert notice.transmitted is False
        # 17 CFR 240.17a-11(b), pinned checksum asserted below, says notice is
        # prompt but within 24 hours; each triggered paragraph is quoted too.
        assert notice.deadline_quote == DEADLINE_QUOTE
        assert notice.paragraph_quote == PARAGRAPH_QUOTES[notice.paragraph]
        assert notice.rule_checksum == (
            "612026da8c0226c20f137de0f72362610d7cbb3fd8a87e904f048363e3eea475"
        )


@pytest.mark.parametrize(
    "mutation", ["EARLY_WARNING_MISSING_DRAFT", "EARLY_WARNING_MISSING_OWNER"]
)
def test_missing_or_unowned_warning_draft_turns_i16_false(mutation: str) -> None:
    day = run_firm(
        _profile(),
        days=1,
        mutation=mutation,
        verify_replay=False,
        early_warning_stress=True,
    ).days[0]
    assert not day.invariants["I16_EARLY_WARNING_DRAFT_OWNED"]


def test_only_verified_human_can_decide_warning_draft() -> None:
    notice = run_firm(
        _profile(), days=1, verify_replay=False, early_warning_stress=True
    ).days[0].early_warning_notices[0]
    human = ActorRef(
        actor_id=ActorId("act_00000000000000000000000101"),
        actor_kind=ActorKind.HUMAN,
        role="FINOP",
        entitlement_refs=("synthetic-finop",),
        authenticated=True,
    )
    service = ActorRef(
        actor_id=ActorId("act_00000000000000000000000102"),
        actor_kind=ActorKind.DETERMINISTIC_SERVICE,
        role="synthetic-service",
        entitlement_refs=("synthetic-finop",),
        authenticated=True,
    )
    verifier = ActorRegistryApproverVerifier(
        {str(human.actor_id): human, str(service.actor_id): service}
    )
    queue = EarlyWarningQueue((notice,), verifier)
    decided_at = datetime(2027, 1, 4, 22, tzinfo=UTC)
    with pytest.raises(PermissionError, match="REQUIRES_VERIFIED_HUMAN"):
        queue.decide(
            notice.notice_id,
            "ACKNOWLEDGE",
            actor=service,
            approval_ref="SYN-SERVICE-REFUSED",
            decided_at=decided_at,
        )
    decided = queue.decide(
        notice.notice_id,
        "ACKNOWLEDGE",
        actor=human,
        approval_ref="SYN-HUMAN-APPROVAL",
        decided_at=decided_at,
    )
    assert decided.status == "ACKNOWLEDGED"
    assert decided.decision_actor_id == str(human.actor_id)
    assert decided.decision_time == decided_at
    assert decided.transmitted is False
