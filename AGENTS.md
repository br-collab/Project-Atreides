# AGENTS.md

**Tier 1 agent skill specifications for the Aureon Post-Trade eFICC workforce.**

This document indexes the four Tier 1 agent skill files in the `agents/` directory and documents the scope boundary that determines what does and does not belong in this repository at the current doctrine version. It is the developer-facing entry point to the agent layer; the architectural and governance specifications remain in the canonical doctrine.

---

## Doctrine anchor

The Aureon workforce is specified in `AUR-CANONICAL-001 v1.5.1` Section IV — Thifur as Workforce — Post-Trade eFICC Agent Specification. Eleven agent roles span three operational tiers. Each role maps to a real institutional job description, a Thifur agent class, a task registry, a guardrail set, and a regulatory framework alignment.

The eleven roles are locked in doctrine. Under `AUR-PT-AGNOSTIC-001 v1.0` (Aureon Doctrine v1.7), the role specifications are reframed as asset-class-agnostic primitives with eFICC as the first deployment domain rather than the architectural scope. This repository operationalizes only the four Tier 1 (Thifur-R, deterministic) roles at v0.2. The remaining seven roles — four Tier 2 (Thifur-J, bounded autonomy) and three Tier 3 (Thifur-H, adaptive advisory) — are documented in canonical Section IV but are deliberately not specified as skill files in this repository. The reasons are stated in the *Out-of-Scope* section below.

The architectural family that backs the workforce — Thifur-C2, Thifur-R, Thifur-J, Thifur-H — is specified in canonical Section II. C2, R, J, and H are governance layers, not workforce roles. They do not receive skill files. The four Tier 1 skill files in `agents/` operate under the Thifur-R class and inherit R-class guardrails directly from canonical Section II.

The function inventory underlying the four skill files — fifteen deterministic functions, twelve primitives and three configuration-dependent — is documented in `agents/FUNCTIONS.md`.

---

## Tier 1 — Execution and Operations (R-class)

Tier 1 agents operate under Thifur-R: strict determinism, zero variance permitted. Same input always produces the same output. These agents replace the highest-volume, most manual operational roles in post-trade. Per `AUR-PT-AGNOSTIC-001 v1.0`, the Tier 1 primitives are asset-class-agnostic; the eFICC (electronic Fixed Income, Currencies, and Commodities) deployment domain is the first active deployment domain, with subsequent deployment domains activated through explicit deployment-readiness doctrine events.

The regulatory anchor for the Tier 1 primitives is SR 11-7 Tier 2 deterministic, OCC 2023-17 (Office of the Comptroller of the Currency Bulletin on Third-Party Risk Management) third-party registry, BCBS 239 (Basel Committee on Banking Supervision Principle 239) Principle 3 automated accuracy, and DORA (Digital Operational Resilience Act) RTO (Recovery Time Objective) 15 minutes for settlement on the primary path. Five-second internal alert thresholds for confirmation mismatch and SLA breach are an operational SLA enforced across all Tier 1 agents; no US statutory equivalent governs the specific timing metric. Deployment-domain-specific regulatory configuration (TRACE, MSRB, CFTC, FINRA OATS, SFTR, MiFIR for eFICC; CAT and Reg NMS for equities; etc.) is specified per agent skill file.

| Agent | Skill File | Cost Displacement |
|---|---|---|
| Settlement Operations Analyst | `agents/settlement-operations-analyst.md` | $85K — $110K |
| Trade Support Analyst | `agents/trade-support-analyst.md` | $80K — $105K |
| Reconciliation Analyst | `agents/reconciliation-analyst.md` | $80K — $105K |
| Regulatory Reporting Analyst | `agents/regulatory-reporting-analyst.md` | $80K — $110K |

---

## Skill file convention

Each Tier 1 skill file follows a fixed structure derived from the canonical Section IV role description, the Thifur-R guardrails in canonical Section II, and the agnostic-primitive framing in `AUR-PT-AGNOSTIC-001 §V`. The structure is:

