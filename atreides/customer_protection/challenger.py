"""Challenger report: the engine's figures against the vendor's or client's.

EXPERIMENTAL (charter section 18.6). ADVISORY_ONLY: the report enforces nothing.
It says where two computations of the same thing differ and offers candidate
explanations. A candidate never proves the operational cause.

HOW A CANDIDATE VARIANCE EXPLANATION IS ASSIGNED
------------------------------------------------
Variance is the vendor figure less the engine figure. Each figure receives the
first candidate classification that applies, in this order:

1. NOT_COMPARED: either side has no figure. Missing evidence, so HOLD.
2. MATCH: no variance.
3. TIMING: the vendor's figure is as of a different date from the engine's.
4. ROUNDING: the variance is within the rounding tolerance the client states.
   The tolerance is the client's policy, not a regulatory figure, so it is an
   input, and without it nothing is classified as rounding.
5. CLASSIFICATION: the variance is offset, within the tolerance, by an opposite
   variance on another figure in the same group (an amount reported on the
   wrong Exhibit A credit line, say, which moves a line without moving the
   total). Figures pair in a fixed order, each at most once.
6. UNKNOWN: none of the above. **Unknown stays unknown.** The report never
   guesses a cause it has no evidence for.

Only MATCH and ROUNDING leave the report at PASS. TIMING and CLASSIFICATION are
hypotheses that require corroborating source evidence and still HOLD for a
FINOP (Financial and Operations Principal) to review. A rule the engine could
not load makes the report INDETERMINATE.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from cannae_kernel.canonical import Digest, digest
from cannae_kernel.disposition import Disposition, coerce_disposition
from pydantic import Field, field_validator

from atreides.customer_protection.common import (
    Frozen,
    Money,
    NonNegativeMoney,
    RuleRef,
    decide,
)
from atreides.customer_protection.control import ControlInputs, ControlResult
from atreides.customer_protection.net_capital import NetCapitalInputs, NetCapitalResult
from atreides.customer_protection.reserve import (
    EXHIBIT_A_CREDITS,
    EXHIBIT_A_DEBITS,
    ReserveInputs,
    ReserveResult,
)
from atreides.customer_protection.rules.model import CLAIM_LABEL

__all__ = [
    "ChallengerInputs",
    "ChallengerReport",
    "Figure",
    "FigureVariance",
    "VarianceClass",
    "VendorFigure",
    "challenge",
    "challenger_inputs",
    "engine_figures",
]

ZERO = Decimal(0)


class VarianceClass(StrEnum):
    """Candidate explanation for a difference. It does not establish causation."""

    #: One side has no figure.
    NOT_COMPARED = "not_compared"
    #: No difference.
    MATCH = "match"
    #: The vendor's figure is as of another date.
    TIMING = "timing"
    #: Within the client's stated rounding tolerance.
    ROUNDING = "rounding"
    #: Offset by an opposite difference on another figure in the same group.
    CLASSIFICATION = "classification"
    #: Not explained by any of the above.
    UNKNOWN = "unknown"


_PASSING = frozenset({VarianceClass.MATCH, VarianceClass.ROUNDING})


class Figure(Frozen):
    """One named figure from an engine computation."""

    name: str
    #: Figures in one group can offset one another (for example, Exhibit A credit lines).
    group: str
    value: Money | None


class VendorFigure(Frozen):
    """The vendor's or client's figure for the same name."""

    name: str
    value: Money | None
    #: When the vendor's figure is as of a different date from its report.
    as_of: date | None = None


class ChallengerInputs(Frozen):
    """The engine's figures, the vendor's, and the client's rounding tolerance."""

    subject: Literal["reserve", "net_capital", "possession_or_control"]
    engine_as_of: date
    engine_figures: tuple[Figure, ...]
    engine_missing_rules: tuple[str, ...]
    engine_result_digest: Digest
    vendor: str = Field(min_length=1)
    vendor_as_of: date
    vendor_figures: tuple[VendorFigure, ...]
    #: The client's stated rounding tolerance. ``None`` means not stated.
    rounding_tolerance: NonNegativeMoney | None


