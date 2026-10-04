"""Deterministic example tests for Cato Cash branches that randomness reached.

The per-file branch floor on ``atreides/rails/cato_cash.py`` was met on some
Hypothesis seeds and missed on others, because the only test reaching one
ladder branch was a property test that reached it by chance (ORDER HYG-1).
A floor that depends on the seed is not a floor. Every test here is a plain
example, so the branches it covers are covered on every run, and the
``floor`` Hypothesis profile in ``tests/conftest.py`` exists to prove that.

Each test names the branch it pins by the condition, not by a line number,
because line numbers move and conditions do not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.rails.cato_cash import (
    CashRail,
    CatoCashDecision,
    Counterparty,
    CounterpartyStanding,
    FinalityClass,
    FreshnessPolicy,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    evaluate,
)


def _rails(**overrides: RailState | None) -> dict[CashRail, RailState]:
    """Standard rail state, with overrides; ``None`` removes a rail."""
    base: dict[CashRail, RailState] = {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, None, Decimal("10000000")
        ),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }
    for name, state in overrides.items():
        rail = CashRail(name)
        if state is None:
            base.pop(rail, None)
        else:
            base[rail] = state
    return base


def _op(notional: str = "1000000", **kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": Decimal(notional),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _funded(obligation: str = "1000000") -> FundingState:
    return FundingState(
        projected_funded_position=Decimal("100000000000"),
        net_obligation=Decimal(obligation),
        net_debit_cap_headroom=Decimal("100000000000"),
        clearing_fund_sufficient=True,
    )


def _eval(
    operation: OperationContext,
    rails: dict[CashRail, RailState],
    *,
    stress_reading_age_seconds: int | None = None,
    freshness_policy: FreshnessPolicy | None = None,
) -> CatoCashDecision:
    return evaluate(
        operation=operation,
        funding=_funded(str(operation.notional)),
        rails=rails,
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=stress_reading_age_seconds,
        freshness_policy=freshness_policy,
    )


def _assert_default_fedwire(decision: CatoCashDecision) -> None:
    assert decision.decision is GateDecision.PROCEED
    assert decision.reason_code is ReasonCode.CLEARED
    assert decision.recommended_rail is CashRail.FEDWIRE
    assert decision.finality_class is FinalityClass.GROSS_FINAL
    assert decision.rationale.startswith("Default rail (CASH-001 SV.C.6).")


# --- WP-1: the tokenized preference falls through to the Fedwire default ---
#
# Rule 5 prefers a tokenized-deposit rail when both counterparties support
# one. Where that rail cannot carry the operation, rule 5 does not apply and
# rule 6, the Fedwire default, decides (CASH-001 SV.C.5 and SV.C.6). Before
# these tests only random property examples reached that fall through.


@pytest.mark.parametrize(
    "tokenized_state",
    [
        pytest.param(None, id="tokenized-rail-absent"),
        pytest.param(
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.CLOSED),
            id="tokenized-rail-closed",
        ),
        pytest.param(
            RailState(CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, -1),
            id="tokenized-rail-past-cutoff",
        ),
    ],
)
def test_supported_but_unusable_tokenized_rail_falls_through_to_fedwire(
    tokenized_state: RailState | None,
) -> None:
    """Both counterparties support tokenized deposits, but the tokenized rail
    is not among the usable rails. Support is not availability."""
    decision = _eval(
        _op(tokenized_deposit_supported=True),
        _rails(tokenized_deposit=tokenized_state),
    )
    _assert_default_fedwire(decision)


def test_tokenized_rail_over_its_value_cap_falls_through_to_fedwire() -> None:
    """The tokenized rail is open, but the notional exceeds its value cap, so
    it cannot carry the operation and the default decides. Also the only
    example that exercises the value cap test inside the ladder's preference
    helper."""
    capped = RailState(
        CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None, Decimal("500000")
    )
    decision = _eval(
        _op("1000000", tokenized_deposit_supported=True),
        _rails(tokenized_deposit=capped),
    )
    _assert_default_fedwire(decision)


def test_tokenized_rail_within_its_value_cap_is_still_preferred() -> None:
    """Control for the test above: the same capped rail wins when the
    operation fits, so the fall through is caused by the cap and nothing
    else."""
    capped = RailState(
        CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None, Decimal("500000")
    )
    decision = _eval(
        _op("400000", tokenized_deposit_supported=True),
        _rails(tokenized_deposit=capped),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.TOKENIZED_DEPOSIT
    assert "CASH-001 SV.C.5" in decision.rationale


# --- WP-2: the remaining branches that a deterministic example can reach --
#
# Classified in the ORDER HYG-1 report. Two branches are left uncovered on
# purpose: the ladder's exhausted fall through loop and the hold that
# follows it. Check 6 refuses every non-linked operation for which no rail
# passes ``_serviceable``, and the loop uses the same predicate on the same
# inputs, so the loop always returns. A depository-linked operation returns
# at rule 4 before the loop. Both remain as defensive code, which this order
# does not remove.


def test_a_counterparty_without_an_identifier_is_refused() -> None:
    with pytest.raises(ValueError, match="counterparty_id is required"):
        Counterparty(counterparty_id="")


def test_a_negative_assessment_age_is_refused() -> None:
    """Assessed, attributed, and dated in the future. The provenance and
    standing checks pass, so the age check is the one that refuses it."""
    with pytest.raises(ValueError, match="may not be negative"):
        Counterparty(
            counterparty_id="CP-1",
            standing=CounterpartyStanding.IN_GOOD_STANDING,
            provenance="credit file, 19 Aug 2026",
            assessed_age_seconds=-1,
        )


def test_a_policy_polices_only_the_bounds_it_states() -> None:
    """A policy that bounds only counterparty age does not police the stress
    reading or the rail states. Their ages are unknown here, which a stated
    bound would treat as stale, and the operation still proceeds."""
    decision = _eval(
        _op(
            counterparty=Counterparty(
                counterparty_id="CP-1",
                standing=CounterpartyStanding.IN_GOOD_STANDING,
                provenance="credit file, 19 Aug 2026",
                assessed_age_seconds=3600,
            )
        ),
        _rails(),
        freshness_policy=FreshnessPolicy(
            max_counterparty_assessment_age_seconds=86400
        ),
    )
    assert decision.decision is GateDecision.PROCEED
    assert ("freshness_policy", "stated") in decision.checks_evaluated
    assert ("stress_reading_age_seconds", "None") in decision.checks_evaluated


def test_a_fresh_counterparty_assessment_under_a_policy_proceeds() -> None:
    """Every bound stated and every age inside it, including the
    counterparty's. The freshness checks pass and the gate goes on to
    decide."""
    rails = {
        CashRail.FEDWIRE: RailState(
            CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200, None, 60
        )
    }
    decision = _eval(
        _op(
            counterparty=Counterparty(
                counterparty_id="CP-1",
                standing=CounterpartyStanding.IN_GOOD_STANDING,
                provenance="credit file, 19 Aug 2026",
                assessed_age_seconds=3600,
            )
        ),
        rails,
        stress_reading_age_seconds=60,
        freshness_policy=FreshnessPolicy(
            max_stress_reading_age_seconds=3600,
            max_rail_state_age_seconds=300,
            max_counterparty_assessment_age_seconds=86400,
        ),
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.FEDWIRE
    assert ("counterparty_standing", "in_good_standing") in decision.checks_evaluated


def test_the_fall_through_skips_the_reserved_ports_placeholder() -> None:
    """Fedwire is absent, so the ladder falls through to the sorted search.
    A caller has marked the reserved PORTS placeholder available, and it
    sorts ahead of the one serviceable rail. It is skipped, not chosen."""
    rails = {
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.AVAILABLE
        ),
        CashRail.REGULATED_STABLECOIN: RailState(
            CashRail.REGULATED_STABLECOIN, RailStatus.AVAILABLE
        ),
    }
    decision = _eval(_op(), rails)
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.REGULATED_STABLECOIN
    assert decision.rationale.startswith("Sole serviceable rail")


def test_the_fall_through_skips_a_usable_rail_that_cannot_carry_it() -> None:
    """Fedwire is absent. FedNow is open but capped below the notional, and
    it sorts ahead of the one rail that can carry the operation. Usable is
    not serviceable, so the search passes over it."""
    rails = {
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, None, Decimal("1000000")
        ),
        CashRail.NSS_DTC_NSCC: RailState(
            CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200
        ),
    }
    decision = _eval(_op("5000000"), rails)
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.NSS_DTC_NSCC
    assert decision.finality_class is FinalityClass.DEFERRED_NET