1. **Doctrine anchor** — exact citation of the canonical sections and subordinate doctrines that bind the agent.
2. **Thifur class and tier** — Thifur-R, Tier 1.
3. **Scope** — what the agent does, framed as asset-class-agnostic primitives plus the active deployment-domain configuration (currently eFICC).
4. **R-class guardrails** — inherited from canonical §II, restated in agent-specific terms.
5. **Inputs and outputs** — what the agent receives via Thifur-C2 handoff and what it emits.
6. **Escalation protocol** — the discrepancy triggers and the routing through C2.
7. **Regulatory mapping** — the specific frameworks and articles the agent's behavior supports.
8. **Out-of-scope** — split into architecturally out-of-scope (never within Aureon's boundary) and deployment-domain out-of-scope (within architectural scope but not yet activated as a deployment domain), per `AUR-PT-AGNOSTIC-001 §V`.

The structure exists so that each skill file can be evaluated independently against the canonical doctrine. Drift between a skill file and the canonical doctrine is resolved by treating the canonical doctrine as authoritative and revising the skill file through the propose/approve doctrine workflow specified in canonical Section VIII.

The function-level decomposition of the four skill files is documented in `agents/FUNCTIONS.md`.

---

## Architectural constraints binding all Tier 1 agents

These constraints are inherited from the canonical doctrine and cannot be overridden by any skill file. They are restated here as a single reference because the same constraints apply uniformly across all four Tier 1 skill files.

**Axiom 2 — Agents Advise, Operators Decide.** No agent at any layer holds approval authority. Agents surface analysis, enforce pre-configured rules, and emit telemetry. Every approval gate requires explicit operator action.

**Axiom 3 — Handoff Before Action.** No Thifur agent acts on a lifecycle object without a recorded Thifur-C2 handoff authorization. Agent-to-agent direct transfers are illegal. Tier 1 agents never receive input from another Tier 1, Tier 2, or Tier 3 agent — only from C2.

**Axiom 4 — One Lineage Record.** The DSOR receives the C2-assembled unified lineage, never raw agent telemetry. Gaps in agent telemetry are flagged explicitly — never silently filled.

**Axiom 9 — Tier 0 Emergency Halt Above All Doctrine.** When the Emergency Halt is active, all Thifur execution is frozen immediately — including every Tier 1 agent — regardless of any other authority or doctrine version active.

**R-class guardrails (canonical §II).** Zero variance — no path selection, no optimization, no judgment. No self-initiation — every action requires a C2-issued tasking record. No settlement without DSOR confirmation — every instruction traces to a pre-trade record. Immediate escalation on discrepancy — no silent retry, no retry without human authority. Immutable lineage — stamped at execution, never modified post-execution.

These five constraints are the architectural floor for every Tier 1 skill file in this repository. Skill files restate them in agent-specific terms but do not relax them.

---

## Out-of-scope (explicit non-coverage)

The following are deliberately not specified as skill files in this repository at the current doctrine version. The reasons are doctrinal, not editorial.

**Tier 2 agents (Thifur-J, bounded autonomy).** Compliance Monitoring, Trade Surveillance Fixed Income, Risk Reporting, and AML/KYC are specified as roles in canonical §IV but require formal documentation of pre-approved path sets, doctrine-conflict-hold logic, and integration with Verana autonomous-block authority that have not yet been articulated at skill-file resolution. J-class agents select among pre-approved paths and never generate new ones; the path inventories are not specified at the resolution required to operationalize as skills.

**Tier 3 agents (Thifur-H, adaptive advisory).** Portfolio Risk, Model Risk SR 11-7, and Data Governance are specified as roles in canonical §IV and operate under the two-state distinction (advisory active, autonomous declared not activated) documented in canonical §II. Tier 3 skill files would need to document the advisory/autonomous boundary and the SR 11-7 Tier 1 independent validation gate that controls activation per domain. Neither is in scope at the current doctrine version.

**Custody operational specifications.** The custody object type inventory is specified in `AUR-CUSTODY-OBJ-001 v1.0` (Aureon Doctrine v1.8). The operational specifications — `AUR-CUSTODY-FED-001` for Atreides Federate Phase 1 governance overlay and `AUR-CUSTODY-INST-001` for Atreides Sovereign — inherit from the object-type inventory and the agnosticity framing but are not yet drafted. Custody-specific agent skill files (e.g., a Pledged Collateral Operations Analyst, a Private-Key Custody Operations Analyst, a Beneficial-Owner Reporting Analyst) are anticipated as part of `AUR-CUSTODY-FED-001` drafting.

**Quorum-required operations.** Defined in canonical §V as a future-mode primitive and explicitly declared out of scope under CAOM-001 (Consolidated Authority Operating Mode). `AUR-CUSTODY-OBJ-001 §V` makes the dependency more concrete: pledged-asset custody at material magnitude (Category 2) and native digital asset custody (Category 5) require quorum authority operationalization. Until that operationalization is complete, no skill file in this repository may cover operations requiring N-of-M signing.

**Architectural layers (Mentat, Kaladan, Verana, Thifur-C2, Thifur-Atrox).** These are governance and orchestration layers, not workforce roles. They are specified in canonical §II and are not represented as skill files. The Tier 1 agents in `agents/` interact with these layers through doctrine-defined interfaces (C2 handoff, Kaladan governed intent packets, Verana network-state checks, DSOR write-through to Kaladan), but the layers themselves are out of scope for the agent skill format.

**Market actions.** No agent in this repository ever takes a market action — no order generation, no position modification, no settlement instruction issued without operator approval recorded in the lineage. This is doctrine, not policy: canonical §I states explicitly that no layer of Aureon, including the most autonomous, takes a market action under any condition.

**Deployment domains beyond eFICC.** Per `AUR-PT-AGNOSTIC-001 §V`, the Tier 1 agent primitives apply across nine asset classes within the post-trade primitive scope, but operational activation in each non-eFICC deployment domain (equities, listed derivatives, OTC derivatives, FX, tokenized securities, native digital assets) requires an explicit deployment-readiness doctrine event before any skill file's regulatory mapping or escalation protocol applies in that domain.

---

## Versioning

Each skill file carries a version stamp matching the doctrine version it was written against. Tier 1 skill files at v0.2 are written against canonical doctrine v1.5.1, reframed under `AUR-PT-AGNOSTIC-001 v1.0` (v1.7) and informed by `AUR-CUSTODY-OBJ-001 v1.0` (v1.8). Material revisions to canonical Section II (Thifur architectural family), Section IV (eFICC workforce specification), or any binding subordinate doctrine trigger a corresponding skill-file revision through the propose/approve doctrine workflow.

The skill files in `agents/` are not free-text documentation. They are derived artifacts of the canonical doctrine and bound to it. Drift between the two is treated as a doctrine open conflict and logged accordingly in the canonical doctrine's Open Conflicts and Drift Log (canonical §X).

---

## Anticipated subsequent additions

In rough priority order, the additions anticipated to follow this v0.2 of `AGENTS.md`:

1. **Per-asset-class deployment-readiness documents.** Each non-eFICC deployment domain requires an explicit deployment-readiness gate per `AUR-PT-AGNOSTIC-001 §IV`. Documents like `AUR-DEPLOY-EQUITY-001` will specify the configuration parameters, regulatory framework mapping, third-party node registry entries, and failure-mode taxonomy applied to each asset class.
2. **Tier 2 path-set specifications.** Documentation at sufficient resolution to operationalize Tier 2 (Thifur-J) agents as skill files. Specifically, the pre-approved path inventories for compliance routing, surveillance scenario libraries, risk-reporting threshold sets, and AML/KYC eligibility decision sets. Once those exist, four Tier 2 skill files become writable.
3. **`AUR-CUSTODY-FED-001` (Federate Phase 1 custody specification).** Inherits the agnosticity framing from `AUR-PT-AGNOSTIC-001 v1.0` and the object-type inventory from `AUR-CUSTODY-OBJ-001 v1.0`. Will introduce custody-specific roles to the workforce and require corresponding skill files.
4. **Tier 3 advisory/autonomous boundary documentation.** The two-state distinction in canonical §II is architecturally specified but not operationalized at skill-file resolution. Once the advisory-mode operational specification is documented separately from the autonomous-mode activation gates, Tier 3 skill files become writable for advisory mode only, with explicit deferral of autonomous-mode skill specifications to a future version.

---

*Aureon · Guillermo Ravelo · Columbia University M.S. Technology Management*
*AGENTS.md · v0.2 · Aureon Doctrine v1.9*
