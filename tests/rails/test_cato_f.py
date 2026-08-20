"""Tests for CATO-F — the FIAT/cash settlement-rail gate.

Exercises the Section V.B check ordering, the Section V.C rail ladder,
the Section V.E absent-gate default, and the Section III PORTS
placeholder invariant.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atreides.rails.cato_f import (
    GOLDEN_VECTORS,
    OFR_HOLD_THRESHOLD,
    OFR_STRESS_PREFERENCE_THRESHOLD,
    CashRail,
    CatoFDecision,
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
    absent_gate_decision,
    evaluate,
)


def _rails(**overrides: RailState) -> dict[CashRail, RailState]:
    base = {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, None, Decimal("1000000")
        ),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }
    base.update(overrides)
    return base


def _funded() -> FundingState:
    return FundingState(
        projected_funded_position=Decimal("50000000"),
        net_obligation=Decimal("1000000"),
        net_debit_cap_headroom=Decimal("10000000"),
        clearing_fund_sufficient=True,
    )


def _op(**kw: object) -> OperationContext:
    defaults: dict[str, object] = {
        "notional": Decimal("1000000"),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    defaults.update(kw)
    return OperationContext(**defaults)  # type: ignore[arg-type]


def _eval(**kw: object) -> CatoFDecision:
    params: dict[str, object] = {
        "operation": _op(),
        "funding": _funded(),
        "rails": _rails(),
        "ofr_stlfsi4": 0.0,
    }
    params.update(kw)
    return evaluate(**params)  # type: ignore[arg-type]


# --- Section V.B: check ordering -------------------------------------------


def test_clear_operation_proceeds_on_fedwire() -> None:
    d = _eval()
    assert d.decision is GateDecision.PROCEED
    assert d.reason_code is ReasonCode.CLEARED
    assert d.recommended_rail is CashRail.FEDWIRE
    assert d.finality_class is FinalityClass.GROSS_FINAL
    assert d.proceeds


def test_check1_systemic_stress_escalates() -> None:
    d = _eval(ofr_stlfsi4=1.5)
    assert d.decision is GateDecision.ESCALATE
    assert d.reason_code is ReasonCode.SYSTEMIC_STRESS_ESCALATE
    assert d.recommended_rail is None


def test_check2_material_magnitude_holds_under_caom() -> None:
    d = _eval(operation=_op(is_material=True))
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE
    assert "CAOM-001" in d.rationale


def test_check3_unfunded_holds() -> None:
    unfunded = FundingState(
        projected_funded_position=Decimal("100"),
        net_obligation=Decimal("1000000"),
        net_debit_cap_headroom=Decimal("10000000"),
        clearing_fund_sufficient=True,
    )
    d = _eval(funding=unfunded)
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.UNFUNDED_AT_SETTLEMENT_INSTANT


def test_check4_net_debit_cap_breach_holds() -> None:
    breached = FundingState(
        projected_funded_position=Decimal("50000000"),
        net_obligation=Decimal("1000000"),
        net_debit_cap_headroom=Decimal("-1"),
        clearing_fund_sufficient=True,
    )
    d = _eval(funding=breached)
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.RISK_CONTROL_BREACH


def test_check4_clearing_fund_deficient_holds() -> None:
    deficient = FundingState(
        projected_funded_position=Decimal("50000000"),
        net_obligation=Decimal("1000000"),
        net_debit_cap_headroom=Decimal("10000000"),
        clearing_fund_sufficient=False,
    )
    d = _eval(funding=deficient)
    assert d.reason_code is ReasonCode.RISK_CONTROL_BREACH


def test_check5_broad_stress_holds() -> None:
    d = _eval(ofr_stlfsi4=0.75)
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.BROAD_STRESS_HOLD


def test_check6_no_usable_rail_holds() -> None:
    closed = _rails(
        **{
            CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.CLOSED),
            CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.CLOSED),
            CashRail.FEDNOW: RailState(CashRail.FEDNOW, RailStatus.CLOSED),
        }
    )
    d = _eval(rails=closed)
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.NO_RAIL_IN_WINDOW


def test_check6_cutoff_passed_makes_rail_unusable() -> None:
    past = _rails(
        **{
            CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, -10),
            CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, -10),
            CashRail.FEDNOW: RailState(CashRail.FEDNOW, RailStatus.CLOSED),
        }
    )
    d = _eval(rails=past)
    assert d.reason_code is ReasonCode.NO_RAIL_IN_WINDOW


def test_check7_unresolvable_finality_holds() -> None:
    d = _eval(operation=_op(correspondent_finality_resolvable=False))
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.UNRESOLVABLE_FINALITY


def test_ordering_material_beats_unfunded() -> None:
    """Check 2 precedes check 3 — ordering is doctrine, not optimization."""
    unfunded = FundingState(
        projected_funded_position=Decimal("0"),
        net_obligation=Decimal("1000000"),
        net_debit_cap_headroom=Decimal("10000000"),
        clearing_fund_sufficient=True,
    )
    d = _eval(operation=_op(is_material=True), funding=unfunded)
    assert d.reason_code is ReasonCode.MATERIAL_MAGNITUDE_QUORUM_UNAVAILABLE


def test_ordering_escalate_beats_everything() -> None:
    d = _eval(operation=_op(is_material=True), ofr_stlfsi4=2.0)
    assert d.decision is GateDecision.ESCALATE


# --- Section V.C: rail ladder ----------------------------------------------


def test_ladder_depository_linkage_is_determined_not_selected() -> None:
    linked = _rails(
        **{
            CashRail.NSS_DTC_NSCC: RailState(
                CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 3600
            )
        }
    )
    d = _eval(
        operation=_op(depository_linked_rail=CashRail.NSS_DTC_NSCC), rails=linked
    )
    assert d.recommended_rail is CashRail.NSS_DTC_NSCC
    assert d.finality_class is FinalityClass.DEFERRED_NET
    assert "determined" in d.rationale


def test_ladder_lvps_material_prefers_gross_final() -> None:
    d = _eval(operation=_op(is_lvps_material=True))
    assert d.recommended_rail is CashRail.FEDWIRE
    assert d.finality_class is FinalityClass.GROSS_FINAL


def test_ladder_off_hours_uses_fednow_within_cap() -> None:
    d = _eval(
        operation=_op(within_business_hours=False, notional=Decimal("500000"))
    )
    assert d.recommended_rail is CashRail.FEDNOW


def test_ladder_off_hours_over_cap_does_not_use_fednow() -> None:
    d = _eval(
        operation=_op(within_business_hours=False, notional=Decimal("5000000"))
    )
    assert d.recommended_rail is not CashRail.FEDNOW


def test_ladder_tokenized_preferred_when_supported() -> None:
    tok = _rails(
        **{
            CashRail.TOKENIZED_DEPOSIT: RailState(
                CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None
            )
        }
    )
    d = _eval(operation=_op(tokenized_deposit_supported=True), rails=tok)
    assert d.recommended_rail is CashRail.TOKENIZED_DEPOSIT
    assert d.finality_class is FinalityClass.LEDGER_FINAL


# --- Section III: PORTS invariant ------------------------------------------


def test_ports_placeholder_never_recommended() -> None:
    only_ports = {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.CLOSED),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.CLOSED),
        CashRail.FEDNOW: RailState(CashRail.FEDNOW, RailStatus.CLOSED),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }
    d = _eval(rails=only_ports)
    assert d.decision is GateDecision.HOLD
    assert d.recommended_rail is not CashRail.PORTS_WHOLESALE


def test_ports_slot_always_present_in_standard_rail_state() -> None:
    assert CashRail.PORTS_WHOLESALE in _rails()


# --- Section V.E: absent-gate default --------------------------------------


def test_absent_gate_defaults_to_hold() -> None:
    d = absent_gate_decision()
    assert d.decision is GateDecision.HOLD
    assert d.reason_code is ReasonCode.GATE_UNAVAILABLE
    assert d.recommended_rail is None
    assert not d.proceeds


def test_absent_gate_never_proceeds_regardless_of_reason() -> None:
    for reason in ("timeout", "not configured", "", "PROCEED"):
        assert absent_gate_decision(reason).decision is GateDecision.HOLD


# --- Section VI: FX / PvP recording ----------------------------------------


def test_fx_without_pvp_records_herstatt_note() -> None:
    d = _eval(operation=_op(is_fx_leg=True, pvp_available=False))
    assert d.decision is GateDecision.PROCEED
    assert "WITHOUT PvP" in d.rationale
    assert "Herstatt" in d.rationale


def test_fx_with_pvp_has_no_herstatt_note() -> None:
    d = _eval(operation=_op(is_fx_leg=True, pvp_available=True))
    assert "Herstatt" not in d.rationale


# --- Replayability ----------------------------------------------------------


def test_decision_records_all_inputs_for_replay() -> None:
    d = _eval()
    keys = {k for k, _ in d.checks_evaluated}
    assert {"ofr_stlfsi4", "is_material", "is_funded", "usable_rails"} <= keys
    assert d.doctrine_version.startswith("AUR-CUSTODY-CASH-001")


def test_decision_is_frozen() -> None:
    d = _eval()
    with pytest.raises(Exception):
        d.decision = GateDecision.HOLD  # type: ignore[misc]


def test_determinism_same_inputs_same_decision() -> None:
    a, b = _eval(), _eval()
    assert (a.decision, a.reason_code, a.recommended_rail) == (
        b.decision,
        b.reason_code,
        b.recommended_rail,
    )
    assert a.checks_evaluated == b.checks_evaluated


# --- Section V.F: golden parity vectors ------------------------------------


@pytest.mark.parametrize("vector", GOLDEN_VECTORS, ids=lambda v: str(v["name"]))
def test_golden_parity_vectors(vector: dict[str, object]) -> None:
    d = _eval(ofr_stlfsi4=vector["ofr_stlfsi4"])
    assert d.decision is vector["expect_decision"]
    assert d.reason_code is vector["expect_reason"]
    assert d.recommended_rail is vector["expect_rail"]


# --- Section V.C.1: stress-posture preference band -------------------------
#
# These pin the OFR_STRESS_PREFERENCE_THRESHOLD boundary. The band only
# changes an outcome where a later ladder rule would otherwise win, so
# every case below uses a tokenized-deposit scenario (rule 5) and asserts
# whether rule 1 overrides it.


def _tokenized_rails() -> dict[CashRail, RailState]:
    return _rails(
        **{
            CashRail.TOKENIZED_DEPOSIT: RailState(
                CashRail.TOKENIZED_DEPOSIT, RailStatus.AVAILABLE, None
            )
        }
    )


def test_preference_band_sits_below_the_hold_band() -> None:
    """The band must be reachable - above it the gate HOLDs instead."""
    assert 0.0 < OFR_STRESS_PREFERENCE_THRESHOLD < OFR_HOLD_THRESHOLD


def test_elevated_stress_prefers_gross_final_over_tokenized() -> None:
    """Rule 1 beats rule 5: stressed windows do not carry ledger-final risk."""
    d = _eval(
        operation=_op(tokenized_deposit_supported=True),
        rails=_tokenized_rails(),
        ofr_stlfsi4=0.3,
    )
    assert d.decision is GateDecision.PROCEED
    assert d.recommended_rail is CashRail.FEDWIRE
    assert d.finality_class is FinalityClass.GROSS_FINAL
    assert "Elevated systemic stress" in d.rationale


def test_below_preference_band_tokenized_wins() -> None:
    d = _eval(
        operation=_op(tokenized_deposit_supported=True),
        rails=_tokenized_rails(),
        ofr_stlfsi4=0.1,
    )
    assert d.recommended_rail is CashRail.TOKENIZED_DEPOSIT
    assert "Elevated systemic stress" not in d.rationale


def test_preference_band_lower_boundary_is_inclusive() -> None:
    d = _eval(
        operation=_op(tokenized_deposit_supported=True),
        rails=_tokenized_rails(),
        ofr_stlfsi4=OFR_STRESS_PREFERENCE_THRESHOLD,
    )
    assert d.recommended_rail is CashRail.FEDWIRE


def test_just_below_preference_band_does_not_fire() -> None:
    d = _eval(
        operation=_op(tokenized_deposit_supported=True),
        rails=_tokenized_rails(),
        ofr_stlfsi4=OFR_STRESS_PREFERENCE_THRESHOLD - 0.01,
    )
    assert d.recommended_rail is CashRail.TOKENIZED_DEPOSIT


def test_zero_stress_does_not_fire_the_band() -> None:
    d = _eval(
        operation=_op(tokenized_deposit_supported=True),
        rails=_tokenized_rails(),
        ofr_stlfsi4=0.0,
    )
    assert d.recommended_rail is CashRail.TOKENIZED_DEPOSIT


# ---------------------------------------------------------------------------
# The three stress findings, closed
#
# Each of these reproduces a defect the adversarial probe found on 18 Aug 2026
# and asserts the behaviour that replaced it. The shape was the same in all
# three: a refusal this framework computes correctly, dropped at a boundary.
# ---------------------------------------------------------------------------


def _serviceable_op(notional: str = "5000000", **kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": Decimal(notional),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _deep_funding(obligation: str = "5000000") -> FundingState:
    return FundingState(
        Decimal("100000000000"), Decimal(obligation), Decimal("100000000000"), True
    )


# -- F1: capacity is part of check 6, and the ladder never asserts ----------


def test_a_capped_sole_rail_holds_rather_than_raising() -> None:
    """The defect: check 6 proved usability, the ladder additionally required
    capacity, and the code asserted that usability implied capacity. It does
    not. FedNow ships with a value cap, so a single-rail off-hours window
    above that cap reached an AssertionError instead of a decision - and an
    assertion is not a governance outcome, because it leaves no record.
    """
    rails = {
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, 7200, Decimal("1000000")
        )
    }
    decision = evaluate(
        operation=_serviceable_op(),
        funding=_deep_funding(),
        rails=rails,
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.NO_RAIL_IN_WINDOW
    assert "5000000" in decision.rationale


def test_a_capped_rail_is_still_used_when_the_operation_fits() -> None:
    """The fix must not turn a capped rail into an unusable one."""
    rails = {
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, 7200, Decimal("1000000")
        )
    }
    decision = evaluate(
        operation=_serviceable_op("500000"),
        funding=_deep_funding("500000"),
        rails=rails,
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.PROCEED
    assert decision.recommended_rail is CashRail.FEDNOW


def test_the_rail_ladder_has_no_unreachable_assertion() -> None:
    """A deliberate absence, marked so a reader finds the refusal.

    The ladder returns None where nothing is serviceable and the caller
    holds. Reintroducing an assertion here would restore a failure mode that
    produces no decision record.
    """
    import inspect

    from atreides.rails import cato_f

    source = inspect.getsource(cato_f._recommend_rail)
    # The comment explaining why the assertion was removed mentions it by
    # name, so test the executable lines rather than the prose.
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "raise AssertionError" not in code


def test_rail_fallback_does_not_depend_on_caller_dict_ordering() -> None:
    """Replay is the framework's central claim and it was conditional on how
    a caller happened to build a dictionary."""
    a = {
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.NSS_DTC_NSCC: RailState(
            CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200
        ),
    }
    b = {
        CashRail.NSS_DTC_NSCC: RailState(
            CashRail.NSS_DTC_NSCC, RailStatus.AVAILABLE, 7200
        ),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
    }
    first = evaluate(
        operation=_serviceable_op(), funding=_deep_funding(), rails=a, ofr_stlfsi4=0.0
    )
    second = evaluate(
        operation=_serviceable_op(), funding=_deep_funding(), rails=b, ofr_stlfsi4=0.0
    )
    assert first.recommended_rail is second.recommended_rail


# -- F2: a stress reading must be a number before it is compared -----------


@pytest.mark.parametrize("reading", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_stress_reading_is_named_and_held(reading: float) -> None:
    """The defect: every stress band is a comparison, and every comparison
    against NaN is False. So a broken feed did not fail one check - it
    satisfied all of them, skipped the escalate band, skipped the hold band,
    skipped the stress rail preference, and cleared. The most permissive
    outcome in the gate was reachable by the single most likely upstream
    defect.
    """
    decision = evaluate(
        operation=_serviceable_op(),
        funding=_deep_funding(),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=reading,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.STRESS_READING_UNUSABLE
    assert not decision.proceeds
    assert decision.recommended_rail is None


def test_an_unusable_reading_is_not_reported_as_observed_stress() -> None:
    """The distinction the new code exists to draw, and the one that made
    +inf change behaviour.

    SYSTEMIC_STRESS_ESCALATE asserts that stress was observed above a band.
    Infinity is a broken feed, not a market condition, and manufacturing an
    observation from it is the error this corpus refuses everywhere else.
    The cost is stated in the reason code's docstring: an operator who wants
    a broken feed to page somebody routes on this code.
    """
    decision = evaluate(
        operation=_serviceable_op(),
        funding=_deep_funding(),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=float("inf"),
    )
    assert decision.reason_code is not ReasonCode.SYSTEMIC_STRESS_ESCALATE


def test_finite_readings_are_unaffected_by_the_new_check() -> None:
    rails = {CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)}
    for reading, expected in (
        (-1.0, GateDecision.PROCEED),
        (0.0, GateDecision.PROCEED),
        (0.5, GateDecision.PROCEED),
        (0.6, GateDecision.HOLD),
        (1.0, GateDecision.HOLD),
        (1.5, GateDecision.ESCALATE),
    ):
        decision = evaluate(
            operation=_serviceable_op(),
            funding=_deep_funding(),
            rails=rails,
            ofr_stlfsi4=reading,
        )
        assert decision.decision is expected, reading


# -- F3: the funding model's refusal travels with its numbers -------------


def test_a_position_the_model_refused_to_assert_is_not_read_as_funded() -> None:
    """The defect: FundingState carries four scalars and no disposition, so a
    projection that explicitly declined to call the position funded handed
    the gate a large number and the gate read a large number as funded.
    """
    decision = evaluate(
        operation=_serviceable_op(),
        funding=FundingState(
            Decimal("100000000000"),
            Decimal("5000000"),
            Decimal("100000000000"),
            True,
            position_is_assertable=False,
        ),
        rails={CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)},
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.FUNDING_INDETERMINATE


def test_a_refused_position_is_distinct_from_a_short_one() -> None:
    """Two different findings with two different remedies. Collapsing them
    would lose the one that matters: 'short' is about the position, 'the
    model would not say' is about the evidence, and you do not fix the second
    by funding the account.
    """
    rails = {CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200)}
    short = evaluate(
        operation=_serviceable_op(),
        funding=FundingState(Decimal("0"), Decimal("5000000"), Decimal("0"), True),
        rails=rails,
        ofr_stlfsi4=0.0,
    )
    refused = evaluate(
        operation=_serviceable_op(),
        funding=FundingState(
            Decimal("100000000000"),
            Decimal("5000000"),
            Decimal("100000000000"),
            True,
            position_is_assertable=False,
        ),
        rails=rails,
        ofr_stlfsi4=0.0,
    )
    assert short.reason_code is ReasonCode.UNFUNDED_AT_SETTLEMENT_INSTANT
    assert refused.reason_code is ReasonCode.FUNDING_INDETERMINATE
    assert short.reason_code is not refused.reason_code


def test_a_hand_built_funding_state_still_asserts_its_position() -> None:
    """Constructing this object by hand IS the assertion. The default must
    not turn every existing caller into a hold.
    """
    state = FundingState(
        Decimal("100000000000"), Decimal("5000000"), Decimal("100000000000"), True
    )
    assert state.position_is_assertable is True


# ---------------------------------------------------------------------------
# Tier A: freshness and counterparty standing
#
# Two of the nine scenario families the stress probe had to report as
# NO_TARGET. They were NO_TARGET because there was no field to attack, not
# because the framework handled them.
# ---------------------------------------------------------------------------


def _fresh_rails() -> dict[CashRail, RailState]:
    return {
        CashRail.FEDWIRE: RailState(
            CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200, None, 60
        )
    }


_POLICY = FreshnessPolicy(
    max_stress_reading_age_seconds=3600,
    max_rail_state_age_seconds=300,
    max_counterparty_assessment_age_seconds=86400,
)


# -- freshness -------------------------------------------------------------


def test_with_no_policy_nothing_is_policed() -> None:
    """Stated rather than hidden: with no policy a reading from six months
    ago is accepted with the same standing as one from this second. The
    default preserves every existing caller, and the record says the check
    did not run."""
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.PROCEED
    assert ("freshness_policy", "not_stated") in decision.checks_evaluated


def test_a_stale_stress_reading_holds() -> None:
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=99_999,
        freshness_policy=_POLICY,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.MARKET_DATA_STALE
    assert "99999s old" in decision.rationale


def test_an_unknown_age_fails_a_stated_policy() -> None:
    """The NOT_ASSESSED rule applied to time. A firm that has decided
    freshness matters has not decided it matters only where the measurement
    is convenient."""
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
        freshness_policy=_POLICY,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.MARKET_DATA_STALE
    assert "never established" in decision.rationale


def test_a_fresh_reading_under_a_policy_proceeds() -> None:
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=60,
        freshness_policy=_POLICY,
    )
    assert decision.decision is GateDecision.PROCEED
    assert ("freshness_policy", "stated") in decision.checks_evaluated


def test_a_stale_rail_state_holds() -> None:
    """A rail recorded as open an hour ago is not a rail known to be open
    now."""
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails={
            CashRail.FEDWIRE: RailState(
                CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200, None, 7200
            )
        },
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=60,
        freshness_policy=_POLICY,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.MARKET_DATA_STALE
    assert "fedwire" in decision.rationale


def test_the_stale_rail_reported_does_not_depend_on_dict_order() -> None:
    """Determinism, on the same reasoning as the rail ladder."""
    stale = {
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200, None, 9999),
        CashRail.FEDWIRE: RailState(
            CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200, None, 9999
        ),
    }
    reordered = dict(reversed(list(stale.items())))
    first = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=stale,
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=60,
        freshness_policy=_POLICY,
    )
    second = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=reordered,
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=60,
        freshness_policy=_POLICY,
    )
    assert first.rationale == second.rationale


def test_a_policy_that_polices_nothing_polices_nothing() -> None:
    empty = FreshnessPolicy()
    assert empty.polices_anything is False
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
        freshness_policy=empty,
    )
    assert decision.decision is GateDecision.PROCEED


def test_a_non_positive_freshness_bound_is_refused() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        FreshnessPolicy(max_stress_reading_age_seconds=0)


# -- counterparty ----------------------------------------------------------


def _cp(standing: CounterpartyStanding, age: int | None = 3600) -> Counterparty:
    assessed = standing is not CounterpartyStanding.NOT_ASSESSED
    return Counterparty(
        counterparty_id="CP-1",
        standing=standing,
        provenance="credit file, 19 Aug 2026" if assessed else None,
        assessed_age_seconds=age if assessed else None,
    )


def test_no_counterparty_is_recorded_rather_than_assumed() -> None:
    """A gate that cannot tell 'no counterparty risk' from 'nobody mentioned
    a counterparty' is recording nothing useful about either."""
    decision = evaluate(
        operation=_serviceable_op("1000000"),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.PROCEED
    assert ("counterparty_standing", "not_supplied") in decision.checks_evaluated


def test_a_named_counterparty_with_no_standing_holds() -> None:
    """Naming one and leaving its standing unread is not the same as having
    no counterparty."""
    decision = evaluate(
        operation=_serviceable_op(
            "1000000", counterparty=_cp(CounterpartyStanding.NOT_ASSESSED)
        ),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.COUNTERPARTY_UNASSESSED


@pytest.mark.parametrize(
    "standing",
    [CounterpartyStanding.SUSPENDED, CounterpartyStanding.DEFAULTED],
)
def test_a_counterparty_out_of_good_standing_holds(
    standing: CounterpartyStanding,
) -> None:
    decision = evaluate(
        operation=_serviceable_op("1000000", counterparty=_cp(standing)),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.COUNTERPARTY_NOT_IN_GOOD_STANDING


def test_a_counterparty_under_review_escalates_rather_than_holds() -> None:
    """A review means somebody is already looking, and this operation is
    evidence for them rather than a decision the gate should take alone."""
    decision = evaluate(
        operation=_serviceable_op(
            "1000000", counterparty=_cp(CounterpartyStanding.UNDER_REVIEW)
        ),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.ESCALATE
    assert decision.reason_code is ReasonCode.COUNTERPARTY_UNDER_REVIEW


def test_a_counterparty_in_good_standing_proceeds() -> None:
    decision = evaluate(
        operation=_serviceable_op(
            "1000000", counterparty=_cp(CounterpartyStanding.IN_GOOD_STANDING)
        ),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.decision is GateDecision.PROCEED
    assert ("counterparty_standing", "in_good_standing") in decision.checks_evaluated


def test_counterparty_is_asked_before_funding() -> None:
    """The prior question. Whether the money is there does not arise if the
    answer to 'should we be facing them' is no, and asking in the other order
    would hold a defaulted name for a reason that was never the point."""
    decision = evaluate(
        operation=_serviceable_op(
            "1000000", counterparty=_cp(CounterpartyStanding.DEFAULTED)
        ),
        funding=FundingState(Decimal("0"), Decimal("1000000"), Decimal("0"), False),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
    )
    assert decision.reason_code is ReasonCode.COUNTERPARTY_NOT_IN_GOOD_STANDING


def test_a_stale_counterparty_assessment_holds() -> None:
    decision = evaluate(
        operation=_serviceable_op(
            "1000000", counterparty=_cp(CounterpartyStanding.IN_GOOD_STANDING, age=10**7)
        ),
        funding=_deep_funding("1000000"),
        rails=_fresh_rails(),
        ofr_stlfsi4=0.0,
        stress_reading_age_seconds=60,
        freshness_policy=_POLICY,
    )
    assert decision.decision is GateDecision.HOLD
    assert decision.reason_code is ReasonCode.MARKET_DATA_STALE
    assert "CP-1" in decision.rationale


def test_an_assessed_standing_requires_provenance() -> None:
    with pytest.raises(ValueError, match="requires provenance"):
        Counterparty(
            counterparty_id="CP-1", standing=CounterpartyStanding.IN_GOOD_STANDING
        )


def test_an_unassessed_counterparty_may_not_carry_an_assessment_date() -> None:
    with pytest.raises(ValueError, match="no assessment to date"):
        Counterparty(counterparty_id="CP-1", assessed_age_seconds=60)


def test_a_counterparty_standing_round_trips_from_a_plain_string() -> None:
    """Portability: an exported profile that cannot be read back in is not
    portable, and enum members arrive from JSON as plain strings."""
    coerced = Counterparty(
        counterparty_id="CP-1",
        standing="in_good_standing",  # type: ignore[arg-type]
        provenance="credit file",
    )
    assert coerced.standing is CounterpartyStanding.IN_GOOD_STANDING
