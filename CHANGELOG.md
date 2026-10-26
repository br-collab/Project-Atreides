# Changelog

Versions before 0.4.0 were tagged without a changelog; their contents are in the pull requests and in the commit history. This file starts at the Wave 2 release.

## 0.7.0 — INST-1 release candidate

- Pinned the breaking kernel 2.0 obligation contract and bound approved-intent direction.
- Bound prepared ISO 20022 cash instructions to the obligation's amount, currency and
  account-to-BIC participant registry; malformed amounts, control characters and same-party
  instructions refuse before emission.
- Bound Cato Cash decisions to evaluated notional and currency and required the recorded net
  obligation to cover the obligation's cash total.
- Added fail-closed allocation, market-profile and customer-sell possession-or-control gates.
- INST-1 Amendment 3 (WP2b, Claude): the delivering account's capacity is read from the
  digest-bound payload (`seller_capacity`), not from a caller keyword; a customer-sell control
  result counts only for the obligation's issue, settlement date and delivery quantity; and the
  account-to-BIC registry is a versioned `ParticipantRegistry` whose digest the payload names
  (`participant_registry_digest`). The `is_customer_sell` keyword is removed.
- The tag is reserved for Bill after the INST-1 WP2b pull request merges (HOLD 2).

## Unreleased — EQ-1

- Replaced the embedded 2026 repo holiday set with one data-backed, fail-closed market calendar
  for United States equities and government securities, including the 2026-2027 year boundary.
- Added the append-only, balanced equities journal and two-sided stock record, duplicate and
  reversal semantics, owned breaks, and versioned projections into the existing reserve,
  net-capital, and possession-or-control engines.
- Added Regulation T and FINRA Rule 4210 customer margin with pinned source hashes, calls, and
  advisory-only liquidation recommendations.
- Added attested account-capacity and synthetic locate documents, quantity-limited locate use,
  and order/locate linkage on Rule 204 close-out evidence.
- Added a deterministic publication scenario connecting CNS fails, books, margin and customer
  protection. Special memorandum accounts, portfolio margin, day-trading requirements, options
  and fixed-income margin, Rule 201, and live NSCC/DTC messages remain declared, not built.

## 0.6.0 — 22 Oct 2026

Everything merged since 0.5.0 is collected here by its governing order.

### Settlement lifecycle and evidence

- **W3 adoption and agent activation:** adopted the frozen kernel envelopes at the acceptance
  and instruction boundaries, added real contract crossings, and published activation evidence.
- **G1 and G2:** added external receipts, finality and reconciliation joins, secured-funding
  evidence, books posting, client output, and cross-stage lifecycle evidence.
- **C2 and C3:** made movement authority explicit and added owned, evidence-backed exception
  closure and break publication.
- **TRACE-1 and DEADLINE-1:** added requirement-to-test traceability plus deadline engines for
  Regulation SHO Rule 204, ACATS, Rule 17a-13, and customer-reserve deposits.

### Clearing capabilities

- **SC-1:** corporate-action event state, entitlement arithmetic, DTC/ISO 20022 adapters, funds,
  fixed income, and reconciliation.
- **SC-2:** customer-protection reserve and net-capital computations on supplied balances,
  claims, rule sources, and challenger evidence.
- **SC-3:** listed-options clearing at the Options Clearing Corporation.
- **R15 and R15B:** FICC Government Securities Division access, novation, member-seat netting,
  and signed security and cash settlement legs.
- **R16:** delivery-versus-payment and General Collateral Finance repo, including direct,
  sponsored, and agent access, two-leg economics, evidence, and exact publication bytes.
- **FIX-7:** repo terms now agree with a declared 2026 government-securities business-day
  calendar; every refusal in `atreides.clearing` is tested and that package is held at 100%
  branch coverage in continuous integration.

### Build, governance, and public truth

- **W5/R14 and COP work:** added participant-access evidence and publication surfaces used by
  the Common Operating Picture.
- **VOC-1 and hygiene orders:** aligned maturity and criticality vocabulary, corrected package
  data and record-date positions, restored strict typing across the full package, and hardened
  dependency and workflow checks.
- **Documentation:** aligned the README and digital-asset status with committed behavior and
  kept the no-submission boundary explicit.

## 0.5.0 — 19 Sep 2026

Wave 3, tasking order `W3-contract-freeze.md`. **Breaking**: a required field is removed from a public model. Aureon pins this tag.

### R5 — `dsor_pre_trade_record_id` resolved to one meaning

The name meant three different things across the boundary Wave 3 freezes. `GateResult` lost it in 0.4.0. The remaining two are resolved here.

