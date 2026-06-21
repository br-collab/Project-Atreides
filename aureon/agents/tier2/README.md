# Aureon Asset-Services Workforce — Tier 2 — FIAT Operations Specialist

Per **AUR-CUSTODY-001 v1.0 Section VI** (Custody-Specific Roles in the
Aureon Asset-Services Workforce — FIAT Operations Specialist) and
**AUR-CANONICAL-001 v1.6 Section II** (Thifur-J — JTAC bounded
autonomy).

This module implements the **FIAT Operations Specialist**, a Tier 2
Thifur-J class agent that handles FIAT-leg operations within bounded
autonomy across the asset-class universe. It is the **1:1 parity
counterpart** to the (forthcoming) Digital Asset Custody Specialist
per CUS Section VI: the doctrine commits to structural symmetry
between FIAT and digital legs because beneficial owners increasingly
hold positions across both representations of the same asset class,
and the framework does not privilege one leg over the other.

## Architectural Position

The agent operates **between** two layers it does not own:

**Consumes — `aureon.contracts`** (the typed substrate built in the
contracts layer, `v0.1-contracts-complete`):

- `asset_class` — the asset-class universe enum and FIAT /
  TOKENIZED / NATIVE_DIGITAL representation axis
- `custody_object` — the five custody object categories
- `failure_mode` — the four-class taxonomy (RA / RM / UR-R / UR-F)
- `inherent_safety` — the inherent-safety surface declarations
- `quorum` — the QuorumAuthority typed structures
- `settlement` — the eleven-method discriminated union
- `dsor_stub` — the DSOR lineage stub fields operations carry
- `operations` — the `CustodyOperation` base and per-asset-class
  models with cross-validators (UR-F → inherent-safety,
  inherent-safety → quorum)

**Produces — structured outputs for downstream consumers**, **none of
which are in scope for this build**:

- DSOR record assembly and persistence (`aureon/dsor/`)
- Quorum ceremony state machine — consumes the
  `QuorumAuthorityRequired` packages this agent produces
- Rail integration (Fedwire, CHIPS, Target2, etc.) — consumes
  `RoutingDecision` outputs
- The Cato-equivalent FIAT-rail governance gate per CUS Section X —
  feeds the agent forward-state routing context (anticipated work)

The agent **produces routing decisions; it does not execute**. It
assembles structured packages that downstream layers consume per
AUR-CANONICAL-001 v1.6 Section II Thifur-J.

## Module Structure

| File | Purpose |
|---|---|
| `outputs.py` | Three discriminated-union output structures (`RoutingDecision`, `EscalationRequired`, `QuorumAuthorityRequired`) plus supporting types (`EligibilityCheck`, `EligibilityVerification`, `JurisdictionalAttribution`, `RoutingRecommendation`, `OperationPackage`) and the `FIAT_SPECIALIST_OWNED_SURFACES` frozenset |
| `routing_tables.py` | `ApprovedPath` model with multi-dimension membership (a path can serve Dim 1 and Dim 5 simultaneously), `RoutingTables` registry with per-dimension query methods, and `default_routing_tables()` representative non-exhaustive factory covering all seven dimensions |
| `eligibility.py` | Five typed evidence models (`KYCEvidence`, `KYBEvidence`, `OFACScreeningEvidence`, `SanctionsScreeningEvidence`, `CorrespondentBankComplianceEvidence`) plus `EligibilityInputs` and the pure `verify_eligibility()` function |
| `fiat_operations_specialist.py` | `MagnitudeThresholdPolicy` model (per-deployment material-magnitude thresholds), `PathSelectionRequest` (common inputs for path-selection methods), and `FIATOperationsSpecialist` class with the seven path-selection methods, the five guardrail enforcement methods, and the material-magnitude routing-to-quorum machinery |

## Seven Path-Selection Dimensions

Per **AUR-CUSTODY-001 v1.0 Section VI lines 618-632**:

