# Changelog

## Unreleased

PS-3C Part 6 makes the clean firm run independently observable through opening,
customer-deposit and reserve-transfer instructions. The reserve break now omits
an instructed receipt instead of manufacturing a post-statement dollar. The
three locked dated SIM-1 packs run again by using their declared minimum order
quantity when they predate the dedicated auction-size field. Their changed net
capital ranges are recorded in `SUPERSEDED.md`, and sale confirmations are
covered with negative quantity, positive proceeds and a books link.

PS-3C Part 5 routes every firm-volume child order through L.C.'s market-access gate. A terminal
decision is recorded as a refused order and is not booked, while the day continues through all six
reconciliations. The synthetic market-access policy states its independent rationale and approving
role instead of deriving its limits from the generator ceiling.

Phase A: a suspicious activity report (SAR) decision and an unidentified-suspect extension are bound to the case. The verified officer payload must carry that case's `case_id` and `alert_id`. `record_human_decision` and `extend_for_unidentified_suspect` refuse a payload signed for another case, including a second case detected on the same day. No run calls these yet.

Phase A: `build_public_summary` writes `public-summary.json` from engine outputs. The file carries the written supervisory procedure register status and version, the Rule 3120 counts from `run_3120_testing` labelled Phase A, Consolidated Audit Trail record and feedback counts, the anti-money laundering alert count, and surveillance dispositions. It has no suspicious activity report field and no case identifier. No run calls this yet.

PS-3C Part 4B removes repository-reconstructible Know Your Customer and human-approval
signing keys. Both identities are generated per process and installed before verification;
the committed trust file contains neither public half, and the KYC writer has no default
signer. Firm volume uses kernel `HUMAN_JUDGMENT` with a signed per-run synthetic human
approver. L.C. commit `c89b67c2c096419453f4bd2ec8386c116e0cdbdb` owns approval verification;
the simulator wrapper and policy-result envelope are deleted. Approvers must resolve from
the verified synthetic-principal register. WSP register version 1.3.0 records the changed
account-opening and approved-intent evidence.

