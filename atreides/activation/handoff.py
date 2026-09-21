"""The pre-C2 handoff refusal, enforced by the receiving agent (W3 § WP-A2, R1).

C2 = Command and Control. CAOM = Consolidated Authority Operating Mode.

Why the check lives here and not above
--------------------------------------
The governing finding of Wave 2, recurring in four independent places:

    An invariant enforced by a filter one layer up is fragile. An invariant
    enforced by the consumer's own type check is not.

Thifur-C2 is a filter one layer up. If C2 were the only thing preventing a
lateral agent-to-agent handoff, that is the fragile pattern — the one that
failed fifteen times in Wave 2, three times carrying authority. So the refusal
is written at the consumer: **the receiving agent refuses input that did not
arrive with a recorded handoff authorization**, and it refuses it whether or
not anything upstream is running.

Today there is no C2 to issue an authorization, so every lateral input is
refused and the refusal is recorded. That is the correct behaviour, not a
placeholder. When C2 arrives it gains the ability to *grant* a handoff; it does
not become the thing that prevents one. That asymmetry is the whole design, and
it is why adding C2 later is safe.

What is deliberately **not** here
---------------------------------
Nothing that issues, assembles or escalates. Under W3-agent-activation-AMD1 §4
no C2 orchestration design — the lineage assembler, handoff issuance, escalation
packaging — reaches any public repository under ``br-collab`` before Bill records
his Research Charter §18.5 decision. This module only states what a consumer
requires and refuses. What C2 eventually puts behind a handoff identifier is
C2's business and is not described here.

The two origins, and the basis each carries
-------------------------------------------
:class:`InputOrigin` is the distinction the check turns on:

- ``OPERATOR_DIRECT`` — a human tasked this agent. CAOM-001 already governs it
  and its terms are unchanged: agents analyse, surface signals and enforce
  pre-configured doctrine; every approval gate requires explicit operator
  action. This is the only admitted path today.
- ``AGENT_LATERAL`` — another agent handed a lifecycle object over. Admitted
  only with a recorded handoff authorization, which nothing can currently issue.

Absence, not null (AMD1 § 3b)
-----------------------------
Every agent output records its handoff basis, and until C2 exists that basis is
**absent, with a reason** — never a bare ``None``. The distinction is the whole
of R2: ``None`` is indistinguishable from a value that has not arrived yet, so a
consumer reading it picks the cheerful reading. :data:`OPERATOR_DIRECT_BASIS` is
that absence, spelled once.

The kernel's ``Recorded``/``Absent`` pair is the absence type used throughout
(AMD1 § 3a); this module defines no refusal type of its own.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from cannae_kernel.absence import AbsenceKind, Absent, Recorded
from cannae_kernel.disposition import Disposition
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "OPERATOR_DIRECT_BASIS",
    "OPERATOR_DIRECT_REASON",
    "Admission",
    "HandoffBasis",
    "InputOrigin",
    "RefusedAtConsumerError",
    "admit",
    "basis_from_lineage",
    "require_handoff",
]

#: The reason a handoff basis is absent while no C2 exists. AMD1 § 3b names it.
OPERATOR_DIRECT_REASON: Final = "operator-direct under CAOM-001"


class InputOrigin(StrEnum):
    """How a unit of work reached an agent."""

    OPERATOR_DIRECT = "OPERATOR_DIRECT"
    """A human tasked this agent. Governed by CAOM-001; no handoff is involved."""

    AGENT_LATERAL = "AGENT_LATERAL"
    """Another agent handed this over. Requires a recorded handoff authorization."""


#: A recorded C2 handoff identifier, or the recorded reason there is none.
#:
#: ``Recorded[str]`` is the identifier C2 issued. ``Absent`` is the reason no
#: identifier exists, which is a value in the record and not an omission from it.
HandoffBasis = Recorded[str] | Absent

#: What ``c2_handoff_id`` is while C2 does not exist: settled absence, with its
#: reason. ``NOTHING_RECORDED`` rather than ``NOT_YET_KNOWN`` on purpose — for an
#: operator-direct tasking no handoff was ever going to be issued, so nothing is
#: in flight and a reader must not be told to wait for one.
OPERATOR_DIRECT_BASIS: Final[Absent] = Absent(
    kind=AbsenceKind.NOTHING_RECORDED, reason=OPERATOR_DIRECT_REASON
)


class Admission(BaseModel):
    """What the receiving agent decided about one input, and why.

    ``disposition`` is the kernel vocabulary: ``PASS`` admits, ``BLOCK`` refuses.
    It is never ``INDETERMINATE`` — the consumer always reaches a decision,
    because "I could not tell" would let the work through on the next reading.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    origin: InputOrigin
    basis: HandoffBasis
    disposition: Disposition
    detail: str = Field(min_length=1)
    """Why this input was admitted or refused. Recorded, not a log line."""

    @property
    def admitted(self) -> bool:
        return self.disposition is Disposition.PASS


