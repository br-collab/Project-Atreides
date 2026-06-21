# FOLLOW-UPS

Items noticed during the contracts-layer build and the FIAT Operations
Specialist agent build that are explicitly out of scope for those
builds but should be addressed in subsequent work.

## Doctrine errata to fix in the next custody doctrine iteration

- **`AUR-CUSTODY-001 v1.0` Section VI line 634 — wrong Section
  citation for Verana jurisdictional attribution.** The doctrine
  cites "AUR-CANONICAL-001 v1.6 Section VIII" as the authority for
  Verana jurisdictional attribution; Section VIII is the
  Institutional Licensing Thesis and does not address attribution.
  The correct citation is **Section II (Layer 0 — Verana — Network
  Governance, lines 121-129) and Axiom 8 (Verana Autonomous Block,
  line 199)**. Confirmed with the operator at the FIAT Operations
  Specialist build start. The FIAT Operations Specialist code uses
  the corrected citation in code comments and runtime error messages
  (Guardrail 5); the build prompt's `Section VIII` reference also
  reproduces the erratum. Fix in the next custody doctrine
  iteration; do not edit the existing v1.0 document for this single
  citation.

## FIAT Operations Specialist build — out-of-scope items deferred

- **`_check_material_magnitude` four-trigger architecture.** Three
  triggers come from AUR-CUSTODY-001 v1.0 Section VI line 636
  (amount-above-threshold, sanctioned-jurisdiction adjacency, and
  correspondent-banking-changes — the third deferred per the
  separate FOLLOW-UPS entry above). The fourth trigger — Trigger 0 —
  is an architectural-completeness trigger: an operation arriving
  with a non-None ``inherent_safety_surface`` (UR-F operations always
  carry one per the contracts-layer validator) routes natively to
  ``QuorumAuthorityRequired``, because inherent-safety surfaces
  require quorum authority per AUR-CANONICAL-001 v1.6 Axiom 10
  regardless of amount or jurisdiction. Trigger 0 was identified
  during sub-commit D integration testing when UR-F coverage required
  it; the architectural reasoning makes it correct rather than
  improvised. Future readers extending ``_check_material_magnitude``
  should preserve all four triggers.
- **OperationPackage contract evolution.** The
  ``eligibility_verification`` field on
  :class:`aureon.agents.tier2.outputs.OperationPackage` carries
  whatever pre-quorum analysis was done, including failed
  verification. This is intentional — the quorum ceremony state
  machine (future module) needs to see failed verification to make
  appropriate routing decisions (ceremony rejection, compliance
  review escalation, possibly Tier 0 Halt depending on which check
  failed). The validator that initially rejected failed eligibility
  (specified in sub-commit A design of Module 4) was removed in
  sub-commit C when the conflict between sub-commit A's "package
  requires passing eligibility" and sub-commit C's "capture
  pre-quorum eligibility even when failed" surfaced. Future readers
  should not reintroduce eligibility-all-passed validation at the
  OperationPackage layer — that concern belongs to the consumer
  (quorum ceremony state machine), not the producer (Tier 2 agents).
- **FX magnitude detection.** The agent checks the base currency
  natively (first half of an ``XXX/YYY`` pair); quote-currency check
  is configurable via
  :attr:`MagnitudeThresholdPolicy.fx_bundled_thresholds` (deployments
  needing the quote currency to also be checked configure both
  currencies in the threshold map). Pair-aware native evaluation
  (currency-pair concentration weighting, base-vs-quote dominance
  logic) is operational-specification work for AUR-CUSTODY-FED-001 /
  AUR-CUSTODY-INST-001 because the optimal evaluation logic depends
  on the licensee's currency-exposure framework.
- **Path-selection tiebreak logic.** When multiple approved paths
  satisfy a dimension's criteria, the agent currently picks
  ``candidates[0]`` (first match). Sophisticated tiebreak based on
  cost ranking, operational-hours-aware preference, latency-aware
  routing, or counterparty concentration is operational-specification
  work deferred to AUR-CUSTODY-FED-001 / AUR-CUSTODY-INST-001 because
  the optimal tiebreak depends on licensee deployment context
  (correspondent banking arrangements, fee economics, redundancy
  posture). The structural correctness — agent selects from approved
  set, never generates — holds at the framework level.
