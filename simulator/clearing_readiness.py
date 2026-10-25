"""Declared clearing membership and funding readiness over real CNS settlement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.rails.cns import (
    CloseOutRegime,
    MarketProfile,
    net_positions,
    settle_net_position,
)

Variant = Literal["ready", "missing-membership", "fund-call"]
DTCC_LICENSE_GATE = "INDETERMINATE"


@dataclass(frozen=True)
class MembershipEvidence:
    """Declared documents; none is inferred from a settlement result."""

    nscc: str | None
    dtc: str | None
    ficc: str | None


@dataclass(frozen=True)
class FundingInputs:
    clearing_fund_requirement: Decimal
    collateral_requirement: Decimal
    available_cash: Decimal


def _cns_money_settlement() -> Decimal:
    positions = net_positions(
        (("SYN-CLEARING-ISSUE", Decimal("137")),),
        market_id="NSCC_SYNTHETIC",
        settlement_date_offset_days=1,
    )
    position = positions[0]
    signed_cash = Decimal("13884.69")
    result = settle_net_position(
        position,
        MarketProfile(
            market_id="NSCC_SYNTHETIC",
            settlement_cycle_days=1,
            close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
            close_out_deadline_days=3,
            allocation_rule_published=True,
            provenance="CONV-3 declared synthetic profile",
        ),
        allocated_quantity=position.quantity,
        signed_cash=signed_cash,
        allocated_cash=signed_cash,
        settlement_date=date(2026, 10, 5),
        as_of_date=date(2026, 10, 5),
        calendar=MarketCalendar.load(Market.US_EQUITIES),
    )
    return abs(result.allocated_cash)


def run_clearing_readiness(
    variant: Variant, *, mutation: Literal["inflate-fund-call"] | None = None
) -> dict[str, object]:
    """Run readiness using rule numbers/titles only; DTCC text is not reproduced."""
    evidence = MembershipEvidence(
        nscc=None if variant == "missing-membership" else "SYN-NSCC-MEMBERSHIP",
        dtc="SYN-DTC-PARTICIPANT",
        ficc="SYN-FICC-GSD-MEMBERSHIP",
    )
    inputs = FundingInputs(
        clearing_fund_requirement=(
            Decimal("1200000")
            if variant == "fund-call" or mutation == "inflate-fund-call"
            else Decimal("250000")
        ),
        collateral_requirement=Decimal("175000"),
        available_cash=Decimal("1000000"),
    )
    cns_money = _cns_money_settlement()
    daily_funding_need = cns_money + inputs.clearing_fund_requirement
    missing = tuple(name.upper() for name, value in asdict(evidence).items() if value is None)
    reasons = [f"missing declared {name} membership evidence" for name in missing]
    if daily_funding_need > inputs.available_cash:
        reasons.append("declared clearing fund call above available cash")
    return {
        "schema_version": "sim.clearing-readiness/1",
        "synthetic": True,
        "variant": variant,
        "dtcc_license_gate": DTCC_LICENSE_GATE,
        "rule_references": [
            "NSCC Rules and Procedures — membership and clearing fund",
            "DTC Rules, By-Laws and Organization Certificate — participant eligibility",
            "FICC GSD Rules — membership and clearing fund",
        ],
        "membership_evidence": asdict(evidence),
        "declared_funding_inputs": {
            key: str(value) for key, value in asdict(inputs).items()
        },
        "cns_money_settlement": str(cns_money),
        "daily_funding_need": str(daily_funding_need),
        "disposition": "HOLD" if reasons else "PASS",
        "reasons": reasons,
        "invariants": {
            "I14_MEMBERSHIP_EVIDENCE_COMPLETE": not missing,
            "I15_FUNDING_NEED_COVERED": daily_funding_need <= inputs.available_cash,
        },
    }


def attack_clearing_readiness() -> dict[str, bool]:
    """Inflate the declared call, rerun, and observe the funding invariant fail."""
    result = run_clearing_readiness("ready", mutation="inflate-fund-call")
    invariants = result["invariants"]
    if not isinstance(invariants, dict):
        raise TypeError("readiness run did not return invariants")
    return {"inflate-fund-call": invariants["I15_FUNDING_NEED_COVERED"] is False}
