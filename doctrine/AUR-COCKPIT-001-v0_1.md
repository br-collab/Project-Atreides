# AUR-COCKPIT-001 — Clearing Operator Cockpit Doctrine

| Field | Value |
| --- | --- |
| Document | AUR-COCKPIT-001 — Clearing Operator Cockpit Doctrine |
| Version | v0.1 (doctrine-first · pre-implementation) |
| Status | Draft for review · drives the cockpit implementation |
| Doctrine anchor | AUR-CANONICAL-001 v1.6 (governance layers, CAOM-001, DSOR) · AUR-CUSTODY-001 v1.0 (settlement operations) · Settlement Operations Analyst (Tier 1, R-class) |
| Classification | Public — academic framework publication (MIT-licensed code) |
| Scope | The human-facing operator surface governing the clearing-and-settlement decision cycle around external CCP/CSD portals |

---

## I. Commander's intent (BLUF)

The Clearing Operator Cockpit governs the operator's decision cycle as it moves around — never through — the external clearing (CCP) and settlement (CSD) portals. It **gathers** the transaction picture, **validates** it against doctrine before anything leaves the firm, **prepares** a governed instruction package, and **reconciles** the result after the entitled member submits. It does not submit. The submission is the entitled member's regulated act; the **decision behind it** — validated, authority-attributed, recorded, replayable — is what the cockpit owns.

The cockpit exists because the portals are excellent at execution and silent on governance. They show what is true and let an entitled participant act. They do not record *why* a participant chose an action, *whose* authority approved it, whether magnitude required quorum, or produce a regulator-replayable decision-of-record traced to the originating event. That governance-and-audit layer above the portal is the vacancy this doctrine fills.

## II. Rules of engagement (the cardinal boundary)

This boundary is absolute and is the load-bearing rule of the entire surface:

> **Atreides prepares · governs · reconciles. The entitled member submits.**

- The cockpit **never** holds CCP/CSD credentials, **never** auto-submits a transaction, and **never** scrapes a portal.
- Data enters the cockpit only as **operator-entered readback** from systems the member is already entitled to (positions, requirements, deficits, net obligations, risk-control status).
- The cockpit emits a **validated instruction package** as a structured artifact for human entry — a prepared, checked, authorized set of details the operator keys (or the firm's own entitled system ingests). It is never a submission.
- Rationale: an outside framework cannot and must not interpose itself in a regulated member's settlement submission. The seat is governance, not execution.

## III. Layer placement

The cockpit is the **HITL operator surface** (CAOM-001 Operator authority) sitting above the R-class Settlement Operations Analyst. It is Layer-0/1 governance over Layer-2 portal execution. The portals (CCP clearing-fund management, CSD settlement UI) are the Layer-2 execution tools the cockpit consumes; the cockpit does not replicate them.

## IV. The operating cycle (the drill)

A repeatable five-beat cycle. Beats 1–3 and 5 are inside the cockpit's authority; beat 4 is explicitly outside it.

1. **Gather** — structured capture of the tasking: trade, counterparty, instrument (CUSIP), settlement date, rail (GSD DvP · sponsored DVP · GCF repo · Fedwire), the CCP net obligation, clearing-fund status, intraday funding/credit position.
2. **Validate** — run the tasking through the existing gates: eligibility → path selection → inherent-safety → intraday funding → clearing-fund compliance → net-obligation. A break caught here is caught **before** it reaches a portal. No package is emitted on a held gate.
3. **Prepare** — emit a validated settlement instruction package, carrying a DSOR pre-trade record and an authority stamp. Material magnitude routes to quorum **before** release. Output is an artifact or display — never a submission.
4. **Submit** — *performed by the entitled member, outside the cockpit's authority.* The operator (or the firm's entitled system) keys the prepared package into the portal under the member's own credentials and controls. The cockpit's role here is zero.
5. **Reconcile** — ingest the operator's readback of post-submission portal state (positions, deficit/excess, net obligation), compare expected vs. actual, and surface any discrepancy as a break routed to the workbench.

**Audit** is cross-cutting: the full cycle — gather → prepare → submission acknowledgment → reconcile — is one replayable DSOR lineage.

## V. Data boundary (consume, don't submit)

**Inbound (operator readback only):** security position balances; clearing-fund requirement / deposit / deficit / excess; CCP net settlement obligation; intraday funding and credit position; risk-control status (net debit cap, receiver-authorized-delivery / collateral monitor).

**Outbound:** validated settlement instruction package (structured artifact or display) for human entry; DSOR record; break tickets.

**Prohibited, without exception:** credential entry; auto-submission; portal scraping; storage of any CCP/CSD secret or entitlement.

## VI. CCP and CSD are separate regimes

The clearing leg (CCP — novation, netting, clearing fund) and the settlement/custody leg (CSD — securities custody, DvP) are distinct subsidiaries under distinct rulebooks, with distinct risk controls and distinct break types. The cockpit maintains **separate contexts** for each and does not flatten them into a single "depository" abstraction. This separation is the same clearing-vs-custody seam the framework is built to govern across.

## VII. Escalation triggers

- **Validation failure (pre-submit)** → hold; no package emitted; break raised.
- **Reconciliation discrepancy (post-submit)** → break to workbench, classified by leg (position break · funding break · clearing-fund break · net-obligation break).
- **Material magnitude** → quorum routing before package release.
- **Risk-control breach** (net debit cap, collateral monitor) → hold and escalate.

## VIII. Capability primitives (drives implementation)

- `capture_tasking` — structured intake of the transaction picture.
- `run_validation_gates` — reuse the Settlement Operations Analyst gate set.
- `emit_instruction_package` — produce the governed, exportable package (no submission surface).
- `ingest_portal_readback` — accept operator-entered post-submission state.
- `reconcile_expected_actual` — diff expected vs. actual; classify discrepancies.
- `raise_break` — route exceptions to the workbench with full lineage.

## IX. Out of scope

- Portal submission, credential handling, or anything requiring CCP/CSD participant entitlements.
- Collateral eligibility and haircut calculation (the CCP's clearing-fund tooling owns this; the cockpit consumes its output).
- Live rail execution.

## X. Regulatory anchors

- SEC Rule 17ad-22 (covered clearing agency standards) and the CCP government-securities rulebook.
- Federal Reserve Payment System Risk policy / net debit cap (CSD daylight-overdraft controls) — distinct from Regulation F (12 CFR 206), which governs correspondent credit exposure.
- SEC Treasury central-clearing mandate: eligible cash transactions by December 31, 2026; eligible repo by June 30, 2027.

## XI. Build status

- **Doctrine:** this document (v0.1).
- **Implementation:** roadmap. The cockpit surface demonstrates the operating cycle on synthetic inputs; live readback ingestion and reconciliation are roadmap. The submission boundary (beat 4) is permanent doctrine — no submission capability is ever to be built.

---

*AUR-COCKPIT-001 · v0.1 · Project-Atreides · Columbia University M.S. Technology Management*
