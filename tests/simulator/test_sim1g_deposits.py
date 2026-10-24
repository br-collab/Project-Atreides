"""SIM-1G: Reserve Bank Account deposits through the real books, and an honest I6.

17 CFR 240.15c3-3(e)(3)(i)(A), pinned source sha256 c7d7067f...: "the deposit so
computed must be made no later than one hour after the opening of banking business on
the second following business day." 17 CFR 240.15c3-3(g): withdrawals only "if and to
the extent that at the time of the withdrawal the amount remaining ... is not less than
the amount then required".

The hold each reserve computation requires is derived from the day's inputs and the
simulated deposit (simulator/runner.py), never from the engine's disposition. The
mutations below force the engine's answer the wrong way and require I6 to fail.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

import pytest
from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import ActorId
from hypothesis import given, seed, settings
from hypothesis import strategies as st

import simulator.estate as estate_module
from atreides.books.ledger import AccountType, EquitiesBooks
from atreides.books.projections import reserve_bank_balances
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    ComputationMode,
    LineBalance,
    NetCapitalStandard,
    ReserveAccounts,
    ReserveInputs,
    compute_reserve,
)
from atreides.customer_protection.rules import load_rule_table
from atreides.deadlines.calendar import Market, MarketCalendar
from simulator.calibration.loader import PACKS_ROOT
from simulator.estate import (
    CENT,
    DepositDraw,
    DepositPolicy,
    _deposit_entry,
    _post_reserve_deposits,
)
from simulator.runner import (
    RESERVE_SECTION_HEADING,
    SHORTFALL_REASON,
    deposit_breach,
    publish_run,
    reserve_section,
    run_simulation,
)

I6 = "I6_DEFAULT_AND_STALE_HOLD"
CALENDAR = MarketCalendar.load(Market.US_EQUITIES)
RULES = load_rule_table()
AS_OF = date(2027, 1, 5)
ACTOR = ActorRef(
    actor_id=ActorId("act_" + "6" * 26),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="sim-1g-test",
    entitlement_refs=("SIM-1G",),
    authenticated=True,
)


def _inputs(accounts: ReserveAccounts, credit: Decimal) -> ReserveInputs:
    """A complete weekly computation whose requirement is exactly ``credit``."""
    lines = tuple(
        LineBalance(rule_id=rule_id, amount=credit if rule_id == "15c3-3a.item.01" else Decimal())
        for rule_id in (*EXHIBIT_A_CREDITS, *EXHIBIT_A_DEBITS)
    )
    return ReserveInputs(
        accounts=accounts,
        as_of=AS_OF,
        standard=NetCapitalStandard.AGGREGATE_INDEBTEDNESS,
        mode=ComputationMode.WEEKLY,
        lines=lines,
        average_total_credits=Decimal(0),
        previously_daily_required=False,
        qualified_securities_deposit=Decimal(0),
    )


money = st.decimals(min_value="0", max_value="5000000000", places=4)
fraction = st.decimals(min_value="0.0001", max_value="0.9999", places=4)
outcome = st.sampled_from(("ON_TIME", "SHORT", "LATE"))


@seed(20261023)
@settings(max_examples=200, deadline=None)
@given(
    customer_requirement=money,
    pab_requirement=money,
    customer_opening=money,
    pab_opening=money,
    customer_outcome=outcome,
    pab_outcome=outcome,
    short_fraction=fraction,
)
def test_deposit_outcome_alone_predicts_the_engine_disposition(
    customer_requirement: Decimal,
    pab_requirement: Decimal,
    customer_opening: Decimal,
    pab_opening: Decimal,
    customer_outcome: str,
    pab_outcome: str,
    short_fraction: Decimal,
) -> None:
    customer_inputs = _inputs(ReserveAccounts.CUSTOMER, customer_requirement)
    pab_inputs = _inputs(ReserveAccounts.PAB, pab_requirement)
    sized = (
        compute_reserve(customer_inputs, RULES),
        compute_reserve(pab_inputs, RULES),
    )
    books = EquitiesBooks(break_owner="TEST")
    reserve, pab, deposits = _post_reserve_deposits(
        books=books,
        run_number=7,
        business_date=AS_OF,
        calendar=CALENDAR,
        actor=ACTOR,
        rules=RULES,
        reserve_inputs=customer_inputs,
        pab_reserve_inputs=pab_inputs,
        sized_from=sized,
        opening=(customer_opening, pab_opening),
        policy=DepositPolicy(
            customer=DepositDraw(outcome=customer_outcome, short_fraction=short_fraction),
            pab=DepositDraw(outcome=pab_outcome, short_fraction=short_fraction),
            bank_equity_capital=Decimal("50000000000"),
        ),
    )
    for result, deposit in zip((reserve, pab), deposits, strict=True):
        assert result.requirement is not None and deposit.needed is not None
        # The independent prediction and the engine agree, both ways.
        assert deposit_breach(deposit) == (result.disposition is Disposition.HOLD)
        assert deposit.amount == deposit.amount.quantize(CENT)
        if deposit.outcome == "SHORT":
            unpaid = deposit.needed - (deposit.needed * (1 - short_fraction)).quantize(
                CENT, rounding=ROUND_FLOOR
            )
            assert result.shortfall == unpaid > 0
        elif deposit.outcome == "LATE":
            assert result.shortfall == deposit.needed
            assert result.requirement <= deposit.closing_balance < result.requirement + CENT
        else:
            # ON_TIME, NO_DEPOSIT_NEEDED or a Rule 15c3-3(g) withdrawal to the requirement.
            assert result.shortfall == 0
            assert result.requirement <= deposit.balance_at_deadline < result.requirement + CENT
        if deposit.needed < 0:
            assert deposit.outcome == "WITHDRAWAL_TO_REQUIREMENT"
        assert deposit.deadline == CALENDAR.add_business_days(AS_OF, 2)


def test_deposit_after_the_deadline_does_not_count() -> None:
    books = EquitiesBooks(break_owner="TEST")
    deadline = CALENDAR.add_business_days(AS_OF, 2)
    late = CALENDAR.add_business_days(deadline, 1)
    for number, effective in ((1, deadline), (2, late)):
        books.post(
            _deposit_entry(
                entry_id=f"t-{number}",
                event_number=number,
                account_type=AccountType.RESERVE_BANK_PAB,
                amount=Decimal(100),
                effective=effective,
                authority="TEST",
                actor=ACTOR,
            )
        )
    assert reserve_bank_balances(books, through=deadline)[AccountType.RESERVE_BANK_PAB] == 100
    assert reserve_bank_balances(books, through=late)[AccountType.RESERVE_BANK_PAB] == 200
    assert reserve_bank_balances(books, through=late)[AccountType.RESERVE_BANK_CUSTOMER] == 0


def _pack(tmp_path: Path, name: str, **values: str | None) -> str:
    calibration = json.loads((PACKS_ROOT / "synthetic/1/calibration.json").read_text())
    generator = next(item for item in calibration["inputs"] if item["input_id"] == "generator")
    for key, value in values.items():
        if value is None:
            del generator["values"][key]
        else:
            generator["values"][key] = value
    destination = tmp_path / f"20_curated/packs/{name}/1"
    destination.mkdir(parents=True)
    data = destination / "calibration.json"
    data.write_text(json.dumps(calibration, sort_keys=True) + "\n")
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "cfma.calibration-manifest/1",
                "pack_id": name,
                "version": "1",
                "files": {"calibration.json": hashlib.sha256(data.read_bytes()).hexdigest()},
            },
            sort_keys=True,
        )
        + "\n"
    )
    return destination.as_uri()


def _breach_pack(tmp_path: Path) -> str:
    # Every needed deposit is late or short, so both breach paths are exercised. The
    # SIM-1E customer credit schedule steps from the maximum to the minimum after the
    # first month; inverting the two values makes the customer requirement rise at the
    # step, so a customer deposit is needed on a day with complete inputs.
    return _pack(
        tmp_path,
        "sim-1g-all-breach",
        reserve_deposit_late_rate="0.5000",
        reserve_deposit_short_rate="0.5000",
        customer_credit_min="900000000",
        customer_credit_max="50000000",
    )


KEYS = {"customer": "reserve", "pab": "pab_reserve"}


def test_canonical_window_funds_and_breaches_both_computations() -> None:
    run = run_simulation(seed=20261023, days=60)
    assert run["all_invariants_pass"]
    outcomes = {
        (name, deposit["outcome"])
        for close in run["closes"]
        for name, deposit in close["protection"]["deposits"].items()
    }
    assert ("pab", "ON_TIME") in outcomes and ("customer", "ON_TIME") in outcomes


def test_unmutated_breach_run_holds_with_the_shortfall_reason(tmp_path: Path) -> None:
    run = run_simulation(seed=20261023, days=40, calibration_uri=_breach_pack(tmp_path))
    assert run["all_invariants_pass"]
    seen = set()
    for close in run["closes"]:
        for name, deposit in close["protection"]["deposits"].items():
            key = KEYS[name]
            if (
                deposit["outcome"] in {"SHORT", "LATE"}
                and close["protection"]["reasons_required"][key] == SHORTFALL_REASON
            ):
                seen.add(name)
                assert close["protection"]["dispositions"][key] == "HOLD"
                assert any(SHORTFALL_REASON in r for r in close["protection"]["reasons"][key])
    assert seen == {"customer", "pab"}


def _mutate(
    monkeypatch: pytest.MonkeyPatch, computation: str, disposition: Disposition, *, strip: bool
) -> None:
    original = estate_module._post_reserve_deposits

    def mutated(**kwargs: Any) -> Any:
        reserve, pab, deposits = original(**kwargs)
        update: dict[str, object] = {"disposition": disposition}
        if strip:
            update["breaches"] = ()
            update["reasons"] = ()
        if computation == "customer":
            reserve = reserve.model_copy(update=update)
        else:
            pab = pab.model_copy(update=update)
        return reserve, pab, deposits

    monkeypatch.setattr(estate_module, "_post_reserve_deposits", mutated)


@pytest.mark.parametrize("computation", ["customer", "pab"])
def test_mutation_forced_hold_on_a_funded_day_fails_i6(
    monkeypatch: pytest.MonkeyPatch, computation: str
) -> None:
    _mutate(monkeypatch, computation, Disposition.HOLD, strip=False)
    run = run_simulation(seed=20261023, days=30)
    funded = [
        close
        for close in run["closes"]
        if not close["protection"]["holds_required"][KEYS[computation]]
    ]
    assert funded, "the window must contain a funded day for this computation"
    assert all(close["invariant_results"][I6] is False for close in funded)
    assert run["all_invariants_pass"] is False


@pytest.mark.parametrize("computation", ["customer", "pab"])
def test_mutation_forced_pass_on_a_short_deposit_day_fails_i6(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, computation: str
) -> None:
    _mutate(monkeypatch, computation, Disposition.PASS, strip=True)
    run = run_simulation(seed=20261023, days=30, calibration_uri=_breach_pack(tmp_path))
    short = [
        close
        for close in run["closes"]
        if close["protection"]["deposits"][computation]["outcome"] in {"SHORT", "LATE"}
    ]
    assert short, "the window must contain a short or late deposit for this computation"
    assert all(close["invariant_results"][I6] is False for close in short)


@pytest.mark.parametrize("computation", ["customer", "pab"])
def test_mutation_hold_without_the_shortfall_reason_fails_i6(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, computation: str
) -> None:
    _mutate(monkeypatch, computation, Disposition.HOLD, strip=True)
    run = run_simulation(seed=20261023, days=40, calibration_uri=_breach_pack(tmp_path))
    short = [
        close
        for close in run["closes"]
        if close["protection"]["deposits"][computation]["outcome"] in {"SHORT", "LATE"}
        and close["protection"]["reasons_required"][KEYS[computation]] == SHORTFALL_REASON
    ]
    assert short, "the window must contain a breach day with complete inputs"
    assert all(close["invariant_results"][I6] is False for close in short)


def test_pack_without_a_deposit_policy_posts_nothing_and_still_holds_honestly(
    tmp_path: Path,
) -> None:
    uri = _pack(
        tmp_path,
        "pre-sim-1g",
        reserve_deposit_late_rate=None,
        reserve_deposit_short_rate=None,
        reserve_deposit_short_fraction_min=None,
        reserve_deposit_short_fraction_max=None,
        reserve_bank_equity_capital=None,
    )
    run = run_simulation(seed=20261023, days=10, calibration_uri=uri)
    assert run["all_invariants_pass"]
    drawn = {
        deposit["drawn_outcome"]
        for close in run["closes"]
        for deposit in close["protection"]["deposits"].values()
    }
    assert drawn == {"NOT_DECLARED_IN_PACK"}
    first = run["closes"][0]["protection"]
    assert first["deposits"]["customer"]["outcome"] == "NOT_DECLARED_IN_PACK"
    assert first["dispositions"]["reserve"] == "HOLD"


def test_deposit_streams_differ_by_seed() -> None:
    def draws(seed_value: int) -> list[object]:
        run = run_simulation(seed=seed_value, days=20)
        return [
            close["protection"]["deposits"]["pab"]["drawn_outcome"] for close in run["closes"]
        ]

    assert draws(1) != draws(2)


def test_deposit_policy_rejects_a_fraction_outside_zero_and_one(tmp_path: Path) -> None:
    uri = _pack(tmp_path, "bad-fraction", reserve_deposit_short_fraction_max="1.0000")
    with pytest.raises(ValueError, match="short fraction"):
        run_simulation(seed=20261023, days=2, calibration_uri=uri)



def test_mutation_projection_counting_late_deposits_fails_i6(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Adversarial (rule 30): if the books projection ignored the deadline, a late
    # deposit would count, the engine would PASS, and only an independent I6 notices.
    original = estate_module.reserve_bank_balances

    def ignores_deadline(books: EquitiesBooks, *, through: date) -> dict[AccountType, Decimal]:
        return original(books, through=date.max)

    monkeypatch.setattr(estate_module, "reserve_bank_balances", ignores_deadline)
    uri = _pack(
        tmp_path,
        "sim-1g-all-late",
        reserve_deposit_late_rate="0.9999",
        reserve_deposit_short_rate="0.0000",
    )
    run = run_simulation(seed=20261023, days=30, calibration_uri=uri)
    late = [
        close
        for close in run["closes"]
        if close["protection"]["deposits"]["pab"]["outcome"] == "LATE"
        and close["protection"]["reasons_required"]["pab_reserve"] == SHORTFALL_REASON
    ]
    assert late
    assert all(close["invariant_results"][I6] is False for close in late)


@pytest.mark.parametrize("artifact", ["spike-2019", "stress-2020-03", "stress-2023-03"])
def test_committed_summaries_disclose_the_reserve_section_from_their_own_closes(
    artifact: str,
) -> None:
    publication = Path(__file__).parents[2] / "simulator/publication" / artifact
    closes = json.loads((publication / "daily-close.json").read_text())["closes"]
    summary = (publication / "SUMMARY.md").read_text()
    assert reserve_section(closes) in summary
    assert summary.count(RESERVE_SECTION_HEADING) == 1


def test_published_summary_states_a_declared_policy_and_counts(tmp_path: Path) -> None:
    run = run_simulation(seed=20261023, days=30)
    publish_run(run, tmp_path)
    summary = (tmp_path / "SUMMARY.md").read_text()
    assert "Customer deposit policy: declared SYNTHETIC in the pack" in summary
    passes = sum(c["protection"]["dispositions"]["reserve"] == "PASS" for c in run["closes"])
    assert f"Customer reserve: `{passes}` PASS" in summary
    assert summary.index(RESERVE_SECTION_HEADING) < summary.index("## New York Fed notices")
