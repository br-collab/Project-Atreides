"""Settlement Operations Analyst — Tier 1 · Thifur-R.

Deterministic settlement instruction routing and execution monitoring.
Per AUR-CANONICAL-001 v1.5.1 Section IV (settlement-operations-analyst v0.3)
and AUR-CUSTODY-001 v1.0 Section VI (R-class roles).

Two stages, deliberately separate (ATR-I-02):

1. :func:`validate_tasking` — the pre-routing gates (4 → 5 → 6 → 1), as a
   pure function. It reads the tasking and returns a
   :class:`~atreides.agents.tier1.outputs.SettlementValidation`. It selects no
   route, reads no clock, creates no reference and writes nothing.
2. :meth:`SettlementOperationsAnalyst.emit` — the explicitly named emission
   stage. A held validation persists a
   :class:`~atreides.agents.tier1.outputs.SettlementEscalation`; a passed one
   routes, generates the instruction reference and persists
   :class:`~atreides.agents.tier1.outputs.SettlementTelemetry`.

Before Wave 2 one ``run`` did both, so validating a clean tasking persisted
telemetry with a rail acknowledgement time before any instruction existed.
``run`` remains for callers that want both stages together.

A rail acknowledgement is never set by emission. It is recorded only from a
verified readback, as a correction record: see
:meth:`SettlementOperationsAnalyst.record_rail_acknowledgment`. R-class
guardrails are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cannae_kernel.disposition import Disposition
from cannae_kernel.domains import Domain
from cannae_kernel.halt import HaltContext, gate_under_halt

from atreides.agents.tier1.outputs import (
    DiscrepancyCode,
    RailAcknowledgment,
    SettlementEscalation,
    SettlementOutput,
    SettlementTaskingRecord,
    SettlementTelemetry,
    SettlementValidation,
)
from atreides.dsor import DSORRecord, DSORStore

#: Pre-routing gate names, in evaluation order.
GATE_ORDER: tuple[str, ...] = (
    "monitor_intraday_funding_position",
    "verify_ficc_clearing_fund_compliance",
    "model_ficc_net_settlement_obligation",
    "verify_dsor_pre_trade_record",
)


def validate_tasking(
    tasking: SettlementTaskingRecord, *, halt: HaltContext | None = None
) -> SettlementValidation:
    """Run the pre-routing gates in order. Pure: no clock, route, reference or I/O.

    An active halt covering Atreides holds before any gate runs (ATR-I-06).
    """
    if halt is not None and gate_under_halt(halt, Domain.ATREIDES) is Disposition.BLOCK:
        return _held(
            tasking,
            DiscrepancyCode.HALT_ACTIVE,
            f"Halt {halt.halt_id} (version {halt.version}) is active for Atreides: "
            f"{halt.reason}. Pre-routing hold. Instruction not issued (ATR-I-06).",
        ).model_copy(update={"checks_evaluated": ("halt",)})
    evaluated: list[str] = []
    checks = (
        (GATE_ORDER[0], _intraday_funding_hold),
        (GATE_ORDER[1], _clearing_fund_hold),
        (GATE_ORDER[2], _net_obligation_hold),
        (GATE_ORDER[3], _lineage_hold),
    )
    for name, check in checks:
        evaluated.append(name)
        held = check(tasking)
        if held is not None:
            return held.model_copy(update={"checks_evaluated": tuple(evaluated)})
    return SettlementValidation(
        operation_id=tasking.operation_id, passed=True, checks_evaluated=tuple(evaluated)
    )


def _held(
    tasking: SettlementTaskingRecord,
    code: DiscrepancyCode,
    detail: str,
    *,
    clearing_fund_deficiency: bool = False,
    net_obligation_discrepancy: str | None = None,
) -> SettlementValidation:
    return SettlementValidation(
        operation_id=tasking.operation_id,
        passed=False,
        checks_evaluated=("pending",),
        discrepancy_code=code,
        failure_detail=detail,
        intraday_credit_usage=tasking.intraday_credit_current_usage,
        intraday_credit_limit=tasking.intraday_credit_limit,
        clearing_fund_deficiency=clearing_fund_deficiency,
        net_obligation_discrepancy=net_obligation_discrepancy,
    )


def _intraday_funding_hold(tasking: SettlementTaskingRecord) -> SettlementValidation | None:
    """Primitive 4 (v0.3): hold if intraday credit usage is at or above the facility limit."""
    if (
        tasking.intraday_credit_limit is not None
        and tasking.intraday_credit_current_usage is not None
        and tasking.intraday_credit_current_usage >= tasking.intraday_credit_limit
    ):
        return _held(
            tasking,
            DiscrepancyCode.INTRADAY_CREDIT_THRESHOLD,
            "Intraday credit usage at or above facility limit. "
            "Pre-routing hold. Instruction not issued. "
            "Primitive: monitor_intraday_funding_position. "
            "AUR-CANONICAL-001 v1.5.1 Section IV.",
        )
    return None


def _clearing_fund_hold(tasking: SettlementTaskingRecord) -> SettlementValidation | None:
    """Primitive 5 (v0.3): hold if FICC clearing fund contribution (VaR-based) is deficient."""
    if not tasking.ficc_clearing_fund_compliant:
        return _held(
            tasking,
            DiscrepancyCode.CLEARING_FUND_DEFICIENCY,
            "FICC clearing fund contribution (VaR-based) deficient. "
            "Pre-routing hold. Instruction not issued. "
            "Primitive: verify_ficc_clearing_fund_compliance. "
            "AUR-CANONICAL-001 v1.5.1 Section IV.",
            clearing_fund_deficiency=True,
        )
    return None


def _net_obligation_hold(tasking: SettlementTaskingRecord) -> SettlementValidation | None:
    """Primitive 6 (v0.3): hold if tasking net delivery diverges from FICC's published figure."""
    if (
        tasking.ficc_published_net_delivery is not None
        and tasking.net_delivery_quantity is not None
        and tasking.ficc_published_net_delivery != tasking.net_delivery_quantity
    ):
        return _held(
            tasking,
            DiscrepancyCode.NET_OBLIGATION_MISMATCH,
            "FICC net settlement obligation does not match "
            "FICC-published net delivery position. Pre-routing hold. "
            "Primitive: model_ficc_net_settlement_obligation. "
            "AUR-CANONICAL-001 v1.5.1 Section IV.",
            net_obligation_discrepancy=(
                f"tasking={tasking.net_delivery_quantity!s}; "
                f"ficc_published={tasking.ficc_published_net_delivery!s}"
            ),
        )
    return None