1. **Multi-currency settlement rail routing** (`select_multi_currency_rail_routing`) — Fedwire, CHIPS, ACH, SWIFT MT103/MT202, Target2, CHAPS, Zengin, and analogous large-value/clearing systems globally
2. **Correspondent banking coordination** (`select_correspondent_banking_coordination`) — nostro/vostro positioning, cover-vs-serial payment, intermediary bank routing
3. **Cross-border settlement with FX leg coordination** (`select_cross_border_fx_leg`) — CLS PvP, on-us, bilateral PvP, traditional gross when PvP unavailable
4. **Depository versus sub-custodian routing** (`select_depository_vs_sub_custodian`) — direct depository membership vs sub-custodian intermediation
5. **Large-value payment system selection** (`select_large_value_payment_system`) — among multiple eligible LVPS by settlement risk profile (Fedwire RTGS-final vs CHIPS net-final vs SWIFT correspondent-dependent)
6. **Fed-related operations** (`select_fed_related_operation`) — Discount Window, SRF, RRF, Federal Reserve account operations
7. **Cash sweep and short-term investment routing** (`select_cash_sweep_and_short_term_investment`) — MMFs, bank deposit programs, repo investment vehicles, tri-party repo

## Five J-Class Guardrails

Per **AUR-CANONICAL-001 v1.6 Section II Thifur-J** and
**AUR-CUSTODY-001 v1.0 Section VI line 634** (FIAT-leg rendering).
Every path-selection decision runs Guardrail 4 → Guardrail 5 →
Guardrail 1 in sequence.

1. **Approved paths only** — the agent selects from path options in the Kaladan-managed routing tables and never generates new paths; no-match produces an `EscalationRequired` rather than improvisation
2. **Doctrine over code** (Axiom 5, meta-guardrail) — when an external system message or instruction would cause one of guardrails 1, 3, 4, or 5 to be violated, the agent emits `EscalationRequired` with `failed_guardrail = DOCTRINE_OVER_CODE` and a typed `cascade_guardrail` field naming the underlying violated rule
3. **No settlement without approval lineage** — every `RoutingDecision` carries the doctrine version stamp, authority routing, agent telemetry hash, and DSOR lineage stub fields populated; missing fields fail validation at the schema layer
4. **Eligibility before routing** — five checks (KYC, KYB, OFAC, sanctions, correspondent-bank compliance) verified before any routing decision; failures produce escalation
5. **Jurisdictional attribution before execution** — Verana attribution required on every cross-border FIAT transfer per **Section II Layer 0** and **Axiom 8** *(note: the doctrine cites "Section VIII" at CUS Section VI line 634; that is a known erratum tracked in `FOLLOW-UPS.md` — the correct citation is Section II + Axiom 8)*

## Material-Magnitude Routing to Quorum

Per **AUR-CUSTODY-001 v1.0 Section VII** and CUS Section VI line 636.
The material-magnitude check runs **BEFORE** the Guardrail 4 → 5 → 1
sequence on every path-selection method — inherent-safety architectural
protection per **AUR-CANONICAL-001 v1.6 Axiom 10** cannot be relaxed
because eligibility failed (eligibility failures can be cured through
re-screening; quorum protection is structural).

`_check_material_magnitude` carries **four triggers**:

- **Trigger 0 (architectural completeness)** — operation arriving with a
  non-None `inherent_safety_surface` (UR-F operations always have one
  per the contracts-layer validator) routes natively to quorum on that
  surface
- **Trigger 1 (sanctioned-jurisdiction adjacency)** — `request.attribution`
  names a jurisdiction in the policy's `sanctioned_adjacency_jurisdictions`
  set; returns `FIAT_SETTLEMENT_MATERIAL`
- **Trigger 2 (amount-above-threshold)** — `request.amount` exceeds the
  per-dimension threshold in the policy; returns the dimension-mapped
  surface (`FIAT_SETTLEMENT_MATERIAL` for Dim 1, `LARGE_VALUE_PAYMENT_FINALITY`
  for Dim 5, `FX_BUNDLED_SETTLEMENT` for Dim 3)
- **Trigger 3 (correspondent banking changes)** — *deferred* per `FOLLOW-UPS.md`;
  requires modeling the operation as a "banking change" type at the
  contracts layer

