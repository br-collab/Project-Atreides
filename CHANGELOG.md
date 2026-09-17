# Changelog

Versions before 0.4.0 were tagged without a changelog; their contents are in the pull requests and in the commit history. This file starts at the Wave 2 release.

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
