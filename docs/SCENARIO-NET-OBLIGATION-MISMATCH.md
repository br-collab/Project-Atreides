# Scenario 02 - Net-Obligation Mismatch: The Framework Does Not Settle to Its Own Number

*Atreides scenario write-up · Settlement Execution (Phase 06) · net-obligation gate*

**Objective:**
Demonstrate the reconciliation control that compares the tasked delivery against the CCP's published net settlement obligation, and the deliberate refusal to resolve a discrepancy without a human decision.

**Scenario Inputs:**

- Rail: `FICC_GSD_DVP`
- Tasked delivery: 10.0M
- FICC published net obligation: 10.5M
- Delta: 500K, direction under-delivery
- Data provenance: synthetic fixture, not a live feed

**Gate Path:**

1. **Phases 01 to 05** clear. The operation is well-formed, eligible, routed to an approved path, cross-validated against the inherent-safety requirement, and below the quorum threshold.

2. **Phase 06 - Settlement Execution.** The Tier 1 Settlement Operations Analyst runs the ordered checks. DSOR pre-trade lineage matches. Intraday funding is sufficient. Clearing-fund compliance passes. **The net-obligation check does not.** The tasked figure and the CCP's published figure disagree by 500K.

3. **Phase 07 - Decision-of-Record.** The hold, the two figures, and the delta are appended.

**Decision:**

**ESCALATED.** The operation holds at the net-obligation gate. The discrepancy detail - both figures and the delta, not merely the fact of a mismatch - is captured in the escalation record.

**The Judgment:**

There are four things the framework could do here, and three of them are wrong.

- **Settle the tasked 10.0M.** Under-delivers against the CCP's obligation. The shortfall surfaces the next morning as a fail, with no record of who chose to ignore the published figure.
- **Settle the published 10.5M.** Silently adopts the CCP's number over the firm's own. If the firm's figure was the correct one - a late trade not yet reflected, an allocation still in flight - the firm has just over-delivered on someone else's arithmetic.
- **Split, adjust, or auto-reconcile.** Invents a third number that neither party asserted.
- **Hold, record both figures, and escalate.** The only action that preserves the information needed to decide correctly.

The framework takes the fourth. It does not resolve the discrepancy, because a discrepancy between the firm's obligation and the CCP's obligation is not an arithmetic problem - it is a question about which upstream record is stale, and no gate can answer that from the two numbers alone. What the gate can do is refuse to proceed while the question is open, and preserve both inputs so the human who resolves it is working from evidence rather than reconstruction.

**Consequence:**

- A 500K under-delivery against a published net obligation lands as a settlement fail, with the associated fail charge and, on the wrong security, buy-in exposure.
- A 500K over-delivery lands as an unreconciled position that has to be unwound bilaterally.
- Either resolved silently by a system: the following morning nobody can say what the firm believed its obligation to be at the moment of settlement. That is the reconstruction failure that turns an operational break into an audit finding.

**Doctrine and Provenance Note:**
This is the reconciliation control in its narrowest and most defensible form: compare two authoritative sources, and where they disagree, hold and record rather than choose. The framework prepares, governs, and reconciles; the entitled member submits. It holds no CCP credential and submits nothing, so the escalation is a decision handed to an operator, not an instruction withheld from a venue. Governing doctrine: `AUR-CUSTODY-CASH-001`. Inputs are synthetic; gate decisions are implemented and tested; live rail execution is roadmap.

**Rubric:**

| Criteria | Definition | Status |
| --- | --- | --- |
| Completeness | Both figures, the delta, the gate, the decision, and the rejected alternatives all stated | Yes |
| Determinism | Same inputs reproduce the same hold and the same escalation record | Yes |
| Provenance | Synthetic inputs disclosed; submission boundary stated | Yes |
| Doctrine trace | Decision names the doctrine section that justifies it | Yes |
