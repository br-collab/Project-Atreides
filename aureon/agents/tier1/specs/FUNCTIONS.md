# FUNCTIONS.md

**Function inventory for the Tier 1 (Thifur-R) agent workforce.**

This document enumerates the deterministic functions encoded across the four Tier 1 agent skill specifications in `agents/`, separates asset-class-agnostic primitive functions from configuration-dependent functions, and serves as the canonical inventory for any subsequent implementation against the doctrine. It is the bridge between the doctrine's role-level specification and the implementation-level function signatures the sandbox build will target.

---

## Doctrine anchor

This inventory is bound to:

- `AUR-CANONICAL-001 v1.5.1` Section IV — Thifur as Workforce, Tier 1 Execution and Operations.
- `AUR-CANONICAL-001 v1.5.1` Section II — Thifur-R · Ranger · Deterministic Execution.
- `AUR-CANONICAL-001 v1.5.1` Section III — Architectural Axioms 2, 3, 4, and 9.
- `AUR-PT-AGNOSTIC-001 v1.0` — Post-Trade Primitive Agnosticity Doctrine. The primitive-vs-configuration distinction below is the implementation-level rendering of `AUR-PT-AGNOSTIC-001 §II`.
- The four Tier 1 skill files at `agents/*.md` v0.2.

Drift between this inventory and any of the above is resolved by treating the doctrine as authoritative.

---

## Function inventory by agent

### Settlement Operations Analyst — 4 functions

| # | Function | Primitive / Configuration | Doctrine anchor |
|---|---|---|---|
| 1 | `verify_dsor_pre_trade_record` | Primitive | Canonical §II R-class; `AUR-PT-AGNOSTIC-001 §II` |
| 2 | `route_settlement_instruction` | Primitive (rail identity is configuration) | Canonical §IV; `AUR-PT-AGNOSTIC-001 §II` |
| 3 | `match_rail_confirmation` | Primitive | Canonical §IV (five-second internal alert; no US statutory equivalent governs settlement-confirmation timing) |
| 4 | `escalate_fail_or_break` | Primitive | Canonical Axiom 3, R-class guardrail (immediate escalation on discrepancy) |

### Trade Support Analyst — 3 functions

| # | Function | Primitive / Configuration | Doctrine anchor |
|---|---|---|---|
| 5 | `capture_fill` | Primitive | Canonical §IV; `AUR-PT-AGNOSTIC-001 §II` |
| 6 | `apply_allocation` | Primitive | Canonical §IV; R-class no-judgment guardrail |
| 7 | `stamp_lineage` | Configuration (protocol identity: FIX, on-chain, hybrid) | Canonical §IV; `AUR-PT-AGNOSTIC-001 §II` |

### Reconciliation Analyst — 3 functions

| # | Function | Primitive / Configuration | Doctrine anchor |
|---|---|---|---|
| 8 | `match_dsor_to_downstream` | Primitive | Canonical §IV; Axiom 3 |
| 9 | `detect_inverse_break` | Primitive | Canonical §IV |
| 10 | `escalate_break_within_one_cycle` | Primitive | Canonical §IV (one-cycle escalation requirement) |

### Regulatory Reporting Analyst — 4 functions

| # | Function | Primitive / Configuration | Doctrine anchor |
|---|---|---|---|
| 11 | `verify_source_record_set` | Primitive | Canonical §IV; Axiom 4 (one lineage record) |
| 12 | `generate_regulatory_report` | Configuration (schema parameterized by deployment domain) | Canonical §IV; `AUR-PT-AGNOSTIC-001 §II` |
| 13 | `validate_against_schema` | Configuration (schema parameterized) | Canonical §IV |
| 14 | `monitor_sla_timeliness` | Primitive | Canonical §IV (five-second internal SLA alert) |

### Shared across all four agents — 1 function

| # | Function | Primitive / Configuration | Doctrine anchor |
|---|---|---|---|
| 15 | `emit_lineage_fragment` | Primitive | Canonical Axiom 4 (one lineage record) |

**Total: 15 functions. 12 primitives. 3 configuration-dependent.**

The 12 primitive functions are asset-class-agnostic per `AUR-PT-AGNOSTIC-001 §II`. The 3 configuration-dependent functions are asset-class-aware only at the parameter layer; the function signature itself does not change across deployment domains.

---

## Uniform function contract

Every function in the inventory follows the same contract, derived from the R-class guardrails (canonical §II) and the architectural axioms:

**Inputs (received from Thifur-C2 only):**

1. **Tasking record.** Specifies what the function should do, against which DSOR records, with which configuration parameters (rail identity, allocation instructions, schema identity, etc.).
2. **DSOR reference.** Read-only handle to the relevant DSOR records for verification.
3. **Active doctrine version stamp.** Delivered by Kaladan via C2; binds the function execution to a specific doctrine version for replay purposes.

