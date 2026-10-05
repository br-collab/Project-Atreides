"""WP-2 acceptance: entitlement arithmetic (ORDER SC-1).

Acceptance criteria, mapped:

- Property tests (Hypothesis):
  - conservation: ``test_property_entitlement_is_conserved``;
  - non-negativity: ``test_property_no_entitlement_is_negative``;
  - order independence: ``test_property_input_order_does_not_change_the_result``.
- Unspecified treatment never returns a number:
  ``test_property_an_unspecified_treatment_never_returns_a_number`` and the named cases
  under "what is refused".

Every balance below is SYNTHETIC.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from atreides.corporate_actions import (
    COMPUTED_EVENT_TYPES,
    CorporateActionEvent,
    EntitlementResult,
    EventType,
    HolderEntitlement,
    HolderPosition,
    Participation,
    UnavailableTreatment,
    compute_entitlements,
)
from atreides.corporate_actions import entitlement as entitlement_module
from atreides.rails.cns import RecordDatePosition, absent_entitlement_treatment
from tests.corporate_actions.conftest import event

D = Decimal
SECURITY = "SYNTHETIC-XYZ"
NONE = D(0)


def cash(rate: str = "0.25") -> CorporateActionEvent:
    return event(cash_rate_per_share=D(rate), currency="USD")


def stock(rate: str = "0.05") -> CorporateActionEvent:
    return event(Participation.MANDATORY, EventType.STOCK_DIVIDEND, stock_rate_per_share=D(rate))


def split(new: int = 3, old: int = 2) -> CorporateActionEvent:
    return event(Participation.MANDATORY, EventType.SPLIT, split_new=new, split_old=old)


def holding(
    account: str,
    eligible: str,
    settled: str | None = None,
    *,
    pending_delivery_balance: Decimal = NONE,
    pending_receipt_balance: Decimal = NONE,
) -> HolderPosition:
    return HolderPosition(
        account_id=account,
        position=RecordDatePosition(
            SECURITY, D(eligible), D(settled if settled is not None else eligible),
            pending_delivery_balance=pending_delivery_balance,
            pending_receipt_balance=pending_receipt_balance,
        ),
    )


def by_account(result: EntitlementResult) -> dict[str, HolderEntitlement]:
    return {h.account_id: h for h in result.holders}


# --- worked examples (SYNTHETIC) -------------------------------------------------------------


def test_a_cash_dividend_is_rate_times_eligible_balance() -> None:
    result = compute_entitlements(cash(), [holding("A", "100"), holding("B", "1000")])
    assert result.disposition is Disposition.PASS
    assert result.unit == "cash" and result.currency == "USD"
    assert {a: h.quantity for a, h in by_account(result).items()} == {"A": D("25"), "B": D("250")}
    assert result.allocated_total == result.event_total == Fraction(275)
    assert result.residual == 0


def test_a_cash_amount_is_exact_and_unrounded() -> None:
    """The payment's rounding convention is not stated, so none is applied."""
    result = compute_entitlements(cash("0.3333"), [holding("A", "7")])
    assert by_account(result)["A"].quantity == D("2.3331")


def test_a_stock_dividend_distributes_whole_shares() -> None:
    result = compute_entitlements(stock("0.05"), [holding("A", "200")])
    assert by_account(result)["A"].quantity == D("10")
    assert result.unit == "shares" and result.currency is None
    assert result.disposition is Disposition.PASS


@pytest.mark.parametrize(
    ("new", "old", "eligible", "additional"),
    [(2, 1, "100", "100"), (3, 2, "200", "100"), (3, 1, "7", "14"), (4, 3, "99", "33")],
)
def test_a_forward_split_distributes_the_additional_shares(
    new: int, old: int, eligible: str, additional: str
) -> None:
    result = compute_entitlements(split(new, old), [holding("A", eligible)])
    assert by_account(result)["A"].quantity == D(additional)
    assert result.factor == Fraction(new - old, old)


# --- what is refused ------------------------------------------------------------------------


def test_a_fractional_share_has_no_number() -> None:
    result = compute_entitlements(stock("0.05"), [holding("A", "30"), holding("B", "200")])
    a, b = by_account(result)["A"], by_account(result)["B"]
    assert a.quantity is None and a.unavailable == (UnavailableTreatment.FRACTIONAL_SHARES,)
    assert b.quantity == D("10")
    assert result.disposition is Disposition.INDETERMINATE
    assert result.residual == Fraction(3, 2)
    assert result.allocated_total + result.residual == result.event_total  # type: ignore[operator]


