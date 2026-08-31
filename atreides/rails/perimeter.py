"""Settlement perimeter - whose book a ledger-final rail is final on.

Per AUR-CUSTODY-CASH-001 Section IV as extended, 29 August 2026.

WHAT THIS MODULE EXISTS TO SAY
------------------------------
``LEDGER_FINAL`` answers "when does this become irrevocable" with "at ledger
commit". It does not answer *whose ledger*, and for a period that omission
did not matter because the gate never used the answer for anything.

It matters now. A ledger-final rail is continuously available when both legs
sit on the same institution's book, because moving value between two accounts
at one bank is a book entry that touches no national payment system. The same
rail carrying value to a counterparty at another institution depends on an
interbank system underneath it, and those systems are not continuously open.

The Federal Reserve's announced expansion of the Fedwire Funds Service and the
National Settlement Service, published 9 October 2025, takes them to six days
a week - Sunday through Friday, including weekday holidays - with daily hours
unchanged at 22 and 21.5 respectively, implemented in 2028 or 2029, with
voluntary participation. The interbank US dollar rail does not become
continuous. So "ledger-final, therefore available at three on a Sunday
morning" is true inside a perimeter and false outside one, and until this
module existed the gate could not tell the two apart.

THE SHAPE OF THE DEFECT THIS CLOSES
-----------------------------------
One class covering two mechanisms that behave differently. The corpus refuses
that collapse in every registry it consumes, and carried it internally here:
``RAIL_FINALITY`` maps ``TOKENIZED_DEPOSIT`` to ``LEDGER_FINAL`` without
qualification, and the rail ladder preferred that rail on "cost and 24/7
grounds" - a claim about continuous availability that the gate had no input
capable of substantiating.

WHY THIS IS ADDITIVE RATHER THAN A SPLIT
----------------------------------------
``FinalityClass`` is deliberately unchanged. Its meaning has been stable since
v0.1 so that historical records stay comparable and replay is not disturbed,
and the same reasoning that put ``obligation_finality_class`` beside the rail's
class rather than inside it applies here. The perimeter is recorded next to the
finality class, not folded into it. A reader of an old record still knows what
``LEDGER_FINAL`` meant when it was written; a reader of a new one additionally
knows whose book it was final on.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["SettlementPerimeter", "continuously_available"]


class SettlementPerimeter(StrEnum):
    """Whether the counterparty sits inside the settling institution's book."""

    NOT_ASSESSED = "NOT_ASSESSED"
    """Nobody has established which side of the perimeter the counterparty is
    on.

    The default, and it fails closed. This is the same discipline applied to
    counterparty standing and to market-data age: an unread fact is not a
    favourable fact, and the absence is given a name rather than a silent
    permissive default. A caller that knows the answer says so; a caller that
    does not gets the conservative branch and a record that says why."""

    ON_US = "ON_US"
    """Both legs settle on one institution's book.

    The transfer is a book entry. It touches no national payment system, so it
    is available continuously and is final on that institution's books at the
    instant it posts. This is the only condition under which a ledger-final
    rail's continuous-availability property actually holds."""

    OFF_US = "OFF_US"
    """The counterparty is outside the perimeter.

    The ledger commit still happens, and it is still final on the issuing
    institution's terms. What does not hold is continuous availability: value
    leaving the perimeter depends on an interbank system underneath, and those
    keep hours. Not a defect in the rail - a limit on what may be claimed for
    it outside those hours."""


def continuously_available(
    *, is_ledger_final: bool, perimeter: SettlementPerimeter
) -> bool:
    """Whether a rail may be treated as available outside banking hours.

    Only ledger-final rails are policed here. Every other class already
    carries its own window through ``seconds_to_cutoff`` and its status, and
    a gross-final or deferred-net rail marked open is open regardless of who
    the counterparty banks with.

    ``NOT_ASSESSED`` returns False, which is the point of the module.
    """
    if not is_ledger_final:
        return True
    return perimeter is SettlementPerimeter.ON_US