- **Correspondent banking changes affecting custody routing as a
  material-magnitude trigger.** AUR-CUSTODY-001 v1.0 Section VI line
  636 names this as the third material-magnitude trigger alongside
  large-value transfers and sanctioned-jurisdiction adjacency. The
  agent's ``_check_material_magnitude`` implements the first two
  triggers; the third requires modeling the operation as a "banking
  change" type at the contracts layer (currently no such operation
  type exists). Deferred to a contracts-layer addition followed by an
  agent-side trigger handler.
- **MagnitudeThresholdPolicy concrete values.** The FIAT Operations
  Specialist enforces structural rules around material-magnitude
  triggering (whether a surface triggers based on policy state) but
  does not encode specific dollar/per-currency/per-jurisdiction
  thresholds. Concrete threshold values are FED-001 / INST-001
  product-specification work per AUR-CUSTODY-001 v1.0 Section VII
  line 686 ("the specific thresholds are Sovereign- and
  Federate-specific and will be set in INST-001 and FED-001
  respectively"). This build provides the policy-injection interface;
  threshold population is a downstream operational specification
  concern.
- **Cato-equivalent FIAT-rail governance gate.** Per AUR-CUSTODY-001
  v1.0 Section X (FIAT Settlement-Rail Governance), a FIAT-rail
  equivalent of the Cato governance gate is anticipated as forthcoming
  doctrine work. The FIAT Operations Specialist is built to **consume**
  gate decisions when they are present (the `RoutingRecommendation`
  carries the path identifier; future iterations may carry an embedded
  gate decision reference). The agent does not provide gate logic; it
  consults gate decisions when present and proceeds without them when
  absent.
- **Routing tables — exhaustive enumeration.** The
  `aureon/agents/tier2/routing_tables.py` module (subsequent build
  step within this build) starts with a representative non-exhaustive
  set of approved paths. Exhaustive enumeration of all eligible
  correspondent banks, all sub-custodian relationships, all MMF
  destinations, and all global large-value systems requires external
  data sources (SWIFT BIC directory, depository membership rosters,
  fund-vendor data) and is deferred. The agent's structural behavior
  (selecting from approved paths only, escalating on no-match) is
  exercised by the representative set.
- **`aureon/agents/tier2/eligibility.py` — external service
  integration.** The eligibility verification module implements
  type-safe checks against operation inputs and does **not** integrate
  with external eligibility services (real OFAC list lookups, real
  KYC/KYB providers, real correspondent-bank compliance APIs). The
  agent's structural behavior (running all five checks before any
  routing decision; escalating on any failure) is exercised against
  synthetic inputs. External-service integration is operational-
  specification work for FED-001 / INST-001.

## Doctrine ambiguities resolved by reasonable assumption

These were flagged during the build and resolved by an explicit
modeling choice. Each entry names the section, the choice made, and the
default that downstream layers can override without breaking
contracts.

- **`AUR-CUSTODY-001 v1.0` Section VII — N-of-M structure ranges.** The
  doctrine names default 3-of-5 and example ranges (2-of-3 through
  5-of-7) but defers per-magnitude threshold selection to FED-001 /
  INST-001. The contracts layer enforces only the structural rule
  N ≥ 1, N ≤ M. Per-deployment thresholds are an operational
  specification concern.
- **`AUR-CUSTODY-001 v1.0` Section VII — organizational independence
  count.** The doctrine names "at least three organizational units" at
  Sovereign deployment and "adapts" for Federate. The contracts layer
  enforces "at least two distinct organizational units" as the general
  principle and leaves the Sovereign-specific tighter threshold to
  INST-001.
- **`AUR-CUSTODY-001 v1.0` Section VII — temporal independence
  interval.** The doctrine references "1 hour minimum between first
  and last signature" as an example. The contracts layer carries the
  per-signature timestamps and the requirement flag but does not
  enforce intervals — this is a runtime ceremony-execution concern.
- **`AUR-CUSTODY-001 v1.0` Section IV — five custody object
  categories.** Restated in Section IV from `AUR-CUSTODY-OBJ-001 v1.0`.
  Per the build prompt, OBJ-001 is not authoritative — the
  categorization as restated in the custody doctrine governs.
  Confirmed with the operator at build start.