When triggered, the agent assembles an **`OperationPackage`** per CUS
Section VII Step 1 with the eight components (operation specification,
beneficial owner ids, asset ids, doctrine version stamp, pre/projected-post
DSOR state stubs, optional routing recommendation if determinable,
eligibility verification results) and emits `QuorumAuthorityRequired`.
The package carries pre-quorum eligibility analysis **even when failed**
so the downstream quorum ceremony state machine sees the complete picture.

The agent **owns five of the inherent-safety surfaces** in CUS Section
IX (`FIAT_SPECIALIST_OWNED_SURFACES`):

- `FIAT_SETTLEMENT_MATERIAL`
- `CORRESPONDENT_BANKING_INTEGRITY`
- `LARGE_VALUE_PAYMENT_FINALITY`
- `FX_BUNDLED_SETTLEMENT`
- `DEPOSITORY_MEMBERSHIP`

Other Section IX surfaces (key ceremonies, cold storage, native digital
asset operations, beneficial-owner identity changes, etc.) are owned
by other roles or by layers above this agent.

## Operator Notes — Known Deferrals

All deferrals are tracked in `FOLLOW-UPS.md` at the repo root. The
load-bearing items:

- **MagnitudeThresholdPolicy concrete values** — per CUS Section VII
  line 686, deployment-specific thresholds are FED-001 / INST-001
  product-specification work. The agent enforces structural rules
  (whether a surface triggers based on policy state) but does not
  encode specific dollar values.
- **Routing tables exhaustive enumeration** — `default_routing_tables()`
  is a representative set covering all seven dimensions. Exhaustive
  enumeration of all eligible correspondent banks, sub-custodians,
  MMFs, and global large-value systems requires external data sources
  (SWIFT BIC directory, depository membership rosters, fund-vendor
  data) and is operational-specification work.
- **Cato-equivalent FIAT-rail governance gate** — per CUS Section X,
  a FIAT-rail equivalent of the Cato governance gate is anticipated
  doctrine work. The agent is built to **consume** gate decisions
  when present; it does not provide gate logic.
- **External eligibility-service integration** — `eligibility.py` runs
  type-safe checks against operation-supplied evidence; real OFAC list
  lookups, real KYC/KYB provider APIs, and real correspondent-bank
  compliance attestation sources are operational-specification work.
- **Path-selection tiebreak logic** — when multiple approved paths
  satisfy a dimension's criteria, the agent picks `candidates[0]`.
  Sophisticated tiebreak (cost ranking, operational-hours preference,
  latency-aware routing, counterparty concentration) depends on
  licensee deployment context and is FED-001 / INST-001 work.
- **FX magnitude pair-aware evaluation** — the agent checks the base
  currency natively (first half of `XXX/YYY`); quote-currency check is
  configurable via `MagnitudeThresholdPolicy.fx_bundled_thresholds`.
  Pair-aware native evaluation depends on the licensee's currency-
  exposure framework.
- **`OperationPackage` contract evolution** — the
  `eligibility_verification` field carries failed verification
  intentionally. The validator that initially rejected failed
  eligibility (specified in sub-commit A design of Module 4) was
  removed in sub-commit C when the conflict between sub-commit A's
  "package requires passing eligibility" and sub-commit C's "capture
  pre-quorum eligibility even when failed" surfaced. Future readers
  should not reintroduce eligibility-all-passed validation at the
  OperationPackage layer — that concern belongs to the consumer
  (quorum ceremony state machine), not the producer (Tier 2 agents).

## Doctrine sources

- [`doctrine/AUR-CANONICAL-001-v1_6.md`](../../../doctrine/AUR-CANONICAL-001-v1_6.md) —
  framework-level source of truth (layered architecture, eight
  governance axioms, inherent-safety doctrinal term and Axiom 10,
  three-class failure-mode taxonomy, CAOM-001 authority structure,
  Asset-Services Workforce specification)
- [`doctrine/AUR-CUSTODY-001-v1_0.md`](../../../doctrine/AUR-CUSTODY-001-v1_0.md) —
  custody-specific operational doctrine (Section VI FIAT Operations
  Specialist, Section VII quorum authority, Section VIII four-class
  failure-mode refinement, Section IX inherent-safety architecture,
  Section X forward-state framework)
