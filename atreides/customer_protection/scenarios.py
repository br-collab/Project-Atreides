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

AS_OF = date.fromisoformat("2026-10-02")
CLEARING = "15c3-3.control.c1"
BANK = "15c3-3.control.c5"
LIEN = "15c3-3.noncontrol.d1"
FULLY_PAID = "800"
EXCESS_MARGIN = "200"
BOOKS_TOTAL = "1500"
PASS_CLEARING = "900"
PASS_BANK = "300"
PASS_LIEN = "300"
HOLD_CLEARING = "600"
HOLD_LIEN = "900"
INDETERMINATE_CLEARING = "1000"
INDETERMINATE_UNKNOWN = "500"


def _inputs(holdings: tuple[Holding, ...]) -> ControlInputs:
    return ControlInputs(
        as_of=AS_OF,
        issues=(
            IssueRequirement(
                issue="SYNTHETIC ISSUE A",
                fully_paid=Decimal(FULLY_PAID),
                excess_margin=Decimal(EXCESS_MARGIN),
                books_total=Decimal(BOOKS_TOTAL),
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
                    Holding(location=CLEARING, quantity=Decimal(PASS_CLEARING)),
                    Holding(location=BANK, quantity=Decimal(PASS_BANK)),
                    Holding(location=LIEN, quantity=Decimal(PASS_LIEN), loaned=False),
                ),
            ),
            _scenario(
                "sc2-control-hold",
                "A synthetic control shortfall requires human review.",
                (
                    Holding(location=CLEARING, quantity=Decimal(HOLD_CLEARING)),
                    Holding(location=LIEN, quantity=Decimal(HOLD_LIEN), loaned=False),
                ),
            ),
            _scenario(
                "sc2-control-indeterminate",
                "An unknown synthetic location leaves the rule evidence incomplete.",
                (
                    Holding(
                        location=CLEARING, quantity=Decimal(INDETERMINATE_CLEARING)
                    ),
                    Holding(
                        location="SYNTHETIC VENDOR VAULT",
                        quantity=Decimal(INDETERMINATE_UNKNOWN),
                    ),
                ),
            ),
        ),
    )