- **`AUR-CUSTODY-001 v1.0` Section III — emerging asset categories.**
  Modelled as a single ``MajorAssetCategory.EMERGING`` with no
  representation constraint. Subsequent doctrine work that names a
  specific emerging category may add a dedicated enum value (which
  will be a doctrine-modifying change per the propose/approve
  workflow).
- **`AUR-CUSTODY-001 v1.0` Section V — UR-R / UR-F per transaction
  type.** The doctrine binds operational specifications (FED-001 /
  INST-001) to tag every operation type with its failure-mode class.
  At the contracts layer the failure-mode class is a per-operation
  field (caller-provided) rather than hard-coded per transaction type.
  The architectural cross-validators on the base operation enforce
  the doctrinal rules (UR-F → inherent-safety; inherent-safety →
  quorum) regardless.

## Out-of-scope work named in the build prompt

- **Aureon Asset-Services Workforce agents.** Custody Operations
  Analyst (Tier 1); FIAT Operations Specialist, Digital Asset Custody
  Specialist, Collateral Operations Specialist (Tier 2). Implementation
  in `aureon/agents/`. Per AUR-CUSTODY-001 v1.0 Section VI.
- **Quorum authority ceremony state machine.** The contracts layer
  exposes the typed substrate (`aureon/contracts/quorum.py`). The
  ceremony execution, signature collection, cryptographic signing
  infrastructure, and runtime enforcement of temporal independence
  are subsequent work. Per AUR-CUSTODY-001 v1.0 Section VII.
- **DSOR record assembly and lineage stamping.** The contracts layer
  exposes `aureon/contracts/dsor_stub.py` for operations to carry the
  minimum lineage fields. Full DSOR (the Thifur-C2-assembled unified
  lineage record) lives in `aureon/dsor/`.
- **Rail integration layer.** FIAT-rail governance gate (AUR-CUSTODY-001
  v1.0 Section X 1:1 parity with Cato), atomic settlement governance,
  PORTS-aligned wholesale tokenized infrastructure activation.
  `aureon/rails/`.
- **Settlement-method-to-asset-class compatibility validators.** The
  build prompt named: "the settlement method on a custody operation
  must be valid for the operation's asset class and transaction type
  — validators enforce this." The contracts layer carries the
  per-operation `settlement_method` field but does not encode the full
  compatibility matrix (e.g., FX cannot use DvD; key ceremonies have
  no settlement leg). Operational specifications detail the per-
  asset-class compatibility per deployment; the contracts layer rejects
  obviously incoherent pairings via existing per-operation validators
  but does not enforce a global matrix.
- **Product-specific operational specifications.** `AUR-CUSTODY-FED-001`
  (Atreides Federate Phase 1 governance overlay) and
  `AUR-CUSTODY-INST-001` (Atreides Sovereign institutional
  displacement). Per AUR-CUSTODY-001 v1.0 Section XI.
- **Asset-class-specific operation modules anticipated by Section VI.**
  Physical Commodity Operations, Real Asset Operations, Insurance and
  ILS Operations, IP and Royalty Stream Operations, Alternative Asset
  Operations. Each is a future addition to
  `aureon/contracts/operations/` with a corresponding workforce
  specialist role per Section VI "Anticipated Additional Asset-Class-
  Specific Roles".

## Repo hygiene noticed

- **Pre-existing root-level markdown files** (`AGENTS.md`,
  `AUR-CUSTODY-OBJ-001-v1_0.md`, `AUR-MARKET-001-v1_0.md`,
  `AUR-PRACTICE-001-v1_0.md`, `AUR-PT-AGNOSTIC-001-v1_0.md`,
  `FUNCTIONS.md`, the four role
  specs `*-analyst.md`) were authoritative in earlier phases but are
  explicitly out of scope per the contracts-build prompt. Worth a
  sweep into a labelled `archive/` or `reference/` subfolder once
  downstream layers are in place.
- **`pyproject.toml` coverage.** Currently configured for terminal
  reporting only. If CI adoption is in flight, consider adding a
  coverage threshold (e.g., `--cov-fail-under=95`) and an XML report
  path for coverage tooling integration.
- **`VS-CODE-PROMPT-CUSTODY-CONTRACTS.md`.** This was the build prompt
  itself. Now that the contracts are in place, the prompt is
  historical — consider moving it to a `prompts/` or `archive/` folder
  rather than leaving it at the repo root where it will be confused
  for current scope.