- **Removed:** the `@property` aliases on `InstructionPackage` and `BreakTicket`, which returned `dsor_record_id` and were marked "Deprecated until Wave 3". An alias is a second meaning kept alive; `dsor_record_id` is the name, and it means the record written at emission.
- **Removed (breaking):** `SettlementTaskingRecord.dsor_pre_trade_record_id`. It was not a DSOR reference. The cockpit set it to `uuid5(NAMESPACE_URL, f"atreides:cockpit:{pre_hash}")` — the same value it assigns to `task_id` — so it was a second copy of the record's own identifier, and no DSOR record with that identifier exists. The nine test fixtures passed an unrelated `uuid4()`, and nothing in any repository read it.

  The order allowed for renaming it, on the reading that it named something different. It named nothing: the record's identity is `task_id`, and its upstream provenance is `lineage_stub`, which carries the operation, the authority tier and identifier, the pre-operation state hash and the `c2_handoff_id` slot. A third field naming none of those had nothing to name, so it is gone rather than renamed.

Nothing outside this repository constructs `SettlementTaskingRecord`, so the break reaches no consumer today.

### The `cannae-kernel` pin moves to v1.0.0

From `v0.1.1`. The kernel's Wave 3 releases (0.2.0 through 1.0.0) added the `measurement`, `absence`, `session`, `effects` and `envelopes` modules, and all five cross-domain envelopes are now frozen at 1.0. Every one of those releases is additive — no existing field, enum member or canonical-serialization rule changed, and the golden vectors carried forward byte-identical — so nothing here needed adapting.

Verified rather than assumed: 1,439 passed, 1 xfailed, ruff clean and strict mypy clean against the installed v1.0.0.

Nothing in Atreides uses the new modules yet. Adoption — `ObligationAcceptanceRecord` in particular, which is where `dsor_record` as `Recorded | Absent` belongs — is its own work package.

## 0.4.1 — 18 Sep 2026

Packaging only. No source change.

- The `cannae-kernel` pin moved from `v0.1.0` to `v0.1.1` (#19).
- The `[[tool.mypy.overrides]]` block with `follow_untyped_imports` for
  `cannae_kernel` was deleted, because v0.1.1 ships a `py.typed` marker and
  strict mypy reads its annotations directly.

## 0.4.0 — 17 Sep 2026

Wave 2, part A of the Cannae Legion joint upgrade map (CL-JUM-001), tasking order W2A. Six work packages, pull requests #12 to #17. Aureon pins this tag in W2B-7.

### Contract-critical fixes

- **ATR-I-03, 05, 07, 09 — Tier 1 integrity (#12).** The boundary between a validated instruction and an emitted one is explicit (`atreides/rails/boundary.py`), preparation refuses to proceed under a halt (`PreparationHaltedError`), and the Tier 1 identifiers and records are consistent across the rails.
- **ATR-I-02 — validation is pure (#13).** `validate_tasking` computes and returns; `emit` is a separate, named stage, and acknowledgment is recorded by `record_rail_acknowledgment`. Validation no longer writes DSOR (Deterministic Sequenced Operational Record) records as a side effect.
- **ATR-I-04, 06 — CATO-F decisions bind and replay; the halt propagates (#14).** `CatoFDecision` carries its binding fields and `GATE_SET_VERSION` (`cato-f-gates/0.3`), an unbound decision is refused where it is consumed rather than at construction, and the cockpit supplies a Tier 0 halt context (`tier0_halt_context`) that every gate reads.
- **ATR-I-01 — obligation acceptance, draft (#15).** `atreides/acceptance/` builds the acceptance candidate, record and service, and preparation is gated on acceptance.
- **ATR-I-12 — lifecycle record kinds and a verifiable journal, slice-minimal draft (#16).** `atreides/dsor/lifecycle_records.py` and `atreides/dsor/journal.py`; journal payloads are `DSORRecordRef`s carrying the SHA-256 of the stored JSON, so a tampered record is detected.
- **Stress regressions (#17).** Wave 2 stress fixes are pinned case by case; E6.4 stays a strict xfail for Wave 6.

### Shapes

- `SettlementDomainOutput` is the name of the settlement domain's output; `AureonOutput` remains as an alias.
- `InstructionPackage.dsor_record_id` carries the emitted record's identifier.
- `DSORStore.records()` and `payload_bytes()` expose stored records for verification.

### Notes for consumers

- **Removed:** `GateResult.dsor_pre_trade_record_id`. The reference now comes from the emitted package (`InstructionPackage.dsor_record_id`), because validation no longer writes the record (ATR-I-02).
- Nothing in this release submits to a settlement rail. `submit=false` still holds.

### Tests

1,429 passed, 1 xfailed (E6.4, Wave 6), 99% statement coverage. Ruff and strict mypy clean; the three probes run.
