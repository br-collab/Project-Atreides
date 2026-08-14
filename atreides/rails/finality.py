"""Finality classes - shared settlement vocabulary.

Per AUR-CUSTODY-CASH-001 Section IV.

This enum was originally defined inside CATO-F, which was correct while
the gate was its only consumer. It now has four: the gate, the intraday
funding model, the determination classifier, and the proposed margin model.
Extracting it here is the honest layering, and it also breaks the import
cycle that the determination classifier would otherwise create - that
module needs FinalityClass, and CATO-F needs the determination vocabulary.

``atreides.rails.cato_f`` re-exports ``FinalityClass``, so every existing
import site keeps working unchanged. Nothing about the enum's meaning moved
with it.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["FinalityClass"]


class FinalityClass(StrEnum):
    """Finality classes per AUR-CUSTODY-CASH-001 Section IV.

    The doctrinal core of the cash gate: materiality tightens as
    reversibility falls. An irreversible operation warrants a lower
    trigger than a reversible one of the same size.

    The first four are classes of the RAIL and every rail maps to exactly
    one of them. The fifth is a class of the OBLIGATION and no rail maps to
    it - see ``DETERMINATION_DEPENDENT`` and
    ``atreides.rails.determination``. A record may therefore carry two
    classes at once, which is the point: the money can be final while the
    entitlement to it is not.
    """

    GROSS_FINAL = "GROSS_FINAL"
    DEFERRED_NET = "DEFERRED_NET"
    LEDGER_FINAL = "LEDGER_FINAL"
    CORRESPONDENT_DEPENDENT = "CORRESPONDENT_DEPENDENT"

    DETERMINATION_DEPENDENT = "DETERMINATION_DEPENDENT"
    """Obligation-level only. The cash movement is irrevocable on its
    rail's own terms, and the venue retains authority to cancel the
    contract and return the funds, so the value can still be taken back for
    reasons the rail knows nothing about. NEVER appears in
    ``RAIL_FINALITY``; supplying it as a rail's class is a caller error and
    is refused rather than guessed at."""