Gate G3 correction to PS-3C Part 4B (#214): `run_firm` ignored a `REFUSED` outcome from L.C.
`accept_intent` and went on to authorize, split and allocate the order, then crashed with a bare
`KeyError` inside L.C.; and it relied on pytest's conftest to install the synthetic keys, so a
direct call refused every intent. The firm run now raises `FIRM_INTENT_REFUSED` with L.C.'s
reason, and both runs install their keys through `ensure_synthetic_trust`, which is a no-op when
every key is installed and refuses a partial set (`SYNTHETIC_TRUST_PARTIAL`).

Gate G3 correction to PS-3D Part 5 (#212): the synthetic AML (anti-money laundering) officer key was derived from a label published in `atreides/supervision/aml.py`, its public key was pinned in `trusted_producer_keys.json`, and the signer shipped in `atreides`, so anyone could sign a SAR decision. A forged `NO_SAR` decision was accepted on `b010bab`. The officer key is now generated per process in `simulator/synthetic_attestation_fixture.py` and installed at the composition root; nothing in `atreides` can sign, and the pin is removed (the trust file is byte-identical to 1.3.0 plus #211). The runtime installer now holds one key per producer, each set once, none after the first verification.

Phase A: a suspicious activity report (SAR) decision is accepted only as a signed attestation from the synthetic AML officer's per-run key. Officer, outcome, reason and date are read from the verified payload. `extend_for_unidentified_suspect` records the officer attestation, the decision date and the stated basis that no suspect was identified on the date of initial detection, and it refuses an extension without them or made after day 30 (inventory finding F1, 20 November 2026). No run calls these yet.

PS-3C Part 4 binds stored Know Your Customer decisions to a pinned Atreides signature and to the
deterministic service holding `KYC_DSOR_WRITE` with policy-result provenance. Human approved
intents require a pinned signed attestation bound to the exact intent digest and human approver;
firm volume records deterministic-service policy results instead of claiming human action. Golden
path mutations prove wrong KYC sealers, missing or bad signatures, missing principal approval,
self-approval, and unattested intent approval are refused. The account-opening and approved-intent
written supervisory procedure rows now point at those run-level tests. Register version 1.2.0.

The suspicious activity report clock runs to filing, not to the decision (inventory finding N4).
Under 31 CFR 1023.320(b)(3) the period is 30 calendar days from initial detection, extendable by
30 when no suspect is identified, never past 60. A `NO_SAR` decision stops the clock; a `SAR`
decision does not, because the simulator never files. `extend_for_unidentified_suspect` applies
the extension once. One token trade no longer hides deposit and withdrawal movement: trading
below a synthetic policy share of the cash moved (`trading_share_floor`, 10%) counts as none.
The Rule 3120 report now carries the WSP register version it graded (M3), and the WSP runner
loads the repository conftest as CI does (M4). Still Phase A: no run calls these yet.

Reconciliation break causes are now read from the two sides (missing outside record, missing
book entry, sign difference, quantity difference, unsourced location), never from age. Until
now every carried break was labelled `TIMING`, which hid aged, unexplained differences
(inventory finding N1, 19 November 2026). Age stays on each break as `age_calendar_days` with a
new `carried` flag, and the five-day firm run now passes each day's control breaks forward, so
an unposted deposit shows as `MISSING_BOOK_ENTRY` aged 0, 1 and 2 days. Test:
`tests/books/test_ps3_break_causes.py`, through `run_firm`.

The US equities calendar now carries the regular 4:00 p.m. close and the NYSE 1:00 p.m. early
closes for 2026 and 2027 (27 November 2026, 24 December 2026, 26 November 2027), read from
the NYSE Holidays and Trading Hours page on 20 November 2026. `MarketCalendar.session_close`
fails closed for a year without session data.

**Retraction (1.2.0).** The 1.2.0 entry below says the anti-money laundering monitoring runs
"over books and instruction-log events" and that breaks are classified "from their own facts".
Neither was true at 1.2.0: no run called the AML engine, and carried breaks were classified by
age. Break causes are fixed above; AML wiring is PS-3D Phase B.

PS-3D Phase A: Rule 3120 testing. Not yet called by `run_golden_path` or `run_firm`;
PS-3D Phase B wires it into the runs. Until then it runs only from the test suite.

Rule 3120 grades each written supervisory procedure row from the outcome the pytest
runner recorded in its JUnit XML file: a test that ran and failed is a `FAILED` exception,
an absent or skipped test is `NOT_RUN`, and rows match on the full test node identifier.
The report no longer accepts an executed-test set from its caller, and the placeholder
tests that only re-read the register are deleted.

Coverage is partial. Rows name an existing test that exercises the control, most through
the golden path or the firm run; the confirmation and statement tests call their builders
on golden path output, and the fail-to-receive row plants a source outage, not a quantity
difference. Customer profile and recommendation share one golden path test. One row has no
run-level test yet and is an exception with its owner: stock loan to register, owed by PS-4A.
WSP register version 1.2.0.

## 1.3.0 - 18 Nov 2026

Correct securities-count sign convention and make the clean five-day firm reconciliation run
truthful. Record both reserve-transfer instruction legs, derive street reconciliation status and
owner, retain the enforced human-judgment approval model pending a signed approval record, and pin market-access limits separately
from generator bounds, bind capacity to its computed result, apply the pinned earlier-of deadline
for lot identification, sign confirmation quantity by side, and record publication anchor write
time when written.

Retraction: version 1.1.0 did not have independent cash sources in every real firm-run path, and
version 1.1.1 sealed KYC chains in resolver callers rather than storing them at decision time.
Version 1.0.0's phrase "externally anchored" described a sibling digest copy, not an external
anchor.

## 1.2.0 - 18 Nov 2026

Add the versioned written supervisory procedure register, self-review refusal, Rule 3120
testing report and unsigned Rule 3130 certification draft. Add deterministic ongoing anti-money
laundering monitoring over books and instruction-log events, with named-human case decisions,
an unfiled SAR draft, filing-clock exceptions and public-artifact confidentiality. Classify
reconciliation breaks from their own facts and independently test both KYC integrity checks.

## 1.1.1 - 18 Nov 2026

Close the PS-1 verification findings: statements now come from an append-only instruction log,
the public reconciliation gate builds both sides, KYC replays the stored decision-event chain,
lot-election timing comes from the sale's settlement journal entry, and customer-side position
facts come from the furnished confirmation. Pin the 2025 annual GovInfo editions of 26 CFR
1.1012-1, 1.6045-1, and 1.1091-1. FIFO and the specific-identification deadline are implemented;
wash-sale adjustment remains `TO_VERIFY` because the synthetic journal does not carry the verified
covered-security identifier required for deterministic same-account application. Publish the
unsettled account-treatment questions as `TO_VERIFY_AGAINST_PRIMARY_TEXT` instead of claiming the
pinned customer-protection text places those internal accounts.

## 1.1.0 - 18 Nov 2026

Split equities trades into trade-date obligations and calendar-derived settlement-date street
movements. Add independent cash, reserve-bank and securities-count controls, journal-replayed tax
lots and statement basis, real KYC chain replay, and a customer-fact statement oracle. Wash-sale
adjustment remains `TO_VERIFY` pending a deterministic implementation of pinned 26 CFR 1.1091-1.

## 1.0.1 - 18 Nov 2026

Align approval provenance with the approving actor, make golden-path evidence identifiers unique,
link the venue fill to the market-access decision, and source SIM-1B limits and capacity from the
declared calibration policy and books. Publish the corrected pack and list the older packs that its
cash-account posting supersedes.

## 1.0.0 - 17 Nov 2026

Close the declared-synthetic retail minimum viable product from MVP-0 through MVP-5B: hardened
books and customer-protection controls, independent reconciliation, governed onboarding and first
trade, one golden-path daily close, client reporting, and the Review B closure. Cash-account buys
now reduce free cash, the booking register carries the real market-access decision, confirmation
consideration ties to linked books, KYC heads are recomputed, evidence packs are externally
anchored, and control tests prove their own failure modes.

## 0.9.9 - 9 Nov 2026

- Correct protection inputs for proprietary haircuts, PAB free credits, fails to deliver, and stock-loan control facts.

## 0.9.8 - 9 Nov 2026

Load synthetic first-trade trust anchors from checksum-pinned package configuration and refuse
unpinned, revoked, expired, and wrong-producer signatures by name.

## 0.9.7 - 9 Nov 2026

Verify producer-bound Ed25519 lifecycle evidence, require authoritative legal-entity and KYB
records for institutional accounts, enforce complete CIP evidence, and require fresh principal
acceptance after restriction.

## 0.9.6 - 9 Nov 2026

Resolve account applications and account type from authoritative evidence, publish account type
with lifecycle status, and enforce the principal and approver role policy.

## 0.9.5 - 9 Nov 2026

Add synthetic retail CIP, customer profile, account record, and principal acceptance evidence.

## 0.9.4 - 8 Nov 2026

Resolve lifecycle evidence from authoritative producer stores instead of caller-built values.

## 0.9.3 - 7 Nov 2026

Harden account lifecycle evidence, chaining, transfers, metrics, and governance walkthroughs.

## 0.9.2 - 7 Nov 2026

Add a zero-baseline Ruff and strict mypy quality ratchet.

## 0.9.1 - 7 Nov 2026

Allow builders to enable check-gated auto-merge while preserving Bill's sole release authority.

## 0.9.0 - 7 Nov 2026

Add SIM-1 governance scenarios for vendor model regression, hosting provider loss, and a refused
unauthorized account lifecycle write. Add replayable Decision System of Record evidence and
negative controls, retire four external Word documents, and clarify merge authority.

## 0.8.0 - 7 Nov 2026

Add the ONB-1 append-only account lifecycle, attested status publication, and synthetic ACATS
integration. Pin the ONB-1 kernel contract branch pending Bill's release tag.

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
- Grok's WP2b review (Claude's fix): a control result binds to the envelope's settlement
  business date, and a cash leg that settles another day is `SETTLEMENT_DATE_CONFLICT`; a
  delivery quantity that is not positive and finite is `DELIVERY_QUANTITY_INVALID`; a CUSTOMER
  free delivery (no cash leg) binds to the envelope's business date, where before it could
  never pass. The registry digest is recorded on the acceptance record transitively: the record
  names the envelope digest, which binds the payload, which names the registry.
- Grok's WP1b review (Claude's fix): the account-capacity document is now
  `atreides.equities_account_capacity/3`. Each account carries its `capacity` (CUSTOMER, PAB
  or PROPRIETARY) derived from its books ownership type (`classify_accounts`), and the
  document names the carrying firm's `firm_participant_id`. An account with no ownership type,
  or booked under two, is refused. A stated seller capacity with no `account_capacity_digest`
  on the payload is `SELLER_CAPACITY_UNATTESTED`. PAB securities are held to possession or
  control under Rule 15c3-3(b)(5); its written-notice exception is not modelled.
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
