"""Reconciling entitlements against movement confirmations (ORDER SC-1, WP-5).

EXPERIMENTAL (charter section 18.6). A comparison, not a book of record, and
never a statement that a break has been resolved. No agent consumes the
result; it is a typed, DSOR-admissible record of what was compared and found.

WHAT IS COMPARED
----------------
For one mandatory event: what each account is entitled to
(:func:`~atreides.corporate_actions.entitlement.compute_entitlements`) against
what the depository confirmed it moved
(:class:`~atreides.corporate_actions.movement.MovementReport`, stage
``confirmation``). Elections change who receives what on an elective event, and
election outcomes are not reconciled here, so an elective event is
INDETERMINATE by name.

THE VOCABULARY, REUSED AND EXTENDED
-----------------------------------
The result speaks as :class:`~atreides.dsor.lifecycle_records.ReconciliationResultRecord`
does: ``matched``, ``break_codes`` and ``reconciled_at``, under the same rule
that a matched account names no break and an unmatched one names at least
one. That record is about a payment's status readback and has no event or
account, so it is extended here rather than reused.

Where the depository already has a word, it is the word used. Three break codes
are the equities rail's own (:class:`~atreides.rails.cns.SecuritiesBreakCode`):

- ``fail_to_deliver``: the confirmation carries a pending delivery balance
  (fails short);
- ``fail_to_receive``: it carries a pending receipt balance (fails long);
- ``eligible_settled_divergence``: its eligible and settlement position
  balances differ.

The others (:class:`CorporateActionBreakCode`) name corporate action
conditions the equities rail has no term for.

KNOWN, OR NOT CLASSIFIABLE
--------------------------
A break is classified only where its cause can be read from the evidence:
a missing or unexpected movement, the wrong currency, security, direction or
kind of movement, or a confirmation calculated against a different balance
(the confirmed quantity is exactly the event's factor times the balance the
depository confirmed against). A difference in quantity that none of those
explains is ``unclassifiable``, and the result is INDETERMINATE. That includes
a difference of a fraction of a cent: the payment's rounding convention is not
stated, so no tolerance is assumed. Open fails are reported as breaks; they
are not taken to explain a quantity difference, because their treatment is
not stated either.

DISPOSITION
-----------
The Atreides advisory convention
(:func:`~atreides.customer_protection.common.decide`): anything unclassifiable,
or an entitlement that could not be computed, is INDETERMINATE; a classified
break is HOLD; PASS means every account matched, and nothing more.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Literal

from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import field_validator, model_validator

from atreides.corporate_actions.entitlement import EntitlementResult
from atreides.corporate_actions.events import CorporateActionEvent
from atreides.corporate_actions.movement import CashMovement, MovementReport, SecuritiesMovement
from atreides.customer_protection.common import Frozen, decide
from atreides.customer_protection.rules.model import CLAIM_LABEL
from atreides.rails.cns import SecuritiesBreakCode

__all__ = [
    "AccountReconciliation",
    "CorporateActionBreakCode",
    "CorporateActionReconciliation",
    "reconcile",
]

ZERO = Decimal(0)


class CorporateActionBreakCode(StrEnum):
    """Corporate action breaks the equities rail's vocabulary has no term for."""

    MISSING_CONFIRMATION = "missing_confirmation"
    """An account is entitled to something and no movement was confirmed."""
    UNEXPECTED_MOVEMENT = "unexpected_movement"
    """A movement was confirmed for an account with no entitlement."""
    WRONG_MOVEMENT_TYPE = "wrong_movement_type"
    """Cash was confirmed where shares are owed, or the reverse."""
    CURRENCY_MISMATCH = "currency_mismatch"
    """Cash was confirmed in a currency other than the announced one."""
    SECURITY_MISMATCH = "security_mismatch"
    """Shares were confirmed in a security other than the event's."""
    DEBIT_NOT_CREDIT = "debit_not_credit"
    """A movement was confirmed as a debit where an entitlement is a credit."""
    CONFIRMED_AGAINST_OTHER_BALANCE = "confirmed_against_other_balance"
    """The confirmed quantity is the event's factor times the balance the depository
    confirmed against, and that balance is not the eligible balance entitled here."""
    ELECTIVE_EVENT = "elective_event"
    """The event is elective, and election outcomes are not reconciled here."""
    ENTITLEMENT_NOT_COMPUTED = "entitlement_not_computed"
    """The entitlement for this account was refused, so there is nothing to compare."""
    UNCLASSIFIABLE = "unclassifiable"
    """The quantities differ and nothing in the evidence says why."""


