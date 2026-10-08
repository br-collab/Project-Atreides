"""WP-5 acceptance: reconciliation of entitlements against movement confirmations (ORDER SC-1).

Acceptance criteria, mapped:

- Known breaks classified: ``test_a_known_break_is_classified_and_holds`` (one case per
  classified code) and the depository-vocabulary cases for fails short, fails long and
  eligible-settled divergence.
- Unclassifiable break returns INDETERMINATE:
  ``test_an_unexplained_difference_is_unclassifiable_and_indeterminate`` and the cases for an
  entitlement that was refused, an elective event and an event with no computed entitlement.
- The result round trips through the DSOR store:
  ``test_a_reconciliation_record_round_trips_through_the_store``.

Every event, account and balance below is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from atreides.corporate_actions import (
    AccountReconciliation,
    CashMovement,
    CorporateActionBreakCode,
    CorporateActionEvent,
    CorporateActionEventRecord,
    CorporateActionReconciliation,
    EntitlementResult,
    EventDates,
    EventTerms,
    EventType,
    HolderPosition,
    MovementBalances,
    MovementReport,
    OptionType,
    Participation,
    ReconciliationBody,
    Release,
    SecuritiesMovement,
    SourceIdentity,
    compute_entitlements,
    decode_movement,
    encode_movement,
    reconcile,
    record_reconciliation,
    verify_reconciliation,
)
from atreides.corporate_actions import reconciliation as reconciliation_module
from atreides.dsor import DSORStore
from atreides.rails.cns import RecordDatePosition, SecuritiesBreakCode

D = Decimal
ISIN = "USSYNTHETIC0"
NOW = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)
DTC = SourceIdentity(source_id="DTC", reference="SYNTHETIC-CONF")
B = CorporateActionBreakCode


def event(
    event_type: EventType = EventType.CASH_DIVIDEND,
    terms: EventTerms | None = None,
    participation: Participation = Participation.MANDATORY,
) -> CorporateActionEvent:
    elective = participation is not Participation.MANDATORY
    return CorporateActionEvent(
        event_id="SYN-EVT-1", security_id=ISIN, event_type=event_type,
        participation=participation,
        dates=EventDates(announcement_date=date(2026, 10, 1), record_date=date(2026, 10, 15),
                         election_deadline=date(2026, 10, 20) if elective else None,
                         payable_date=date(2026, 10, 30)),
        terms=terms or EventTerms(cash_rate_per_share=D("0.25"), currency="USD"),
        provenance=Provenance.FACT_SYNTHETIC, source=DTC,
    )


CASH_EVENT = event()
STOCK_EVENT = event(EventType.STOCK_DIVIDEND, EventTerms(stock_rate_per_share=D("0.05")))


def holding(account: str, eligible: str, settled: str | None = None) -> HolderPosition:
    return HolderPosition(account_id=account, position=RecordDatePosition(
        ISIN, D(eligible), D(settled if settled is not None else eligible)))


def entitled(built: CorporateActionEvent, *holdings: HolderPosition) -> EntitlementResult:
    return compute_entitlements(built, holdings)


def confirmation(
    account: str = "ACCT-A",
    amount: str = "25",
    *,
    moved: CashMovement | SecuritiesMovement | None = None,
    balances: MovementBalances | None = None,
    **changes: Any,
) -> MovementReport:
    base: dict[str, Any] = {
        "stage": "confirmation", "event_id": "SYN-EVT-1", "event_type": EventType.CASH_DIVIDEND,
        "security_id": ISIN, "account_id": account, "option_id": "001",
        "option_type": OptionType.CASH,
        "balances": balances or MovementBalances(confirmed_balance=D(100)),
        "movement": moved or CashMovement(amount=D(amount), currency="USD"),
        "direction": "credit", "movement_date": date(2026, 10, 30),
        "provenance": Provenance.FACT_EXTERNAL, "source": DTC,
    }
    return MovementReport(**(base | changes))


def run(
    built: CorporateActionEvent, entitlement: EntitlementResult, *reports: MovementReport
) -> CorporateActionReconciliation:
    return reconcile(built, entitlement, reports, reconciled_at=NOW)


def account(result: CorporateActionReconciliation, account_id: str) -> AccountReconciliation:
    return next(a for a in result.accounts if a.account_id == account_id)


# --- matched ---------------------------------------------------------------------------------


def test_every_account_confirmed_as_entitled_passes() -> None:
    entitlement = entitled(CASH_EVENT, holding("ACCT-A", "100"), holding("ACCT-B", "40"))
    paid = (confirmation("ACCT-A", "25"), confirmation("ACCT-B", "10"))
    result = run(CASH_EVENT, entitlement, *paid)
    assert result.disposition is Disposition.PASS
    assert result.matched and result.break_codes == ()
    assert account(result, "ACCT-A").difference == 0
    assert result.reconciled_at == NOW and result.claim_label == "EXPERIMENTAL"


def test_partial_confirmations_are_summed() -> None:
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")),
                 confirmation(amount="10"), confirmation(amount="15"))
    assert result.matched
    assert account(result, "ACCT-A").confirmations == 2


def test_an_account_entitled_to_nothing_needs_no_confirmation() -> None:
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "0")))
    assert result.matched and account(result, "ACCT-A").confirmed is None


def test_shares_confirmed_as_entitled_pass() -> None:
    shares = confirmation(moved=SecuritiesMovement(security_id=ISIN, quantity=D(10)),
                          option_type=OptionType.SECU, event_type=EventType.STOCK_DIVIDEND)
    result = run(STOCK_EVENT, entitled(STOCK_EVENT, holding("ACCT-A", "200")), shares)
    assert result.disposition is Disposition.PASS


# --- known breaks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("built", "holdings", "reports", "code"),
    [
        (CASH_EVENT, [holding("ACCT-A", "100")], [], B.MISSING_CONFIRMATION),
        (CASH_EVENT, [], [confirmation()], B.UNEXPECTED_MOVEMENT),
        (CASH_EVENT, [holding("ACCT-A", "100")],
         [confirmation(moved=SecuritiesMovement(security_id=ISIN, quantity=D(25)))],
         B.WRONG_MOVEMENT_TYPE),
        (STOCK_EVENT, [holding("ACCT-A", "200")], [confirmation(amount="10")],
         B.WRONG_MOVEMENT_TYPE),
        (CASH_EVENT, [holding("ACCT-A", "100")],
         [confirmation(moved=CashMovement(amount=D(25), currency="EUR"))], B.CURRENCY_MISMATCH),
        (STOCK_EVENT, [holding("ACCT-A", "200")],
         [confirmation(moved=SecuritiesMovement(security_id="USSYNTHETIC9", quantity=D(10)))],
         B.SECURITY_MISMATCH),
        (CASH_EVENT, [holding("ACCT-A", "100")], [confirmation(direction="debit")],
         B.DEBIT_NOT_CREDIT),
        (CASH_EVENT, [holding("ACCT-A", "100")],
         [confirmation(amount="22.5", balances=MovementBalances(confirmed_balance=D(90)))],
         B.CONFIRMED_AGAINST_OTHER_BALANCE),
    ],
    ids=["missing", "unexpected", "cash-for-shares", "shares-for-cash", "currency", "security",
         "debit", "other-balance"],
)
@pytest.mark.requirement("SC-P-07")
def test_a_known_break_is_classified_and_holds(
    built: CorporateActionEvent, holdings: list[HolderPosition],
    reports: list[MovementReport], code: CorporateActionBreakCode,
) -> None:
    result = run(built, entitled(built, *holdings), *reports)
    assert code.value in result.break_codes
    assert result.disposition is Disposition.HOLD
    assert not result.matched


@pytest.mark.parametrize(
    ("balances", "code"),
    [
        (MovementBalances(confirmed_balance=D(100), pending_delivery_balance=D(10)),
         SecuritiesBreakCode.FAIL_TO_DELIVER),
        (MovementBalances(confirmed_balance=D(100), pending_receipt_balance=D(10)),
         SecuritiesBreakCode.FAIL_TO_RECEIVE),
        (MovementBalances(confirmed_balance=D(100), eligible_balance=D(100),
                          settlement_position_balance=D(90)),
         SecuritiesBreakCode.ELIGIBLE_SETTLED_DIVERGENCE),
    ],
    ids=["fails-short", "fails-long", "divergence"],
)
def test_the_depositorys_own_conditions_use_its_own_words(
    balances: MovementBalances, code: SecuritiesBreakCode
) -> None:
    """Reported even where the quantity matches: an open fail is a break in its own right."""
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")),
                 confirmation(balances=balances))
    assert result.break_codes == (code.value,)
    assert result.disposition is Disposition.HOLD
    assert account(result, "ACCT-A").difference == 0


def test_a_structural_break_is_not_also_a_quantity_break() -> None:
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")),
                 confirmation(moved=CashMovement(amount=D(30), currency="EUR")))
    assert account(result, "ACCT-A").break_codes == (B.CURRENCY_MISMATCH.value,)


# --- unclassifiable, and what cannot be reconciled at all -------------------------------------


@pytest.mark.parametrize(
    ("amount", "balances"),
    [
        ("24.99", MovementBalances(confirmed_balance=D(100))),
        ("26", MovementBalances(confirmed_balance=D(90))),
        ("24", MovementBalances(confirmed_balance=D(100), pending_receipt_balance=D(4))),
    ],
    ids=["short-a-cent", "neither-balance-explains-it", "open-fail-does-not-explain-it"],
)
def test_an_unexplained_difference_is_unclassifiable_and_indeterminate(
    amount: str, balances: MovementBalances
) -> None:
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")),
                 confirmation(amount=amount, balances=balances))
    assert B.UNCLASSIFIABLE.value in result.break_codes
    assert result.disposition is Disposition.INDETERMINATE
    assert account(result, "ACCT-A").difference == D(amount) - D(25)


def test_a_sub_cent_difference_is_not_assumed_to_be_rounding() -> None:
    """The entitlement is exact and unrounded (WP-2); the payment's rounding is not stated."""
    unrounded = event(terms=EventTerms(cash_rate_per_share=D("0.3333"), currency="USD"))
    result = run(unrounded, entitled(unrounded, holding("ACCT-A", "7")),
                 confirmation(amount="2.33", balances=MovementBalances(confirmed_balance=D(7))))
    assert result.break_codes == (B.UNCLASSIFIABLE.value,)


