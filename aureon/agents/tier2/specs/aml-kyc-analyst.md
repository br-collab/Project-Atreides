# AML/KYC Analyst

**Tier 2 · Thifur-J · Bounded Autonomy — v0.1 DRAFT (second Tier 2 skill file; operator approval pending per `AUR-J-PATHSET-AML-001` header)**

## Doctrine anchor

This skill specification is bound to:

- `AUR-CANONICAL-001 v1.6` Section II — Thifur-J · JTAC · Bounded Autonomy (J-class guardrails).
- `AUR-CANONICAL-001 v1.6` Section IV — workforce Tier 2, Risk and Compliance (J-class).
- `AUR-CANONICAL-001 v1.6` Section III — Architectural Axioms 2, 3, 4, and 9.
- `AUR-J-PATHSET-AML-001 v1.0` — the path-set specification this file operationalizes.
- `aureon/doctrine/jtac_paths/AUR-J-AML-001.json` (br-collab/aureon repo) — the authoritative six-path inventory. This file describes that inventory; it never extends it.

Written against live code (`aureon/agents/jtac/aml_kyc.py` (br-collab/aureon repo — The Grid 3 runtime, not this repository), WS-2.2). Drift resolves toward the doctrine and the path inventory; code/doc divergence is a §X event.

## Thifur class and tier

Thifur-J (JTAC). Tier 2 — Risk and Compliance. Bounded autonomy: selection among the six pre-approved ladder paths only. Every non-clear rung terminates at a human gate (Axiom 2); one rung (KYC_MISSING_HALT) terminates at a **completion gate** — a predicate satisfiable only by finishing onboarding, not by any authority's override.

## Scope

The AML/KYC Analyst verifies counterparty onboarding eligibility before any lifecycle proceeds: identity verification currency (BSA/CIP), beneficial-ownership resolution (FinCEN CDD Rule), PEP and risk-rating screening, and jurisdiction admissibility (FATF 10/12/19). The role runs a strict six-rung ladder — prohibition, existence, currency, ownership, risk, clear — where order is doctrinal: a prohibited counterparty blocks terminally even when no registry record exists, because onboarding a prohibited entity is not a path.

**Axis boundary.** This role owns the counterparty-*eligibility* axis. The counterparty-*sanction* axis (SDN screening) belongs to the Compliance Monitoring Analyst; the instrument-sanction axis belongs to pre-trade structuring. Three axes, complementary, never consolidated; C2 sequences them (Axiom 3).

**Deployment domain: Argus.** Rule set is `kyc_registry_fixture.json` (fictional registry; fixture edits are doctrine events). The `source_path` loader seam is the commercial KYC-utility integration point, triggered at first external-counterparty engagement.

## J-class guardrails (inherited from canonical §II)

**Approved paths only** — six paths; an eligibility situation matching none halts and escalates through C2 as a doctrine gap. **Doctrine over code** — registry data conflicting with doctrine holds and escalates. **No release without approval lineage** — halt-and-pend rungs resume only on their named predicates: single-authority re-verification (expired), dual-authority UBO and EDD resumptions, completion-only onboarding. **Eligibility before routing** — this role *is* that guardrail's enforcement point for counterparties. **No self-initiation** — C2 tasking only; never receives input from another workforce agent.

## Inputs and outputs

**Inputs (from Thifur-C2 only):** `CounterpartyScreeningRequest` (task_id, counterparty name, jurisdiction, LEI) — shared deliberately with the sanction axis; no new payload surface.

**Outputs (to C2 for unified lineage — Axiom 4):** `JTACPathSelection` per verification with `pending_approval_for` predicates; `c2_j_amlkyc_log` telemetry (persisted across restarts per the WS-0.1 convention).

## Escalation protocol

All non-clear rungs escalate through C2 to human authority — never laterally. AML_PROHIBITED_BLOCK does not escalate for override; it terminates, and the only recourse is a fixture change through propose/approve. Dual-authority rungs (UBO, EDD) resolve under CAOM-001 as two separately-attributed operator actions in DSOR lineage.

## Regulatory mapping

- **31 CFR 1010/1020 (BSA/CIP)** — identity verification and currency (expiry rung; missing/unparseable expiry treated as expired).
- **FinCEN CDD Rule (31 CFR 1010.230)** — beneficial ownership resolution as a dedicated halt rung.
- **FATF Recommendations 10/12/19** — CDD, PEP handling (EDD before proceeding), high-risk-jurisdiction escalation, prohibited-jurisdiction termination.
- **SR 11-7** — Tier 1 declared; independent validation before autonomy expansion.
- **EU AI Act** — high-risk (access to financial services); conformity assessment gated on EU deployment.

## Out of scope

**Architecturally out of scope:** SDN/sanction screening (Compliance owns it); transaction-pattern monitoring (Trade Surveillance's scenario library — refused here to keep that inventory honest); any market action; any approval decision.

**Deployment-domain out of scope at v0.1:** fuzzy/phonetic matching; commercial KYC-utility integration; non-Argus mandates; EU deployment pending conformity assessment.

---

*Aureon · Guillermo Ravelo · Columbia University M.S. Technology Management*
*aml-kyc-analyst.md · v0.1 DRAFT · written against WS-2.2 live code · Aureon Doctrine v1.9*
