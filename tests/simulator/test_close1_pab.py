"""CLOSE-1 WP5: PAB activity through the real books and the real PAB reserve.

17 CFR 240.15c3-3(e)(1), as the PAB computation is applied in
atreides/customer_protection/reserve.py: the PAB Reserve Bank Account computation
is made with the same Exhibit A formula, PAB Note 4 removing the debit
reduction. Item 4 ("Customers' securities failed to receive") is a credit, routed
to the PAB computation when the source activity is PAB
(atreides/books/projections.py).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId, EventId
from cannae_kernel.provenance import Provenance
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.books.ledger import (
    AccountType,
    EquitiesBooks,
    JournalEntry,
    LedgerLine,
    PostingSource,
    RecordSide,
    ReserveActivity,
    ReserveSourceFact,
)
from atreides.books.projections import project_customer_protection
from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.dsor.books import BooksPosting
from simulator.calibration.loader import PACKS_ROOT
from simulator.runner import run_simulation


def _pab_item_4(quantity: Decimal, price: Decimal, activity: ReserveActivity) -> Decimal | None:
    books = EquitiesBooks(break_owner="TEST")
    books.post(
        JournalEntry(
            entry_id="pab-ftr",
            source_event_id="evt_" + "1" * 26,
            source=PostingSource.CNS_FAIL,
            effective_date=date(2027, 1, 5),
            effective_date_basis="SETTLEMENT_DATE",
            authority="TEST",
            lines=(
                LedgerLine(
                    account_id="PAB-FTR",
                    account_type=AccountType.FAIL_TO_RECEIVE,
                    record_side=RecordSide.LOCATION,
                    issue="SYN-PAB-0",
                    quantity=quantity,
                ),
                LedgerLine(
                    account_id="DTC",
                    account_type=AccountType.DTC,
                    record_side=RecordSide.LOCATION,
                    issue="SYN-PAB-0",
                    quantity=-quantity,
                ),
            ),
            reserve_source_facts=(
                ReserveSourceFact(
                    account_type=AccountType.FAIL_TO_RECEIVE,
                    issue="SYN-PAB-0",
                    activity=activity,
                    settlement_date=date(2027, 1, 5),
                    contract_price=price,
                ),
            ),
            posting=BooksPosting(
                posted_record_id="pab-ftr",
                posting_authority=ActorRef(
                    actor_id=ActorId("act_" + "7" * 26),
                    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
                    role="close-1-test",
                    entitlement_refs=("CLOSE-1",),
                    authenticated=True,
                ),
                effective_time=datetime(2027, 1, 5, tzinfo=UTC),
                source_event_id=EventId("evt_" + "1" * 26),
                provenance=Provenance.FACT_SYNTHETIC,
            ),
            synthetic=True,
        )
    )
    projected = project_customer_protection(
        books,
        as_of=date(2027, 1, 5),
        prices={"SYN-PAB-0": price},
        net_worth=Decimal(1_000_000),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
        margin_results=(),
    )
    return next(
        line.amount for line in projected.pab_reserve.lines if line.rule_id == "15c3-3a.item.04"
    )


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10_000_000),
    price=st.decimals(min_value="0.0001", max_value="100000", places=4),
)
def test_pab_fail_to_receive_credit_conserves_to_the_cent(quantity: int, price: Decimal) -> None:
    amount = _pab_item_4(Decimal(quantity), price, ReserveActivity.PAB)
    assert amount == Decimal(quantity) * price


def test_firm_activity_never_reaches_the_pab_computation() -> None:
    assert _pab_item_4(Decimal(100), Decimal(10), ReserveActivity.FIRM) is None


def test_generated_run_produces_nonzero_pab_reserve_figures() -> None:
    run = run_simulation(seed=20261023, days=40)
    figures = [
        Decimal(close["protection"]["figures"]["pab_reserve_requirement"])
        for close in run["closes"]
        if close["protection"]["figures"]["pab_reserve_requirement"] is not None
    ]
    assert any(figure > 0 for figure in figures)
    assert run["all_invariants_pass"]


def test_seeds_differ_in_pab_activity() -> None:
    def draws(seed_value: int) -> list[object]:
        run = run_simulation(seed=seed_value, days=20)
        return [c["market_data"]["pab_fail_to_receive_quantity"] for c in run["closes"]]

    assert draws(1) != draws(2)


def test_pack_without_pab_parameters_declares_the_absence(tmp_path: Path) -> None:
    calibration = json.loads((PACKS_ROOT / "synthetic/1/calibration.json").read_text())
    generator = next(item for item in calibration["inputs"] if item["input_id"] == "generator")
    pab_keys = (
        "pab_fail_rate",
        "pab_fail_quantity_min",
        "pab_fail_quantity_max",
        "pab_fail_price",
    )
    for key in pab_keys:
        del generator["values"][key]
    destination = tmp_path / "20_curated/packs/pre-close-1/1"
    destination.mkdir(parents=True)
    data = destination / "calibration.json"
    data.write_text(json.dumps(calibration, sort_keys=True) + "\n")
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "cfma.calibration-manifest/1",
                "pack_id": "pre-close-1",
                "version": "1",
                "files": {"calibration.json": hashlib.sha256(data.read_bytes()).hexdigest()},
            },
            sort_keys=True,
        )
        + "\n"
    )
    run = run_simulation(seed=20261023, days=5, calibration_uri=destination.as_uri())
    assert {c["market_data"]["pab_fail_to_receive_quantity"] for c in run["closes"]} == {
        "NOT_DECLARED_IN_PACK"
    }
