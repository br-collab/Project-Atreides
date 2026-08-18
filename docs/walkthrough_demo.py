"""Runnable companion to docs/CASH-LEG-WALKTHROUGH.md.

Follows one USD 1,000,000 cash leg from funding check to instruction
package. Every output in the walkthrough is produced by this script.

    python docs/walkthrough_demo.py
"""
from datetime import UTC, datetime
from decimal import Decimal

from atreides.messaging import (
    CashLegInstruction,
    FinancialInstitution,
    emit_instruction_artifact,
    settlement_method_for_rail,
)
from atreides.rails.cato_f import (
    CashRail,
    FinalityClass,
    OperationContext,
    RailState,
    RailStatus,
    absent_gate_decision,
    evaluate,
)
from atreides.rails.funding_state import CashFlow, FundingInputs, project_funding

D, T0 = Decimal, datetime(2026, 8, 3, 14, 30, tzinfo=UTC)
line = lambda t: print(f"\n{'='*66}\n{t}\n{'='*66}")

# ---- 1. Can it settle? -------------------------------------------------
line("1. FUNDING — can this leg settle at all?")
short = FundingInputs(
    opening_position=D("250000"), obligation=D("1000000"),
    finality_class=FinalityClass.GROSS_FINAL,
    settlement_offset_seconds=1800, window_close_offset_seconds=14400,
    flows=(CashFlow(5400, D("900000"), "incoming FICC net receipt"),),
    net_debit_cap=D("50000000"),
    clearing_fund_requirement=D("500000"), clearing_fund_posted=D("500000"),
)
p = project_funding(short)
print(f"  disposition        : {p.disposition.value}")
print(f"  shortfall          : {p.shortfall}")
print(f"  clears at          : +{p.funded_at_offset_seconds}s")
print(f"  is_failure         : {p.is_failure}   <-- a queue is NOT a failure")

funded = FundingInputs(
    opening_position=D("5000000"), obligation=D("1000000"),
    finality_class=FinalityClass.GROSS_FINAL,
    settlement_offset_seconds=1800, window_close_offset_seconds=14400,
    net_debit_cap=D("50000000"),
    clearing_fund_requirement=D("500000"), clearing_fund_posted=D("500000"),
)
pf = project_funding(funded)
print(f"\n  funded case        : {pf.disposition.value}  (settles={pf.settles})")

# ---- 2. Which rail, and how final? -------------------------------------
line("2. CATO-F — which cash rail, and what finality?")
rails = {
    CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
    CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
    CashRail.FEDNOW: RailState(CashRail.FEDNOW, RailStatus.AVAILABLE, None, D("1000000")),
    CashRail.PORTS_WHOLESALE: RailState(CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED),
}
op = OperationContext(
    notional=D("1000000"), currency="USD",
    is_material=False, is_lvps_material=True,
)
g = evaluate(operation=op, funding=pf.to_gate_input(), rails=rails, ofr_stlfsi4=0.12)
print(f"  decision           : {g.decision.value}")
print(f"  recommended_rail   : {g.recommended_rail.value}")
print(f"  finality_class     : {g.finality_class.value}")
print(f"  rationale          : {g.rationale}")

stressed = evaluate(operation=op, funding=pf.to_gate_input(), rails=rails, ofr_stlfsi4=0.75)
print(f"\n  under stress (0.75): {stressed.decision.value} / {stressed.reason_code.value}")
unfunded = evaluate(operation=op, funding=p.to_gate_input(), rails=rails, ofr_stlfsi4=0.12)
print(f"  queued leg         : {unfunded.decision.value} / {unfunded.reason_code.value}")
print(f"  gate missing       : {absent_gate_decision().decision.value}  <-- never PROCEED")

# ---- 3. Onto the wire ---------------------------------------------------
line("3. ISO 20022 — the instruction package")
method = settlement_method_for_rail(g.recommended_rail)
print(f"  rail {g.recommended_rail.value!r} -> SettlementMethod1Code {method.value!r}")
instr = CashLegInstruction(
    message_id="AUR20260803000117", end_to_end_id="TSY-SETTL-000117",
    created_at=T0, amount=D("1000000.00"), currency="USD",
    debtor=FinancialInstitution("CHASUS33", "Debtor Bank NA"),
    creditor=FinancialInstitution("BOFAUS3N"),
    settlement_method=method,
    sender=FinancialInstitution("CHASUS33"),
    receiver=FinancialInstitution("DTCYUS33"),
    dsor_lineage_uri="dsor://operation/117",
)
art = emit_instruction_artifact(instr)
print(f"  message_definition : {art.message_definition}")
print(f"  profile            : {art.profile_name} (verified={art.profile_verified})")
print(f"  is_submission      : {art.is_submission}  <-- Literal[False], unconstructible otherwise")
print("\n" + art.document_xml.decode().replace("><", ">\n<")[:520])

# ---- 4. The rail we must not guess -------------------------------------
line("4. RAILS WITH NO pacs EXPRESSION — raise, never default")
for r in (CashRail.TOKENIZED_DEPOSIT, CashRail.PORTS_WHOLESALE):
    try:
        settlement_method_for_rail(r)
    except ValueError as e:
        print(f"  {r.value:20s} -> {str(e)[:70]}...")