#: Codes that make the result INDETERMINATE rather than HOLD.
_INDETERMINATE: frozenset[str] = frozenset(
    {
        CorporateActionBreakCode.ELECTIVE_EVENT,
        CorporateActionBreakCode.ENTITLEMENT_NOT_COMPUTED,
        CorporateActionBreakCode.UNCLASSIFIABLE,
    }
)


class AccountReconciliation(Frozen):
    """One account: what it was entitled to, what was confirmed, and any break."""

    account_id: str
    #: The entitlement. ``None`` where it was refused or there is none.
    expected: Decimal | None
    #: The sum of confirmed movements. ``None`` where nothing was confirmed.
    confirmed: Decimal | None
    #: Confirmed less expected, where both are stated.
    difference: Decimal | None
    confirmations: int
    matched: bool
    break_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _matched_means_no_breaks(self) -> AccountReconciliation:
        if self.matched == bool(self.break_codes):
            raise ValueError("a matched account has no breaks; an unmatched one names them")
        return self


class CorporateActionReconciliation(Frozen):
    """Every account's reconciliation for one event, and the disposition."""

    engine: Literal["corporate_action_reconciliation"] = "corporate_action_reconciliation"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    event_id: str
    disposition: Disposition
    matched: bool
    #: Every code any account carries, plus any that stopped the event as a whole.
    break_codes: tuple[str, ...]
    #: Why the event as a whole could not be reconciled, where that is so.
    unavailable: tuple[str, ...] = ()
    accounts: tuple[AccountReconciliation, ...] = ()
    reconciled_at: datetime

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)

    @model_validator(mode="after")
    def _matched_means_no_breaks(self) -> CorporateActionReconciliation:
        if self.matched == bool(self.break_codes):
            raise ValueError("a matched reconciliation has no breaks; an unmatched one names them")
        return self


def _depository_conditions(report: MovementReport) -> list[str]:
    balances, codes = report.balances, []
    if balances.pending_delivery_balance:
        codes.append(SecuritiesBreakCode.FAIL_TO_DELIVER.value)
    if balances.pending_receipt_balance:
        codes.append(SecuritiesBreakCode.FAIL_TO_RECEIVE.value)
    if (
        balances.eligible_balance is not None
        and balances.settlement_position_balance is not None
        and balances.eligible_balance != balances.settlement_position_balance
    ):
        codes.append(SecuritiesBreakCode.ELIGIBLE_SETTLED_DIVERGENCE.value)
    return codes


def _movement_conditions(
    event: CorporateActionEvent, entitlement: EntitlementResult, report: MovementReport
) -> list[str]:
    codes = []
    movement = report.movement
    if report.direction != "credit":
        codes.append(CorporateActionBreakCode.DEBIT_NOT_CREDIT.value)
    if entitlement.unit == "cash":
        if not isinstance(movement, CashMovement):
            codes.append(CorporateActionBreakCode.WRONG_MOVEMENT_TYPE.value)
        elif movement.currency != entitlement.currency:
            codes.append(CorporateActionBreakCode.CURRENCY_MISMATCH.value)
    elif not isinstance(movement, SecuritiesMovement):
        codes.append(CorporateActionBreakCode.WRONG_MOVEMENT_TYPE.value)
    elif movement.security_id != event.security_id:
        codes.append(CorporateActionBreakCode.SECURITY_MISMATCH.value)
    return codes