def test_a_refused_entitlement_is_not_reconciled() -> None:
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100", settled="90")),
                 confirmation())
    assert account(result, "ACCT-A").break_codes == (B.ENTITLEMENT_NOT_COMPUTED.value,)
    assert account(result, "ACCT-A").expected is None
    assert result.disposition is Disposition.INDETERMINATE


@pytest.mark.parametrize(
    ("built", "code"),
    [
        (event(participation=Participation.MANDATORY_WITH_CHOICE), B.ELECTIVE_EVENT),
        (event(EventType.MERGER, EventTerms()), B.ENTITLEMENT_NOT_COMPUTED),
    ],
)
def test_an_event_that_cannot_be_reconciled_says_why(
    built: CorporateActionEvent, code: CorporateActionBreakCode
) -> None:
    result = run(built, entitled(built, holding("ACCT-A", "100")), confirmation())
    assert result.break_codes == (code.value,)
    assert result.disposition is Disposition.INDETERMINATE
    assert result.accounts == () and result.unavailable


# --- wrong requests --------------------------------------------------------------------------


def test_a_reconciliation_compares_one_events_evidence() -> None:
    other = event().model_copy(update={"event_id": "SYN-EVT-2"})
    with pytest.raises(ValueError, match="entitlement is for another event"):
        run(CASH_EVENT, entitled(other, holding("ACCT-A", "100")))
    with pytest.raises(ValueError, match="is for another event"):
        run(CASH_EVENT, entitled(CASH_EVENT), confirmation(event_id="SYN-EVT-2"))
    advice = confirmation(stage="preliminary_advice", participation=Participation.MANDATORY,
                          default_option=True, balances=MovementBalances(eligible_balance=D(1)))
    with pytest.raises(ValueError, match="not advices"):
        run(CASH_EVENT, entitled(CASH_EVENT), advice)


