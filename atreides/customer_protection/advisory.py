"""Customer protection advisory: the engines' answer, digest-bound, ADVISORY_ONLY.

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence.

THIS IS ADVICE. IT ENFORCES NOTHING.
------------------------------------
:class:`CustomerProtectionAdvisory` carries a constant ``enforcement_status`` of
``ADVISORY_ONLY``, and the type admits no other value. No shared attestation
contract for it exists in cannae-kernel, and no Aureon consumer reads it, so no
gate anywhere holds on it. A HOLD here is a recommendation to a person, most
likely a FINOP (Financial and Operations Principal), that something needs
looking at before anybody relies on the figures. Adoption by Aureon as a
pre-trade gate is reserved for a separately approved order (ORDER SC-2 section
5) and is not drafted, claimed or anticipated by anything in this package.

WHAT IT BINDS
-------------
The disposition the engine reached, the reasons and missing rules behind it,
the version of every rule source the engine read (citation, SHA-256 and
retrieval DTG, date-time group), the rule table digest, a digest of the inputs
and a digest of the result. Each digest is ``sha256:`` over the kernel's
canonical bytes, so anybody holding the inputs and the pinned rule text can
recompute all three and check them.

A breach or a projected breach (a triggered early warning) is HOLD. A missing
balance is HOLD. A missing rule is INDETERMINATE. PASS means this computation
found nothing, never that the firm complies.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from cannae_kernel.canonical import Digest, digest
from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import Field, field_validator, model_validator

from atreides.customer_protection.challenger import ChallengerInputs, ChallengerReport
from atreides.customer_protection.common import Frozen
from atreides.customer_protection.control import ControlInputs, ControlResult
from atreides.customer_protection.net_capital import NetCapitalInputs, NetCapitalResult
from atreides.customer_protection.reserve import ReserveInputs, ReserveResult
from atreides.customer_protection.rules.model import CLAIM_LABEL, RuleTable, RuleVersion

__all__ = [
    "ENFORCEMENT_STATUS",
    "CustomerProtectionAdvisory",
    "EngineInputs",
    "EngineResult",
    "advise",
]

#: The only enforcement status this package has. See the module docstring.
ENFORCEMENT_STATUS: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"

EngineInputs = ReserveInputs | NetCapitalInputs | ControlInputs | ChallengerInputs
EngineResult = Annotated[
    ReserveResult | NetCapitalResult | ControlResult | ChallengerReport,
    Field(discriminator="engine"),
]
_Result = ReserveResult | NetCapitalResult | ControlResult | ChallengerReport


class CustomerProtectionAdvisory(Frozen):
    """One engine's advice, bound to its inputs, result and rule text. ADVISORY_ONLY.

    Enforces nothing. No Aureon consumer exists and no gate is claimed.
    """

    schema_version: Literal["0.1-draft"] = "0.1-draft"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    enforcement_status: Literal["ADVISORY_ONLY"] = ENFORCEMENT_STATUS
    subject: Literal["reserve", "net_capital", "possession_or_control", "challenger"]
    as_of: date
    disposition: Disposition
    reasons: tuple[str, ...]
    missing_rules: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    rule_versions: tuple[RuleVersion, ...]
    rule_table_version: str
    rule_table_digest: Digest
    input_digest: Digest
    result_digest: Digest

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)

    @model_validator(mode="after")
    def _pass_has_nothing_behind_it(self) -> Self:
        if self.disposition is Disposition.PASS and (
            self.reasons_for_hold or self.missing_rules or self.missing_inputs
        ):
            raise ValueError("a PASS advisory carries no breach, missing rule or missing input")
        if self.disposition is Disposition.BLOCK:
            raise ValueError("an advisory never blocks; it enforces nothing")
        return self

    @property
    def reasons_for_hold(self) -> tuple[str, ...]:
        """The reasons that are breaches, as distinct from explanatory notes."""
        return tuple(reason for reason in self.reasons if reason.startswith("breach: "))


def _versions(result: _Result, table: RuleTable) -> tuple[RuleVersion, ...]:
    sources = sorted({ref.source_id for ref in result.rules_used})
    return tuple(v for v in (table.version_of(s) for s in sources) if v is not None)


def advise(inputs: EngineInputs, result: _Result, table: RuleTable) -> CustomerProtectionAdvisory:
    """The advisory for one computation. ADVISORY_ONLY: it is returned, never enforced."""
    reasons = (
        tuple(f"breach: {b}" for b in result.breaches)
        + tuple(f"unrecognised input: {u}" for u in result.unrecognised_inputs)
        + tuple(f"note: {r}" for r in result.reasons)
    )
    return CustomerProtectionAdvisory(
        subject=result.engine,
        as_of=result.as_of,
        disposition=result.disposition,
        reasons=reasons,
        missing_rules=result.missing_rules,
        missing_inputs=result.missing_inputs,
        rule_versions=_versions(result, table),
        rule_table_version=table.table_version,
        rule_table_digest=table.table_digest,
        input_digest=digest(inputs),
        result_digest=digest(result),
    )