def test_a_non_terminating_total_stays_exact() -> None:
    """A 4-for-3 split on 100 shares is 100/3 additional: fractional, and kept exact."""
    result = compute_entitlements(split(4, 3), [holding("A", "100")])
    assert by_account(result)["A"].quantity is None
    assert result.residual == result.event_total == Fraction(100, 3)
    assert '"event_total":"100/3"' in result.model_dump_json()
    assert EntitlementResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    ("position", "reasons"),
    [
        ({"eligible": "100", "settled": "90"}, [UnavailableTreatment.RECORD_DATE_DIVERGENCE]),
        ({"eligible": "100", "pending_delivery_balance": D(10)},
         [UnavailableTreatment.PENDING_DELIVERY_OR_RECEIPT]),
        ({"eligible": "100", "pending_receipt_balance": D(10)},
         [UnavailableTreatment.PENDING_DELIVERY_OR_RECEIPT]),
        ({"eligible": "100", "settled": "90", "pending_receipt_balance": D(10)},
         [UnavailableTreatment.RECORD_DATE_DIVERGENCE,
          UnavailableTreatment.PENDING_DELIVERY_OR_RECEIPT]),
    ],
)
def test_a_record_date_condition_without_a_stated_treatment_has_no_number(
    position: dict[str, Any], reasons: list[UnavailableTreatment]
) -> None:
    eligible, settled = position.pop("eligible"), position.pop("settled", None)
    result = compute_entitlements(cash(), [holding("A", eligible, settled, **position)])
    entitlement = by_account(result)["A"]
    assert entitlement.quantity is None
    assert list(entitlement.unavailable) == reasons
    assert entitlement.explanation == absent_entitlement_treatment(SECURITY)
    assert result.disposition is Disposition.INDETERMINATE
    assert result.residual == Fraction(25)


def test_a_short_holder_has_no_number() -> None:
    result = compute_entitlements(cash(), [holding("A", "-100")])
    entitlement = by_account(result)["A"]
    assert entitlement.quantity is None
    assert entitlement.unavailable == (UnavailableTreatment.SHORT_POSITION,)
    assert entitlement.explanation is None


@pytest.mark.parametrize("event_type", sorted(set(EventType) - COMPUTED_EVENT_TYPES))
def test_an_event_class_outside_the_computed_three_is_indeterminate(event_type: EventType) -> None:
    result = compute_entitlements(event(Participation.MANDATORY, event_type), [holding("A", "100")])
    assert result.disposition is Disposition.INDETERMINATE
    assert result.holders == () and result.factor is None
    assert result.event_total is None and result.allocated_total is None
    assert event_type.value in result.unavailable_rules[0]


def test_a_split_that_does_not_increase_the_position_is_indeterminate() -> None:
    result = compute_entitlements(split(1, 10), [holding("A", "100")])
    assert result.disposition is Disposition.INDETERMINATE
    assert "reverse split is not computed" in result.unavailable_rules[0]
    assert result.holders == ()


@pytest.mark.parametrize(
    ("built", "missing"),
    [
        (event(Participation.MANDATORY, EventType.CASH_DIVIDEND, split_new=2, split_old=1),
         ("terms.cash_rate_per_share",)),
        (event(Participation.MANDATORY, EventType.STOCK_DIVIDEND, split_new=2, split_old=1),
         ("terms.stock_rate_per_share",)),
        (event(Participation.MANDATORY, EventType.SPLIT, stock_rate_per_share=D("0.05")),
         ("terms.split_new", "terms.split_old")),
    ],
)
def test_an_unstated_term_holds_and_names_itself(
    built: CorporateActionEvent, missing: tuple[str, ...]
) -> None:
    result = compute_entitlements(built, [holding("A", "100")])
    assert result.disposition is Disposition.HOLD
    assert result.missing_inputs == missing
    assert result.holders == () and result.event_total is None


def test_no_holdings_is_a_zero_event() -> None:
    result = compute_entitlements(cash(), [])
    assert result.disposition is Disposition.PASS
    assert result.event_total == result.allocated_total == result.residual == 0


# --- requests that are wrong, not events that are unclear ------------------------------------


def test_an_account_appears_once() -> None:
    with pytest.raises(ValueError, match="more than once"):
        compute_entitlements(cash(), [holding("A", "1"), holding("A", "2")])


def test_a_holding_is_in_the_events_security() -> None:
    other = HolderPosition(account_id="A",
                           position=RecordDatePosition("SYNTHETIC-OTHER", D(1), D(1)))
    with pytest.raises(ValueError, match="not the event's security"):
        compute_entitlements(cash(), [other])


@pytest.mark.parametrize(
    "changes",
    [{"account_id": ""}, {"position": RecordDatePosition(SECURITY, 1.5, D(1))}],  # type: ignore[arg-type]
    ids=["unnamed", "float"],
)
def test_a_holding_is_named_and_exact(changes: dict[str, Any]) -> None:
    base: dict[str, Any] = {"account_id": "A", "position": RecordDatePosition(SECURITY, D(1), D(1))}
    with pytest.raises(ValidationError):
        HolderPosition(**(base | changes))


