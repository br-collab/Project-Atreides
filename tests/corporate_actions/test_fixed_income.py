"""SC-1B WP-1: fixed income corporate actions end to end."""

import hashlib
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance

from atreides.corporate_actions.dtc_sources import MessageFamily, Release
from atreides.corporate_actions.entitlement import HolderPosition, compute_entitlements
from atreides.corporate_actions.events import (
    CorporateActionEvent,
    EventDates,
    EventTerms,
    EventType,
    OptionType,
    Participation,
    SourceIdentity,
)
from atreides.corporate_actions.iso20022 import PROFILES, decode_announcement, encode_announcement
from atreides.corporate_actions.movement import CashMovement, MovementBalances, MovementReport
from atreides.corporate_actions.reconciliation import reconcile
from atreides.rails.cns import RecordDatePosition

D = Decimal
ISIN = "US0000000001"
SOURCE = SourceIdentity(source_id="synthetic-dtc", reference="FIXED-1")
FIXED_TYPES = (
    EventType.INTEREST_PAYMENT,
    EventType.FINAL_MATURITY,
    EventType.PARTIAL_REDEMPTION,
    EventType.FULL_CALL,
    EventType.REDEMPTION_LOTTERY,
)
XSD_DIR = os.environ.get("DTC_CA_XSD_DIR")


def event(kind: EventType) -> CorporateActionEvent:
    terms = (
        EventTerms(interest_amount_per_face=D("0.0375"), currency="USD")
        if kind is EventType.INTEREST_PAYMENT
        else EventTerms(redemption_price_per_face=D("1.025"), currency="USD")
    )
    return CorporateActionEvent(
        event_id=f"FI-{kind.name.replace('_', '')[:13]}", security_id=ISIN, event_type=kind,
        participation=Participation.MANDATORY,
        dates=EventDates(
            announcement_date=date(2026, 10, 1), record_date=date(2026, 10, 10),
            payable_date=date(2026, 10, 20),
        ),
        terms=terms, provenance=Provenance.FACT_SYNTHETIC, source=SOURCE,
    )


def holding(face: str = "1000") -> HolderPosition:
    return HolderPosition(
        account_id="A1", quantity_basis="face_amount",
        position=RecordDatePosition(ISIN, D(face), D(face)),
    )


@pytest.mark.parametrize("kind", FIXED_TYPES)
def test_each_fixed_income_event_has_an_exact_face_amount_entitlement(kind: EventType) -> None:
    result = compute_entitlements(event(kind), [holding()])
    expected = D("37.5000") if kind is EventType.INTEREST_PAYMENT else D("1025.000")
    assert result.disposition is Disposition.PASS
    assert result.holders[0].quantity == expected
    assert result.currency == "USD" and result.unit == "cash"


@pytest.mark.parametrize("kind", FIXED_TYPES)
@pytest.mark.parametrize("release", list(Release))
def test_each_fixed_income_announcement_round_trips_at_both_releases(
    kind: EventType, release: Release
) -> None:
    original = event(kind)
    encoded = encode_announcement(original, release)
    decoded = decode_announcement(
        encoded.xml, release, provenance=Provenance.FACT_SYNTHETIC, source=SOURCE
    )
    assert decoded == original


@pytest.mark.skipif(not XSD_DIR, reason="DTC XSDs are external; set DTC_CA_XSD_DIR")
@pytest.mark.parametrize("kind", FIXED_TYPES)
@pytest.mark.parametrize("release", list(Release))
def test_each_fixed_income_announcement_validates_against_the_pinned_dtc_xsd(
    kind: EventType, release: Release
) -> None:
    etree = pytest.importorskip("lxml.etree")
    message = encode_announcement(event(kind), release)
    pin = PROFILES[(release, MessageFamily.ANNOUNCEMENT)].xsd
    path = Path(str(XSD_DIR)) / Path(pin.path_in_package).name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin.sha256
    schema = etree.XMLSchema(etree.parse(str(path)))
    assert schema.validate(etree.fromstring(message.xml)), schema.error_log.last_error


@pytest.mark.parametrize("kind", FIXED_TYPES)
@pytest.mark.requirement("SC-P-04")
def test_each_fixed_income_event_reconciles_to_its_confirmation(kind: EventType) -> None:
    original = event(kind)
    entitlement = compute_entitlements(original, [holding()])
    confirmation = MovementReport(
        stage="confirmation", event_id=original.event_id, event_type=kind,
        security_id=ISIN, account_id="A1", option_id="001", option_type=OptionType.CASH,
        balances=MovementBalances(confirmed_balance=D(1000)),
        movement=CashMovement(amount=entitlement.holders[0].quantity, currency="USD"),
        direction="credit", movement_date=date(2026, 10, 20),
        provenance=Provenance.FACT_SYNTHETIC, source=SOURCE,
    )
    result = reconcile(
        original, entitlement, [confirmation],
        reconciled_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    assert result.disposition is Disposition.PASS and result.matched


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        (EventType.INTEREST_PAYMENT, "interest_amount_per_face"),
        (EventType.FINAL_MATURITY, "redemption_price_per_face"),
        (EventType.PARTIAL_REDEMPTION, "redemption_price_per_face"),
        (EventType.FULL_CALL, "redemption_price_per_face"),
        (EventType.REDEMPTION_LOTTERY, "redemption_price_per_face"),
    ],
)
def test_an_unstated_fixed_income_term_never_returns_a_number(
    kind: EventType, missing: str
) -> None:
    result = compute_entitlements(
        event(kind).model_copy(update={"terms": EventTerms()}), [holding()]
    )
    assert result.disposition is Disposition.HOLD
    assert result.holders == () and missing in result.missing_inputs[0]


def test_fixed_income_refuses_a_unit_quantity_instead_of_treating_it_as_face_amount() -> None:
    with pytest.raises(ValueError, match="face amount quantity"):
        compute_entitlements(
            event(EventType.INTEREST_PAYMENT),
            [holding().model_copy(update={"quantity_basis": "units"})],
        )
