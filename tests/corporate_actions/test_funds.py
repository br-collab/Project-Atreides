"""SC-1B WP-2: fund corporate actions end to end."""

import hashlib
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance

from atreides.corporate_actions.dtc_sources import MessageFamily, Release
from atreides.corporate_actions.election import ElectionBook, ElectionInstruction, ElectionPolicy
from atreides.corporate_actions.entitlement import HolderPosition, compute_entitlements
from atreides.corporate_actions.events import (
    CorporateActionEvent,
    ElectionOption,
    EventDates,
    EventTerms,
    EventType,
    OptionType,
    Participation,
    SourceIdentity,
)
from atreides.corporate_actions.iso20022 import PROFILES, decode_announcement, encode_announcement
from atreides.corporate_actions.movement import (
    CashMovement,
    MovementBalances,
    MovementReport,
    SecuritiesMovement,
)
from atreides.corporate_actions.reconciliation import reconcile
from atreides.rails.cns import RecordDatePosition

D = Decimal
ISIN = "US0000000001"
SOURCE = SourceIdentity(source_id="synthetic-dtc", reference="FUND-1")
FUND_TYPES = (
    EventType.CAPITAL_GAINS_DISTRIBUTION,
    EventType.CAPITAL_DISTRIBUTION,
    EventType.REINVESTMENT,
)
XSD_DIR = os.environ.get("DTC_CA_XSD_DIR")


def event(kind: EventType, *, elective: bool = False) -> CorporateActionEvent:
    participation = Participation.MANDATORY_WITH_CHOICE if elective else Participation.MANDATORY
    terms = (
        EventTerms(
            cash_rate_per_share=D("1.25"), reinvestment_price_per_share=D("12.50"),
            currency="USD",
        )
        if kind is EventType.REINVESTMENT
        else EventTerms(cash_rate_per_share=D("1.25"), currency="USD")
    )
    return CorporateActionEvent(
        event_id=f"FD-{kind.name.replace('_', '')[:13]}", security_id=ISIN,
        event_type=kind, participation=participation,
        dates=EventDates(
            announcement_date=date(2026, 10, 1), record_date=date(2026, 10, 10),
            election_deadline=date(2026, 10, 15) if elective else None,
            payable_date=date(2026, 10, 20),
        ),
        terms=EventTerms() if elective else terms,
        options=(
            (
                ElectionOption(option_id="001", description="cash", option_type=OptionType.CASH),
                ElectionOption(
                    option_id="002", description="reinvest", option_type=OptionType.SECU
                ),
            )
            if elective else ()
        ),
        default_option_id="001" if elective else None,
        provenance=Provenance.FACT_SYNTHETIC, source=SOURCE,
    )


def holding(shares: str = "100") -> HolderPosition:
    return HolderPosition(
        account_id="A1", position=RecordDatePosition(ISIN, D(shares), D(shares))
    )


@pytest.mark.parametrize("kind", FUND_TYPES)
def test_each_fund_event_has_an_exact_entitlement(kind: EventType) -> None:
    result = compute_entitlements(event(kind), [holding()])
    assert result.disposition is Disposition.PASS
    assert result.holders[0].quantity == D(10 if kind is EventType.REINVESTMENT else 125)
    assert result.unit == ("shares" if kind is EventType.REINVESTMENT else "cash")


@pytest.mark.parametrize("kind", FUND_TYPES)
@pytest.mark.parametrize("release", list(Release))
def test_each_fund_announcement_round_trips_at_both_releases(
    kind: EventType, release: Release
) -> None:
    original = event(kind)
    encoded = encode_announcement(original, release)
    assert decode_announcement(
        encoded.xml, release, provenance=Provenance.FACT_SYNTHETIC, source=SOURCE
    ) == original


@pytest.mark.skipif(not XSD_DIR, reason="DTC XSDs are external; set DTC_CA_XSD_DIR")
@pytest.mark.parametrize("kind", FUND_TYPES)
@pytest.mark.parametrize("release", list(Release))
def test_each_fund_announcement_validates_against_the_pinned_dtc_xsd(
    kind: EventType, release: Release
) -> None:
    etree = pytest.importorskip("lxml.etree")
    message = encode_announcement(event(kind), release)
    pin = PROFILES[(release, MessageFamily.ANNOUNCEMENT)].xsd
    path = Path(str(XSD_DIR)) / Path(pin.path_in_package).name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin.sha256
    schema = etree.XMLSchema(etree.parse(str(path)))
    assert schema.validate(etree.fromstring(message.xml)), schema.error_log.last_error


@pytest.mark.parametrize("kind", FUND_TYPES)
def test_each_fund_event_reconciles_to_its_confirmation(kind: EventType) -> None:
    original = event(kind)
    entitlement = compute_entitlements(original, [holding()])
    amount = entitlement.holders[0].quantity
    assert amount is not None
    report = MovementReport(
        stage="confirmation", event_id=original.event_id, event_type=kind,
        security_id=ISIN, account_id="A1", option_id="001", option_type=OptionType.CASH,
        balances=MovementBalances(confirmed_balance=D(100)),
        movement=(
            SecuritiesMovement(security_id=ISIN, quantity=amount)
            if kind is EventType.REINVESTMENT
            else CashMovement(amount=amount, currency="USD")
        ),
        direction="credit",
        movement_date=date(2026, 10, 20), provenance=Provenance.FACT_SYNTHETIC, source=SOURCE,
    )
    result = reconcile(
        original, entitlement, [report], reconciled_at=datetime(2026, 10, 20, tzinfo=UTC)
    )
    assert result.disposition is Disposition.PASS and result.matched


@pytest.mark.parametrize("kind", FUND_TYPES)
def test_elective_fund_distributions_use_the_existing_election_workflow(kind: EventType) -> None:
    original = event(kind, elective=True)
    instruction = ElectionInstruction(
        instruction_id="I-1", account_id="A1", option_id="002", quantity=D(100),
        received_date=date(2026, 10, 10), provenance=Provenance.HUMAN_JUDGMENT,
        source=SOURCE,
    )
    _, entry = ElectionBook(
        event=original, policy=ElectionPolicy(firm_lead_days=1)
    ).submit(instruction)
    assert entry.outcome == "accepted"


def test_reinvestment_without_a_price_is_indeterminate_and_never_returns_shares() -> None:
    missing = event(EventType.REINVESTMENT).model_copy(
        update={"terms": EventTerms(cash_rate_per_share=D("1.25"), currency="USD")}
    )
    result = compute_entitlements(missing, [holding()])
    assert result.disposition is Disposition.HOLD
    assert result.holders == ()
    assert result.missing_inputs == ("terms.reinvestment_price_per_share",)


def test_fractional_reinvestment_shares_are_indeterminate() -> None:
    result = compute_entitlements(event(EventType.REINVESTMENT), [holding("3")])
    assert result.disposition is Disposition.INDETERMINATE
    assert result.holders[0].quantity is None
