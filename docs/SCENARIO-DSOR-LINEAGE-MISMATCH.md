# Scenario 03 - DSOR Lineage Mismatch: Fail-Safe, Not Fail-Open

*Atreides scenario write-up · Settlement Execution (Phase 06) · DSOR pre-trade verification*

**Objective:**
Demonstrate the framework's behaviour when the governance record itself is the thing that is wrong, and establish the default that governs every gate: an absent or non-matching decision resolves to HOLD, never to PROCEED.

**Scenario Inputs:**

- Rail: `FICC_GSD_DVP`
- Condition under test: `operation_id` does not match the pre-trade lineage stub
- The operation is otherwise clean - funded, eligible, within limits, correctly routed
- Data provenance: synthetic fixture, not a live feed

**Gate Path:**

1. **Phases 01 to 05** clear. Nothing about the operation itself is defective.

2. **Phase 06 - Settlement Execution.** DSOR pre-trade verification is the first ordered check the Tier 1 Settlement Operations Analyst runs, before funding, before clearing fund, before the net obligation. The operation carries a lineage reference that does not resolve to the pre-trade decision record. **The sequence stops here**, and the four downstream checks are never reached.

3. **Phase 07 - Decision-of-Record.** The hold is appended with the mismatch detail.

**Decision:**

**ESCALATED.** The framework refuses to settle an operation it cannot tie to a matching pre-trade record.

**The Judgment:**

This is the scenario that looks like a technicality and is not. Every other gate in the sequence asks whether the *operation* is sound. This gate asks whether the *governance* is sound - whether the thing about to settle is the thing that was authorised.

The tempting behaviour is to proceed. The operation is funded, eligible, and within every limit; the lineage reference is metadata; a system optimised for throughput treats a metadata mismatch as a warning and settles. That system has just executed a transaction that cannot afterwards be attributed to any approval. Nobody can say who authorised it, under what constraint, or against which mandate - not because the record was destroyed, but because it never existed in a form that could be matched.

The framework fails toward the safe state instead. `absent_gate_decision()` is a named exported function precisely so that "what happens when governance did not run" has exactly one auditable answer rather than an implicit answer at every call site, and the Tier 2 FIAT Operations Specialist refuses to select a cash rail without a gate decision, returning an escalation under `NO_SETTLEMENT_WITHOUT_LINEAGE`. The ordering is also deliberate: lineage is checked first because there is no point evaluating the economics of an operation whose authority cannot be established.

**Consequence:**

- Settling without matching lineage produces a transaction that is unreconstructible after the fact. The money moved correctly and the record cannot prove it.
- That is the distinction between an operational error, which is explained and closed, and a control failure, which is escalated to a regulator and answered for.
- The cost is not the notional. The cost is that the firm cannot demonstrate the decision was governed, which is the entire claim the platform exists to support.

**Doctrine and Provenance Note:**
Fail-safe, not fail-open, is an architectural commitment rather than a configuration choice. Where the gate is unavailable the answer is HOLD; where the lineage does not match the answer is HOLD; where finality cannot be observed the answer is `INDETERMINATE` rather than an assertion. Refusing to claim what cannot be verified is the governance decision most systems get wrong, and it is the reason the decision-of-record can be replayed years later from its recorded inputs. Governing doctrine: `AUR-CANONICAL-001`, `AUR-CUSTODY-CASH-001`. Inputs are synthetic; gate decisions are implemented and tested; the DSOR is append-only by construction, and cryptographic hash-chaining is roadmap - no tamper-evidence is claimed.

**Rubric:**

| Criteria | Definition | Status |
| --- | --- | --- |
| Completeness | Condition, gate ordering, decision, tempting alternative, and consequence all stated | Yes |
| Determinism | Same inputs reproduce the same hold and the same record | Yes |
| Provenance | Synthetic inputs disclosed; hash-chaining stated as roadmap, not claimed | Yes |
| Doctrine trace | Decision names the doctrine sections and the named guardrail that justify it | Yes |