def _account(
    account_id: str,
    event: CorporateActionEvent,
    entitlement: EntitlementResult,
    reports: list[MovementReport],
) -> AccountReconciliation:
    holder = next((h for h in entitlement.holders if h.account_id == account_id), None)
    confirmed = sum((r.quantity for r in reports), ZERO) if reports else None
    expected = None if holder is None else holder.quantity
    codes: list[str] = []
    if holder is not None and holder.quantity is None:
        codes.append(CorporateActionBreakCode.ENTITLEMENT_NOT_COMPUTED.value)
    elif holder is None:
        codes.append(CorporateActionBreakCode.UNEXPECTED_MOVEMENT.value)
    elif not reports:
        if expected:
            codes.append(CorporateActionBreakCode.MISSING_CONFIRMATION.value)
    else:
        structural = sorted(
            {c for r in reports for c in _movement_conditions(event, entitlement, r)}
        )
        codes.extend(structural)
        codes.extend(sorted({c for r in reports for c in _depository_conditions(r)}))
        if not structural and confirmed != expected:
            assert entitlement.factor is not None and holder is not None
            balances = {r.balances.confirmed_balance for r in reports}
            other = next(iter(balances)) if len(balances) == 1 else None
            if (
                other is not None
                and other != holder.eligible_balance
                and Fraction(confirmed or ZERO) == entitlement.factor * Fraction(other)
            ):
                codes.append(CorporateActionBreakCode.CONFIRMED_AGAINST_OTHER_BALANCE.value)
            else:
                codes.append(CorporateActionBreakCode.UNCLASSIFIABLE.value)
    difference = (
        None if confirmed is None or expected is None else confirmed - expected
    )
    return AccountReconciliation(
        account_id=account_id, expected=expected, confirmed=confirmed, difference=difference,
        confirmations=len(reports), matched=not codes, break_codes=tuple(codes),
    )


def reconcile(
    event: CorporateActionEvent,
    entitlement: EntitlementResult,
    confirmations: Sequence[MovementReport],
    *,
    reconciled_at: datetime,
) -> CorporateActionReconciliation:
    """Reconcile ``entitlement`` against ``confirmations``. Pure and independent of order.

    Raises ``ValueError`` where the entitlement or a confirmation belongs to another
    event, or a report is an advice rather than a confirmation: those are errors in
    the request, not breaks.
    """
    if entitlement.event_id != event.event_id:
        raise ValueError("the entitlement is for another event")
    for report in confirmations:
        if report.event_id != event.event_id:
            raise ValueError(f"a confirmation for account {report.account_id} is for another event")
        if report.stage != "confirmation":
            raise ValueError("only movement confirmations are reconciled, not advices")

    stopped: dict[str, str] = {}
    if event.participation.elective:
        stopped[CorporateActionBreakCode.ELECTIVE_EVENT.value] = (
            "the event is elective, and election outcomes are not reconciled here"
        )
    if entitlement.factor is None:
        stopped[CorporateActionBreakCode.ENTITLEMENT_NOT_COMPUTED.value] = (
            "the entitlement was not computed for this event"
        )
    if stopped:
        return CorporateActionReconciliation(
            event_id=event.event_id, disposition=decide(stopped.values(), (), ()),
            matched=False, break_codes=tuple(sorted(stopped)),
            unavailable=tuple(stopped.values()), reconciled_at=reconciled_at,
        )

    by_account: dict[str, list[MovementReport]] = {}
    for report in confirmations:
        by_account.setdefault(report.account_id, []).append(report)
    accounts = tuple(
        _account(account_id, event, entitlement, by_account.get(account_id, []))
        for account_id in sorted({h.account_id for h in entitlement.holders} | set(by_account))
    )
    codes = sorted({c for a in accounts for c in a.break_codes})
    return CorporateActionReconciliation(
        event_id=event.event_id,
        disposition=decide(
            [c for c in codes if c in _INDETERMINATE], (),
            [c for c in codes if c not in _INDETERMINATE],
        ),
        matched=not codes,
        break_codes=tuple(codes),
        accounts=accounts,
        reconciled_at=reconciled_at,
    )
