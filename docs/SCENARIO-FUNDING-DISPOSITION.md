# Scenario 01 - Funding Disposition: A Queued Payment Is Not a Failed Payment

*Atreides scenario write-up · Settlement Execution (Phase 06) · intraday funding gate*

**Objective:**
Demonstrate how the intraday funding model answers the question "can this leg settle at all," and why the distinction between a queued instruction and a failed instruction is the single most consequential judgment on a gross-final rail.

**Scenario Inputs:**

- Rail: `FICC_GSD_DVP` (gross-final finality class)
- Operation: US Treasury delivery-versus-payment, cash leg funded from an intraday credit facility
- Condition under test: the instruction amount cannot be covered by the available intraday position at the moment of evaluation
- Data provenance: synthetic fixture, not a live feed

**Gate Path:**

1. **Phase 01 - Operation Intake.** Typed custody operation validated against the contract substrate. A malformed operation never reaches a funding question.

2. **Phase 02 - Eligibility.** KYC, KYB, OFAC and sanctions screening, correspondent-bank compliance.

3. **Phase 03 - Path Selection.** Tier 2 FIAT Operations Specialist enumerates from the pre-declared approved-path registry across seven doctrine-defined dimensions and assigns a settlement rail. The agent never constructs a path at decision time; an empty match returns `EscalationRequired` under `APPROVED_PATHS_ONLY`.

4. **Phase 04 - Inherent-Safety and Failure-Mode.** Unrecoverable failure surfaces are cross-validated against the quorum requirement.

5. **Phase 05 - Quorum Authority.** Material magnitude routing. Routing decision is built; the signature ceremony is roadmap.

6. **Phase 06 - Settlement Execution.** The Tier 1 Settlement Operations Analyst evaluates DSOR pre-trade lineage, then the intraday funding position, then clearing-fund compliance, then the net obligation, then the rail. **This scenario halts here, at the funding sub-gate.**

7. **Phase 07 - Decision-of-Record.** Append-only, DTG-stamped, deterministically replayable.

**The Disposition Set:**

The funding model does not return a boolean. It returns one of six dispositions, because "can it settle" has six materially different answers:

| Disposition | Meaning | Correct operator action |
| --- | --- | --- |
| `FUNDED` | Position covers the instruction | Proceed |
| `WILL_QUEUE` | Unfunded now; queues and settles when funding arrives | Wait. Do not re-issue. |
| `WILL_FAIL` | Will not settle on this rail under these conditions | Remediate before submission |
| `CAP_BREACH` | Facility cap reached | Hold and escalate |
| `CLEARING_FUND_DEFICIENT` | Clearing-fund obligation not met | Hold and escalate |
| `INDETERMINATE` | Finality is not observable on this path | Refuse to assert; escalate |

**Decision (as exercised in the console fixture):**

The `Intraday Credit Breach` scenario runs credit usage at 500M against a 500M facility cap. Disposition: `CAP_BREACH`. Outcome: **ESCALATED**. The operation holds at the funding gate and escalates to Command and Control with no path deviation, and the escalation itself is written to the decision record.

**The Judgment:**

On a gross-final rail an unfunded instruction does not fail. It **queues**, and it settles when funding arrives. A system that classifies a queued instruction as a failure, and re-issues on that basis, has created a duplicate payment. Once a gross-final payment is final, the settlement system cannot reverse it. Recovery is counterparty goodwill or litigation.

For that reason `is_failure` deliberately excludes `WILL_QUEUE`, and the model reports the offset at which the shortfall clears rather than a bare negative. Both facts are true at once - the instruction is not funded, and the instruction is not failed - and collapsing them into a single boolean is the mechanism by which duplicate payments happen.

**Consequence:**

- Misclassifying `WILL_QUEUE` as failure: an irreversible duplicate payment at the full notional of the instruction.
- Misclassifying `CAP_BREACH` as fundable: a facility breach discovered by the provider rather than declared by the operator.
- Treating all six dispositions as one: no operator can tell "wait" from "fix it," which is the difference between a non-event and a break.

**Doctrine and Provenance Note:**
Finality class drives treatment. The funding model reads the rail's finality class before it interprets a shortfall, because the same shortfall means different things on gross-final, deferred-net, ledger-final, and correspondent-dependent rails. Where the gate is unavailable the answer is HOLD, never PROCEED: `absent_gate_decision()` is a named exported function so that "what happens when governance did not run" is answered in one auditable place rather than at every call site. Governing doctrine: `AUR-CUSTODY-CASH-001`, CATO-F specification. Inputs are synthetic; gate decisions are implemented and tested; live rail execution is roadmap.

**Rubric:**

| Criteria | Definition | Status |
| --- | --- | --- |
| Completeness | Inputs, gate path, disposition, decision, and consequence all stated | Yes |
| Determinism | Same inputs reproduce the same disposition and the same record, byte for byte | Yes |
| Provenance | Synthetic inputs disclosed; built and roadmap components distinguished | Yes |
| Doctrine trace | Each decision names the doctrine section that justifies it | Yes |
