# PROJECT AUREON · CONSOLIDATED CANONICAL DOCTRINE v1.6

**PROJECT AUREON**

*The Grid 3*

**AUREON CONSOLIDATED CANONICAL DOCTRINE**

v1.6 — Custody Operationalized · Asset-Services Workforce · Capstone Publication

*Doctrine-governed, AI-augmented financial operating system for the convergence of tokenization, AI execution, and programmable payment rails.*

| Field | Value |
| --- | --- |
| Document ID | AUR-CANONICAL-001 · Consolidated Canonical Doctrine |
| Version | v1.6 · May 2, 2026 |
| Supersedes | Aureon Consolidated Canonical Doctrine v1.5.1 |
| Author | Guillermo "Bill" Ravelo |
| Document Class | Capstone Doctrine Publication |
| Academic | Columbia University · M.S. Technology Management (Incoming, Dean's Fellowship) |
| Doctrine Stack | Aureon Doctrine v1.6 · Cato (mixed: core v0.2.2 / cache v0.2.3) · CAOM-001 (this document) · AUR-CUSTODY-001 v1.0 (custody operational doctrine, delivered as v1.6 substantive addition) |
| Live Deployment | Endowment Series I — Argus · $100M paper AUM (live deployment URL withheld) |
| Status | Paper trading · approaching institutional testing · no real capital at risk |
| Classification | Public — academic framework publication (MIT-licensed code) |

# I. DOCTRINE PREAMBLE

## Purpose

Aureon is the control layer between portfolio intent and execution. It validates doctrine, risk, compliance, and human authority before a signal becomes a market event. Every decision carries an immutable audit lineage — signal origin, doctrine check, risk evaluation, compliance gate, human authority stamp, execution confirmation, settlement evidence — re-constructable on demand for any trade at any granularity within a ten-year retention window.

The thesis is structural, not ornamental. Most financial technology is built execution-first, with governance retrofitted under regulatory pressure. That approach survives until market structure changes faster than institutions can adapt. The convergence already underway — tokenized Treasuries clearing on-chain around the clock, the CFTC confirming tokenized assets as eligible derivatives collateral (December 2025), the GENIUS Act in the legislative pipeline, JPMorgan's first on-chain commercial paper issuance on Solana — will not wait for governance to be retrofitted. Aureon inverts the order: doctrine first, technology built to the doctrine.

## Scope

Aureon governs the decision boundary between signal and execution. It sits above Order Management Systems (OMS), Execution Management Systems (EMS), Smart Order Routers (SOR), and post-trade infrastructure — never inside them. Aureon governs what enters those systems and produces the unified lineage record that trustees, rating agencies, and regulators can rely on. The three deployment modes — governance overlay, full-stack operating system, and compliance artifact engine — are expressions of the same control layer at different integration depths.

## What Aureon Is Not

Aureon is not a broker. It never holds venue connectivity, exchange sessions, or custody relationships. It is not an OMS or EMS — order state, allocations, parent-order lifecycle, and trader execution workflow remain outside Aureon's boundary. It is not a portfolio management replacement; portfolio construction and mandate design remain with the operator and the fund's investment doctrine. It is not a market-action agent — no layer of Aureon, including the most autonomous one, ever takes a market action under any condition. Every agent advises. The operator decides. It is not a counterparty-credit gate; the live settlement gate (Cato) is a market-regime gate, and counterparty-credit signals are an explicit, documented out-of-scope decision pending a future doctrine version.

## Live Deployment — Endowment Series I · Argus

The canonical proof-of-concept runs against a $100M paper-AUM endowment portfolio — Endowment Series I, codename Argus — with a 5% spending-rate target and an intergenerational preservation mandate. Argus is not a generic paper trade; it is a named test harness that stresses the full doctrine stack against a mandate profile representative of institutional endowments, foundations, and sovereign wealth administrators. System of record live inception date: April 7, 2026. Every decision the system has made against Argus is replayable from the DSOR (Decision System of Record).

## Document Genealogy

This is v1.6 of the Aureon Consolidated Canonical Doctrine. It supersedes v1.5.1 (April 27, 2026) through a substantive doctrine addition: `AUR-CUSTODY-001 v1.0` (Aureon Custody Operational Doctrine) is delivered as the v1.6 substantive content, operationalizing the architectural prerequisites established in v1.5 (Axiom 10 inherent-safety, three-class failure-mode taxonomy, quorum authority primitive) within the custody domain and establishing asset-class breadth as the durable architectural axis. Section IV workforce framing is renamed framework-wide from "Post-Trade eFICC" to "Aureon Asset-Services Workforce" to match the asset-class breadth and broader Asset Services strategic positioning. v1.5.1 itself superseded v1.5 (April 26, 2026) through an administrative reframing — the document was reissued as a Columbia M.S. Technology Management capstone publication; no doctrinal substance was modified between v1.5 and v1.5.1. v1.5 itself superseded v1.4 (April 26, 2026), which consolidated and superseded four predecessor artifacts: the Canonical Governing Architecture v1.1 (April 17, 2026), the Consolidated Authority Operating Mode CAOM-001 Draft 1.0 (April 6, 2026, issued under the prior name "Project Arcadia"), the Post-Trade eFICC Agent Specification AUR-PT-EFICC-001 Draft 1.0 (April 2026), and the deployed server.py (live deployment, URL withheld) as the live implementation reconciliation point.

v1.5 adds inherent-safety as a defined doctrinal term, Axiom 10 governing inherent-safety surfaces, the three-class failure-mode taxonomy (RA / RM / UR), and the quorum authority primitive declared as future-mode and out of scope under CAOM-001. These additions are the architectural foundation for v1.6 (custody), the next anticipated major doctrine addition. v1.5 itself does not introduce custody; it makes custody possible to specify cleanly when v1.6 is drafted.

*Where the deployed code diverges from any predecessor document, the live code has been treated as authoritative. Reconciliation actions are tracked in Section X — Open Conflicts and Drift Log.*

# II. LAYER-BY-LAYER ARCHITECTURE

The Aureon stack is not a pipeline. Each layer holds doctrine authority for its own domain. Authority flows top-down. Intelligence flows bidirectionally. No layer operates without the one above it, and no layer substitutes for the human authority tiers declared in CAOM-001 (Section V).

The canonical decomposition renders four governance layers, with the execution layer internally decomposed into the Thifur agent family. An earlier six-layer presentation separated the alpha-origination layer (Atrox) as its own altitude above Mentat. This canonical document treats Atrox as the advisory intent-origination surface feeding Mentat, not as a governance layer — because Atrox is advisory only and holds no independent gate authority. The governance layers are Mentat, Kaladan, Thifur, and Verana.

## Architecture at a Glance

| Layer | Altitude | Doctrine Name | Governance Function |
| --- | --- | --- | --- |
| Layer 3 | 500 ft | Thifur — Agentic Execution | C2 coordination · R deterministic · J bounded autonomy · H adaptive (advisory active, autonomous declared not activated) |
| Layer 2 | 10,000 ft | Kaladan — Lifecycle Orchestration | Approval lineage · DSOR record assembly · evidence packaging · treasury, settlement, compliance artifacts |
| Layer 1 | 30,000 ft | Mentat — Strategic Intelligence | Intent synthesis · scenario support · doctrine truth evaluation · strategy-context framing |
| Layer 0 | Ground | Verana — Network Governance | Session controls · policy boundary enforcement · MCP registry · Cato doctrine gate · supervisory posture |

*Advisory surface above Mentat: Thifur-Atrox (operational nickname: Neptune Spear, retained in code paths only) surfaces alpha hypotheses and pre-trade intent at 50,000 ft. Operator review is required before any Atrox-originated intent reaches Kaladan for structuring. Atrox originates; Kaladan packages; Thifur-C2 coordinates; Thifur R / J / H execute within bounded scope; Verana enforces network state throughout.*

## Layer 1 · Mentat — Strategic Intelligence (30,000 ft)

Mentat is the decision-intelligence layer. It receives operator-approved intent from Atrox, synthesizes portfolio context, frames scenario analysis, and evaluates doctrine truth. Mentat is the only layer authorized to interpret doctrine — every other layer either enforces doctrine (Verana), orchestrates under doctrine (Kaladan), or executes within doctrine bounds (Thifur). When doctrine is ambiguous, only Mentat may resolve it, and only after operator authority closes the resolution loop.

Mentat's responsibilities are: synthesize portfolio intent from Atrox-originated, operator-approved signals into structured decision objects; surface mandate alignment, underweight and overweight flags, conviction scores, and risk framing; evaluate doctrine truth when scenarios encounter ambiguity, presenting both valid paths with rationale to the operator; stamp every downstream Kaladan packet with the active doctrine version; record operator-selected resolutions as doctrine precedent for future scenarios.

Mentat does not approve — it frames; the operator approves. Mentat does not orchestrate execution — Kaladan orchestrates. Mentat does not take network actions — Verana enforces network state.

## Layer 2 · Kaladan — Lifecycle Orchestration (10,000 ft)

Kaladan is the lifecycle orchestration layer. It converts Mentat-framed intent into a governed intent packet carrying the complete pre-trade record: doctrine version stamp, approval lineage, mandate validation, and evidence bundle. The governed intent packet is the only object Thifur-C2 accepts as valid input. Kaladan is also the system of record for the DSOR (Decision System of Record) and owns the assembly of the replayable governance package that every decision, at every granularity, can be reconstructed from.

Kaladan's responsibilities are: assemble the governed intent packet with doctrine version, authority hashes, mandate validation, and evidence bundle; sequence the role-based approval workflow through the authority tiers declared in CAOM-001; package regulatory evidence at every lifecycle stage — pre-trade, execution, post-trade, settlement; surface drawdown guard, position limits, liquidity buffer status, and concentration state; hold degraded-operations state and coordinate fallback sequences across Thifur agents under DORA (Digital Operational Resilience Act); deliver the final unified lineage record — assembled by Thifur-C2 — to the DSOR.

Kaladan does not interpret doctrine — it enforces the version Mentat stamped. Kaladan does not coordinate agent handoff — Thifur-C2 does. Kaladan does not execute — it packages what Thifur will execute.

## Layer 3 · Thifur — Agentic Execution (500 ft)

Thifur is the execution family. It is internally decomposed into four agents: C2 (Command and Control coordination), R (Ranger — deterministic execution), J (JTAC — bounded autonomy), and H (Hunter-Killer — adaptive intelligence). Each agent has bounded scope. Agent-to-agent transfers are illegal. All handoff flows through C2. All escalations present a single unified picture to human authority.

### Thifur-C2 — Command and Control

C2 is the agent orchestration layer between Kaladan's governed intent packet and the execution triplet. C2 does not originate. C2 does not execute. C2 does not interpret doctrine. C2 sequences agent activation, records every handoff, assembles the unified lineage record, and presents a single escalation surface to human authority. C2 is the architectural answer to the multi-agent convergence problem: when a single lifecycle object simultaneously requires deterministic settlement (R), programmable-asset governance (J), and adaptive optimization (H), C2 is the only layer that holds the complete picture.

C2 is also the sole coordination point at the TradFi–DeFi convergence boundary. No Thifur agent on either side of that boundary communicates directly across it. All cross-boundary coordination routes through C2.

| C2 — Five Immutable Stops |
| --- |
| (1) No self-execution. C2 never takes a market action, generates an order, modifies a position, or issues a settlement instruction under any condition. (2) No doctrine interpretation. C2 receives doctrine version stamps from Kaladan; doctrine ambiguity escalates to Mentat via the human authority surface. (3) Handoff before action. No Thifur agent may act on a lifecycle object without a recorded C2 handoff authorization — no exceptions. (4) One lineage record. C2 assembles the unified lineage; DSOR never receives raw agent telemetry as a substitute. Gaps are flagged explicitly — never silently filled. (5) Escalation completeness. C2 never escalates a partial picture. If agent context is pending, C2 waits within defined time bounds before escalating. Gaps are flagged explicitly in the escalation package. |

### Thifur-R — Ranger · Deterministic Execution

Thifur-R governs the TradFi execution domain under strict determinism. Same input, same output. Always. This is the agent that makes a Citi Revlon $900M-class error structurally impossible — zero variance, immutable lineage stamped at execution time, and no retroactive modification under any condition. Thifur-R owns payment rail execution in the convergence model: when a tokenized asset requires traditional-rail settlement, J prepares the instruction package and C2 hands off to R. R never receives input directly from any other agent.

R guardrails: zero variance — no path selection, no optimization, no judgment; no self-initiation — every action requires a C2-issued tasking record; no settlement without DSOR confirmation — every instruction traces to a pre-trade record; immediate escalation on discrepancy — no silent retry, no retry without human authority; immutable lineage — stamped at execution, never modified post-execution.

### Thifur-J — JTAC · Bounded Autonomy

Thifur-J governs the TradFi–DeFi convergence zone — tokenized assets moving through programmable workflows, cross-border flows with jurisdictional constraints, and multi-constraint paths where strict determinism is insufficient but unconstrained optimization is impermissible. JTAC — Joint Terminal Attack Controller — selects among pre-approved paths, never generates new ones. Code does not override doctrine: when smart-contract logic conflicts with Mentat doctrine, J holds execution and escalates to C2.

J guardrails: approved paths only — J selects from the Kaladan-defined routing and lifecycle set, never generates new; doctrine over code — smart contract execution never overrides doctrine, and conflict holds the object; no release without approval lineage — attributed human approval record required in DSOR; eligibility before routing — KYC and KYB and mandate validation must pass before routing; jurisdictional attribution before execution — every cross-border segment requires a Verana-assigned jurisdictional authority.

### Thifur-H — Hunter-Killer · Adaptive Intelligence

Thifur-H is the adaptive optimization agent — VWAP, TWAP, and POV execution strategy; liquidity-aware timing; collateral optimization; FX hedging within doctrine-defined risk parameters. H is the most powerful agent in the architecture and the most scrutinized. Its power and its risk come from the same source: continuous optimization within multi-variable financial domains at machine speed.

| Thifur-H Activation Status — Two-State Distinction |
| --- |
| Thifur-H operates in two distinct modes that require separate doctrine treatment. Advisory mode is ACTIVE in the deployed system: signal surfacing, gate validation, session-bounded execution under explicit operator approval (CAOM-001 HITL), and DSOR write-through against the live Kraken account in the Leto operator console. Every advisory-mode action requires explicit per-signal operator approval. Autonomous mode is DECLARED, NOT ACTIVATED. The continuous optimization surface — VWAP/TWAP/POV strategy selection, autonomous collateral optimization, autonomous FX hedging within risk envelope — is architecturally specified but not enabled. Autonomous activation requires independent SR 11-7 Tier 1 validation per domain, EU AI Act high-risk system registration, and a formal doctrine amendment recorded in the version log. This two-state distinction was previously rendered as a single "declared, not activated" status in v1.1 — that rendering is corrected here against the deployed system. The advisory and autonomous surfaces are governed independently. |

H guardrails apply to both modes: objective function supremacy — H optimizes within Tier 2-approved objective functions only and never redefines its own; doctrine over optimization — an efficient but non-compliant action does not execute; risk parameter hard stops — maximum loss, concentration, and liquidity thresholds are hard stops, and breach triggers automatic suspension; emergency suspension — any Tier 1 or above can suspend H immediately with no prior approval, and resumption requires Tier 2; no autonomous activation without independent validation under SR 11-7 Tier 1; explainability before execution — if an action cannot be explained in human-readable terms, it does not execute.

## Layer 0 · Verana — Network Governance (Ground)

Verana is the network layer. It holds the registry of every node the system interacts with — settlement rails, payment counterparties, tokenized-asset platforms, data sources, MCP servers. It enforces session boundaries, jurisdictional attribution, OFAC screening, doctrine integrity, and systemic-stress monitoring. Verana is the only layer authorized to autonomously block: if a doctrine integrity check fails, Verana stops the session regardless of any other authority present.

Verana's responsibilities are: register every third-party node under OCC 2023-17 with SLA enforcement and pre-staged fallback; enforce session boundary checks at session open (CAOM-001 Step 1); host the Cato settlement doctrine gate as the pre-settlement enforcement point; record the CAOM operating mode declaration in the Network Registry at session open; run the Jurisdictional Boundary Engine for cross-border flow attribution; monitor concentration, systemic stress, and doctrine integrity continuously and autonomously; absorb regulatory mandates autonomously — the doctrine v1.1 bump (DORA Article 28 absorption) was a Verana L0 event, not a human-authority event.

### Cato — The Live Verana Gate

Cato is the Verana L0 pre-settlement doctrine gate for tokenized institutional repo. It answers one question before every settlement: is atomic on-chain Delivery-versus-Payment viable right now, or should this trade route to FICC (Fixed Income Clearing Corporation)? The gate runs four deterministic checks and emits PROCEED, HOLD, or ESCALATE plus a recommended settlement rail.

Cato exists in two implementations that must produce bit-for-bit identical decisions for identical inputs: the external open-source MCP server (Node.js, MIT license, 23 tools at github.com/br-collab/Cato---FICC-MCP) and the in-process Python twin inside Aureon. The deterministic parity — what Section VIII defines as the Parity Principle — is currently in a known mixed state, tracked in the open conflicts log.

### Cato v0.2.2 Thresholds

| Input | Threshold | Effect |
| --- | --- | --- |
| OFR STLFSI4 | > 1.0 | ESCALATE — systemic stress, route to human authority |
| OFR STLFSI4 | > 0.5 | HOLD — broad stress, route to FICC traditional |
| ETH L1 gas | > 50 gwei | HOLD — L1 congestion, route to FICC traditional |
| \|SOFR(t) − SOFR(t−1)\| × 100 | > 10 bps | HOLD — funding-market shock (v0.2.2 Sept 2019 backtest fix) |
| All below threshold | — | PROCEED — atomic settlement viable |

### Supported Settlement Rails

| Rail | Speed | Cost (normal state) | Status |
| --- | --- | --- | --- |
| FICC traditional | T+1 | ~0.5 bps net of 40% netting + SOFR cost of capital | Live |
| Ethereum L1 | ~12s | ~$0.08 at 0.5 gwei, $2,300 ETH | Live |
| Base (Ethereum L2) | ~2s | ~$0.001 at 0.01 gwei | Live |
| Arbitrum (L2) | ~2s | ~$0.10 at 0.6 gwei | Live |
| Solana | ~400ms | ~$0.0004 at 5,000 lamports | Live |
| Fed L1 / PORTS | Instant | TBD — sovereign tokenized reserve rail | Pending GENIUS Act |

*The governance gate — not the rail — is the product. When the Fed issues tokenized reserves or PORTS ships, Cato routes there. The doctrine does not change. The rail does. The fed_l1 placeholder slot in every Cato chain_state response is reserved for exactly that event (Duffie, 2025, "The Case for PORTS," Brookings).*

### SR 11-7 Tier 1 Backtest — Cato v0.2.2

| Event | v0.2.1 | v0.2.2 | Verdict |
| --- | --- | --- | --- |
| March 2020 — COVID repo freeze | 100% (20/20) | 100% (20/20) | ✓ Caught — OFR peak 5.657, SOFR Δ 84 bps |
| September 2019 — repo spike | 0% (0/5) | 80% (4/5) | ✓ Caught after v0.2.2 fix — pure funding crunch |
| March 2023 — SVB collapse | 45.5% (5/11) | 45.5% (5/11) | ! Calibration limit — slow credit event, not in stress signals |

*The September 2019 gap closed in v0.2.2 by restoring the SOFR one-day delta trigger dropped in the v0.2.0 refactor. SVB is a documented calibration limitation — it requires counterparty-credit signals (HY OAS, bank equity) not currently in the doctrine. Cato is a market-regime gate, not a counterparty-credit gate. That is a design choice, not a gap. A future Cato version may extend into credit signals; that extension will be a doctrine amendment, not a patch.*

# III. GOVERNANCE AXIOMS

These are the rules the system enforces on itself. They are not configurable. They are not overridden by any agent. They may only be modified by the operator through the Doctrine Modification Governance workflow (Section VIII). Every axiom is architecturally enforced — not aspirational.

## Doctrinal Term: Inherent-Safety

The doctrine uses the term inherent-safety with a specific technical meaning, separate from its colloquial use. An inherent-safety surface is one where the failure mode requires multiple independent simultaneous failures to produce loss, each of which is itself bounded below institutional risk thresholds under stated assumptions. Inherent-safety does not claim impossibility. Cryptographic security fails at computationally bounded rates under stated assumptions. Hardware security modules fail at measurable rates per operation. Inherent-safety claims that the failure surface has been driven below the threshold of any plausible institutional risk-modeling framework, and that single-point failure cannot produce loss.

This distinction matters because zero-fail in the colloquial sense does not exist for any real system, and the doctrine must not claim what no system can deliver. Inherent-safety is the language a regulator will recognize from aviation safety, nuclear operations, and ISO 26262 functional-safety frameworks. Where this document declares a surface inherent-safety, the standard is multiple independent simultaneous failures required, each independently bounded, with no single authority and no single component able to produce loss alone.

*Marketing material may use "zero-fail" as shorthand. Doctrine uses "inherent-safety." Where the two terms appear in this document, they refer to the same architectural standard defined above.*

| AXIOM 1 — DOCTRINE BEFORE EXECUTION |
| --- |
| No decision executes without a doctrine version stamp, an authority hash, and an approval-lineage record in the DSOR. The ordering is absolute: Mentat stamps doctrine, Kaladan packages, C2 coordinates, R / J / H execute. No layer substitutes for the layer above it. Enforced in the deployed code by the startup doctrine-stack cycle that signs every ready state with a SHA-256 audit hash. |

| AXIOM 2 — AGENTS ADVISE, OPERATORS DECIDE |
| --- |
| No agent at any layer holds approval authority. Agents surface analysis, enforce pre-configured rules, and emit telemetry. Every approval gate requires explicit operator action. This holds under CAOM-001 and remains non-negotiable in any transition to institutional role separation. |

| AXIOM 3 — HANDOFF BEFORE ACTION |
| --- |
| No Thifur agent acts on a lifecycle object without a recorded C2 handoff authorization. Agent-to-agent direct transfers are illegal. This is the architectural enforcement of BCBS 239 P3 (automated, reconciled risk-data aggregation) and the SR 11-7 aggregate-model-risk view. |

| AXIOM 4 — ONE LINEAGE RECORD |
| --- |
| The DSOR receives the C2-assembled unified lineage, never raw agent telemetry. Gaps in agent telemetry are flagged explicitly — never silently filled. A unified picture with a flagged gap is valid. A complete-looking picture with an unflagged gap is an SR 11-7 violation. |

| AXIOM 5 — DOCTRINE OVER CODE |
| --- |
| Smart-contract execution logic never overrides Mentat doctrine. When code and doctrine conflict, Thifur-J holds the object, C2 escalates, human authority decides. This axiom is what makes programmable assets governable inside a regulatory framework. |

| AXIOM 6 — ESCALATION COMPLETENESS |
| --- |
| C2 never presents a partial picture to human authority. If agent context is pending, C2 waits within defined time bounds before escalating. The escalation package always carries complete context or explicit flags for what is missing. Human authority is never overwhelmed with three concurrent agent contexts — always one governed picture. |

| AXIOM 7 — EXPLAINABILITY BEFORE EXECUTION |
| --- |
| Every Thifur-H action — advisory or autonomous — must be explainable in human-readable terms before execution. If it cannot be explained, it does not execute. This is the EU AI Act high-risk AI requirement applied architecturally rather than compliance-theatrically. |

| AXIOM 8 — VERANA AUTONOMOUS BLOCK |
| --- |
| Verana is the only layer authorized to autonomously block. Doctrine integrity failure, OFAC screening failure, session-boundary violation, and systemic-stress hard-stop are enforced by Verana without reference to any other authority. An autonomous block is a feature of Layer 0, not a failure of Layers 1–3. |

| AXIOM 9 — TIER 0 EMERGENCY HALT ABOVE ALL DOCTRINE |
| --- |
| The Emergency Halt is a Tier 0 authority that sits above the three-tier CAOM-001 structure. Any authority can trigger it. When Halt is active, all Thifur execution is frozen immediately — R, J, and any future H domain — regardless of what other authorities or doctrine versions are active. Halt state carries its own immutable lineage: activation timestamp, invoking authority, stated reason. Resumption requires explicit operator action and generates a doctrine-change-style audit record. Halt is the system's circuit breaker; it is outside the tier hierarchy by design. |

| AXIOM 10 — INHERENT-SAFETY SURFACES REQUIRE ARCHITECTURAL IMPOSSIBILITY OF SINGLE-POINT FAILURE |
| --- |
| Where the doctrine declares a surface inherent-safety, the failure mode must be eliminated by design — multiple independent simultaneous failures required to produce loss, each independently bounded under stated assumptions. Procedural controls, training, monitoring, and recovery procedures are necessary but never sufficient on an inherent-safety surface. No single authority, no single component, no single signature, no single key, no single jurisdiction, and no single counterparty may sit on the loss path. Surfaces declared inherent-safety in this document or in any addendum (custody being the first such addendum, anticipated in v1.6) inherit the requirements of this axiom automatically. Failure to meet inherent-safety requirements on a declared inherent-safety surface is treated as a doctrine integrity violation under Axiom 8. |

# IV. THIFUR AS WORKFORCE — AUREON ASSET-SERVICES WORKFORCE SPECIFICATION

Section II describes Thifur as a four-agent architectural family (C2 + R + J + H). This section describes Thifur as a deployed workforce: the eleven operational agent roles that the architectural family decomposes into when Aureon is deployed in an institutional asset-services environment. Both views are correct at their respective resolutions. The architectural view governs design; the workforce view governs deployment.

| From eFICC to Asset Services |
| --- |
| v1.6 evolves the workforce framing from "Post-Trade eFICC" (electronic Fixed Income, Currencies, and Commodities) to "Aureon Asset-Services Workforce" to match the architectural commitment delivered in `AUR-CUSTODY-001 v1.0`: custody under Aureon governance is bounded only by the legal definition of custodiable assets, not by current operational practice and not by any incumbent platform's coverage. The workforce must operate across the full asset-class universe (traditional securities, fixed income, derivatives, FX, funds, commodities both physical and financial, real estate and real assets, insurance and reinsurance, intellectual property, trade finance, tokenized representations of all above, native digital assets, alternative assets, and emerging asset categories) and across the broader operational surface that the Asset Services strategic positioning encompasses (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue). The eFICC framing was correct for v1.4 / v1.5 scope but is too narrow for v1.6 commitments. The rename is operational, not architectural — existing role names remain correct at the function level (Settlement Operations is still Settlement Operations) but their implicit scope expanded to span the full asset-class universe. |

| Why the Asset-Services Surface Matters |
| --- |
| Institutional asset services is the most operationally complex domain in capital markets. The repo clearing mandate (June 2027), EU T+1 transition (October 2027), Treasury cash clearing compliance (December 2026), and the broader 2026-2027 forced-rebuild calendar drive every major institutional actor to rebuild parts of their post-trade and custody infrastructure simultaneously. Aureon Asset Services provides the doctrine-first governance layer that sits above incumbent systems — governing what enters them, producing the audit record that proves it was governed correctly, and deploying an agent workforce that replaces manual institutional roles at a fraction of the cost. The `AUR-CUSTODY-001 v1.0` doctrine extends this surface with custody-specific agent roles in 1:1 FIAT/digital parity (FIAT Operations Specialist, Digital Asset Custody Specialist, Collateral Operations Specialist, Custody Operations Analyst), establishing the Aureon Asset-Services Workforce as the framework's deployed agent population across the full asset-class universe. |

## Workforce Decomposition

Eleven canonical agent roles span three operational tiers. Each role maps to a real institutional job description, a Thifur agent class, a task registry, a guardrail set, and a regulatory framework alignment. The HITL (Human-In-The-Loop) Orchestrator role is held by the operator under CAOM-001 (Section V). Custody-specific roles delivered in `AUR-CUSTODY-001 v1.0` (Custody Operations Analyst at Tier 1; FIAT Operations Specialist, Digital Asset Custody Specialist, and Collateral Operations Specialist at Tier 2) extend this canonical workforce within their respective tiers and are governed by the same canonical guardrails.

| Tier | Role | Thifur Class |
| --- | --- | --- |
| HITL | Head of Operations / VP Post-Trade | Operator (CAOM-001) |
| 1 — Execution & Ops | Settlement Operations Analyst | R (deterministic) |
| 1 — Execution & Ops | Trade Support Analyst | R (deterministic) |
| 1 — Execution & Ops | Reconciliation Analyst | R (deterministic) |
| 1 — Execution & Ops | Regulatory Reporting Analyst | R (deterministic) |
| 2 — Risk & Compliance | Compliance Monitoring Analyst | J (bounded autonomy) |
| 2 — Risk & Compliance | Trade Surveillance Analyst | J (bounded autonomy) |
| 2 — Risk & Compliance | Risk Reporting Analyst | J (bounded autonomy) |
| 2 — Risk & Compliance | AML / KYC Analyst | J (bounded autonomy) |
| 3 — Intelligence & Gov | Portfolio Risk Manager | H (advisory active) |
| 3 — Intelligence & Gov | Model Risk Analyst — SR 11-7 | H (advisory active) |
| 3 — Intelligence & Gov | Data Governance Analyst | H (advisory active) |

*Tier 3 agents inherit the two-state Thifur-H distinction (Section II): advisory functions are active in deployment; autonomous activation per domain requires independent SR 11-7 Tier 1 validation and EU AI Act registration. The licensing economics (Section IX) are based on advisory-mode deployment; autonomous-mode deployment commands a separate license tier.*

## Tier 1 — Execution and Operations (R-class)

Tier 1 agents operate under Thifur-R: strict determinism, zero variance permitted. The same input always produces the same output. These agents replace the highest-volume, most manual operational roles in asset-services post-trade across the full asset-class universe established in `AUR-CUSTODY-001 v1.0`. SR 11-7 Tier 2 deterministic; OCC 2023-17 third-party registry; BCBS 239 P3 automated accuracy; DORA RTO 15 minutes for settlement on the primary path. Five-second internal alert thresholds for confirmation mismatch and SLA breach are an operational SLA; no single US statute governs the specific timing metric.

The Settlement Operations Analyst executes T+1 / T+2 settlement sequencing through FICC sponsored repo, DvP instruction routing, SWIFT and Fedwire handoff, with no path deviation. Fails and breaks management escalates immediately to C2 with full discrepancy record. Repo clearing mandate readiness covers FICC GSD rulebook compliance for the June 2027 mandate. Rail confirmation matching against DSOR intent triggers a five-second alert on any mismatch and immediate C2 escalation.

The Trade Support Analyst handles trade capture, allocation, and confirmation lineage — every executed trade carries a FIX (Financial Information eXchange) lineage stamp through to settlement. Allocation errors trigger immediate C2 escalation with no silent retry.

The Reconciliation Analyst runs continuous reconciliation between DSOR records and downstream system state — OMS, custodian, clearing, and settlement records must reconcile to the doctrine record. Any unreconciled break triggers C2 escalation within one cycle.

The Regulatory Reporting Analyst generates the regulatory reports that broker-dealers and asset managers are required to file — TRACE for corporate bonds, MSRB for municipals, CFTC for swaps, FINRA OATS, and the equivalent EU MiFIR transaction reports. Every report ties back to the DSOR lineage record. SLA breach on report generation triggers a five-second alert and C2 escalation.

## Tier 2 — Risk and Compliance (J-class)

Tier 2 agents operate under Thifur-J: bounded autonomy. They select among pre-approved paths, never generate new ones. Code does not override doctrine. SR 11-7 Tier 1 — pre-deploy validation, MRM (Model Risk Management) committee oversight; MiFID II RTS 6 algorithmic trading controls including the AUR-J-TRADE-001 algorithm inventory; EU AI Act high-risk system conformity assessment; DORA ICT third-party node registry; BCBS 239 P4 completeness.

The Compliance Monitoring Analyst runs continuous OFAC, sanctions, and mandate-compliance screening against every pre-trade decision and every settlement instruction. Verana's autonomous block authority sits underneath this role — when Verana hard-blocks, Compliance Monitoring writes the explainability record. Algorithm inventory AUR-J-TRADE-001 is the master registry.

The Trade Surveillance Analyst — Fixed Income runs the surveillance scenarios that Fixed Income markets require: spoofing, layering, marking the close, and the more domain-specific patterns (duration manipulation, off-the-run / on-the-run spread anomalies, cross-product surveillance for rates curve trades). Every alert is tied to a DSOR pre-trade record. Kill Switch Level 2 authority sits with the human operator, never with the agent.

The Risk Reporting Analyst generates the daily, intraday, and ad-hoc risk reports that the CRO (Chief Risk Officer) and the Risk Committee require. VaR (Value at Risk), stressed VaR, expected shortfall, concentration metrics, and the bespoke risk attribution that the operator's mandate requires. Every report carries the DSOR lineage. RTS 6 post-trade controls timing applies.

The AML / KYC Analyst runs ongoing eligibility screening — KYC (Know Your Customer), KYB (Know Your Business), and AML (Anti-Money Laundering) — against every counterparty, every wallet, every settlement endpoint. Eligibility failure holds the lifecycle object; J does not route to a non-eligible counterparty under any condition. EU AI Act high-risk financial-access classification applies.

## Tier 3 — Intelligence and Governance (H-class, advisory)

Tier 3 agents operate under Thifur-H in advisory mode. They surface optimization analysis to the operator; the operator decides. SR 11-7 Tier 1 — independent validation required; MiFID II RTS 6 algorithmic trading controls plus price collars; EU AI Act high-risk classification with mandatory EU database registration; DORA TLPT (Threat-Led Penetration Testing) annual scope; BCBS 239 P5 real-time timeliness.

The Portfolio Risk Manager surfaces VaR, drawdown, concentration, liquidity-tier, and stress-test signals to the operator continuously. It does not rebalance autonomously — it surfaces the case for rebalancing. Kill Switch and price collars enforced architecturally.

The Model Risk Analyst — SR 11-7 runs continuous model-validation telemetry: backtest performance, parameter drift, calibration limits, regime-change detection. Quarterly MRM committee briefings are produced from the agent's output, reviewed by the operator, signed by the operator. Annual self-assessment per RTS 6.

The Data Governance Analyst manages data lineage, data quality monitoring, and the regulatory data-governance posture. Every DSOR record traces back through this agent's lineage map. EU AI Act Article 22 GDPR (General Data Protection Regulation) compliance and DORA continuous data-integrity monitoring apply.

## Regulatory Stress Test Matrix — Workforce View

Every agent role maps to a testable regulatory claim. Each cell is traceable to a specific doctrine section, guardrail, or task registry entry.

| Role | SR 11-7 | MiFID II RTS 6 | EU AI Act | DORA |
| --- | --- | --- | --- | --- |
| Settlement Ops (R) | Tier 2 deterministic | 5-sec alerts | Not high-risk | RTO 15 min |
| Trade Support (R) | Tier 2 deterministic | FIX lineage | Not high-risk | Settlement integrity |
| Reconciliation (R) | Tier 2 deterministic | Post-trade monitoring | Not high-risk | Continuous |
| Reg Reporting (R) | Tier 2 deterministic | 5-sec alerts | Not high-risk | SLA compliance |
| Compliance (J) | Tier 1 pre-deploy | AUR-J-TRADE-001 | High-risk conformity | ICT 3rd-party |
| Surveillance (J) | Tier 1 annual | Kill Switch L2 | High-risk conformity | Resilience test |
| Risk Reporting (J) | Tier 1 MRM | Post-trade controls | High-risk registered | Continuous |
| AML/KYC (J) | Tier 1 pre-deploy | Onboarding gate | High-risk financial | ICT nodes |
| Portfolio Risk (H) | Tier 1 indep. val | Price collars | High-risk EU DB | TLPT annual |
| Model Risk (H) | Tier 1 quarterly | Annual self-assess | High-risk registered | TLPT annual |
| Data Gov (H) | Tier 1 validation | Data lineage | Art. 22 GDPR | Continuous |

# V. CAOM-001 — CONSOLIDATED AUTHORITY OPERATING MODE

CAOM-001 is the formally governed configuration under which a single human operator holds all three tiers of Human Authority simultaneously, while agents assume the analytical and advisory functions that institutional role-holders perform in a multi-person deployment. Effective April 6, 2026.

| CAOM-001 Is Not a Workaround |
| --- |
| CAOM-001 is not a reduced-governance state. It is a defined, doctrine-consistent operating mode purpose-built for solo fund operators running a one-person shop with AI agents filling operational roles, proof-of-concept and testing environments validating the full governance stack, and early-stage deployment prior to institutional staffing build-out. All Human Authority Doctrine requirements remain in force under CAOM. The difference is in how roles are assigned — not in whether governance applies. |

## The Core Problem CAOM Solves

The Aureon Human Authority Doctrine defines three tiers of authority and a set of role-based approval gates (Trader, Risk Manager, Portfolio Manager, Compliance Officer, Executive). These gates are designed for institutional environments where distinct individuals hold distinct roles. In a single-operator environment, the system has no mapping between the human user and these named roles. As a result, approval gates stall indefinitely — the system is waiting for a Trader, Risk Manager, or Compliance Officer who is never coming because that person is the same person sitting at the terminal.

The observed failure mode on April 6, 2026: pre-trade routing check failed, execution blocked, decision detail "Awaiting approvals: TRADER · risk review required." The operator clicked Approve. Nothing happened. The system was waiting for a role-credentialed authority it could not find because no role mapping existed for the single operator. CAOM-001 resolves this by establishing a governed role consolidation: the single operator is formally registered as the holder of all three authority tiers, and agents are mapped to the analytical functions those roles perform.

## Authority Mapping

| Institutional Role | Tier | CAOM Mapping | Agent Advisory Support |
| --- | --- | --- | --- |
| Emergency Halt | T0 Circuit Breaker | Operator holds seat · above all doctrine | No agent may trigger or override · audit record on activation and resumption |
| Trader | T1 Operational | Operator holds seat | Thifur-H (advisory): VWAP/TWAP, slippage, liquidity depth |
| Risk Manager | T1 Operational | Operator holds seat | Mentat risk framing; Kaladan drawdown; Thifur-J policy check |
| Portfolio Manager | T1 Operational | Operator holds seat | Mentat: mandate alignment, conviction score |
| Compliance Officer | T2 Governance | Operator holds seat | Verana: OFAC, doctrine integrity, stress (autonomous) |
| Head of Risk / CRO | T2 Governance | Operator holds seat | Kaladan: drawdown guard, limits, liquidity buffer |
| Executive / Principal | T3 Executive | Operator holds seat | All systemic / doctrine / kill-switch decisions — operator only |

*Agents provide analysis, surface signals, enforce pre-configured doctrine rules. Agents do not make approval decisions. Every approval gate requires explicit operator action. The agent fills the analytical role; the human fills the authority role. This distinction is non-negotiable.*

## Tier 0 Emergency Halt — Formal Declaration

The original CAOM-001 (April 6, 2026) declared three tiers — T1 Operational, T2 Governance, T3 Executive. The deployed code added a Tier 0 Emergency Halt that sits above all three. This consolidated document formally declares Tier 0 as a constitutional authority distinct from the three CAOM tiers.

Tier 0 is the system's circuit breaker. Any authority — operator, any agent escalation, or any external trigger configured at session open — can activate Halt. When Halt is active, every Thifur execution surface (R, J, H advisory, and any future H autonomous domain) is frozen immediately, regardless of what other authorities or doctrine versions are active. Halt state carries its own immutable lineage: activation timestamp, invoking authority, stated reason.

Halt is engaged through the /api/halt POST endpoint and is visible in real time on /api/halt GET and the Leto operator console governance pane. Resumption through /api/halt/resume POST is a deliberate two-step action that itself becomes an audit record equivalent to a doctrine change. Halt is not a fallback and not a DORA degraded-operations trigger — it is the kill-switch of last resort for the entire execution surface.

Tier 0 is outside the three-tier hierarchy by design. It cannot be delegated, cannot be conditioned on agent telemetry, and cannot be overridden by any other authority. The architectural invariant is: a human can always stop the system; the system can never stop a human from stopping the system.

## Quorum Authority — Future Mode (Out of Scope Under CAOM-001)

Quorum authority is a doctrinal primitive defined here for forward compatibility and explicitly declared out of scope under CAOM-001. It is documented in v1.5 because v1.6 (custody) will require it, and because risk committees, rating agencies, and licensing counterparties will ask whether the framework anticipates the requirement. The framework does.

A quorum authority operation is one that cannot be authorized by any single tier of the CAOM authority structure — including Tier 3 — and instead requires N-of-M independent signatures from authorities with separation of duties enforced architecturally rather than procedurally. This is the authority pattern required for institutional custody operations of material magnitude: large transfers, key ceremonies, encumbrance changes on pledged assets, lien releases, cold-storage rotations. Single-authority approval on these operations is an inherent-safety violation under Axiom 10.

Under CAOM-001, the operator holds all three CAOM tiers simultaneously. A quorum-authority operation cannot be satisfied by a single human signing in three different tier seats — that is theater, not separation of duties, and it does not meet the inherent-safety standard of Axiom 10. Therefore: any operation that the doctrine flags as quorum-required is unavailable while CAOM-001 is the active operating mode. The system must hold the operation and surface a CAOM-transition trigger before the operation can proceed.

This produces a fifth CAOM transition trigger, joining the four already declared in this section: any operation that the doctrine declares quorum-required forces a formal review of CAOM transition. The system does not silently approve such an operation under CAOM. It does not theatrically approve it through three operator clicks. It holds, surfaces the trigger, and waits for the operator to either decline the operation or initiate transition.

The detailed quorum authority specification — the N-of-M selection per operation class, the separation-of-duties enforcement mechanism, the signature ceremony protocol, the architectural enforcement of independence between signing authorities — was anticipated as v1.6 (custody) work and is **operationalized within the custody domain in `AUR-CUSTODY-001 v1.0` Section VII** (Quorum Authority Operational Specification). The custody doctrine specifies the default 3-of-5 N-of-M structure, the five independence requirements (identity, organizational, geographic, system, temporal), and the six-step signature ceremony protocol. The primitive is operationalized for custody; subsequent post-CAOM doctrine revisions will operationalize quorum for non-custody operations that also require it (large doctrine amendments, fund-level position limits, regulatory engagement).

*The honest reading of this primitive: an Aureon licensee cannot run institutional custody operations of material magnitude under CAOM-001 because the operationalized specification in `AUR-CUSTODY-001 v1.0` requires architectural separation of duties that single-operator three-tier signing does not meet. The framework names this constraint in v1.5, operationalizes the alternative in v1.6, and binds the alternative to the post-CAOM authority structure that licensees must establish before running quorum-required custody operations.*

## Session Open Protocol Under CAOM

At the start of each trading session, the following sequence must complete before any execution gate is reachable. All six steps are implemented as discrete endpoints in the deployed server.

| Step | Action | Owner | Gate |
| --- | --- | --- | --- |
| 1 | Verana Session Boundary Check | Verana (automated) | Must PASS before session opens |
| 2 | CAOM Mode Declaration | Operator confirms CAOM-001 is active | Operator action required |
| 3 | Role Consolidation Acknowledgment | Operator affirms tier holdings | Operator action — logged to DSOR |
| 4 | Agent Advisory Readiness Check | Thifur-C2 confirms agents online | Must PASS before gates activate |
| 5 | Systemic Stress Status Review | Verana surfaces OFR signal | Operator may proceed unless Verana hard-blocks |
| 6 | Session Open Confirmation | Operator confirms session open | All execution gates now active |

*The April 6, 2026 pre-trade routing failure was caused by the absence of Steps 2 and 3 prior to CAOM-001 codification. CAOM-001 is both the architectural fix and the formal doctrine. Endpoints: /api/session/status, /api/session/step/1 through /api/session/step/6, /api/session/open.*

## What CAOM Does Not Change

Agents advise only. No agent may make an approval decision. The Kill Switch authority remains with the operator at all tiers, and no agent may activate or override a Kill Switch at any level. Tier 3 (Executive) decisions — systemic risk, fundamental doctrine change, regulatory authority engagement — require explicit operator action with no agent substitution under any condition. Every approval action is stamped with CAOM-001 mode identifier, operator identity, timestamp, and agent advisory summary in the DSOR lineage. Automated enforcement of OFAC screening, doctrine integrity checks, and systemic stress monitoring remains operator-independent — Verana enforces these regardless of CAOM mode. Novel scenarios with no doctrine precedent still require operator authority — agents surface the gap, operators define the response, Mentat records it as new doctrine.

## Transition Out of CAOM

CAOM is the initial operating mode, not the permanent one. The following conditions trigger a formal review of institutional role separation: AUM exceeds $10M triggers a formal review of dedicated Risk Manager role separation. External investor capital onboarding requires Compliance Officer role separation — CAOM is not compatible with third-party investor governance obligations. Regulatory examination scheduled forces a Tier 2 and Tier 3 authority review under applicable framework. First institutional staff hire begins formal CAOM transition plan, role separation phased by function starting with Compliance. Strategy licensing to a third party may impose role separation standards from the licensing counterparty.

Until a transition trigger is reached, CAOM-001 remains the active and fully governed operating mode. It is not a gap in governance. It is a defined mode of governance appropriate to a one-person, agent-augmented fund operation.

# VI. FAILURE MODES AND ESCALATION LOGIC

The architecture is specified by its failure modes. An institutional risk committee should be able to name each class of failure, the detecting layer, the holding behavior, and the escalation destination. Every cell maps to a guardrail or protocol in this canonical document, and every row has a corresponding enforcement path in the deployed code.

## Failure-Mode Taxonomy — Three Recoverability Classes

Aureon classifies every failure surface into one of three recoverability classes. The class determines the holding behavior, the escalation tier, the regulatory reporting obligation, and — for inherent-safety surfaces — whether the failure mode is permitted to be reachable at all.

| Class | Definition | Holding Behavior | Examples |
| --- | --- | --- | --- |
| RA — Recoverable Automatic | Failure detected, recovered by the system without human action, lineage continuous across the event | Verana fallback rail engages · DSOR records the failover · operator notified post-recovery | Settlement rail outage with pre-staged fallback · transient telemetry loss within RTO · Cato data-source failover within cache window |
| RM — Recoverable Manual | Failure detected, recovered with explicit human action, lineage may have flagged gap requiring manual reconciliation | C2 holds affected lifecycle · escalation package assembled · operator decides recovery path · DSOR records manual reconciliation lineage | Reconciliation break requiring investigation · doctrine ambiguity requiring Mentat resolution · cross-border jurisdictional conflict · settlement break requiring counterparty contact |
| UR — Unrecoverable | Failure produces loss that cannot be undone by any subsequent action, asset or position permanently impaired | MUST NOT BE REACHABLE on inherent-safety surfaces (Axiom 10) · if reached on any other surface, immediate Tier 0 Halt and full incident response | On-chain transaction with finality to wrong address · physical security misroute beyond DTC recall window · key compromise with active signing authority · pledged collateral release without lien-holder authorization |

The taxonomy is intentionally three classes at the canonical framework level. Two classes (recoverable / unrecoverable) loses the operational distinction between automatic and manual recovery, which is the distinction DORA cares about. Four classes (further subdividing unrecoverable into reversible-via-other-means and final) is custody-specific and is **operationalized within the custody domain in `AUR-CUSTODY-001 v1.0` Section VIII** (Custody-Specific Failure-Mode Taxonomy Refinement), where the distinction between insurance-recoverable loss (UR-R) and final loss (UR-F) matters for licensee economics. The custody doctrine specifies UR-R / UR-F examples spanning the full asset-class universe (traditional securities, physical commodities, real estate, insurance, IP, trade finance, tokenized assets, native digital assets) and binds operational specifications for Sovereign and Federate to tag every custody operation type with its failure-mode class.

Every existing failure-mode entry in this section, in the Aureon Asset-Services Workforce specification (Section IV), and in the convergence governance table below, can be tagged with its recoverability class. The retrofit within the custody domain is delivered in `AUR-CUSTODY-001 v1.0`. Retrofit across non-custody surfaces (the broader convergence governance table below, the Tier 0/1/2/3 escalation logic, the regulatory stress test matrix in Section IV) remains anticipated work to be completed alongside subsequent doctrine additions where new operational scope is introduced.

*UR-class failures on inherent-safety surfaces are the architectural concern of Axiom 10. Where the doctrine declares a surface inherent-safety, no UR-class failure path may be reachable through any single component, single authority, single signature, or single jurisdiction. This is the operational standard custody is measured against per `AUR-CUSTODY-001 v1.0` Section IX (Inherent-Safety Architecture for Custody), which declares twenty-plus inherent-safety surfaces across the asset-class universe in 1:1 FIAT/digital parity (material-magnitude FIAT settlement operations, correspondent banking integrity, depository membership operations, large-value payment system finality operations, FX bundled settlement operations on the FIAT side; native digital asset operations, key ceremonies, cold storage, tokenized issuer operations on the digital side; plus asset-class-specific surfaces for physical commodities, real estate title, IP rights, insurance contracts, ILS triggers, carbon credits, and authenticated alternative assets).*

## Convergence Governance — TradFi / DeFi Boundary

| Scenario | Primary Agent | Supporting | Coordination Rule |
| --- | --- | --- | --- |
| Tokenized asset requires traditional-rail settlement | Thifur-J (lifecycle) | Thifur-R (settles) | J prepares package · C2 records handoff · R executes deterministically · no direct J→R |
| AI optimization concurrent with tokenized settlement | Thifur-J (lifecycle) | H (collateral), R (settles) | C2 sequences H advisory first · J validates · R executes · H never generates settlement instruction |
| Smart-contract logic conflicts with Mentat doctrine | Thifur-J (holds) | C2 escalates | J suspends · C2 packages conflict · minimum Tier 2 to proceed |
| Payment rail failure during tokenized settlement | Thifur-R (fallback) | Thifur-J (holds asset) | C2 freezes J object · R executes Verana fallback · J resumes only after governed fallback confirmed |
| Tokenized concentration breach mid-lifecycle | Verana Concentration Monitor | All Thifur agents | C2 halts all agents on affected lifecycle · minimum Tier 1 escalation · no resumption without human clearance |
| Cross-border flow with jurisdictional conflict | Thifur-J (holds routing) | Mentat conflict resolution | J suspends · C2 packages for Mentat · Kaladan holds lifecycle · minimum Tier 2 before J resumes |

## Tier 0 Emergency Halt — Operational

The Emergency Halt endpoint freezes all Thifur execution system-wide in a single operation. Halt state is stamped with activation timestamp, invoking authority, and stated reason, and is visible on /api/halt GET and in the Leto governance pane. Resumption is a deliberate two-step action that itself becomes an audit record. Halt is not a fallback and not a DORA degraded-operations trigger — it is the kill-switch of last resort for the entire execution surface.

## Degraded Operations

Under DORA, no Thifur agent enters degraded mode unilaterally. When any agent detects a degradation trigger — rail outage, telemetry loss, latency breach — the agent emits a degradation signal to C2. C2 activates the pre-defined fallback sequence under Kaladan's Degraded Operations Mode. All three execution agents are sequenced and coordinated — partial-degradation races are not permitted. The unified lineage record is maintained continuously across the degradation event.

Recovery Time Objective (RTO): 15 minutes for settlement execution on the primary path. Fallback sequences are pre-staged in Verana's Fallback Authority registry before any live execution. Annual Threat-Led Penetration Testing (TLPT) covers the full Thifur surface, with Thifur-H autonomous activation explicitly in scope when activated.

## Kill Switch Hierarchy

Under MiFID II RTS 6 algorithmic trading controls, the kill switch is three-level once Tier 0 is counted.

Level 1 — Algo-scope suspension. Suspends a single algorithm or agent in a single domain. Any Tier 1 authority can trigger. Resumption requires Tier 2.

Level 2 — Full Algo Suspension. C2 cancels all Thifur-H and Thifur-J orders across all domains in one command within five seconds. Any Tier 2 authority can trigger. Resumption requires Tier 3 and a post-incident doctrine review.

Tier 0 — Emergency Halt. Complete execution freeze across R, J, and H. Any authority can trigger. Resumption requires explicit operator action and generates an audit record equivalent to a doctrine change.

*No agent — under any condition — may activate or override a kill switch at any level. Kill-switch authority resides with human operators. This is non-negotiable under CAOM-001 and in any post-CAOM institutional deployment.*

# VII. DOCTRINE PROVENANCE AND PARITY

## Version Log — v1.0 Through v1.6

The doctrine version log is a live, append-only record in the deployed system. Every version bump carries a SHA-256 hash, the authority that authorized the bump, the tier the bump required, the trigger class, and the stated reason. This is the change-control evidence a risk committee independently verifies.

| Version | Authority | Tier / Trigger | Reason |
| --- | --- | --- | --- |
| 1.0 | SYSTEM | System Init | Initial doctrine load — Aureon Grid 3 deployment. |
| 1.1 | Verana L0 Regulatory Absorption | T2 — Regulatory Mandate | EU DORA Article 28 absorbed. Four nodes flagged. Doctrine updated autonomously. |
| 1.2 | Operator (T1 Human Authority) | T1 — Human Authority | Basel III Endgame vs EU CRR III conflict. Operator resolved by applying higher RWA standard. |
| 1.3 | Operator (CAOM-001) | T1 — Human Authority | Thifur-Atrox and Thifur-C2 doctrine documents registered. Atrox formalized above execution triplet. Five Immutable Stops codified in C2 doctrine. |
| 1.4 | Operator (CAOM-001) | T1 — Human Authority | Canonical consolidation: CAOM-001 reissued under Aureon masthead (Project Arcadia retired); eFICC eleven-role workforce specification absorbed; Tier 0 Emergency Halt formally declared above three-tier CAOM structure; Thifur-H two-state distinction (advisory active / autonomous declared not activated) corrected against deployed system; open conflicts log updated. |
| 1.5 | Operator (CAOM-001) | T1 — Human Authority | Inherent-safety foundations established: "inherent-safety" defined as doctrinal term; Axiom 10 (architectural impossibility of single-point failure on inherent-safety surfaces); three-class failure-mode taxonomy (RA / RM / UR); quorum authority defined as future-mode primitive and declared out of scope under CAOM-001; fifth CAOM transition trigger added (any quorum-required operation forces transition review). Custody (v1.6) anticipated as first major addendum to inherit these foundations. |
| 1.5.1 | Operator (CAOM-001) | T1 — Human Authority | Administrative reframing: document reissued as a Columbia M.S. Technology Management capstone publication. No doctrinal substance modified; Sections II through X identical to v1.5. Recorded under propose/approve doctrine modification workflow per Section VII. |
| 1.6 | Operator (CAOM-001) | T1 — Human Authority | Custody specification delivered as substantive doctrine addition. `AUR-CUSTODY-001 v1.0` operationalizes the architectural prerequisites established in v1.5 (Axiom 10 inherent-safety, three-class failure-mode taxonomy, quorum authority primitive) within the custody domain. The architectural choice that distinguishes v1.6: custody under Aureon governance is bounded only by the legal definition of custodiable assets, not by current operational practice or any incumbent platform's coverage. Asset-class breadth is established as the durable architectural axis; settlement methods are framed as the variable operational layer beneath, accommodating future evolution (atomic settlement, PORTS-aligned wholesale tokenized infrastructure, FedNow 24/7/365 FIAT, ISO 20022 migration, currently-unimagined rails) through configuration rather than rebuild. The doctrine specifies the asset-class universe (traditional securities, fixed income, derivatives, FX, funds, commodities both physical and financial, real estate and real assets, insurance and reinsurance, intellectual property, trade finance, tokenized representations of all above, native digital assets, alternative and specialty assets, and emerging future categories), the comprehensive enumeration of transaction types and settlement methods across the asset-class universe, the operational quorum authority specification (default 3-of-5 N-of-M with five independence requirements and six-step ceremony protocol), the four-class custody-specific UR-R / UR-F failure-mode taxonomy refinement with examples spanning the full asset-class universe, the inherent-safety architecture per Axiom 10 with twenty-plus declared inherent-safety surfaces in 1:1 FIAT/digital parity, and the forward-state framework covering atomic settlement, 24/7 operational continuity, selective FIAT/tokenized custody, PORTS-aligned architecture, and FIAT settlement-rail governance. Custody-specific roles added to the workforce: Custody Operations Analyst at Tier 1; FIAT Operations Specialist, Digital Asset Custody Specialist, and Collateral Operations Specialist at Tier 2 (the FIAT and Digital Specialists in explicit 1:1 parity). Workforce framing renamed framework-wide from "Post-Trade eFICC" to "Aureon Asset-Services Workforce" to match the asset-class breadth and the broader Asset Services strategic positioning (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue). Anchored in modern Top 5 institutional custody practice (BNY Mellon for global custody breadth and tri-party, State Street for institutional asset managers and ETFs, JPMorgan for systematic strategy funds and prime brokerage integration, Citi for cross-border emerging markets and FX-bundled custody, BNP Paribas Securities Services for European institutional and post-trade integration) with explicit recognition that no single Top 5 incumbent serves every asset-class segment — the framework's competitive position is the asset-class breadth no individual custodian provides under unified governance. |

*Project Arcadia is retired as a name across all artifacts. The historical name is preserved here in the v1.0 — v1.5 lineage and nowhere else. All future references use Project Aureon. The v1.1 entry remains material evidence that Axiom 8 (Verana Autonomous Block) is implemented, not theoretical: Verana absorbed a regulatory mandate autonomously and advanced the doctrine version without human intervention.*

## Doctrine Modification Governance

Doctrine amendments in the deployed system flow through a two-step tier-gated workflow. /api/doctrine/propose POST registers a proposed amendment with rationale, trigger, and affected layer. /api/doctrine/approve/<update_id> POST executes the version bump with the approving authority identity, tier, and a fresh SHA-256 hash. The propose-and-approve endpoints are the only path that advances the version log. The Five Immutable Stops in the Thifur-C2 doctrine may only be modified through this workflow.

## The Parity Principle

Any component of Aureon implemented in two codebases — the external MCP server and the in-process Python twin, for Cato today and by extension for any future Verana tool — must produce bit-for-bit identical decisions for identical inputs. Doctrine changes land in both codebases in the same commit series. The external and internal implementations should be at the same doctrine version at all times. This parity is what lets a trustee, a rating agency, or a regulator trust the gate regardless of caller.

# VIII. INSTITUTIONAL LICENSING THESIS

Aureon's commercial path is licensing the governance layer, not operating a fund. The convergence of tokenization, AI-driven execution, and programmable payment rails is arriving in capital markets faster than incumbent governance frameworks can adapt. BlackRock BUIDL is live on nine chains with more than $2B AUM. Franklin Templeton BENJI runs on ten. Tokenized US Treasuries alone reached $12.88B in April 2026 inside a $27B+ tokenized RWA market growing 300% year-over-year. None of these live institutional products has publicly documented a complete governance model — continuous compliance surveillance, human-in-the-loop gate framework, immutable audit chain — that a trustee, a rating agency, or a regulator can actually rely on. That gap is the addressable market. The governance layer is not commoditized.

## Three Deployment Modes

Aureon is deployable in three modes against that market. As a governance overlay above existing OMS infrastructure, providing pre-trade gates, compliance surfaces, and DSOR audit artifacts without displacing execution infrastructure. As a full-stack doctrine operating system for a fund or desk building greenfield. As a pure compliance artifact engine, where every decision returns a replayable regulatory submission package. The unifying thesis under all three modes is the same: doctrine was built before the technology, so when market structure shifts — PORTS ships, the GENIUS Act passes, Fed L1 tokenized reserves go live — the doctrine does not change. The rail does. That is the structural advantage, and it is what will be licensed.

## Workforce Licensing Economics

The Aureon Asset-Services Workforce (Section IV) is licensed as a governed service — doctrine framework, agent deployment, DSOR artifact generation, and regulatory maintenance — at a fraction of the incumbent salary cost it displaces. Twelve canonical roles are displaced per deployment across the three tiers. Custody-specific roles delivered in `AUR-CUSTODY-001 v1.0` (Custody Operations Analyst at Tier 1; FIAT Operations Specialist, Digital Asset Custody Specialist, Collateral Operations Specialist at Tier 2) extend the workforce when custody operational specifications (`AUR-CUSTODY-FED-001` for Federate, `AUR-CUSTODY-INST-001` for Sovereign) are deployed, with displaced-salary economics calibrated per product specification.

The license model is a base annual deployment fee plus usage-based fees: per-DSOR artifact generated at execution, regulatory replay requests, doctrine version upgrade subscriptions, and new strategy onboarding. Each named strategy deployment is a separate license event.

Aureon's architectural distinction is that governance is the platform rather than a module bolted onto a transaction-processing system. When a regulator asks for post-hoc reconstruction of any decision within the ten-year retention window, the answer is a doctrine-version-stamped, authority-attributed, agent-telemetry-reconciled DSOR record rather than a transaction log.

## Phase Map — Crawl, Walk, Run

| Capability | Phase 1 — Now | Phase 2 — Walk |
| --- | --- | --- |
| Asset scope | Treasuries, agencies, repo (current Argus paper-trading deployment) | Corporate bonds, MBS, ABS, structured products, with framework architectural commitment to the full asset-class universe per `AUR-CUSTODY-001 v1.0` Section III (commodities physical and financial, real estate, insurance and ILS, IP and royalty streams, alternative assets, tokenized representations of all above) |
| Tier 1 agents | All four R-class active | Extended to tokenized settlement rails |
| Tier 2 agents | Compliance, surveillance, risk reporting, AML/KYC active | Full EU AI Act conformity assessments completed |
| Tier 3 agents (advisory) | All three H-advisory active | Independent validation per autonomous domain begins |
| Repo clearing mandate | Governance layer for sponsored / agent clearing | Full tokenized repo collateral lifecycle |
| Regulatory coverage | SR 11-7 Tier 2, OCC 2023-17, BCBS 239 P3/P5 | Full six-framework coverage including DORA TLPT |
| DSOR completeness | Pre-trade to settlement confirmation | Full 10-year retention, replay engine live |

# IX. REGULATORY POSTURE — SIX-FRAMEWORK ALIGNMENT

Every governance claim Aureon makes is testable under one or more of six regulatory frameworks. The architecture is designed to be defensible under all six simultaneously, including under CAOM-001 single-operator deployment.

| Framework | Aureon Posture |
| --- | --- |
| SR 11-7 (Federal Reserve Model Risk Management) | Single operator holds Tier 1/2/3 authority under CAOM. Agents provide model advisory output only. Independent validation required before any Thifur-H autonomous activation. Quarterly MRM committee briefings. Aggregate model risk view assembled by Thifur-C2. |
| MiFID II RTS 6 (Algorithmic Trading) | Algorithm inventory AUR-J-TRADE-001. Three-level kill switch including Tier 0 Emergency Halt. Five-second post-trade alert thresholds. Annual self-assessment per RTS 6. Pre-trade controls enforced by Verana and Thifur autonomously. Operator holds Compliance Officer role under CAOM — explicitly documented. |
| EU AI Act | Thifur-J and Thifur-H classified as high-risk AI. Conformity assessment required pre-deploy. EU database registration before autonomous activation. Article 22 GDPR compliance for data governance. Human oversight surface is the operator. Override capability exists at all tiers. CAOM-001 mode documented and auditable. |
| DORA (Digital Operational Resilience Act) | Verana network governance, session boundary enforcement, and fallback path pre-staging fully active under CAOM. ICT third-party node registry maintained. RTO 15 minutes for settlement on primary path. Annual TLPT covers full Thifur surface. |
| BCBS 239 (Risk Data Aggregation) | DSOR lineage record produced for every decision regardless of CAOM mode. P3 automated accuracy enforced architecturally. P4 completeness via JTAC compliance. P5 real-time timeliness via H-advisory and Verana monitoring. Role consolidation stamped on all records. |
| OCC 2023-17 (Third-Party Risk) | Verana's Network Registry governs all third-party nodes — settlement rails, MCP servers, data sources, payment counterparties. SLA enforcement and pre-staged fallback per registered node. CAOM does not change third-party oversight requirements. |

# X. OPEN CONFLICTS AND DRIFT LOG

The following items surfaced during canonical synthesis against the deployed April 17-26, 2026 state and are recorded here for explicit tracking rather than silent resolution. Each requires a documented closure action before the next institutional demonstration. This is the change-control evidence a risk committee, rating agency, or regulator independently verifies.

## Resolved in v1.4

Project naming. Aureon canonical across all artifacts. Project Arcadia retired except in version log lineage.

Alpha-origination layer naming. Atrox is doctrine canonical. Neptune Spear retained only as operational nickname in code paths and filenames.

Layer count. Four governance layers (Mentat, Kaladan, Thifur, Verana) with Thifur internally decomposed into C2 + R/J/H. Atrox is advisory above Mentat, not an independent governance layer.

CAOM-001 Tier 0 declaration. Tier 0 Emergency Halt formally declared in Section V above the three-tier CAOM structure, bound to /api/halt endpoint behavior.

Thifur-H activation status. Two-state distinction documented: advisory active, autonomous declared not activated. Replaces prior "declared, not activated" rendering, which was inconsistent with deployed Kraken integration.

eFICC workforce specification absorbed. AUR-PT-EFICC-001 content rendered as Section IV with explicit cross-reference to architectural Thifur family in Section II.

## Resolved in v1.5

Doctrinal term "inherent-safety" defined. Section III opens with the explicit definition: multiple independent simultaneous failures required to produce loss, each independently bounded under stated assumptions. Marketing shorthand "zero-fail" mapped to this term. Doctrine no longer claims architectural impossibility in the colloquial sense, which would be undefendable under SR 11-7.

Axiom 10 added. Surfaces declared inherent-safety inherit the requirement that no single authority, single component, single signature, single key, single jurisdiction, or single counterparty may sit on the loss path. Failure to meet inherent-safety requirements on a declared inherent-safety surface is a doctrine integrity violation under Axiom 8.

Failure-mode taxonomy formalized. Three classes — Recoverable Automatic (RA), Recoverable Manual (RM), Unrecoverable (UR) — with the operational rule that UR-class failures may not be reachable on inherent-safety surfaces. The taxonomy is established here; exhaustive retrofit across existing failure-mode entries is part of v1.6.

Quorum authority defined as future-mode. Specified as the architectural requirement for institutional custody operations of material magnitude (large transfers, key ceremonies, encumbrance changes, lien releases, cold-storage rotations). Explicitly out of scope under CAOM-001 because single-operator three-tier signing does not meet separation-of-duties architecturally. Fifth CAOM transition trigger added: any quorum-required operation forces a formal CAOM transition review.

## Resolved in v1.6

Custody specification delivered. `AUR-CUSTODY-001 v1.0` is the substantive v1.6 doctrine addition. Asset-class breadth established as the durable architectural axis; settlement methods framed as the variable operational layer beneath. Operational quorum authority specification delivered (default 3-of-5 N-of-M with five independence requirements and six-step signature ceremony protocol). Four-class failure-mode taxonomy refinement (UR-R / UR-F) operationalized within the custody domain with examples spanning the full asset-class universe. Twenty-plus inherent-safety surfaces declared in 1:1 FIAT/digital parity. Forward-state framework covering atomic settlement, 24/7 operational continuity, selective FIAT/tokenized custody, PORTS-aligned architecture, and FIAT settlement-rail governance.

Failure-mode taxonomy retrofit within custody domain. Every custody operation type in operational specifications (FED-001, INST-001) is now bound to be tagged with its recoverability class (RA / RM / UR-R / UR-F). Operations tagged UR-F that are not on inherent-safety surfaces with quorum authority are doctrine integrity gaps and must be either remediated (move to inherent-safety surface with quorum authority) or eliminated (operation type is not offered). Retrofit across non-custody surfaces (broader convergence governance table, regulatory stress test matrix) remains anticipated work.

Quorum authority operational specification delivered. The N-of-M structure per operation class, the architectural enforcement of signing-authority independence, the signature ceremony protocol, and the integration with the propose/approve doctrine workflow are operationalized within `AUR-CUSTODY-001 v1.0` Section VII. The primitive remains out of scope under CAOM-001 because single-operator three-tier signing does not meet the architectural separation-of-duties requirements; licensees that wish to run quorum-required custody operations of material magnitude must establish post-CAOM authority structure first.

Workforce framing evolution from eFICC to Aureon Asset-Services Workforce. The Section IV workforce specification renamed framework-wide to match the asset-class breadth committed in `AUR-CUSTODY-001 v1.0` and the broader Asset Services strategic positioning. Existing role names (Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, Regulatory Reporting Analyst, the four Tier 2 roles, the three Tier 3 roles) remain canonical; the implicit scope of each role expands to span the full asset-class universe. Custody-specific roles added: Custody Operations Analyst at Tier 1; FIAT Operations Specialist, Digital Asset Custody Specialist, and Collateral Operations Specialist at Tier 2 (FIAT and Digital Specialists in explicit 1:1 parity). Anticipated additional asset-class-specific Tier 2 specialists (Physical Commodity Custody Specialist, Real Asset Custody Specialist, Alternative Asset Custody Specialist, Insurance and ILS Custody Specialist) named for future doctrine work.

## Open

Cato version parity. Deployed code is version-mixed: core gate logic at v0.2.2 (SOFR one-day delta trigger active), sticky last-known-good price cache at v0.2.3, several endpoint docstrings still at v0.2.1. External MCP README documents v0.2.0 / v0.2.1 routing. Action: issue a consolidated v0.2.3 stamp across core, cache, docstrings, and external README in a single commit series with verified identical decisions on identical inputs. Until that happens, the claim of parity is conditional, not established.

server.py duplicate function definitions. Three functions are defined twice in the live server.py: _save_state (lines 3793 and 3913), _load_state (lines 3831 and 3923), _build_trade_report (lines 742 and 3930). Python silently shadows the first definition with the second. The live system runs the second versions; the first versions are dead code carried in the binary. Action: delete the dead copies. This is implementation hygiene, not architectural risk, but for a system whose claim is doctrine before execution, carrying dead code in the live binary undermines the claim.

run_doctrine_stack theatricality. The run_doctrine_stack() function in server.py (line 4330) executes six time.sleep() calls totaling 2.0 seconds and returns a hardcoded "integrity: PASS" result with a SHA-256 audit hash signing the doctrine seed string. The audit hash is genuine; the layer execution it claims to sign is simulated. Action: either rip the sleeps and have the function actually invoke the doctrine layer modules (now present as imports), or rename to _seed_doctrine_state() so the function name reflects what it does. The current state is doctrine theater, which is the opposite of what Axiom 1 demands.

Hunter-Killer code path consolidation. The deployed Thifur-H lives at aureon/thifur/thifur_h.py and is the canonical implementation. A stub at aureon/agents/hunter_killer/ exists but is not imported by server.py. Action: archive or delete the stub and document that aureon/thifur/ is the canonical Thifur-H code path. Add a README to aureon/thifur/ that names the consolidation.

Framework Brief v2 republication. The public-facing framework brief at /framework-brief still uses the prior "Neptune Spear" rendering for the alpha-origination layer. Action: republish the brief to align with this canonical document and the live UI.

SVB calibration limit. Cato v0.2.2 catches March 2020 (100%) and September 2019 (80%) but only 45.5% of SVB (March 2023). Recorded as documented calibration limit — Cato is a market-regime gate, not a counterparty-credit gate. Any future extension into counterparty-credit signals (HY OAS, bank equity) will be a formal doctrine amendment with its own backtest and SR 11-7 review.

Thifur-H autonomous activation gate. Autonomous mode is architecturally specified but not activated. Activation per domain requires independent SR 11-7 Tier 1 validation, EU AI Act high-risk system EU database registration, and a formal doctrine amendment recorded in the version log. No conflict — this is the documented gating sequence. Tracked for risk-committee visibility: autonomous activation is the next major doctrine event and will require its own risk-committee review.

Failure-mode taxonomy retrofit beyond custody domain. The four-class taxonomy (RA / RM / UR-R / UR-F) is operationalized within the custody domain in `AUR-CUSTODY-001 v1.0` but has not been applied as tags to existing failure-mode entries in the broader convergence governance table (Section VI), the regulatory stress test matrix (Section IV), or the Tier 0/1/2/3 escalation logic in non-custody surfaces. Action: tag remaining non-custody failure-mode entries with their recoverability class as part of subsequent doctrine work that introduces new operational scope (anticipated alongside escrow doctrine, IPA doctrine, fund administration doctrine in the Asset Services roadmap).

Post-CAOM quorum authority for non-custody operations. Quorum authority is operationalized within the custody domain in `AUR-CUSTODY-001 v1.0`. Non-custody operations that may also require quorum (large doctrine amendments, fund-level position limits, regulatory engagement with multi-jurisdictional implications) remain out of scope under CAOM-001 with operational specification deferred to post-CAOM doctrine revisions. The architectural pattern is established; specific N-of-M structures and ceremony protocols for non-custody quorum operations are anticipated work.

Asset Services adjacency doctrine. The Asset Services roadmap (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue) is bound by `AUR-CUSTODY-001 v1.0` Section XI as inheriting the foundation doctrine. Operational specifications for each adjacency (anticipated document IDs `AUR-ESCROW-001`, `AUR-IPA-001`, `AUR-FUNDADMIN-001`, `AUR-STRUCTCRED-001`) are anticipated work following completion of `AUR-CUSTODY-FED-001` and `AUR-CUSTODY-INST-001`.

# CLOSING

This document is v1.6 of the Aureon Consolidated Canonical Doctrine. It supersedes v1.5.1 through a substantive doctrine addition: `AUR-CUSTODY-001 v1.0` (Aureon Custody Operational Doctrine) operationalizes the architectural prerequisites established in v1.5 within the custody domain and establishes asset-class breadth as the durable architectural axis. Section IV workforce framing is renamed framework-wide to "Aureon Asset-Services Workforce" to match the asset-class breadth and broader Asset Services strategic positioning. v1.6 inherits the supersession of all predecessor artifacts named in v1.5.1, v1.5, and v1.4. It is the single source of truth for the Aureon doctrine stack as of May 2, 2026. Where this document conflicts with any predecessor, this document governs.

v1.5 established inherent-safety as a doctrinal term, added Axiom 10 governing inherent-safety surfaces, formalized the three-class failure-mode taxonomy, and defined quorum authority as a future-mode primitive declared out of scope under CAOM-001. These four additions were the architectural prerequisites for v1.6 (custody), and they are now operationalized in `AUR-CUSTODY-001 v1.0` within the first inherent-safety domain. The custody doctrine establishes asset-class breadth as the durable architectural axis, frames settlement methods as the variable operational layer beneath, declares twenty-plus inherent-safety surfaces in 1:1 FIAT/digital parity, operationalizes the quorum authority specification (default 3-of-5 N-of-M with five independence requirements and six-step ceremony protocol), refines the failure-mode taxonomy with the four-class custody-specific UR-R / UR-F distinction, and establishes the forward-state framework covering atomic settlement, 24/7 operational continuity, selective FIAT/tokenized custody, PORTS-aligned architecture, and FIAT settlement-rail governance.

Future doctrine amendments flow through the propose / approve workflow defined in Section VII. The open conflicts log in Section X is the authoritative tracker of items pending closure. The next anticipated doctrine work: `AUR-CUSTODY-FED-001` (Atreides Federate Phase 1 operational specification) and `AUR-CUSTODY-INST-001` (Atreides Sovereign operational specification), both inheriting `AUR-CUSTODY-001 v1.0`, followed by Asset Services adjacency doctrine (anticipated `AUR-ESCROW-001`, `AUR-IPA-001`, `AUR-FUNDADMIN-001`, `AUR-STRUCTCRED-001`) tracking the strategic positioning roadmap (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue).

*— End of Aureon Consolidated Canonical Doctrine v1.6 —*

*Project Aureon · Columbia University M.S. Technology Management · Capstone Doctrine Publication*

*AUR-CANONICAL-001 · v1.6 · May 2, 2026*
