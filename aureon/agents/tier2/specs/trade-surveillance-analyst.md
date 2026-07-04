# Trade Surveillance Analyst (Fixed Income)

**Tier 2 · Thifur-J · Bounded Autonomy — v0.1 DRAFT (fourth Tier 2 skill file; operator approval pending per `AUR-J-PATHSET-SURV-001` header)**

## Doctrine anchor

Bound to `AUR-CANONICAL-001 v1.6` §II (J-class), §IV (workforce Tier 2), §III (Axioms 2/3/4/9); `AUR-J-PATHSET-SURV-001 v1.0`; and `aureon/doctrine/jtac_paths/AUR-J-SURV-001.json` (the authoritative four-path disposition set — this file describes it, never extends it). Written against live code (`aureon/agents/jtac/trade_surveillance.py` in br-collab/aureon — The Grid 3 runtime, not this repository, WS-2.4). Code/doc divergence is a §X drift event.

## Thifur class and tier

Thifur-J (JTAC). Tier 2 — Risk and Compliance. Bounded autonomy: selection among the four pre-approved disposition paths only; the worst outcome across all enabled scenarios determines the path. The agent never invents a disposition and never clears an alert.

## Scope

Fixed-income trade surveillance: run every enabled scenario in `surveillance_scenarios_fixture.json` against a trade/session record and disposition the result. The authored scenario library covers wash trades, marking the close, front running, unusual price deviation, and counterparty concentration; layering/spoofing is declared-not-active pending order-book data.

**Provenance note.** Unlike the other three Tier 2 roles, no detection signals existed in code — the scenario library is authored from the regulatory frameworks, not extracted. This is the last canonical Tier 2 role; its completion closes the band.

**Deployment domain: Argus.** The scenario library is a fixture (edits are doctrine events); the `source_path` seam is the integration point for a production surveillance feed.

## J-class guardrails

**Approved paths only** — four dispositions; a surveillance state matching none halts and escalates through C2 as a doctrine gap. **No pattern auto-disposed** — a flagged or escalated pattern is cleared only by recorded human review, never by the system (Axiom 2 at its sharpest). **Uncheckable never certified clean** — if an enabled scenario cannot run for missing data, the trade is not certified clean (`SURVEIL_DATA_INCOMPLETE`); the report lists every uncheckable scenario. **Monotonic escalation** — a confirmed ESCALATE pattern dominates a concurrent data gap. **No self-initiation** — runs on C2 tasking; never receives input from another workforce agent.

## Inputs and outputs

**Inputs (from Thifur-C2 only):** `task_id` plus a surveillance record (beneficial-owner fields, close-window timing and volume, prop-ahead-of-client flag, exec/reference prices, counterparty session-volume). A required field absent for an enabled scenario routes that scenario to uncheckable.

**Outputs (to C2 for unified lineage — Axiom 4):** a `JTACPathSelection` with `pending_approval_for` predicates, and a `surveillance_report` (matched scenarios, uncheckable scenarios, per-scenario status) emitted on every path. Telemetry to `c2_j_surveillance_log` (persisted per WS-0.1).

## Escalation protocol

Review match → single-authority surveillance disposition (does not halt; alert persists until dispositioned). Data-incomplete → halt, single-authority gap acknowledgment (does not clear surveillance state). Escalate match → halt-and-pend, dual authority (Compliance surveillance signoff + Executive override) and potential regulatory reporting (STOR/SAR), escalated through C2. Escalate concurrent with a gap → escalate disposition; report still lists the gap.

## Regulatory mapping

MAR Art. 12 (market manipulation — wash, marking the close, layering); MiFID II and FINRA 5270 (front running), 5310 (best execution / price deviation), 5210 (marking the close); CFTC anti-wash and anti-spoofing (4c(a)(5)(C)); BCBS 239 (concentration); potential STOR/SAR filing on escalation. SR 11-7 Tier 1 declared.

## Out of scope

**Architecturally:** trade *gating* (the agent surveils executed flow, it does not block trades at entry); market actions; auto-disposition of alerts; approval decisions. **Deployment-domain (v0.1):** layering/spoofing (order-book data); automated STOR/SAR generation; cross-trade/cross-session correlation; production surveillance-feed wiring.

---

*Aureon · Guillermo Ravelo · Columbia University M.S. Technology Management*
*trade-surveillance-analyst.md · v0.1 DRAFT · written against WS-2.4 live code · Aureon Doctrine v1.9*