**Outputs (emitted to Thifur-C2 only):**

1. **Execution telemetry.** What the function did, with timestamps and status.
2. **Discrepancy events** (if any). Full record of any condition that triggered escalation.
3. **Lineage fragment.** The function's contribution to the unified DSOR lineage record assembled by C2.

**Behavioral invariants (apply to every function):**

- **No self-initiation** — the function is never invoked except through a C2 tasking record.
- **No agent-to-agent communication** — outputs flow to C2 only, never to another agent directly. This is the architectural enforcement of canonical Axiom 3 (Handoff Before Action).
- **No silent retry** — discrepancies escalate immediately. The function does not attempt remediation.
- **Immutable lineage** — the lineage fragment is stamped at execution and never modified post-execution.
- **Halt compliance** — when the Tier 0 Emergency Halt is active, no function executes. (Canonical Axiom 9.)

The uniform contract is what makes the agnosticity claim operationally enforceable: every function looks the same from C2's perspective, regardless of deployment domain. Asset-class context is in the tasking record's parameters, not in the function signature.

---

## Configuration parameters by deployment domain

The three configuration-dependent functions (`stamp_lineage`, `generate_regulatory_report`, `validate_against_schema`) are parameterized by the active deployment domain. The parameter sets currently specified or anticipated:

### eFICC (active deployment domain)

| Function | Configuration Parameters |
|---|---|
| `stamp_lineage` | FIX 4.4 / 5.0 SP2 protocol family identifiers; FICC GSD trade identifiers; tri-party agent allocation references |
| `generate_regulatory_report` | TRACE schema; MSRB schema; CFTC swaps schema; FINRA OATS schema; SFTR schema; MiFIR schema |
| `validate_against_schema` | Schema validators corresponding to each generated report type |

### Equities (anticipated deployment domain, readiness gate pending)

| Function | Configuration Parameters |
|---|---|
| `stamp_lineage` | FIX equity-specific extensions; CAT identifiers |
| `generate_regulatory_report` | CAT schema; Reg NMS reporting schema; equity-specific FINRA reports |
| `validate_against_schema` | Schema validators for each |

### Tokenized securities (anticipated deployment domain, readiness gate pending)

| Function | Configuration Parameters |
|---|---|
| `stamp_lineage` | Hybrid FIX-plus-on-chain identifiers; smart-contract event signatures |
| `generate_regulatory_report` | Active tokenized-securities regulatory regime (evolving) |
| `validate_against_schema` | Schema validators for each |

### Native digital assets (anticipated deployment domain, readiness gate pending)

| Function | Configuration Parameters |
|---|---|
| `stamp_lineage` | On-chain transaction identifiers; wallet attribution |
| `generate_regulatory_report` | FinCEN reporting where applicable; jurisdiction-specific |
| `validate_against_schema` | Schema validators for each |

The full parameter sets per deployment domain are specified in the deployment-readiness documents anticipated under `AUR-PT-AGNOSTIC-001 §VII` (e.g., `AUR-DEPLOY-EQUITY-001`, `AUR-DEPLOY-TOK-001`, `AUR-DEPLOY-DIGITAL-001`). This document lists the placeholders.

---

## Implementation contract suggestions

This section is non-doctrinal guidance for the sandbox build. It is not binding and may be revised through normal engineering workflow without doctrine amendment.

The 15 functions decompose naturally into a Python (or equivalent) module with the following shape:

- A `TaskingRecord` dataclass capturing the C2 input contract.
- A `DSORReference` dataclass for read-only DSOR access.
- A `LineageFragment` dataclass capturing the per-function lineage output.
- A `DiscrepancyEvent` dataclass for escalation packaging.
- A `Telemetry` dataclass for non-discrepancy execution telemetry.
- A base agent class implementing the uniform contract — receive tasking, verify, execute, emit — with the four agent classes inheriting and implementing their specific functions.
- A `LineageFragmentEmitter` mixin or trait providing the shared `emit_lineage_fragment` function.
- Test harnesses for each function with deterministic test cases verifying R-class behavior (same input, same output) and discrepancy paths (escalation triggers without retry).

The implementation is stubbable. The contract is the value. Building the test harness against the uniform contract before any rail-specific or schema-specific code is written is the recommended weekend build sequence.

---

## Versioning

| Field | Value |
|---|---|
| FUNCTIONS.md version | v0.1 |
| Doctrine version | Aureon Doctrine v1.8 |
| Last revision | Initial draft, derived from agent skill files at v0.2 and `AUR-PT-AGNOSTIC-001 v1.0` |
| Revision authority | Operator (CAOM-001), via propose/approve doctrine workflow per canonical §VIII for material changes; engineering workflow for non-binding implementation guidance updates |

---

*Aureon · Tier 1 Function Inventory*
