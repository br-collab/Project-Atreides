# PS-3C evidence plan

**Order:** PS-3C Firm run, identity and approvals  
**Date:** 2026-11-18 EST  
**Standing rules:** MVP-00-STANDING-RULES v0.2, including rule 14  
**Baselines:** Project-Atreides `49eff87`; L.C. `5ed3a73`; aureon `d1901d7`

## Sequence and stop rule

Parts execute in order. Each part ends only after baseline-defect evidence, passing focused tests, a one-line rule 14 break and restoration, and required-check merge evidence. If work must stop, it stops after the last completed part.

## Part 1: central street reconciliation

- Baseline defect: identify both runs calling the legacy value-taking street gate and the literal status path.
- Implementation: adapt all three independent outside sources to `atreides.books.ps1.reconcile`; owner is read from the pinned reconciliation calendar; status is derived from the result.
- Run proof: a clean `run_firm` and `run_golden_path` retain their reconciliation results.
- Mutation: `STREET_ONE_SHARE` changes one independent street position.
- Rule 14: replace one derived street status with a constant. The mutation test must fail and name the street-row status control.
- Gate inputs: books are the journal; outside positions are run artifacts from depository, CNS fail, and stock-loan readers; owner and schedule are the pinned reconciliation calendar.

## Part 2: money breaks through the firm run

- Baseline defect: both named mutations are unknown to `run_firm`.
- Implementation: `UNPOSTED_DEPOSIT_INSTRUCTION` logs one customer deposit instruction without a book posting; `RESERVE_DEPOSIT_NOT_RECEIVED` omits exactly one instructed reserve transfer from the bank source.
- Run proof: on day one, the named row has exactly one break and each other row is `RAN` with zero breaks.
- Rule 14: disable each mutation's divergence one line at a time. Its real-run test must fail with the named money control.
- Gate inputs: instructions are instruction-log run artifacts; book values are the journal; bank values are instruction receipt artifacts.

## Part 3: KYC stored at decision time

- Baseline defect: locate caller-side `kyc_event_chain` construction and fixed or reusable event identifiers.
- Implementation: the KYC decision recorder creates a unique event chain, seals it, and stores it beside the lifecycle record. Resolvers accept only stored chains.
- Proof: cross-record chain use is refused and two decisions have distinct event identifiers through `run_golden_path` mutations.
- Rule 14: restore caller-side chain acceptance for one line. The golden-path mutation test must fail and name the stored-chain identity control.
- Gate inputs: decision facts are lifecycle run artifacts; trust keys are pinned onboarding keys; no resolver caller supplies a chain.

## Part 4: approval provenance

- Baseline defect: show `accept_intent` accepts unsupported human claims and simulator helpers choose actor kind or provenance.
- Implementation: human judgment requires a verified signed attestation; human actor kind requires the same record. Golden path stores one verified synthetic-human approval. Firm volume uses deterministic service plus policy-result provenance.
- Proof: unsupported service-human and unattested-human cases are refused; `run_golden_path` publishes exactly one human decision and attestation identifier.
- Rule 14: bypass attestation verification by one line. The golden-path mutation test must fail and name the approval-attestation control.
- Gate inputs: human identity and signature are a signed-attestation run artifact verified with pinned onboarding trust keys; service identity and policy provenance are lifecycle run artifacts.

## Part 5: refusal is recorded and close continues

- Baseline defect: an over-limit market-access decision aborts or lacks a refused-order record.
- Implementation: store the refusal and reason, skip release, and continue the day close.
- Run proof: a `run_firm` mutation creates exactly one refusal while all six reconciliation rows remain `RAN` with zero breaks.
- Rule 14: restore abort-on-refusal for one line. The real-run test must fail and name the refusal-continuation control.
- Gate inputs: limits are the pinned market-access policy; capacity and order are run artifacts; refusal reason is the gate result.

## Part 6: hygiene

- aureon: create the legacy fixture by executing commit `11c9db2` and persisting its real state, then test current migration against those bytes. Rule 14 removes old-key migration for one line.
- L.C.: correct the `ci.yml` pull-request label. Rule 14 restores the wrong label for one line.
- Atreides packs: run all three named packs at `ead38fe^` and current main; record exact old and new figures and reasons in `SUPERSEDED.md`. Rule 14 removes one pack row.
- Sale confirmation: prove negative quantity, positive proceeds, and journal tie through `run_golden_path`. Rule 14 makes the quantity unsigned for one line.
- Gate inputs: the tombstone fixture is a run artifact from the pinned commit; CI label is a pinned workflow file; pack comparisons are run artifacts from pinned commits; sale facts come from lifecycle and journal run artifacts.

## Final probes and report

- Run the clean five-day small firm probe and confirm six `RAN`, zero-break rows every day.
- Run the golden-path customer probe and compare statement amounts with the baseline.
- Run repository lint, strict typing, focused and full required tests.
- Merge only through required checks with auto-merge. Create no tags.
- Report every verified claim with a main merge commit plus file and line, or a command with quoted output. Put every other statement under `Unverified`.

