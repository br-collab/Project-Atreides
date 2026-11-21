"""Adapters that route observed street sources through the central books gate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from atreides.books.ledger import EquitiesBooks
from atreides.books.ps1 import (
    ControlBreak,
    SecuritiesConfirmation,
    build_securities_count,
    calendar_owner,
    reconcile,
)
from simulator.street import (
    ObservedSourceReader,
    ReconciliationCompletion,
    ReconciliationStatus,
    StreetBreak,
)


def reconcile_observed_street(
    books: EquitiesBooks,
    source_reader: ObservedSourceReader,
    prior_breaks: tuple[StreetBreak, ...] = (),
    *,
    as_of: date,
    item_id: str,
    failure_location: str,
) -> tuple[tuple[StreetBreak, ...], ReconciliationCompletion]:
    """Read an independent street source and use the central reconciliation gate."""
    source_names = ("Atreides equities books", source_reader.name)
    try:
        source = source_reader.read()
        confirmations = tuple(
            SecuritiesConfirmation(
                f"{source.name}:{position.issue}:{position.location}",
                source.as_of,
                position.issue,
                position.location,
                -position.quantity,
            )
            for position in source.positions
        )
        prior = tuple(
            ControlBreak(
                item_id,
                f"{item.issue}@{item.location}",
                item.books_quantity,
                item.street_quantity,
                item.difference,
                item.owner,
                item.opened_at,
                item.age_calendar_days,
                item.cause,
            )
            for item in prior_breaks
        )
        result = reconcile(
            item_id,
            books,
            build_securities_count(confirmations, as_of),
            as_of,
            prior_breaks=prior,
        )
        breaks = tuple(
            StreetBreak(
                issue=item.key.rsplit("@", 1)[0],
                location=item.key.rsplit("@", 1)[1],
                books_quantity=item.books_value,
                street_quantity=item.outside_value,
                difference=item.difference,
                owner=item.owner,
                opened_at=item.opened_at,
                age_calendar_days=item.age_calendar_days,
                cause=item.cause,
            )
            for item in result.breaks
        )
        return breaks, ReconciliationCompletion(
            item_id=item_id,
            close_date=as_of,
            sources_read=result.sources_read,
            break_count=len(breaks),
            status=ReconciliationStatus(result.status),
            error="reconciliation differences detected" if breaks else None,
        )
    except Exception as error:
        owner = calendar_owner(item_id)
        failure = StreetBreak(
            issue="RECONCILIATION",
            location=failure_location,
            books_quantity=Decimal(),
            street_quantity=Decimal(),
            difference=Decimal(),
            owner=owner,
            opened_at=as_of,
            age_calendar_days=0,
            cause="RECONCILIATION_FAILED",
        )
        return (failure,), ReconciliationCompletion(
            item_id=item_id,
            close_date=as_of,
            sources_read=source_names,
            break_count=1,
            status=ReconciliationStatus.FAILED,
            error=f"{type(error).__name__}: {error}",
        )
