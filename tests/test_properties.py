"""Property-based tests - the invariants, over inputs nobody chose.

WHY THIS FILE EXISTS
--------------------
Every other test in this repository asserts a case somebody thought of. That
is necessary and it has a known blind spot: the cases an author thinks of
are the cases the author already had in mind while writing the code, so
example tests are correlated with the implementation in exactly the way that
makes them miss things.

This file asserts **invariants** instead - claims that must hold for every
input, not for the inputs I chose - and lets Hypothesis look for the
counterexample. Where an example test says "a queue is not a failure in this
scenario", a property here says "a queue is never a failure", and the
difference is that the second one can be wrong in a way I did not anticipate.

The properties chosen are not arbitrary. Each one is a doctrinal claim made
somewhere in the corpus, restated in a form a machine can attack:

- A queued payment is never a failed payment.
- A qualification never improves a disposition.
- Hard checks outrank soft ones, whatever else is true.
- Netting conserves quantity, and does not depend on trade order.
- What was allocated plus what remains is what was owed.
- Prioritisation loses no break and invents none.
- Unknown exposure outranks known cost.
- Time moves a determination in one direction only.
- Silence is never settlement, and never failure.
- A date the market never fixed is never derived from a clock.

A failure in this file is worth more than a failure anywhere else in the
suite, because it means a sentence in the doctrine is false rather than a
line of code being wrong.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from atreides.contracts.margin_impact import (
    CallWindow,
    IndeterminacyReason,
    MarginDirection,
    MarginDisposition,
    MarginImpact,
    Observability,
    absent_margin_assessment,
    margin_priority_rank,
    sort_by_margin_consequence,
)
from atreides.contracts.margin_profile import CollectionModel
from atreides.messaging.readback import (
    RECOGNISED_STATUS_CODES,
    ingest_readback,
    parse_status_report,
)
from atreides.rails.cato_f import (
    OFR_ESCALATE_THRESHOLD,
    CashRail,
    FundingState,
    GateDecision,
    OperationContext,
    RailState,
    RailStatus,
    ReasonCode,
    absent_gate_decision,
    evaluate,
)
from atreides.rails.cns import (
    CloseOutRegime,
    CNSDisposition,
    MarketProfile,
    ProcessingDateRule,
    SecuritiesBreakCode,
    net_positions,
    processing_date_offset,
    settle_net_position,
)
from atreides.rails.determination import (
    DeterminationOutcome,
    DeterminationProfile,
    RevocationForm,
    absent_determination_profile,
    classify_determination,
    obligation_finality_class,
)
from atreides.rails.finality import FinalityClass
from atreides.rails.funding_state import (
    CashFlow,
    FundingDisposition,
    FundingInputs,
    project_funding,
)

#: Example count comes from the active Hypothesis profile - see
#: ``tests/conftest.py``. Run ``pytest --hypothesis-profile=deep`` to hunt
#: rather than confirm.
SETTINGS = settings()

# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

money = st.decimals(
    min_value=Decimal("-1e9"),
    max_value=Decimal("1e9"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
positive_money = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1e9"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
offsets = st.integers(min_value=0, max_value=86_400)

flows = st.lists(
    st.builds(
        CashFlow,
        offset_seconds=offsets,
        amount=money,
        label=st.text(min_size=1, max_size=8),
        committed=st.booleans(),
    ),
    max_size=8,
).map(tuple)

#: Rail-level classes only. DETERMINATION_DEPENDENT is obligation-level and
#: has its own property below.
rail_finality = st.sampled_from(
    [f for f in FinalityClass if f is not FinalityClass.DETERMINATION_DEPENDENT]
)


@st.composite
def funding_inputs(draw, finality=None, determination=None):
    return FundingInputs(
        opening_position=draw(money),
        obligation=draw(positive_money),
        finality_class=draw(rail_finality if finality is None else finality),
        settlement_offset_seconds=draw(offsets),
        window_close_offset_seconds=draw(st.one_of(st.none(), offsets)),
        flows=draw(flows),
        net_debit_cap=draw(st.one_of(st.none(), positive_money)),
        clearing_fund_requirement=draw(positive_money),
        clearing_fund_posted=draw(positive_money),
        determination_outcome=draw(
            st.sampled_from(list(DeterminationOutcome))
            if determination is None
            else determination
        ),
    )


# --------------------------------------------------------------------------
# Funding: a queue is never a failure
# --------------------------------------------------------------------------


@SETTINGS
@given(funding_inputs())
def test_every_input_yields_a_disposition(inputs: FundingInputs) -> None:
    """Totality. There is no combination of inputs for which the model has
    no answer, which is what lets callers branch exhaustively."""
    assert isinstance(project_funding(inputs).disposition, FundingDisposition)


@SETTINGS
@given(funding_inputs())
def test_a_queue_is_never_a_failure(inputs: FundingInputs) -> None:
    """The doctrine the whole cash leg rests on, asserted over every input
    rather than over the scenarios somebody wrote down. Classifying a queue
    as a failure is the mechanism that produces duplicate payments."""
    projection = project_funding(inputs)
    if projection.disposition is FundingDisposition.WILL_QUEUE:
        assert projection.is_failure is False


@SETTINGS
@given(funding_inputs())
def test_settling_and_failing_are_mutually_exclusive(inputs: FundingInputs) -> None:
    projection = project_funding(inputs)
    assert not (projection.settles and projection.is_failure)


@SETTINGS
@given(funding_inputs())
def test_only_a_qualified_disposition_reports_qualified(
    inputs: FundingInputs,
) -> None:
    projection = project_funding(inputs)
    assert projection.qualified == (
        projection.disposition is FundingDisposition.FUNDED_QUALIFIED
    )


@SETTINGS
@given(funding_inputs())
def test_a_qualification_never_improves_a_disposition(inputs: FundingInputs) -> None:
    """A shortfall is a shortfall whether or not the venue can later cancel
    the contract. Qualifying an obligation may downgrade FUNDED, and must
    never turn a failure into anything else."""
    plain = project_funding(
        replace(inputs, determination_outcome=DeterminationOutcome.NOT_APPLICABLE)
    )
    qualified = project_funding(
        replace(inputs, determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED)
    )
    if plain.is_failure:
        assert qualified.is_failure
    if plain.disposition is FundingDisposition.WILL_QUEUE:
        assert qualified.disposition is FundingDisposition.WILL_QUEUE


@SETTINGS
@given(funding_inputs(finality=st.just(FinalityClass.DETERMINATION_DEPENDENT)))
def test_an_obligation_class_as_a_rail_class_is_always_refused(
    inputs: FundingInputs,
) -> None:
    """Never falls through to gross-final treatment, for any other input."""
    projection = project_funding(inputs)
    assert projection.disposition is FundingDisposition.INDETERMINATE
    assert "obligation-level" in projection.rationale


@SETTINGS
@given(funding_inputs())
def test_funding_is_deterministic(inputs: FundingInputs) -> None:
    a = project_funding(inputs)
    b = project_funding(inputs)
    assert a == b


@SETTINGS
@given(
    funding_inputs(
        determination=st.just(DeterminationOutcome.AWAITING_DETERMINATION)
    )
)
def test_an_undetermined_obligation_is_never_projected(
    inputs: FundingInputs,
) -> None:
    """No shortfall can be projected against an amount that is not yet a
    number, whatever the rail or the ladder says."""
    projection = project_funding(inputs)
    assert projection.disposition in {
        FundingDisposition.INDETERMINATE,
        FundingDisposition.CLEARING_FUND_DEFICIENT,
        FundingDisposition.CAP_BREACH,
    }
    assert projection.settles is False


# --------------------------------------------------------------------------
# Gate: hard checks outrank everything
# --------------------------------------------------------------------------


@st.composite
def gate_call(draw):
    operation = OperationContext(
        notional=draw(positive_money),
        currency="USD",
        is_material=draw(st.booleans()),
        is_lvps_material=draw(st.booleans()),
        is_fx_leg=draw(st.booleans()),
        pvp_available=draw(st.booleans()),
        correspondent_finality_resolvable=draw(st.booleans()),
        tokenized_deposit_supported=draw(st.booleans()),
        within_business_hours=draw(st.booleans()),
        determination_outcome=draw(st.sampled_from(list(DeterminationOutcome))),
    )
    funding = FundingState(
        projected_funded_position=draw(money),
        net_obligation=draw(positive_money),
        net_debit_cap_headroom=draw(money),
        clearing_fund_sufficient=draw(st.booleans()),
    )
    rails = {
        rail: RailState(
            rail,
            draw(st.sampled_from(list(RailStatus))),
            draw(st.one_of(st.none(), st.integers(-3600, 86400))),
        )
        for rail in draw(
            st.lists(st.sampled_from(list(CashRail)), min_size=1, unique=True)
        )
    }
    return operation, funding, rails, draw(st.floats(-1.0, 3.0, allow_nan=False))


@SETTINGS
@given(gate_call())
def test_the_gate_always_decides(call) -> None:
    operation, funding, rails, stress = call
    decision = evaluate(
        operation=operation, funding=funding, rails=rails, ofr_stlfsi4=stress
    )
    assert isinstance(decision.decision, GateDecision)
    assert decision.rationale


@SETTINGS
@given(gate_call())
def test_systemic_stress_outranks_every_other_condition(call) -> None:
    """Check order is doctrine, not optimisation. Above the escalation band
    the gate escalates whatever else is true of the operation."""
    operation, funding, rails, _stress = call
    decision = evaluate(
        operation=operation,
        funding=funding,
        rails=rails,
        ofr_stlfsi4=OFR_ESCALATE_THRESHOLD + 0.5,
    )
    assert decision.decision is GateDecision.ESCALATE
    assert decision.reason_code is ReasonCode.SYSTEMIC_STRESS_ESCALATE


@SETTINGS
@given(gate_call())
def test_proceeding_always_names_a_usable_rail(call) -> None:
    """A PROCEED with no rail, or with the reserved placeholder, would be a
    decision nobody can act on."""
    operation, funding, rails, stress = call
    decision = evaluate(
        operation=operation, funding=funding, rails=rails, ofr_stlfsi4=stress
    )
    if decision.proceeds:
        assert decision.recommended_rail is not None
        assert decision.recommended_rail is not CashRail.PORTS_WHOLESALE
        assert decision.finality_class is not None


@SETTINGS
@given(gate_call())
def test_an_obligation_class_never_leaks_into_the_rail_class(call) -> None:
    """The two fields mean different things and a record that confuses them
    is unreplayable."""
    operation, funding, rails, stress = call
    decision = evaluate(
        operation=operation, funding=funding, rails=rails, ofr_stlfsi4=stress
    )
    assert decision.finality_class is not FinalityClass.DETERMINATION_DEPENDENT
    if decision.obligation_finality_class is not None:
        assert (
            decision.obligation_finality_class
            is FinalityClass.DETERMINATION_DEPENDENT
        )


@SETTINGS
@given(st.text(max_size=40))
def test_the_absent_gate_default_is_always_hold(reason: str) -> None:
    decision = absent_gate_decision(reason) if reason else absent_gate_decision()
    assert decision.decision is GateDecision.HOLD
    assert decision.proceeds is False


# --------------------------------------------------------------------------
# Determination: time moves one way
# --------------------------------------------------------------------------


@st.composite
def determination_call(draw):
    form = draw(st.sampled_from(list(RevocationForm)))
    assessed = form is not RevocationForm.NOT_ASSESSED
    profile = DeterminationProfile(
        venue_id="V",
        revocation_form=form,
        qualification_window_seconds=(
            draw(st.one_of(st.none(), st.integers(1, 100_000))) if assessed else None
        ),
        provenance="property test" if assessed else None,
    )
    return (
        profile,
        draw(st.booleans()),
        draw(st.booleans()),
        draw(st.one_of(st.none(), st.integers(0, 200_000))),
    )


@SETTINGS
@given(determination_call())
def test_classification_is_total_and_maps_to_a_decided_class(call) -> None:
    profile, contingent, determined, elapsed = call
    outcome = classify_determination(
        profile=profile,
        instrument_is_contingent=contingent,
        determined=determined,
        seconds_since_determination=elapsed,
    )
    assert isinstance(outcome, DeterminationOutcome)
    result = obligation_finality_class(outcome)
    assert result is None or result is FinalityClass.DETERMINATION_DEPENDENT


@SETTINGS
@given(st.booleans(), st.one_of(st.none(), st.integers(0, 200_000)))
def test_an_unread_rulebook_never_reads_as_clean(
    contingent: bool, elapsed: int | None
) -> None:
    """An unassessed venue can never produce UNQUALIFIED. That is the
    property that stops an unread venue passing as a safe one."""
    outcome = classify_determination(
        profile=absent_determination_profile("V"),
        instrument_is_contingent=contingent,
        determined=True,
        seconds_since_determination=elapsed,
    )
    assert outcome is not DeterminationOutcome.UNQUALIFIED


@SETTINGS
@given(st.integers(1, 100_000), st.integers(0, 200_000), st.integers(0, 200_000))
def test_qualification_is_monotone_in_elapsed_time(
    window: int, first: int, second: int
) -> None:
    """Time moves a determination in one direction only. Once a stated window
    has elapsed the position is unqualified, and more time never puts it
    back."""
    assume(first <= second)
    profile = DeterminationProfile(
        venue_id="V",
        revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
        qualification_window_seconds=window,
        provenance="property test",
    )

    def at(elapsed: int) -> DeterminationOutcome:
        return classify_determination(
            profile=profile,
            instrument_is_contingent=True,
            determined=True,
            seconds_since_determination=elapsed,
        )

    if at(first) is DeterminationOutcome.UNQUALIFIED:
        assert at(second) is DeterminationOutcome.UNQUALIFIED


@SETTINGS
@given(st.integers(0, 200_000))
def test_an_unbounded_window_never_expires(elapsed: int) -> None:
    """However long anyone waits. This is the answer to the duration
    question, expressed as something a machine can falsify."""
    outcome = classify_determination(
        profile=DeterminationProfile(
            venue_id="V",
            revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
            provenance="property test",
        ),
        instrument_is_contingent=True,
        determined=True,
        seconds_since_determination=elapsed,
    )
    assert outcome is DeterminationOutcome.QUALIFIED_UNBOUNDED


# --------------------------------------------------------------------------
# Netting: quantity is conserved and order does not matter
# --------------------------------------------------------------------------

trades = st.lists(
    st.tuples(st.sampled_from(["SEC-A", "SEC-B", "SEC-C"]), money),
    max_size=12,
).map(tuple)


@SETTINGS
@given(trades)
def test_netting_conserves_quantity(trade_list) -> None:
    """Whatever went in comes out, per security. A netting engine that
    creates or destroys quantity is the worst class of bug in this domain
    because it reconciles to nothing."""
    positions = net_positions(
        trade_list, market_id="X", settlement_date_offset_days=1
    )
    for position in positions:
        expected = sum(
            (q for s, q in trade_list if s == position.security_id), Decimal(0)
        )
        assert position.quantity == expected


@SETTINGS
@given(trades)
def test_netting_is_order_independent(trade_list) -> None:
    forward = net_positions(trade_list, market_id="X", settlement_date_offset_days=1)
    backward = net_positions(
        tuple(reversed(trade_list)), market_id="X", settlement_date_offset_days=1
    )
    assert forward == backward


@SETTINGS
@given(trades)
def test_every_trade_is_accounted_for(trade_list) -> None:
    positions = net_positions(
        trade_list, market_id="X", settlement_date_offset_days=1
    )
    assert sum(p.constituent_trade_count for p in positions) == len(trade_list)


@SETTINGS
@given(money, st.one_of(st.none(), money), st.booleans(), st.booleans())
def test_allocated_plus_residual_is_what_was_owed(
    quantity: Decimal,
    allocated: Decimal | None,
    published: bool,
    spans: bool,
) -> None:
    """The conservation law of the settlement side. If this ever fails, a
    residual has been dropped or invented."""
    position = net_positions(
        (("SEC-A", quantity),), market_id="X", settlement_date_offset_days=1
    )[0]
    profile = MarketProfile(
        market_id="X",
        settlement_cycle_days=1,
        close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
        close_out_deadline_days=3,
        allocation_rule_published=published,
        provenance="property test",
    )
    result = settle_net_position(
        position, profile, allocated_quantity=allocated, spans_record_date=spans
    )
    if result.disposition is CNSDisposition.INDETERMINATE:
        assert allocated is None
        return
    residual = result.residual.quantity if result.residual else Decimal(0)
    assert result.allocated_quantity + residual == position.quantity


@SETTINGS
@given(money, st.one_of(st.none(), money))
def test_completion_and_residuals_are_mutually_exclusive(
    quantity: Decimal, allocated: Decimal | None
) -> None:
    position = net_positions(
        (("SEC-A", quantity),), market_id="X", settlement_date_offset_days=1
    )[0]
    result = settle_net_position(
        position, MarketProfile(market_id="X"), allocated_quantity=allocated
    )
    if result.completed:
        assert result.residual is None
        assert result.is_fail is False


@SETTINGS
@given(money)
def test_an_unreported_outcome_is_never_a_settlement(quantity: Decimal) -> None:
    """Silence is never settlement, on the securities side as on the cash
    side."""
    position = net_positions(
        (("SEC-A", quantity),), market_id="X", settlement_date_offset_days=1
    )[0]
    result = settle_net_position(
        position, MarketProfile(market_id="X"), allocated_quantity=None
    )
    assert result.disposition is CNSDisposition.INDETERMINATE
    assert result.completed is False


@SETTINGS
@given(money, st.one_of(st.none(), money), st.integers(0, 5))
def test_a_message_determined_date_is_never_derived_from_a_clock(
    quantity: Decimal, allocated: Decimal | None, offset: int
) -> None:
    """On a market that fixes its processing date by a session-closure
    message, no combination of quantity, allocation or settlement offset
    produces a processing date. The date arrives from the market or it does
    not arrive - the framework never computes its way to one."""
    position = net_positions(
        (("SEC-A", quantity),),
        market_id="X",
        settlement_date_offset_days=offset,
    )[0]
    profile = MarketProfile(
        market_id="X",
        settlement_cycle_days=1,
        close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
        close_out_deadline_days=3,
        processing_date_rule=ProcessingDateRule.SESSION_CLOSURE_MESSAGE,
        session_closure_message="property test message",
        provenance="property test",
    )
    assert processing_date_offset(profile, position) is None
    result = settle_net_position(position, profile, allocated_quantity=allocated)
    assert SecuritiesBreakCode.PROCESSING_DATE_NOT_ESTABLISHED in {
        b.code for b in result.breaks
    }


@SETTINGS
@given(
    st.sampled_from(list(ProcessingDateRule)),
    st.one_of(st.none(), st.integers(0, 5)),
)
def test_only_a_read_fixed_cycle_dates_settlement_from_the_trade_date(
    rule: ProcessingDateRule, cycle: int | None
) -> None:
    """An unread rule must never read the same as a fixed cycle. This is the
    collapse the field was added to prevent, asserted over every combination
    rather than the two somebody wrote a test for."""
    profile = MarketProfile(
        market_id="X",
        settlement_cycle_days=cycle,
        close_out_regime=CloseOutRegime.NONE_PUBLISHED,
        processing_date_rule=rule,
        session_closure_message=(
            "property test message"
            if rule is ProcessingDateRule.SESSION_CLOSURE_MESSAGE
            else None
        ),
        provenance="property test",
    )
    expected = (
        rule is ProcessingDateRule.FIXED_CYCLE_FROM_TRADE_DATE and cycle is not None
    )
    assert profile.settlement_date_follows_from_trade_date is expected


# --------------------------------------------------------------------------
# Prioritisation: nothing lost, nothing invented
# --------------------------------------------------------------------------


@st.composite
def margin_impacts(draw):
    disposition = draw(st.sampled_from(list(MarginDisposition)))
    direction = {
        MarginDisposition.UNDER_COLLATERALIZED: MarginDirection.OWED_TO_VENUE,
        MarginDisposition.OVER_COLLATERALIZED: MarginDirection.OWED_TO_FIRM,
        MarginDisposition.NO_MARGIN_EFFECT: MarginDirection.NEUTRAL,
    }.get(disposition, draw(st.sampled_from(list(MarginDirection))))
    quantified = disposition in {
        MarginDisposition.UNDER_COLLATERALIZED,
        MarginDisposition.OVER_COLLATERALIZED,
        MarginDisposition.CALL_WINDOW_CLOSED,
    }
    window_open = draw(st.booleans())
    needs_window = disposition is MarginDisposition.CALL_WINDOW_CLOSED
    window = None
    if needs_window or draw(st.booleans()):
        window = CallWindow(
            collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
            is_open=False if needs_window else window_open,
            closes_at_offset_seconds=7200 if (not needs_window and window_open) else None,
            reopens_at_offset_seconds=(
                3600 if (needs_window or not window_open) else None
            ),
        )
    return MarginImpact(
        disposition=disposition,
        direction=direction,
        indeterminacy=(
            draw(
                st.sampled_from(
                    [r for r in IndeterminacyReason
                     if r is not IndeterminacyReason.NOT_APPLICABLE]
                )
            )
            if disposition is MarginDisposition.INDETERMINATE
            else IndeterminacyReason.NOT_APPLICABLE
        ),
        observability=(
            Observability.OBSERVED
            if quantified
            else draw(st.sampled_from(list(Observability)))
        ),
        collateral_observability=draw(st.sampled_from(list(Observability))),
        materiality_threshold=Decimal("1"),
        call_window=window,
        venue=draw(st.text(min_size=1, max_size=4)),
        basis="property test",
    )


@SETTINGS
@given(st.lists(margin_impacts(), max_size=25).map(tuple))
def test_prioritisation_loses_nothing_and_invents_nothing(impacts) -> None:
    """A queue that silently drops a break is worse than an unsorted one."""
    ordered = sort_by_margin_consequence(impacts)
    assert len(ordered) == len(impacts)
    assert sorted(map(id, ordered)) == sorted(map(id, impacts))


@SETTINGS
@given(st.lists(margin_impacts(), max_size=25).map(tuple))
def test_prioritisation_is_ordered_and_idempotent(impacts) -> None:
    ordered = sort_by_margin_consequence(impacts)
    ranks = [margin_priority_rank(i) for i in ordered]
    assert ranks == sorted(ranks)
    assert sort_by_margin_consequence(ordered) == ordered


@SETTINGS
@given(st.text(min_size=1, max_size=4), st.text(min_size=1, max_size=4))
def test_unknown_exposure_always_outranks_known_cost(
    venue_a: str, venue_b: str
) -> None:
    """An operator can plan around a quantified over-collateralisation and
    cannot plan around a position nobody can observe. Asserted as an ordering
    law rather than as one example.

    Built directly rather than filtered: generating pairs and discarding the
    ones that do not match would throw away 98% of them, which distorts the
    distribution and tests less than it appears to.
    """
    unknown = MarginImpact(
        disposition=MarginDisposition.INDETERMINATE,
        direction=MarginDirection.UNKNOWN,
        observability=Observability.UNOBSERVABLE,
        collateral_observability=Observability.UNOBSERVABLE,
        indeterminacy=IndeterminacyReason.VENUE_PUBLISHES_NOTHING,
        venue=venue_a,
        basis="property test",
    )
    known_cost = MarginImpact(
        disposition=MarginDisposition.OVER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_FIRM,
        observability=Observability.OBSERVED,
        collateral_observability=Observability.OBSERVED,
        venue=venue_b,
        basis="property test",
    )
    assert margin_priority_rank(unknown) < margin_priority_rank(known_cost)


@SETTINGS
@given(margin_impacts())
def test_an_in_cycle_call_always_leads_the_queue(impact) -> None:
    """Priority tracks what can be acted on and how fast the window closes,
    so nothing outranks a call with a hard deadline today."""
    in_cycle = MarginImpact(
        disposition=MarginDisposition.UNDER_COLLATERALIZED,
        direction=MarginDirection.OWED_TO_VENUE,
        observability=Observability.OBSERVED,
        collateral_observability=Observability.OBSERVED,
        call_window=CallWindow(
            collection_model=CollectionModel.TRADITIONAL_HOURS_ONLY,
            is_open=True,
            closes_at_offset_seconds=3600,
        ),
        basis="property test",
    )
    assert margin_priority_rank(in_cycle) <= margin_priority_rank(impact)


@SETTINGS
@given(st.text(max_size=40))
def test_the_absent_assessment_is_never_margin_neutral(reason: str) -> None:
    impact = absent_margin_assessment(reason) if reason else absent_margin_assessment()
    assert impact.disposition is MarginDisposition.INDETERMINATE
    assert impact.disposition is not MarginDisposition.NO_MARGIN_EFFECT
    assert impact.escalates


# --------------------------------------------------------------------------
# Readback: every block the venue sent is accounted for
# --------------------------------------------------------------------------

_NS = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16"

status_codes = st.sampled_from(
    [*RECOGNISED_STATUS_CODES, "ZZZZ", "XXXX", "AB12"]
)
#: Alphanumerics and a hyphen only. The first version of this used a
#: codepoint range that included "<", which produced invalid XML and made the
#: parser raise a document-level error - correctly. Worth recording: the
#: generator reached for a character no hand-written fixture ever would,
#: inside a minute.
identifiers = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", min_size=1, max_size=12
)


@st.composite
def status_entries(draw):
    """Entry blocks, including deliberately unusable ones.

    The generator is allowed to emit entries with no status and entries with
    no identifier, because those are schema-valid and the parser's handling
    of them is the behaviour under test.
    """
    has_status = draw(st.booleans())
    has_e2e = draw(st.booleans())
    has_txid = draw(st.booleans())
    parts = ["<TxInfAndSts>"]
    e2e = draw(identifiers) if has_e2e else None
    if e2e:
        parts.append(f"<OrgnlEndToEndId>{e2e}</OrgnlEndToEndId>")
    if has_txid:
        parts.append(f"<OrgnlTxId>{draw(identifiers)}</OrgnlTxId>")
    code = draw(status_codes) if has_status else None
    if code:
        parts.append(f"<TxSts>{code}</TxSts>")
    parts.append("</TxInfAndSts>")
    return "".join(parts), (code is not None and (has_e2e or has_txid))


@st.composite
def status_reports(draw):
    entries = draw(st.lists(status_entries(), max_size=8))
    body = "".join(block for block, _usable in entries)
    xml = (
        f'<Document xmlns="{_NS}"><FIToFIPmtStsRpt>'
        "<GrpHdr><MsgId>M</MsgId><CreDtTm>2026-08-14T13:00:00Z</CreDtTm></GrpHdr>"
        f"{body}</FIToFIPmtStsRpt></Document>"
    )
    return xml.encode(), len(entries)


@SETTINGS
@given(status_reports())
def test_no_status_entry_is_ever_silently_dropped(report) -> None:
    """The property the partial-batch fix exists to guarantee. Whatever mix
    of readable and unreadable entries a venue sends, the count coming out
    equals the count going in - a count that silently shrinks is worse than
    a finding."""
    payload, sent = report
    parsed = parse_status_report(payload)
    assert parsed.entry_count == sent
    assert len(parsed.entries) + len(parsed.malformed) == sent


@SETTINGS
@given(status_reports())
def test_a_document_level_valid_report_never_raises(report) -> None:
    """Entry-level problems are collected, never raised. If this fails, one
    bad record can again cost an operator a whole venue file."""
    payload, _sent = report
    parse_status_report(payload)


@SETTINGS
@given(status_reports())
def test_reconciling_against_nothing_prepared_matches_nothing(report) -> None:
    """Atreides never submits, so with no prepared work every readable entry
    is unsolicited and none of them can match."""
    payload, _sent = report
    match = ingest_readback(payload, ())
    assert match.matched == {}
    assert match.settled_ids == ()


@SETTINGS
@given(status_reports())
def test_parsing_is_deterministic(report) -> None:
    payload, _sent = report
    assert parse_status_report(payload) == parse_status_report(payload)