def test_matched_means_no_breaks() -> None:
    with pytest.raises(ValidationError, match="matched account"):
        AccountReconciliation(account_id="A", expected=None, confirmed=None, difference=None,
                              confirmations=0, matched=False)
    good = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")), confirmation())
    with pytest.raises(ValidationError, match="matched reconciliation"):
        CorporateActionReconciliation.model_validate(good.model_dump() | {"matched": False})


# --- properties ------------------------------------------------------------------------------

_rows = st.lists(
    st.tuples(st.integers(0, 400), st.sampled_from(["25", "match", "missing", "debit"])),
    max_size=6,
)


def _scenario(rows: list[tuple[int, str]]) -> tuple[EntitlementResult, list[MovementReport]]:
    holdings, reports = [], []
    for i, (eligible, kind) in enumerate(rows):
        name = f"ACCT-{i:02d}"
        holdings.append(holding(name, str(eligible)))
        if kind == "missing":
            continue
        amount = kind if kind == "25" else str(D(eligible) * D("0.25"))
        reports.append(confirmation(
            name, amount, direction="debit" if kind == "debit" else "credit",
            balances=MovementBalances(confirmed_balance=D(eligible)),
        ))
    return entitled(CASH_EVENT, *holdings), reports


@given(rows=_rows, data=st.data())
def test_property_the_order_of_confirmations_does_not_matter(
    rows: list[tuple[int, str]], data: st.DataObject
) -> None:
    entitlement, reports = _scenario(rows)
    shuffled = data.draw(st.permutations(reports))
    assert run(CASH_EVENT, entitlement, *shuffled) == run(CASH_EVENT, entitlement, *reports)


