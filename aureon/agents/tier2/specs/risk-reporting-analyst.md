# Risk Reporting Analyst

**Tier 2 · Thifur-J · Bounded Autonomy — v0.1 DRAFT (third Tier 2 skill file; operator approval pending per `AUR-J-PATHSET-RISK-001` header)**

## Doctrine anchor

Bound to `AUR-CANONICAL-001 v1.6` §II (J-class), §IV (workforce Tier 2), §III (Axioms 2/3/4/9); `AUR-J-PATHSET-RISK-001 v1.0` (path-set spec); and `aureon/doctrine/jtac_paths/AUR-J-RISK-001.json` (the authoritative four-path disposition set — this file describes it, never extends it). Written against live code (`aureon/agents/jtac/risk_reporting.py`, WS-2.3). Code/doc divergence is a §X drift event.

## Thifur class and tier

Thifur-J (JTAC). Tier 2 — Risk and Compliance. Bounded autonomy: selection among the four pre-approved disposition paths only. Path is determined by the worst rung any metric reaches; the agent never invents a disposition.

## Scope

Periodic **portfolio-level** risk aggregation: compute drawdown, single-position concentration, sector concentration, and liquidity-buffer metrics against `risk_thresholds_fixture.json`, assemble a per-metric risk report (BCBS 239 aggregation), and select the disposition — within-limits, warn, data-incomplete, or breach.

**Boundary.** This role reports **standing** risk. Per-trade risk *gating* (blocking a single trade at entry) belongs to `pretrade_structuring` and is architecturally separate — see `AUR-J-PATHSET-RISK-001` §II. This role never gates a trade; it surfaces the aggregate picture to human authority. Complementary, not redundant; C2 sequences them (Axiom 3).

**Deployment domain: Argus.** Thresholds are a fixture (edits are doctrine events); the `source_path` seam is the production-risk-engine integration point.

## J-class guardrails

**Approved paths only** — four dispositions; a risk state matching none halts and escalates through C2 as a doctrine gap. **Gaps flagged, never silently filled** — a report with a missing metric never presents as within-limits (`RISK_DATA_INCOMPLETE` outranks within/warn); the report lists `missing_metrics` on every path. **Escalation strength is monotonic** — a hard breach dominates a concurrent data gap, so a known breach always draws dual authority. **No release without approval lineage** — warn needs CRO acknowledgment; breach needs dual authority (CRO + Executive). **No self-initiation** — runs on C2 tasking; never receives input from another workforce agent.

## Inputs and outputs

**Inputs (from Thifur-C2 only):** `task_id` plus a portfolio snapshot (drawdown %, single-position concentration %, sector concentration %, liquidity buffer %). A required metric absent from the snapshot routes to `RISK_DATA_INCOMPLETE`.

**Outputs (to C2 for unified lineage — Axiom 4):** a `JTACPathSelection` with `pending_approval_for` predicates, and a `risk_report` (per-metric status, flagged and missing metrics) emitted on every path. Telemetry to `c2_j_risk_log` (persisted per WS-0.1).

## Escalation protocol

Warn → CRO single-authority acknowledgment (not a halt). Data-incomplete → halt, single-authority gap acknowledgment (does not clear the risk state). Breach → halt-and-pend, dual authority (CRO signoff + Executive override), escalated through C2 to the single human authority surface. Breach concurrent with a gap → breach disposition (dual authority), report still lists the gap.

## Regulatory mapping

BCBS 239 P3 (accuracy — automated aggregation) and P5 (timeliness); SR 11-7 (risk monitoring, Tier 1 declared); DORA (liquidity resilience — the cash-buffer metric); mandate compliance (concentration caps).

## Out of scope

**Architecturally:** per-trade risk gating (pre-trade structuring owns it); market actions; approval decisions (the agent selects a disposition; humans acknowledge/sign off). **Deployment-domain (v0.1):** live-state wiring pending a sector-concentration computation not yet in `_calc_portfolio`; production risk-engine integration; historical trending.

---

*Aureon · Guillermo Ravelo · Columbia University M.S. Technology Management*
*risk-reporting-analyst.md · v0.1 DRAFT · written against WS-2.3 live code · Aureon Doctrine v1.9*
