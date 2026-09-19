# Changelog

Versions before 0.4.0 were tagged without a changelog; their contents are in the pull requests and in the commit history. This file starts at the Wave 2 release.

## Unreleased

### The `cannae-kernel` pin moves to v1.0.0

From `v0.1.1`. The kernel's Wave 3 releases (0.2.0 through 1.0.0) added the `measurement`, `absence`, `session`, `effects` and `envelopes` modules, and all five cross-domain envelopes are now frozen at 1.0. Every one of those releases is additive — no existing field, enum member or canonical-serialization rule changed, and the golden vectors carried forward byte-identical — so nothing here needed adapting.

Verified rather than assumed: 1,439 passed, 1 xfailed, ruff clean and strict mypy clean against the installed v1.0.0.

Nothing in Atreides uses the new modules yet. Adoption — `ObligationAcceptanceRecord` in particular, which is where `dsor_record` as `Recorded | Absent` belongs — is its own work package.


Wave 3, tasking order `W3-contract-freeze.md` § R5. **Breaking**: a required field is removed from a public model.

### R5 — `dsor_pre_trade_record_id` resolved to one meaning

The name meant three different things across the boundary Wave 3 freezes. `GateResult` lost it in 0.4.0. The remaining two are resolved here.

- **Removed:** the `@property` aliases on `InstructionPackage` and `BreakTicket`, which returned `dsor_record_id` and were marked "Deprecated until Wave 3". An alias is a second meaning kept alive; `dsor_record_id` is the name, and it means the record written at emission.
- **Removed (breaking):** `SettlementTaskingRecord.dsor_pre_trade_record_id`. It was not a DSOR reference. The cockpit set it to `uuid5(NAMESPACE_URL, f"atreides:cockpit:{pre_hash}")` — the same value it assigns to `task_id` — so it was a second copy of the record's own identifier, and no DSOR record with that identifier exists. The nine test fixtures passed an unrelated `uuid4()`, and nothing in any repository read it.

  The order allowed for renaming it, on the reading that it named something different. It named nothing: the record's identity is `task_id`, and its upstream provenance is `lineage_stub`, which carries the operation, the authority tier and identifier, the pre-operation state hash and the `c2_handoff_id` slot. A third field naming none of those had nothing to name, so it is gone rather than renamed.

Nothing outside this repository constructs `SettlementTaskingRecord`, so the break reaches no consumer today.

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