def _lineage_hold(tasking: SettlementTaskingRecord) -> SettlementValidation | None:
    """Primitive 1: verify the lineage stub operation_id matches the tasking operation_id."""
    if tasking.lineage_stub.operation_id != tasking.operation_id:
        return _held(
            tasking,
            DiscrepancyCode.DSOR_MISMATCH,
            "Lineage stub operation_id does not match tasking operation_id. "
            "DSOR pre-trade record verification failed. "
            "Primitive: verify_dsor_pre_trade_record. "
            "AUR-CANONICAL-001 v1.5.1 Section IV.",
        )
    return None


class SettlementOperationsAnalyst:
    """Tier 1 · Thifur-R — Settlement Operations Analyst.

    Fully deterministic: zero variance, no path selection.

    Usage::

        analyst = SettlementOperationsAnalyst()
        validation = validate_tasking(tasking)          # pure
        output, record = analyst.emit(tasking, validation, store)
        # or both at once:
        output, record = analyst.run(tasking, store)
    """

    def run(
        self,
        tasking: SettlementTaskingRecord,
        store: DSORStore,
        *,
        now: datetime | None = None,
        halt: HaltContext | None = None,
    ) -> tuple[SettlementOutput, DSORRecord]:
        """Validate, then emit. Equivalent to ``emit(tasking, validate_tasking(tasking), store)``.

        Args:
            tasking: C2-delivered tasking record (frozen).
            store: DSOR store for output persistence.
            now: Override emission timestamp (testing only).

        Returns:
            ``(output, record)``: the emitted :data:`SettlementOutput` and the
            persisted :class:`DSORRecord`.
        """
        return self.emit(
            tasking, validate_tasking(tasking, halt=halt), store, now=now, halt=halt
        )

    def emit(
        self,
        tasking: SettlementTaskingRecord,
        validation: SettlementValidation,
        store: DSORStore,
        *,
        now: datetime | None = None,
        halt: HaltContext | None = None,
    ) -> tuple[SettlementOutput, DSORRecord]:
        """The emission stage: persist the escalation or route and persist telemetry.

        The only method here that selects a route, creates an instruction
        reference, reads the clock or writes to the DSOR. It never sets a rail
        acknowledgement.

        A halt in effect at emission overrides a validation that passed before
        it was declared: the escalation is persisted instead (ATR-I-06).
        """
        if validation.operation_id != tasking.operation_id:
            raise ValueError("validation and tasking describe different operations")
        if validation.passed and halt is not None:
            validation = validate_tasking(tasking, halt=halt)
        emitted_at = now if now is not None else datetime.now(tz=UTC)

        if not validation.passed:
            esc = self._make_escalation(tasking, validation, emitted_at)
            return esc, store.append(esc, dtg=emitted_at)

        # Primitive 2: route settlement instruction
        instruction_ref = self._route_settlement_instruction(tasking)

        # Primitive 3: match_rail_confirmation is NOT performed here. The rail
        # acknowledgement arrives only from a verified readback, recorded by
        # record_rail_acknowledgment() as a correction of this record.
        telemetry = SettlementTelemetry(
            operation_id=tasking.operation_id,
            task_id=tasking.task_id,
            doctrine_version=tasking.doctrine_version,
            lineage_stub=tasking.lineage_stub,
            emitted_at=emitted_at,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            instruction_reference=instruction_ref,
            net_cusip=tasking.net_cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            clearing_fund_compliant=tasking.ficc_clearing_fund_compliant,
            intraday_credit_usage_at_execution=tasking.intraday_credit_current_usage,
            intraday_credit_limit=tasking.intraday_credit_limit,
            sponsoring_member_id=tasking.sponsoring_member_id,
            gcf_pool_custodian=tasking.gcf_pool_custodian,
        )
        return telemetry, store.append(telemetry, dtg=emitted_at)

    def record_rail_acknowledgment(
        self,
        record: DSORRecord,
        acknowledgment: RailAcknowledgment,
        store: DSORStore,
        *,
        now: datetime | None = None,
    ) -> tuple[SettlementTelemetry, DSORRecord]:
        """Append the rail's acknowledgement as a correction of the telemetry record.

        The original record is never changed (Axiom 4). The acknowledgement
        must come from :meth:`RailAcknowledgment.from_readback`.
        """
        if not isinstance(record.output, SettlementTelemetry):
            raise ValueError("only emitted settlement telemetry can be acknowledged")
        acknowledged = record.output.model_copy(update={"rail_acknowledgment": acknowledgment})
        dtg = now if now is not None else datetime.now(tz=UTC)
        return acknowledged, store.append(acknowledged, dtg=dtg, correction_of=record.record_id)

    # ------------------------------------------------------------------
    # Primitive 2: route_settlement_instruction
    # ------------------------------------------------------------------

    def _route_settlement_instruction(self, tasking: SettlementTaskingRecord) -> str:
        """Generate a deterministic routing reference from rail + task_id.

        Production replaces this with the rail-assigned acknowledgment
        reference (FICC CNS sequence number or Fedwire end-to-end reference).
        """
        task_hex = str(tasking.task_id).replace("-", "")[:12].upper()
        return f"{tasking.rail.value.upper()}-{task_hex}"

    # ------------------------------------------------------------------
    # Internal factory
    # ------------------------------------------------------------------

    def _make_escalation(
        self,
        tasking: SettlementTaskingRecord,
        validation: SettlementValidation,
        now: datetime,
    ) -> SettlementEscalation:
        assert validation.discrepancy_code is not None
        assert validation.failure_detail is not None
        return SettlementEscalation(
            operation_id=tasking.operation_id,
            task_id=tasking.task_id,
            doctrine_version=tasking.doctrine_version,
            lineage_stub=tasking.lineage_stub,
            emitted_at=now,
            rail=None,
            discrepancy_code=validation.discrepancy_code,
            failure_detail=validation.failure_detail,
            intraday_credit_usage=validation.intraday_credit_usage,
            intraday_credit_limit=validation.intraday_credit_limit,
            clearing_fund_deficiency=validation.clearing_fund_deficiency,
            net_obligation_discrepancy=validation.net_obligation_discrepancy,
        )
