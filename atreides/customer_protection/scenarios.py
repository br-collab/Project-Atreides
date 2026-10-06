"""Committed synthetic inputs used to publish customer protection advisories.

These examples are invented solely to exercise PASS, HOLD and INDETERMINATE
through the real possession or control engine. They are not any firm's data or
position.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from atreides.customer_protection.advisory import advise
from atreides.customer_protection.control import (
    ControlInputs,
    Holding,
    IssueRequirement,
    check_possession_or_control,
)
from atreides.customer_protection.publication import AdvisoryPublication, AdvisoryScenario
from atreides.customer_protection.rules import load_rule_table

AS_OF = date(2026, 10, 2)
CLEARING = "15c3-3.control.c1"
BANK = "15c3-3.control.c5"
LIEN = "15c3-3.noncontrol.d1"


def _inputs(holdings: tuple[Holding, ...]) -> ControlInputs:
    return ControlInputs(
        as_of=AS_OF,
        issues=(
            IssueRequirement(
                issue="SYNTHETIC ISSUE A",
                fully_paid=Decimal(800),
                excess_margin=Decimal(200),
                books_total=Decimal(1500),
                holdings=holdings,
            ),
        ),
    )


def _scenario(
    scenario_id: str, description: str, holdings: tuple[Holding, ...]
) -> AdvisoryScenario:
    inputs = _inputs(holdings)
    table = load_rule_table()
    result = check_possession_or_control(inputs, table)
    return AdvisoryScenario(
        scenario_id=scenario_id,
        description=description,
        advisories=(advise(inputs, result, table),),
    )


def build_publication(taken_at: datetime) -> AdvisoryPublication:
    """Run the three committed inputs and return their synthetic publication."""
    return AdvisoryPublication(
        taken_at=taken_at,
        scenarios=(
            _scenario(
                "sc2-control-pass",
                "Known control locations satisfy the synthetic issue requirement.",
                (
                    Holding(location=CLEARING, quantity=Decimal(900)),
                    Holding(location=BANK, quantity=Decimal(300)),
                    Holding(location=LIEN, quantity=Decimal(300), loaned=False),
                ),
            ),
            _scenario(
                "sc2-control-hold",
                "A synthetic control shortfall requires human review.",
                (
                    Holding(location=CLEARING, quantity=Decimal(600)),
                    Holding(location=LIEN, quantity=Decimal(900), loaned=False),
                ),
            ),
            _scenario(
                "sc2-control-indeterminate",
                "An unknown synthetic location leaves the rule evidence incomplete.",
                (
                    Holding(location=CLEARING, quantity=Decimal(1000)),
                    Holding(location="SYNTHETIC VENDOR VAULT", quantity=Decimal(500)),
                ),
            ),
        ),
    )
