"""Clearing Operator Cockpit — the human-facing settlement decision surface.

Per **AUR-COCKPIT-001 v0.1** (Clearing Operator Cockpit Doctrine),
AUR-CANONICAL-001 v1.6, and AUR-CUSTODY-001 v1.0 (Settlement Operations).

The cockpit governs the operator's decision cycle as it moves *around* —
never *through* — the external clearing (CCP) and settlement (CSD)
portals. It implements the six capability primitives named in
AUR-COCKPIT-001 Section VIII and the five-beat operating cycle in
Section IV:

    1. gather    -> capture_tasking
    2. validate  -> run_validation_gates   (reuses the Settlement
                    Operations Analyst gate set — no divergent gate logic)
    3. prepare   -> emit_instruction_package
    4. submit    -> PERFORMED BY THE ENTITLED MEMBER, OUTSIDE THIS SURFACE
    5. reconcile -> ingest_portal_readback + reconcile_expected_actual
                    + raise_break

THE CARDINAL BOUNDARY (AUR-COCKPIT-001 Section II), enforced structurally
below:

    Atreides prepares - governs - reconciles. The entitled member submits.

- The cockpit NEVER holds CCP/CSD credentials, NEVER auto-submits, and
  NEVER scrapes a portal. There is deliberately no ``submit`` method and
  no credential field anywhere in this module.
- Inbound data enters ONLY as operator-entered readback
  (``ingest_portal_readback``).
- Outbound is a validated instruction package for human entry — a
  structured artifact, never a submission. ``InstructionPackage`` pins
  ``is_submission`` to ``Literal[False]`` so a submission object is
  unconstructible at the type layer.
- CCP and CSD are separate regimes (Section VI): the cockpit keeps
  separate contexts per regime and never flattens them into one
  "depository" abstraction.
- Material-magnitude operations route to quorum before release; under
  CAOM-001 quorum is unavailable, so they HOLD and surface a
  CAOM-transition trigger (AUR-CUSTODY-001 Section VII; canonical
  Section V). No package is emitted.
- Tier 0 Halt propagates across the surface: when the halt predicate is
  set, every primitive refuses (Axiom 9).

Build status per AUR-COCKPIT-001 Section XI: the operating cycle runs on
operator-entered / synthetic inputs. Beat 4 (submission) is permanent
doctrine — no submission capability is ever to be built.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext, gate_under_halt
from cannae_kernel.ids import ActorId, HaltId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from atreides.agents.tier1.outputs import (
    CreditFacilityType,
    GCFPoolCustodian,
    SettlementKind,
    SettlementRail,
    SettlementTaskingRecord,
)
from atreides.agents.tier1.settlement_operations_analyst import (
    SettlementOperationsAnalyst,
    validate_tasking,
)
from atreides.contracts import DSORLineageStub
from atreides.contracts.dsor_stub import CAOMTier
from atreides.dsor import DSORStore
from atreides.escalation import Escalation, EscalationRegister

# Default material-magnitude threshold above which an operation is
# quorum-required. The doctrine fixes no number (per-magnitude threshold
# selection is a Federate/Sovereign operational-specification concern —
# AUR-CUSTODY-001 Section VII / quorum.py). This default is operator-set.
DEFAULT_MATERIAL_MAGNITUDE = Decimal("50000000")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PortalRegime(StrEnum):
    """The two distinct external regimes the cockpit governs around.

    Per AUR-COCKPIT-001 Section VI: the clearing leg (CCP — novation,
    netting, clearing fund) and the settlement/custody leg (CSD —
    securities custody, DvP) are distinct subsidiaries under distinct
    rulebooks. The cockpit maintains SEPARATE contexts and never
    flattens them.
    """

    CCP = "ccp"
    CSD = "csd"


class CycleBeat(StrEnum):
    """The cockpit-owned beats of the five-beat cycle (Section IV).

    Beat 4 (SUBMIT) is deliberately absent — it is the entitled member's
    regulated act, outside the cockpit's authority, and is never recorded
    here as a cockpit action.
    """

    GATHER = "gather"
    VALIDATE = "validate"
    PREPARE = "prepare"
    RECONCILE = "reconcile"


class PackageDisposition(StrEnum):
    """Outcome of ``emit_instruction_package``."""

    EMIT_FOR_HUMAN_ENTRY = "emit_for_human_entry"
    """Gates passed, magnitude sub-material: a governed package is emitted
    as a structured artifact for the entitled member to key."""

    GATE_HELD = "gate_held"
    """A validation gate held. No package is emitted (Section IV Beat 2)."""

    QUORUM_REQUIRED_HOLD = "quorum_required_hold"
    """Material magnitude routes to quorum; quorum is unavailable under
    CAOM-001, so the operation HOLDS and surfaces a CAOM-transition
    trigger. No package is emitted (AUR-CUSTODY-001 Section VII)."""


class BreakLeg(StrEnum):
    """Reconciliation break classification by leg (Section VII)."""

    POSITION = "position_break"
    FUNDING = "funding_break"
    CLEARING_FUND = "clearing_fund_break"
    NET_OBLIGATION = "net_obligation_break"
    RISK_CONTROL = "risk_control_break"
    """The venue reported a risk-control breach (ATR-I-07). A break whether or
    not every amount matches: a declared breach is a control failure in its own
    right, not a discrepancy between two numbers."""


#: Which key in a Reconciliation's ``detail`` carries each leg's figures.
#:
#: Stated as a table rather than derived from the member name. It was derived,
#: with ``leg.value.split("_")[0]``, and that silently worked for two legs and
#: silently failed for the other two: CLEARING_FUND became "clearing" against a
#: key of "clearing_fund", and NET_OBLIGATION became "net" against
#: "net_obligation". Both tickets reached the workbench well-formed and empty -
#: and they are the two legs whose numbers are the entire point of the ticket.
#:
#: An exhaustiveness test asserts every member appears here, so adding a leg
#: without its key fails the suite rather than shipping a blank ticket.
_DETAIL_KEY: dict[BreakLeg, str] = {
    BreakLeg.POSITION: "position",
    BreakLeg.FUNDING: "funding",
    BreakLeg.CLEARING_FUND: "clearing_fund",
    BreakLeg.NET_OBLIGATION: "net_obligation",
    BreakLeg.RISK_CONTROL: "risk_control",
}

#: The readback word for a declared risk-control breach. Compared after
#: stripping and upper-casing: a misspelt breach must still break, because the
#: failure mode of guessing wrong here is a breach that closes clean.
RISK_CONTROL_BREACHED = "BREACHED"


def _is_risk_control_breach(status: str | None) -> bool:
    return status is not None and status.strip().upper() == RISK_CONTROL_BREACHED


#: Fixed identities for the halt context the legacy ``halt_check`` predicate
#: produces. The predicate carries no identity of its own, so the cockpit
#: declares on behalf of its Tier 0 control.
TIER0_HALT_ID = HaltId("hlt_" + "0" * 26)
TIER0_HALT_ACTOR = ActorRef(
    actor_id=ActorId("act_" + "0" * 26),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="atreides-cockpit-tier0-halt",
    entitlement_refs=("AUR-CANONICAL-001 v1.6 Axiom 9",),
    authenticated=True,
)


def tier0_halt_context(declared_at: datetime) -> HaltContext:
    """The kernel halt context for a raised cockpit ``halt_check``: all domains."""
    return HaltContext(
        halt_id=TIER0_HALT_ID,
        version=1,
        active=True,
        scope="ALL",
        declared_by=TIER0_HALT_ACTOR,
        declared_at=declared_at,
        reason="Tier 0 Halt raised through the cockpit halt_check predicate",
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CockpitHalted(RuntimeError):
    """Raised when a primitive is invoked while Tier 0 Halt is active."""


class CockpitBoundaryError(RuntimeError):
    """Raised on an attempt that would cross the cardinal boundary."""


# ---------------------------------------------------------------------------
# Models (frozen, extra-forbid — no hidden credential/submission fields)
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CockpitTasking(_Frozen):
    """Structured transaction picture captured at Beat 1 (Section V inbound).

    Operator-entered readback only. Carries the transaction picture the
    gates read; carries no credential or entitlement.
    """

    operation_id: UUID
    regime: PortalRegime
    rail: SettlementRail
    settlement_kind: SettlementKind
    counterparty_id: str
    cusip: str | None = None
    settlement_date: datetime
    authority_tier: CAOMTier
    authority_id: str
    captured_at: datetime

    # Net settlement obligation (operator readback)
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None
    ficc_published_net_delivery: Decimal | None = None

    # Intraday funding / credit position (operator readback)
    intraday_credit_limit: Decimal | None = None
    intraday_credit_current_usage: Decimal | None = None
    credit_facility_type: CreditFacilityType | None = None

    # Clearing-fund status (operator readback)
    ficc_clearing_fund_compliant: bool = True

    # FICC netting configuration
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None

    def pre_operation_state_hash(self) -> str:
        """Deterministic SHA-256 of the captured picture — the pre-operation
        DSOR state hash the lineage stub binds (Axiom 4)."""
        payload = self.model_dump(mode="json", exclude={"captured_at"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class GateResult(_Frozen):
    """Outcome of Beat 2 validation against the Settlement Operations
    Analyst gate set. On a hold, ``passed`` is False and no package may be
    emitted.

    Validation writes nothing (ATR-I-02), so this result references no DSOR
    record. It used to carry ``dsor_pre_trade_record_id``, which named the
    settlement telemetry validation had persisted - not a pre-trade record.
    That name is gone from the codebase (R5); the DSOR record comes from
    Beat 3 and is on the package as ``dsor_record_id``.
    """

    operation_id: UUID
    regime: PortalRegime
    passed: bool
    #: The record kind Beat 3 will persist: settlement telemetry on a pass,
    #: settlement escalation on a hold. Nothing has been persisted yet.
    output_kind: str
    checks_evaluated: tuple[str, ...]
    discrepancy_code: str | None = None
    detail: str | None = None


class InstructionPackage(_Frozen):
    """Beat 3 output — a governed, exportable instruction package.

    A structured artifact for human entry, carrying a DSOR pre-trade
    record reference and an authority stamp. It is NEVER a submission:
    ``is_submission`` is pinned to ``Literal[False]`` so a submission
    package cannot be constructed. There is no credential field.

    The pin holds at runtime on every path (ATR-I-03): only the value
    ``False`` is accepted, so ``0`` is not a spelling of it, and :meth:`model_copy`
    revalidates, because Pydantic's default copy skips validation and would
    otherwise let ``update={"is_submission": True}`` through.
    """

    operation_id: UUID
    regime: PortalRegime
    disposition: PackageDisposition
    rail: SettlementRail
    settlement_kind: SettlementKind
    cusip: str | None
    net_delivery_quantity: Decimal | None
    net_payment_amount: Decimal | None
    #: The DSOR record Beat 3 persisted: telemetry when emitted for human
    #: entry, the escalation when the gate held. ``None`` for a quorum hold,
    #: where no instruction was issued and nothing is recorded as emitted.
    dsor_record_id: UUID | None
    authority_stamp: dict[str, str]
    quorum_required: bool
    for_human_entry: bool
    is_submission: Literal[False] = False
    notes: str | None = None

    @field_validator("is_submission", mode="before")
    @classmethod
    def _exactly_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError(
                f"is_submission must be False, got {value!r}: Atreides never "
                f"constructs a submission (ATR-I-03)"
            )
        return value

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> Self:
        """Copy with validation, so an update cannot produce a submission."""
        if not update:
            return super().model_copy(deep=deep)
        return self.model_validate({**self.model_dump(), **update})


class PortalReadback(_Frozen):
    """Beat 5 inbound — operator-entered post-submission portal state.

    ``source`` is pinned to operator readback. The cockpit never obtains
    this by scraping or via credentials.
    """

    operation_id: UUID
    regime: PortalRegime
    source: Literal["operator_readback"] = "operator_readback"
    ingested_at: datetime
    position_balance: Decimal | None = None
    clearing_fund_deficit: Decimal | None = None
    ccp_net_obligation: Decimal | None = None
    intraday_credit_usage: Decimal | None = None
    risk_control_status: str | None = None


class Reconciliation(_Frozen):
    """Beat 5 output — expected-vs-actual diff with per-leg breaks."""

    operation_id: UUID
    regime: PortalRegime
    matched: bool
    breaks: tuple[BreakLeg, ...] = ()
    detail: dict[str, dict[str, str]] = Field(default_factory=dict)
    #: Escalations raised by this reconciliation, by id. A risk-control breach
    #: raises one (ATR-I-07); see ``ClearingCockpit.escalations``.
    escalation_ids: tuple[str, ...] = ()


class BreakTicket(_Frozen):
    """A break routed to the workbench with full lineage (Section VII)."""

    break_id: str
    operation_id: UUID
    regime: PortalRegime
    leg: BreakLeg
    detail: str
    dsor_record_id: UUID | None
    raised_at: datetime
    status: Literal["OPEN_ON_WORKBENCH"] = "OPEN_ON_WORKBENCH"


# ---------------------------------------------------------------------------
# The cockpit
# ---------------------------------------------------------------------------


class ClearingCockpit:
    """The Clearing Operator Cockpit surface.

    One instance per operator session. Holds separate CCP and CSD
    contexts and a per-operation cycle ledger — the replayable lineage
    of the gather -> validate -> prepare -> reconcile cycle (Section IV
    "Audit" is cross-cutting).

    The cockpit reuses :class:`SettlementOperationsAnalyst` for Beat 2:
    the gate logic is not reimplemented here, so there is exactly one
    settlement gate set in the estate (Parity Principle).
    """

    def __init__(
        self,
        dsor_store: DSORStore | None = None,
        *,
        material_magnitude_threshold: Decimal = DEFAULT_MATERIAL_MAGNITUDE,
        halt_check: Callable[[], bool] | None = None,
        doctrine_version: str = "1.6",
        caom_mode: str = "CAOM-001",
        escalation_register: EscalationRegister | None = None,
        halt: Callable[[], HaltContext | None] | None = None,
    ) -> None:
        """``halt`` supplies the kernel halt context in force (ATR-I-06).

        ``halt_check`` is the older boolean predicate. It still works: a true
        result produces an all-domain halt context (:func:`tier0_halt_context`),
        so there is one halt mechanism, not two. Where both are given, either
        one halting halts the cockpit.
        """
        self._store = dsor_store if dsor_store is not None else DSORStore(":memory:")
        self._escalations = (
            escalation_register if escalation_register is not None else EscalationRegister()
        )
        self._analyst = SettlementOperationsAnalyst()
        self._threshold = material_magnitude_threshold
        self._halt_check = halt_check
        self._halt = halt
        self._doctrine_version = doctrine_version
        self._caom_mode = caom_mode

        # Separate regime contexts — NEVER flattened (Section VI).
        self._ccp_context: dict[UUID, CockpitTasking] = {}
        self._csd_context: dict[UUID, CockpitTasking] = {}

        # Per-operation replayable cycle ledger (Section IV Audit).
        self._ledger: dict[UUID, list[dict]] = {}

        # The break workbench (Section VII).
        self._workbench: list[BreakTicket] = []

    # -- boundary guards ---------------------------------------------------

    def current_halt(self) -> HaltContext | None:
        """The halt context in force for this cockpit, if any halt blocks Atreides."""
        if self._halt is not None:
            ctx = self._halt()
            if ctx is not None and gate_under_halt(ctx, Domain.ATREIDES) is Disposition.BLOCK:
                return ctx
        if self._halt_check is not None and self._halt_check():
            return tier0_halt_context(datetime.now(tz=UTC))
        return None

    def _guard_halt(self, primitive: str) -> HaltContext | None:
        """Refuse the primitive under a halt; otherwise return the context consulted."""
        ctx = self.current_halt()
        if ctx is not None:
            raise CockpitHalted(
                f"Tier 0 Halt active (halt {ctx.halt_id}, version {ctx.version}: "
                f"{ctx.reason}) — cockpit primitive {primitive!r} refused. "
                "AUR-CANONICAL-001 v1.6 Axiom 9; ATR-I-06."
            )
        return None

    def _context_for(self, regime: PortalRegime) -> dict[UUID, CockpitTasking]:
        return self._ccp_context if regime is PortalRegime.CCP else self._csd_context

    def _ledger_append(self, operation_id: UUID, beat: CycleBeat, obj) -> None:
        self._ledger.setdefault(operation_id, []).append(
            {"beat": beat.value, "at": datetime.now(tz=UTC).isoformat(), "record": obj}
        )

    # -- Beat 1: gather ----------------------------------------------------

    def capture_tasking(
        self,
        *,
        regime: PortalRegime,
        rail: SettlementRail,
        settlement_kind: SettlementKind,
        counterparty_id: str,
        settlement_date: datetime,
        authority_id: str,
        authority_tier: CAOMTier = CAOMTier.T1,
        operation_id: UUID | None = None,
        cusip: str | None = None,
        net_delivery_quantity: Decimal | None = None,
        net_payment_amount: Decimal | None = None,
        ficc_published_net_delivery: Decimal | None = None,
        intraday_credit_limit: Decimal | None = None,
        intraday_credit_current_usage: Decimal | None = None,
        credit_facility_type: CreditFacilityType | None = None,
        ficc_clearing_fund_compliant: bool = True,
        sponsoring_member_id: str | None = None,
        gcf_pool_custodian: GCFPoolCustodian | None = None,
    ) -> CockpitTasking:
        """Beat 1 — structured intake of the transaction picture.

        Stores the tasking in the regime-appropriate context and opens the
        cycle ledger. Purely a capture step: nothing here reaches a portal.
        """
        self._guard_halt("capture_tasking")
        tasking = CockpitTasking(
            operation_id=operation_id or uuid.uuid4(),
            regime=regime,
            rail=rail,
            settlement_kind=settlement_kind,
            counterparty_id=counterparty_id,
            cusip=cusip,
            settlement_date=settlement_date,
            authority_tier=authority_tier,
            authority_id=authority_id,
            captured_at=datetime.now(tz=UTC),
            net_delivery_quantity=net_delivery_quantity,
            net_payment_amount=net_payment_amount,
            ficc_published_net_delivery=ficc_published_net_delivery,
            intraday_credit_limit=intraday_credit_limit,
            intraday_credit_current_usage=intraday_credit_current_usage,
            credit_facility_type=credit_facility_type,
            ficc_clearing_fund_compliant=ficc_clearing_fund_compliant,
            sponsoring_member_id=sponsoring_member_id,
            gcf_pool_custodian=gcf_pool_custodian,
        )
        self._context_for(regime)[tasking.operation_id] = tasking
        self._ledger_append(tasking.operation_id, CycleBeat.GATHER, tasking)
        return tasking

    # -- Beat 2: validate --------------------------------------------------

    def run_validation_gates(self, tasking: CockpitTasking) -> GateResult:
        """Beat 2 — run the tasking through the Settlement Operations Analyst
        gate set (intraday funding -> clearing fund -> net obligation ->
        DSOR lineage). A hold here is caught before anything reaches a
        portal; no package is emitted on a held gate.

        Pure with respect to the decision of record (ATR-I-02): no route is
        selected, no reference created, no telemetry or DSOR record written.
        Only the in-memory cycle ledger records that validation ran.
        """
        self._guard_halt("run_validation_gates")
        validation = validate_tasking(self._tasking_record(tasking))
        result = GateResult(
            operation_id=tasking.operation_id,
            regime=tasking.regime,
            passed=validation.passed,
            output_kind="settlement_telemetry" if validation.passed else "settlement_escalation",
            checks_evaluated=validation.checks_evaluated,
            discrepancy_code=(
                None if validation.discrepancy_code is None else validation.discrepancy_code.value
            ),
            detail=validation.failure_detail,
        )
        self._ledger_append(tasking.operation_id, CycleBeat.VALIDATE, result)
        return result

    def _tasking_record(self, tasking: CockpitTasking) -> SettlementTaskingRecord:
        """The analyst's tasking record for a cockpit tasking, built deterministically.

        Identifiers derive from the captured picture (UUID version 5 of its
        pre-operation state hash), so Beat 2 and Beat 3 build the same record
        and validation creates no new reference.
        """
        pre_hash = tasking.pre_operation_state_hash()
        lineage_stub = DSORLineageStub(
            operation_id=tasking.operation_id,
            doctrine_version=self._doctrine_version,
            caom_mode=self._caom_mode,
            authority_tier=tasking.authority_tier,
            authority_id=tasking.authority_id,
            initiated_at=tasking.captured_at,
            c2_handoff_id=None,  # operator-direct under CAOM-001
            pre_operation_state_hash=pre_hash,
        )
        derived = uuid.uuid5(uuid.NAMESPACE_URL, f"atreides:cockpit:{pre_hash}")
        return SettlementTaskingRecord(
            task_id=derived,
            operation_id=tasking.operation_id,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            counterparty_id=tasking.counterparty_id,
            deadline=tasking.settlement_date,
            lineage_stub=lineage_stub,
            net_cusip=tasking.cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            ficc_published_net_delivery=tasking.ficc_published_net_delivery,
            intraday_credit_limit=tasking.intraday_credit_limit,
            intraday_credit_current_usage=tasking.intraday_credit_current_usage,
            credit_facility_type=tasking.credit_facility_type,
            ficc_clearing_fund_compliant=tasking.ficc_clearing_fund_compliant,
            sponsoring_member_id=tasking.sponsoring_member_id,
            gcf_pool_custodian=tasking.gcf_pool_custodian,
        )

    # -- Beat 3: prepare ---------------------------------------------------

    def emit_instruction_package(
        self, tasking: CockpitTasking, gate_result: GateResult
    ) -> InstructionPackage:
        """Beat 3 — emit a governed instruction package, or HOLD.

        Emits only on a clean gate pass AND sub-material magnitude.
        Material magnitude routes to quorum, which is unavailable under
        CAOM-001, so the operation HOLDS (no package). The output is
        always an artifact for human entry — never a submission.

        This is the emission stage (ATR-I-02): the only cockpit step that
        writes to the DSOR. A held gate persists its escalation; an emitted
        package persists its settlement telemetry, with no rail
        acknowledgement. A quorum hold persists nothing, because no
        instruction was issued.
        """
        self._guard_halt("emit_instruction_package")
        if gate_result.operation_id != tasking.operation_id:
            raise CockpitBoundaryError("gate_result/operation_id mismatch")
        record = self._tasking_record(tasking)
        validation = validate_tasking(record)
        if validation.passed != gate_result.passed:
            raise CockpitBoundaryError(
                "gate_result no longer matches the tasking; re-run Beat 2 before emitting"
            )
        emit_now = gate_result.passed and not self._is_material(tasking)
        dsor_record_id: UUID | None = None
        if not gate_result.passed or emit_now:
            _, dsor_record = self._analyst.emit(record, validation, self._store)
            dsor_record_id = dsor_record.record_id

        authority_stamp = {
            "authority_tier": tasking.authority_tier.value,
            "authority_id": tasking.authority_id,
            "doctrine_version": self._doctrine_version,
            "caom_mode": self._caom_mode,
        }
        base = dict(
            operation_id=tasking.operation_id,
            regime=tasking.regime,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            cusip=tasking.cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            dsor_record_id=dsor_record_id,
            authority_stamp=authority_stamp,
        )

        if not gate_result.passed:
            pkg = InstructionPackage(
                disposition=PackageDisposition.GATE_HELD,
                quorum_required=False,
                for_human_entry=False,
                notes=(
                    f"Gate held ({gate_result.discrepancy_code}); no package emitted. "
                    "AUR-COCKPIT-001 Section IV Beat 2."
                ),
                **base,
            )
            self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
            return pkg

        if not emit_now:
            pkg = InstructionPackage(
                disposition=PackageDisposition.QUORUM_REQUIRED_HOLD,
                quorum_required=True,
                for_human_entry=False,
                notes=(
                    "Material magnitude — quorum required (default 3-of-5). "
                    "Quorum is unavailable under CAOM-001: operation HOLDS and "
                    "surfaces a CAOM-transition trigger. No package emitted. "
                    "AUR-CUSTODY-001 Section VII; canonical Section V."
                ),
                **base,
            )
            self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
            return pkg

        pkg = InstructionPackage(
            disposition=PackageDisposition.EMIT_FOR_HUMAN_ENTRY,
            quorum_required=False,
            for_human_entry=True,
            notes="Validated instruction package for entitled-member entry. Not a submission.",
            **base,
        )
        self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
        return pkg

    def _is_material(self, tasking: CockpitTasking) -> bool:
        magnitude = tasking.net_payment_amount
        if magnitude is None:
            magnitude = tasking.net_delivery_quantity
        return magnitude is not None and abs(magnitude) >= self._threshold

    # -- Beat 5: reconcile -------------------------------------------------

    def ingest_portal_readback(
        self,
        *,
        operation_id: UUID,
        regime: PortalRegime,
        position_balance: Decimal | None = None,
        clearing_fund_deficit: Decimal | None = None,
        ccp_net_obligation: Decimal | None = None,
        intraday_credit_usage: Decimal | None = None,
        risk_control_status: str | None = None,
    ) -> PortalReadback:
        """Beat 5 inbound — accept operator-entered post-submission state.

        Readback only. The cockpit never obtains this via credentials or
        scraping (Section V "Prohibited, without exception").
        """
        self._guard_halt("ingest_portal_readback")
        if operation_id not in self._context_for(regime):
            raise CockpitBoundaryError(
                f"readback for unknown {regime.value} operation {operation_id}"
            )
        readback = PortalReadback(
            operation_id=operation_id,
            regime=regime,
            ingested_at=datetime.now(tz=UTC),
            position_balance=position_balance,
            clearing_fund_deficit=clearing_fund_deficit,
            ccp_net_obligation=ccp_net_obligation,
            intraday_credit_usage=intraday_credit_usage,
            risk_control_status=risk_control_status,
        )
        self._ledger_append(operation_id, CycleBeat.RECONCILE, readback)
        return readback

    def reconcile_expected_actual(
        self,
        expected: InstructionPackage,
        readback: PortalReadback,
        *,
        expected_position: Decimal | None = None,
    ) -> Reconciliation:
        """Beat 5 — diff expected vs actual; classify discrepancies by leg.

        Compares the emitted package (expected) against operator readback
        (actual) and classifies any divergence into POSITION / FUNDING /
        CLEARING_FUND / NET_OBLIGATION breaks (Section VII).
        """
        self._guard_halt("reconcile_expected_actual")
        if expected.operation_id != readback.operation_id:
            raise CockpitBoundaryError("expected/readback operation mismatch")

        tasking = self._context_for(readback.regime).get(readback.operation_id)
        breaks: list[BreakLeg] = []
        detail: dict = {}

        # NET_OBLIGATION leg: CCP net obligation vs expected net payment.
        if (
            readback.ccp_net_obligation is not None
            and expected.net_payment_amount is not None
            and readback.ccp_net_obligation != expected.net_payment_amount
        ):
            breaks.append(BreakLeg.NET_OBLIGATION)
            detail["net_obligation"] = {
                "expected": str(expected.net_payment_amount),
                "actual": str(readback.ccp_net_obligation),
            }

        # CLEARING_FUND leg: any positive deficit is a break.
        if readback.clearing_fund_deficit is not None and readback.clearing_fund_deficit > 0:
            breaks.append(BreakLeg.CLEARING_FUND)
            detail["clearing_fund"] = {"deficit": str(readback.clearing_fund_deficit)}

        # FUNDING leg: intraday usage at/above the captured facility limit.
        if (
            readback.intraday_credit_usage is not None
            and tasking is not None
            and tasking.intraday_credit_limit is not None
            and readback.intraday_credit_usage >= tasking.intraday_credit_limit
        ):
            breaks.append(BreakLeg.FUNDING)
            detail["funding"] = {
                "usage": str(readback.intraday_credit_usage),
                "limit": str(tasking.intraday_credit_limit),
            }

        # RISK_CONTROL leg: a declared breach is a break regardless of amounts,
        # and it escalates (ATR-I-07). Before Wave 2 the status was ingested
        # and never read, so a breach with matching amounts closed clean.
        escalation_ids: list[str] = []
        if _is_risk_control_breach(readback.risk_control_status):
            breaks.append(BreakLeg.RISK_CONTROL)
            detail["risk_control"] = {"status": str(readback.risk_control_status)}
            escalation = self._escalations.raise_escalation(
                Escalation(
                    escalation_id=(
                        f"ESC-{str(readback.operation_id)[:8]}-risk_control-"
                        f"{len(self._escalations) + 1}"
                    ),
                    operation_id=readback.operation_id,
                    # The register reads no clock: offsets run from the
                    # operation's capture, which both records carry.
                    raised_at_offset_seconds=(
                        int((readback.ingested_at - tasking.captured_at).total_seconds())
                        if tasking is not None
                        else 0
                    ),
                    reason=(
                        f"Venue readback reports risk_control_status="
                        f"{readback.risk_control_status!r} for operation "
                        f"{readback.operation_id} ({readback.regime.value}). A declared "
                        f"risk-control breach is a break even where every amount matches "
                        f"(AUR-COCKPIT-001 SVII; ATR-I-07)."
                    ),
                    routed_to=(
                        f"authority_tier:{tasking.authority_tier.value}"
                        if tasking is not None
                        else "authority_tier:unknown"
                    ),
                )
            )
            escalation_ids.append(escalation.escalation_id)

        # POSITION leg: readback position vs expected position (delivery qty).
        exp_pos = expected_position
        if exp_pos is None and expected.net_delivery_quantity is not None:
            exp_pos = expected.net_delivery_quantity
        if (
            readback.position_balance is not None
            and exp_pos is not None
            and readback.position_balance != exp_pos
        ):
            breaks.append(BreakLeg.POSITION)
            detail["position"] = {
                "expected": str(exp_pos),
                "actual": str(readback.position_balance),
            }

        recon = Reconciliation(
            operation_id=readback.operation_id,
            regime=readback.regime,
            matched=not breaks,
            breaks=tuple(breaks),
            detail=detail,
            escalation_ids=tuple(escalation_ids),
        )
        self._ledger_append(readback.operation_id, CycleBeat.RECONCILE, recon)
        return recon

    def raise_break(
        self, reconciliation: Reconciliation, dsor_record_id: UUID | None
    ) -> list[BreakTicket]:
        """Route each reconciliation break to the workbench with lineage.

        One ticket per broken leg, each carrying the DSOR record Beat 3
        persisted (``InstructionPackage.dsor_record_id``) so the workbench can
        replay the full cycle (Section VII).
        """
        self._guard_halt("raise_break")
        tickets: list[BreakTicket] = []
        for leg in reconciliation.breaks:
            ticket = BreakTicket(
                break_id=f"BRK-{str(reconciliation.operation_id)[:8]}-{leg.value}",
                operation_id=reconciliation.operation_id,
                regime=reconciliation.regime,
                leg=leg,
                detail=json.dumps(reconciliation.detail.get(_DETAIL_KEY[leg], {})),
                dsor_record_id=dsor_record_id,
                raised_at=datetime.now(tz=UTC),
            )
            tickets.append(ticket)
            self._workbench.append(ticket)
        return tickets

    # -- Audit (cross-cutting) --------------------------------------------

    def get_cycle_ledger(self, operation_id: UUID) -> list[dict]:
        """Return the replayable gather->validate->prepare->reconcile
        lineage for one operation (Section IV Audit)."""
        return list(self._ledger.get(operation_id, []))

    @property
    def workbench(self) -> list[BreakTicket]:
        """Open break tickets routed to the workbench."""
        return list(self._workbench)

    @property
    def escalations(self) -> EscalationRegister:
        """The register escalations raised by this cockpit are recorded in."""
        return self._escalations


__all__ = [
    "TIER0_HALT_ACTOR",
    "TIER0_HALT_ID",
    "BreakLeg",
    "BreakTicket",
    "ClearingCockpit",
    "CockpitBoundaryError",
    "CockpitHalted",
    "CockpitTasking",
    "CycleBeat",
    "GateResult",
    "InstructionPackage",
    "PackageDisposition",
    "PortalReadback",
    "PortalRegime",
    "Reconciliation",
    "tier0_halt_context",
]