def admit(origin: InputOrigin, basis: HandoffBasis | None) -> Admission:
    """The consumer's own rule. Returns the decision; never raises on bad input.

    - A ``None`` basis is refused outright (acceptance test A-T6). A handoff
      basis that was never stated is not the same as one stated to be absent,
      and only the second is a record.
    - ``OPERATOR_DIRECT`` is admitted when its basis is the recorded absence
      :data:`OPERATOR_DIRECT_BASIS`. An operator-direct tasking carrying a
      handoff identifier is refused: it claims an authority nothing issued.
    - ``AGENT_LATERAL`` is admitted only with a recorded identifier. Today
      nothing can issue one, so every lateral input is refused here.
    """
    if basis is None:
        return Admission(
            origin=origin,
            basis=Absent(
                kind=AbsenceKind.NOTHING_RECORDED,
                reason="no handoff basis was stated; null is not a record",
            ),
            disposition=Disposition.BLOCK,
            detail=(
                "Refused at the receiving agent: the handoff basis is null rather than "
                "absent-with-reason. A field nobody filled in is not evidence that no "
                "handoff was required (W3 § R2, AMD1 § 3b)."
            ),
        )
    if origin is InputOrigin.OPERATOR_DIRECT:
        if isinstance(basis, Recorded):
            return Admission(
                origin=origin,
                basis=basis,
                disposition=Disposition.BLOCK,
                detail=(
                    "Refused at the receiving agent: an operator-direct tasking carries a "
                    "handoff identifier. Nothing issues handoff authorizations, so the "
                    "identifier cannot be checked and is not admitted on trust."
                ),
            )
        return Admission(
            origin=origin,
            basis=basis,
            disposition=Disposition.PASS,
            detail=(
                f"Admitted: operator-direct tasking under CAOM-001, handoff basis "
                f"absent ({basis.label})."
            ),
        )
    if isinstance(basis, Absent):
        return Admission(
            origin=origin,
            basis=basis,
            disposition=Disposition.BLOCK,
            detail=(
                f"Refused at the receiving agent: a lateral agent-to-agent input with no "
                f"recorded handoff authorization ({basis.label}). No C2 runtime exists to "
                f"issue one, so every lateral input is refused (W3 § R1, WP-A2)."
            ),
        )
    return Admission(
        origin=origin,
        basis=basis,
        disposition=Disposition.PASS,
        detail=(
            f"Admitted: lateral input carrying recorded C2 handoff {basis.value!r}, checked "
            f"by the receiving agent."
        ),
    )


class RefusedAtConsumerError(PermissionError):
    """Raised by :func:`require_handoff`. Carries the :class:`Admission` refused.

    A ``PermissionError`` rather than a bespoke class: the refusal *record* is
    the kernel-typed :class:`Admission` on the exception, and AMD1 § 3a leaves no
    room for a locally invented refusal type to compete with it. This is control
    flow, and it says so.
    """

    def __init__(self, decision: Admission) -> None:
        super().__init__(decision.detail)
        self.decision = decision


def basis_from_lineage(c2_handoff_id: str | None) -> HandoffBasis:
    """Convert a lineage stub's ``c2_handoff_id`` into a stated handoff basis.

    ``DSORLineageStub.c2_handoff_id`` is ``str | None``, where ``None`` means
    "operator-direct operation". That is the shape AMD1 § 3b exists to correct:
    ``None`` is indistinguishable from a handoff that has not been recorded yet,
    and a reader cannot tell "no handoff was ever required" from "the field was
    not filled in". This function is the boundary where the bare null becomes a
    recorded absence with its reason, before any agent output carries it.

    It is deliberately one-way. The contract type keeps its current shape in this
    work package — changing ``DSORLineageStub`` is a contract change with its own
    blast radius, and the tasking order separates contract work from activation.
    """
    if c2_handoff_id is None:
        return OPERATOR_DIRECT_BASIS
    return Recorded[str](value=c2_handoff_id)


def require_handoff(origin: InputOrigin, basis: HandoffBasis | None) -> Admission:
    """:func:`admit`, raising :class:`RefusedAtConsumerError` when the input is refused.

    For call sites that cannot continue with a refused input. The refusal is
    carried on the exception so the caller records it rather than inventing one.
    """
    decision = admit(origin, basis)
    if not decision.admitted:
        raise RefusedAtConsumerError(decision)
    return decision