def test_a_holder_has_a_number_or_a_reason() -> None:
    with pytest.raises(ValidationError, match="never both"):
        HolderEntitlement(account_id="A", eligible_balance=D(1), quantity=None)
    with pytest.raises(ValidationError, match="never both"):
        HolderEntitlement(account_id="A", eligible_balance=D(1), quantity=D(1),
                          unavailable=(UnavailableTreatment.SHORT_POSITION,))
    with pytest.raises(ValidationError, match="never negative"):
        HolderEntitlement(account_id="A", eligible_balance=D(1), quantity=D(-1))


def test_a_result_cannot_state_unconserved_totals() -> None:
    good = compute_entitlements(cash(), [holding("A", "100")]).model_dump()
    with pytest.raises(ValidationError, match="must equal the event total"):
        EntitlementResult.model_validate(good | {"residual": Fraction(1)})
    with pytest.raises(ValidationError, match="all stated or none"):
        EntitlementResult.model_validate(good | {"residual": None})
    with pytest.raises(ValidationError, match="binary float"):
        EntitlementResult.model_validate(good | {"factor": 0.25})


# --- properties ------------------------------------------------------------------------------

_balance = st.decimals(min_value=-1000, max_value=100_000, places=0)
_positions = st.lists(
    st.tuples(_balance, st.booleans(), st.booleans()), max_size=8
).map(
    lambda rows: [
        HolderPosition(
            account_id=f"ACCT-{i:02d}",
            position=RecordDatePosition(
                SECURITY, eligible,
                eligible - D(1) if diverges else eligible,
                pending_receipt_balance=D(1) if pending else D(0),
            ),
        )
        for i, (eligible, diverges, pending) in enumerate(rows)
    ]
)
_events = st.one_of(
    st.decimals(min_value=0, max_value=10, places=4).map(lambda r: cash(str(r))),
    st.decimals(min_value=0, max_value=1, places=3).map(lambda r: stock(str(r))),
    st.tuples(st.integers(1, 12), st.integers(1, 12)).map(lambda t: split(*t)),
    st.sampled_from(sorted(set(EventType) - COMPUTED_EVENT_TYPES)).map(
        lambda t: event(Participation.MANDATORY, t)
    ),
)


@given(built=_events, holdings=_positions)
def test_property_entitlement_is_conserved(
    built: CorporateActionEvent, holdings: list[HolderPosition]
) -> None:
    result = compute_entitlements(built, holdings)
    if result.factor is None:
        return
    assert result.allocated_total is not None and result.residual is not None
    assert result.allocated_total + result.residual == result.event_total
    assert result.event_total == result.factor * sum(
        (Fraction(h.position.eligible_balance) for h in holdings), Fraction(0)
    )
    assert result.allocated_total == sum(
        (Fraction(h.quantity) for h in result.holders if h.quantity is not None), Fraction(0)
    )


@given(built=_events, holdings=_positions)
def test_property_no_entitlement_is_negative(
    built: CorporateActionEvent, holdings: list[HolderPosition]
) -> None:
    result = compute_entitlements(built, holdings)
    assert all(h.quantity is None or h.quantity >= 0 for h in result.holders)
    assert result.allocated_total is None or result.allocated_total >= 0


@given(built=_events, holdings=_positions, data=st.data())
def test_property_input_order_does_not_change_the_result(
    built: CorporateActionEvent, holdings: list[HolderPosition], data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(holdings))
    assert (
        compute_entitlements(built, shuffled).model_dump_json()
        == compute_entitlements(built, holdings).model_dump_json()
    )


@given(built=_events, holdings=_positions)
def test_property_an_unspecified_treatment_never_returns_a_number(
    built: CorporateActionEvent, holdings: list[HolderPosition]
) -> None:
    result = compute_entitlements(built, holdings)
    if built.event_type not in COMPUTED_EVENT_TYPES or result.factor is None:
        assert result.holders == () and result.event_total is None
        assert result.disposition is not Disposition.PASS
        return
    for entitlement in result.holders:
        position = next(h.position for h in holdings if h.account_id == entitlement.account_id)
        exact = result.factor * Fraction(position.eligible_balance)
        unspecified = (
            position.diverges
            or position.pending_receipt_balance != 0
            or position.eligible_balance < 0
            or (result.unit == "shares" and exact.denominator != 1)
        )
        if unspecified:
            assert entitlement.quantity is None and entitlement.unavailable
        else:
            assert entitlement.quantity is not None
            assert Fraction(entitlement.quantity) == exact
    clean = all(h.quantity is not None for h in result.holders)
    assert (result.disposition is Disposition.PASS) == clean


def test_docstring_states_experimental() -> None:
    assert "EXPERIMENTAL" in (entitlement_module.__doc__ or "")