class FigureVariance(Frozen):
    """One comparison with a candidate, rather than proven causal, explanation."""

    name: str
    group: str
    engine: Money | None
    vendor: Money | None
    #: Vendor less engine.
    variance: Money | None
    classification: VarianceClass
    explanation: str
    causal_status: Literal["CANDIDATE_NOT_CONFIRMED"] = "CANDIDATE_NOT_CONFIRMED"


class ChallengerReport(Frozen):
    """The comparison, figure by figure, and its disposition. ADVISORY_ONLY."""

    engine: Literal["challenger"] = "challenger"
    claim_label: Literal["EXPERIMENTAL"] = CLAIM_LABEL
    subject: Literal["reserve", "net_capital", "possession_or_control"]
    as_of: date
    vendor: str
    disposition: Disposition
    variances: tuple[FigureVariance, ...]
    missing_rules: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    unrecognised_inputs: tuple[str, ...] = ()
    breaches: tuple[str, ...]
    reasons: tuple[str, ...]
    rules_used: tuple[RuleRef, ...] = ()

    @field_validator("disposition", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Disposition:
        return coerce_disposition(value)


def _named(group: str, values: Iterable[tuple[str, Decimal | None]]) -> list[Figure]:
    return [Figure(name=name, group=group, value=value) for name, value in values]


def engine_figures(
    inputs: ReserveInputs | NetCapitalInputs | ControlInputs,
    result: ReserveResult | NetCapitalResult | ControlResult,
) -> tuple[Figure, ...]:
    """The figures a vendor computation can be compared with, in a fixed order."""
    if isinstance(inputs, ReserveInputs) and isinstance(result, ReserveResult):
        lines = {line.rule_id: line.amount for line in inputs.lines}
        return tuple(
            _named("exhibit_a_credits", ((r, lines.get(r)) for r in EXHIBIT_A_CREDITS))
            + _named("exhibit_a_debits", ((r, lines.get(r)) for r in EXHIBIT_A_DEBITS))
            + _named(
                "reserve",
                (
                    ("total_credits", result.total_credits),
                    ("total_debits", result.total_debits),
                    ("debit_reduction", result.debit_reduction),
                    ("requirement", result.requirement),
                    ("eligible_deposit", result.eligible_deposit),
                    ("shortfall", result.shortfall),
                ),
            )
        )
    if isinstance(result, NetCapitalResult):
        return tuple(
            _named(
                "net_capital",
                (
                    ("net_worth", result.net_worth),
                    ("total_additions", result.total_additions),
                    ("total_deductions", result.total_deductions),
                    ("tentative_net_capital", result.tentative_net_capital),
                    ("haircuts", result.haircuts),
                    ("net_capital", result.net_capital),
                    ("minimum_requirement", result.minimum_requirement),
                    ("excess_net_capital", result.excess_net_capital),
                ),
            )
            + _named(
                "haircuts",
                ((f"haircut:{line.description}", line.amount) for line in result.haircut_lines),
            )
        )
    assert isinstance(result, ControlResult)
    figures: list[Figure] = []
    for issue in result.issues:
        figures += _named(
            f"issue:{issue.issue}",
            (
                (f"{issue.issue}:in_control", issue.in_control),
                (f"{issue.issue}:shortfall", issue.shortfall),
            ),
        )
    return tuple(figures)


def challenger_inputs(
    inputs: ReserveInputs | NetCapitalInputs | ControlInputs,
    result: ReserveResult | NetCapitalResult | ControlResult,
    *,
    vendor: str,
    vendor_as_of: date,
    vendor_figures: tuple[VendorFigure, ...],
    rounding_tolerance: Decimal | None,
) -> ChallengerInputs:
    """Assemble the challenger's inputs from one engine computation and the vendor's figures."""
    return ChallengerInputs(
        subject=result.engine,
        engine_as_of=result.as_of,
        engine_figures=engine_figures(inputs, result),
        engine_missing_rules=result.missing_rules,
        engine_result_digest=digest(result),
        vendor=vendor,
        vendor_as_of=vendor_as_of,
        vendor_figures=vendor_figures,
        rounding_tolerance=rounding_tolerance,
    )


def _first_pass(
    figure: Figure, vendor: VendorFigure | None, inputs: ChallengerInputs
) -> FigureVariance:
    vendor_value = None if vendor is None else vendor.value
    if figure.value is None or vendor_value is None:
        side = "engine" if figure.value is None else "vendor"
        return FigureVariance(
            name=figure.name, group=figure.group, engine=figure.value, vendor=vendor_value,
            variance=None, classification=VarianceClass.NOT_COMPARED,
            explanation=f"no {side} figure",
        )
    variance = vendor_value - figure.value
    vendor_as_of = inputs.vendor_as_of if vendor is None or vendor.as_of is None else vendor.as_of
    tolerance = inputs.rounding_tolerance
    if variance == ZERO:
        classification, explanation = VarianceClass.MATCH, "no difference"
    elif vendor_as_of != inputs.engine_as_of:
        classification = VarianceClass.TIMING
        explanation = f"vendor figure as of {vendor_as_of}, engine as of {inputs.engine_as_of}"
    elif tolerance is not None and abs(variance) <= tolerance:
        classification, explanation = VarianceClass.ROUNDING, f"within {tolerance}"
    else:
        classification, explanation = VarianceClass.UNKNOWN, "not explained"
    return FigureVariance(
        name=figure.name, group=figure.group, engine=figure.value, vendor=vendor_value,
        variance=variance, classification=classification, explanation=explanation,
    )


def _pair_offsets(
    variances: list[FigureVariance], tolerance: Decimal | None
) -> list[FigureVariance]:
    """Reclassify UNKNOWN pairs in one group whose variances cancel, within the tolerance."""
    allowed = ZERO if tolerance is None else tolerance
    out = list(variances)
    paired: set[int] = set()
    for i, first in enumerate(out):
        if first.classification is not VarianceClass.UNKNOWN or i in paired:
            continue
        for j in range(i + 1, len(out)):
            second = out[j]
            if (
                j in paired
                or second.classification is not VarianceClass.UNKNOWN
                or second.group != first.group
                or first.variance is None
                or second.variance is None
                or abs(first.variance + second.variance) > allowed
            ):
                continue
            paired |= {i, j}
            out[i] = first.model_copy(
                update={"classification": VarianceClass.CLASSIFICATION,
                        "explanation": f"offset by {second.name}"}
            )
            out[j] = second.model_copy(
                update={"classification": VarianceClass.CLASSIFICATION,
                        "explanation": f"offset by {first.name}"}
            )
            break
    return out


def challenge(inputs: ChallengerInputs) -> ChallengerReport:
    """Compare and suggest candidate explanations. Pure: no I/O and no clock."""
    vendor = {figure.name: figure for figure in inputs.vendor_figures}
    engine_names = {figure.name for figure in inputs.engine_figures}
    variances = [_first_pass(f, vendor.get(f.name), inputs) for f in inputs.engine_figures]
    variances += [
        FigureVariance(
            name=v.name, group="vendor_only", engine=None, vendor=v.value, variance=None,
            classification=VarianceClass.NOT_COMPARED,
            explanation="the engine computes no figure of this name",
        )
        for v in inputs.vendor_figures
        if v.name not in engine_names
    ]
    variances = _pair_offsets(variances, inputs.rounding_tolerance)

    missing_inputs = [
        f"figure:{v.name}" for v in variances if v.classification is VarianceClass.NOT_COMPARED
    ]
    if inputs.rounding_tolerance is None:
        missing_inputs.append("rounding_tolerance")
    breaches = [
        f"{v.name}: {v.classification.value} variance of {v.variance} ({v.explanation})"
        for v in variances
        if v.classification not in _PASSING and v.classification is not VarianceClass.NOT_COMPARED
    ]
    return ChallengerReport(
        subject=inputs.subject,
        as_of=inputs.engine_as_of,
        vendor=inputs.vendor,
        disposition=decide(inputs.engine_missing_rules, missing_inputs, breaches),
        variances=tuple(variances),
        missing_rules=inputs.engine_missing_rules,
        missing_inputs=tuple(missing_inputs),
        breaches=tuple(breaches),
        reasons=(f"compared with {inputs.vendor} as of {inputs.vendor_as_of}",),
    )