@given(rows=_rows)
def test_property_the_disposition_follows_the_codes(rows: list[tuple[int, str]]) -> None:
    entitlement, reports = _scenario(rows)
    result = run(CASH_EVENT, entitlement, *reports)
    indeterminate = {B.UNCLASSIFIABLE.value, B.ENTITLEMENT_NOT_COMPUTED.value,
                     B.ELECTIVE_EVENT.value}
    if not result.break_codes:
        assert result.disposition is Disposition.PASS
    elif indeterminate & set(result.break_codes):
        assert result.disposition is Disposition.INDETERMINATE
    else:
        assert result.disposition is Disposition.HOLD
    for entry in result.accounts:
        if entry.matched:
            assert entry.difference in (None, 0)


# --- the DSOR record, and the whole path through the adapter ---------------------------------


def recorded() -> CorporateActionEventRecord:
    return record_reconciliation(
        CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100"), holding("ACCT-B", "40")),
        (confirmation("ACCT-A", "25", balances=MovementBalances(
            confirmed_balance=D(100), pending_receipt_balance=D(5))),),
        operation_id=UUID(int=500), recorded_at=NOW,
    )


def test_a_reconciliation_record_round_trips_through_the_store() -> None:
    record = recorded()
    assert isinstance(record.body, ReconciliationBody)
    assert record.body.result.break_codes == (
        SecuritiesBreakCode.FAIL_TO_RECEIVE.value, B.MISSING_CONFIRMATION.value,
    )
    with DSORStore(":memory:") as store:
        stored = store.append(record, dtg=NOW)
        assert stored.kind == "corporate_action_event"
        assert store.payload_bytes(stored.record_id) == record.model_dump_json().encode()
        replayed = store.replay(stored.record_id)
    assert isinstance(replayed, CorporateActionEventRecord)
    assert replayed == record
    assert verify_reconciliation(replayed) is True


def test_an_altered_reconciliation_record_does_not_verify() -> None:
    record = recorded()
    assert isinstance(record.body, ReconciliationBody)
    forged_result = record.body.result.model_copy(update={"disposition": Disposition.PASS})
    forged = record.model_copy(update={"body": record.body.model_copy(
        update={"result": forged_result})})
    assert verify_reconciliation(forged) is False


def test_only_a_reconciliation_record_is_verified() -> None:
    other = recorded().model_copy(update={"body": None})
    with pytest.raises(ValueError, match="not a reconciliation"):
        verify_reconciliation(other)


@pytest.mark.parametrize("release", list(Release))
def test_a_confirmation_read_from_iso_20022_reconciles(release: Release) -> None:
    """The adapter's real encoder and decoder between the depository's message and the
    comparison, so the reconciliation reads what the message says."""
    sent = confirmation(balances=MovementBalances(confirmed_balance=D(100)))
    received = decode_movement(encode_movement(sent, release).xml, release, "confirmation",
                               provenance=Provenance.FACT_EXTERNAL, source=DTC)
    result = run(CASH_EVENT, entitled(CASH_EVENT, holding("ACCT-A", "100")), received)
    assert result.disposition is Disposition.PASS


def test_docstring_states_experimental_and_no_consumer() -> None:
    text = " ".join((reconciliation_module.__doc__ or "").split())
    assert "EXPERIMENTAL" in text and "No agent consumes the result" in text
