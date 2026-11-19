# PS-3D evidence plan

Date: 2026-11-18. Owner of committed copy: Project-Atreides. Canonical copy: workspace `_reports/PS-3D-evidence-plan.md`.

This is the closure checklist for ORDER PS-3D (supervision wired into the runs). Standing rules are MVP-00-STANDING-RULES v0.2, including rule 14. Acronyms used below: WSP is written supervisory procedure, AML is anti-money laundering, SAR is suspicious activity report, CAT is Consolidated Audit Trail, CAIS is CAT Customer and Account Information System, COP is Common Operating Picture, FDID is Firm Designated ID, PR is pull request.

The order file on disk is `_tasking/PS-3D-supervision-wired.md` v0.1 and has no Parallel build section. The execution instruction names v0.2 and supplies that section. This plan follows the instruction. Phase A starts on current `main`. Phase B starts later, from a fresh `main`.

## Baselines at Phase A start

Recorded before this plan's commit. Each line is `origin/main` after `git fetch`.

| Repository | Commit | Subject |
|---|---|---|
| Project-Atreides | `49eff8756617b74ca6ece6732218cbcb371db16c` | docs: correct approval provenance claim (#199) |
| L.C. (Legiones Cannenses) | `5ed3a73dc9bad8d94748b81f21c76b49746fccfd` | fix: correct CAT deadlines and identifiers (#158) |
| aureon | `d1901d744e003801f5bc73454193b55b239f997e` | fix: correct surveillance and tombstone controls (#152) |

PS-3C is open in parallel. Its evidence-plan PR is Project-Atreides #200. Phase A does not edit `simulator/firm.py`, `simulator/golden_path.py`, `simulator/estate.py`, `simulator/street.py`, `atreides/account_lifecycle.py`, `atreides/books/ps1.py`, L.C. `.github/workflows/ci.yml`, or `aureon/dsor/`.

## How a part closes

Every row below needs three quoted runs in the report:

1. The named test failing at the Phase A baseline for the defect it names (rule 6).
2. The named test passing after the implementation, on the merge commit.
3. The named test failing after the one-line deliberate break, with a failure message that names the control, then passing again after the exact source line is restored (rule 14). The break lives on a local scratch branch and is never pushed or merged.

A control counts for acceptance only when `run_golden_path` or `run_firm` calls it. Phase A builds the callee, the pack or panel reader, and the test. Phase A does not insert those calls into the two run functions, because that wiring is reserved for Phase B and those files are in the parallel-build exclusion list. Until Phase B re-quotes the test from inside the run, acceptance item 1 stays open and the report says so.

Gate inputs come from a run artifact, a signed attestation verified with pinned trust keys, a JUnit XML file the test runner wrote, or a pinned file. A value supplied by the caller of the gate is a defect.

## Phase A, in order

Parts run 0, then 2, then 3, then 5, then 6, then 7. Each part is merged through required checks before the next part starts. A part left half done counts as not done.

### Part 2. Rule 3120 reads the run's JUnit file

`run_3120_testing` today takes `executed_tests` from its caller (`atreides/supervision/controls.py`). That is the defect.

- The WSP register names eighteen tests. Those tests exist and a runner executes them with pytest, writing JUnit XML.
- The 3120 report reads executed test names from that file. A skipped or deselected test is absent. An absent WSP test is status `EXCEPTION`, owned by the row's `supervisor_role`.
- The report does not accept an executed-test set argument.

| ID | Test | One-line break |
|---|---|---|
| SC-01 | `test_3120_reads_executed_names_from_junit_xml` | Ignore the JUnit file and treat every WSP row as passed. |
| SC-02 | `test_3120_deselect_one_wsp_test_is_one_exception` | Treat a WSP test missing from the JUnit file as `PASS`. |

Gate inputs: test names and supervisor roles are the packaged WSP register. The executed set is the JUnit file the runner wrote. The run id is the runner's output path stem, not a caller argument.

### Part 3. CAT on the live COP

L.C. builds CAT records from the golden-path evidence chain inside the vendored pack (`cop/vendor/atreides-golden-path/`). Rejected records are an exception source on the live COP exceptions panel, with the correction deadline already computed by `lc.cat.validate`. CAIS field bases are read from a pinned table, one citation per field, and the builder's sent or withheld action must match that table. The pinned specification file `lc/rules/CAT-IM-2d-v4.2.0-r4.meta.json` gains a SHA-256 of its own bytes, checked before validation runs.

| ID | Test | One-line break |
|---|---|---|
| CAT-10 | `test_cat_records_come_from_vendored_evidence_chain` | Replace one evidence-chain symbol with a constant before building records. |
| CAT-11 | `test_planted_invalid_cat_record_shows_on_cop_exceptions` | Drop CAT feedback before the exceptions panel is built. |
| CAT-12 | `test_cais_field_bases_match_pinned_table` | Mark one withheld field as sent in the builder and leave the pin unchanged. |
| CAT-13 | `test_cat_specification_checksum_matches_pin` | Change one hex digit of the recorded checksum. |

The planted invalid record is one evidence fact in a copy of the vendored pack whose parent link is removed. The panel test renders the COP exceptions route and reads the deadline from that render. T+3 still uses the existing holiday calendar. Gate inputs: evidence facts and account numbers come from the pack; FDID is derived; the CAIS table and the specification checksum are pinned files; the review date is the pack's close date.

### Part 5. SAR decision and confidentiality

Stop this part and report, without a code change, if the decision cannot be verified with `cannae_kernel.signed_attestation` and `atreides.trust_anchors` as they exist. Do not edit those modules, and do not edit `atreides/account_lifecycle.py`.

The decision function accepts only an attestation wire. It verifies the wire against the pinned trust anchors for a synthetic AML officer producer, then reads officer, outcome, reason, and date from the verified payload. An unsigned or unverifiable wire is refused. No SAR field is copied into a pack, a COP page, or a customer document.

The scan walks every file under the publication directory and the rendered body of every COP GET route (`/`, `/section/<name>`, `/panel/<name>`, `/healthz`, `/login`). A case identifier or a SAR field fails the scan.

| ID | Test | One-line break |
|---|---|---|
| SAR-01 | `test_unsigned_sar_decision_is_refused` | Skip signature verification and read the outcome from the raw bytes. |
| AML-10 | `test_planted_case_identifier_fails_publication_and_cop_scan` | Stop the scan before the planted pack file. |

AML-10 is an owed PS-3 rule 14 row. Gate inputs: the wire is the officer attestation; the public key and producer come from the pinned trust-anchor file; publication bytes and rendered routes are the artifacts under scan. The test does not pass officer, outcome, reason, or date as arguments.

### Part 6. Public summary

`build_public_summary` writes `public-summary.json` into the publication directory from engine outputs only: WSP row count, 3120 exception count, CAT record and exception counts, AML alert count, and surveillance dispositions. The file has no SAR field and no case identifier. The live COP route reads that file from the pack and shows those counts.

| ID | Test | One-line break |
|---|---|---|
| PUB-01 | `test_cop_route_shows_public_summary_counts_from_pack` | Hard-code the CAT record count in the COP renderer. |
| PUB-02 | `test_customer_artifacts_unchanged_and_free_of_ps3_data` | Append the word supervisory to the statement tax disclaimer default. |

PUB-02 is an owed PS-3 rule 14 row. The test already calls `run_golden_path`. Closing cash stays `9000.00` and the confirmation and statement JSON stay free of supervisory, AML, surveillance, and SAR text. Gate inputs: each count is the matching engine result. The COP reads the pack file and does not recompute a second set of numbers.

### Part 7. Surveillance reads L.C. run records

`screen_equities` stops accepting caller tuples of `EquityOrderFill`. An adapter reads order and fill rows from an L.C. lifecycle export. L.C. writes that export from a lifecycle register. aureon does not import a caller-built record tuple. A missing beneficial-owner field on an otherwise present row is `SURVEIL_DATA_INCOMPLETE`, not clear.

| ID | Test | One-line break |
|---|---|---|
| SURV-05 | `test_lc_run_wash_pair_is_flagged_through_adapter` | Compare order ids instead of beneficial-owner ids. |
| SURV-06 | `test_lc_run_missing_beneficial_owner_is_data_incomplete` | Map a missing beneficial owner to `SURVEIL_CLEAR`. |

The wash pair is two L.C. lifecycle executions, opposite sides, same owner, same symbol, same quantity, inside 300 seconds. The incomplete case removes the beneficial-owner field from that export and leaves the rest. Gate inputs: side, symbol, quantity, timestamps, and owner are fields of the L.C. export. The adapter does not take those values as arguments.

## Phase B, after PS-3C

Start Phase B only when `_reports/PS-3C-report-*.md` exists and every PS-3C pull request is merged. Check out a fresh `main` in each repository and record the new baselines. Phase B is Part 1, Part 4, and the call sites inside `run_golden_path` and `run_firm` for every Phase A control. Re-quote each Phase A test from that run. Customer artifacts stay unchanged.

### Part 1. Reviews from real gate decisions

For each gate decision the golden path makes, emit one review. The decision id and the decider come from that decision's record. The reviewer is the principal the WSP register names for that gate. A self-review is refused.

| ID | Test | One-line break |
|---|---|---|
| WSP-03 | `test_golden_path_emits_one_review_per_gate_decision` | Skip the reserve decision when emitting reviews. |
| WSP-04 | `test_golden_path_refuses_self_review` | Remove the reviewer-equals-decider refusal. |

WSP-03 is an owed PS-3 rule 14 row. Gate inputs: decision id, decider, outcome, and time come from the gate's own record. The reviewer comes from the WSP register. None of those five values is a caller argument.

### Part 4. AML inside both runs

Monitoring runs over the books and the instruction log inside the five-day firm run and inside the golden path. The firm run seeds three scenario customers, one per scenario. The golden-path customer stays clean. The SAR clock starts at initial detection. A missed deadline is a supervisory exception.

| ID | Test | One-line break |
|---|---|---|
| AML-11 | `test_firm_run_each_aml_scenario_fires_once` | Skip the instruction-log source inside the firm-run adapter. |
| AML-12 | `test_golden_path_customer_raises_no_aml_alert` | Treat the golden-path customer as a planted scenario customer. |
| AML-08 | `test_firm_run_sar_clock_starts_at_detection` | Start the clock at case creation. |

AML-08 is an owed PS-3 rule 14 row. Gate inputs: events come from the run's books and instruction log. Thresholds and the filing window come from `AMLPolicy`. Scenario identity comes from the run's seeded customer, not from a caller argument.

## Release and report

Each repository this order changes takes the next free minor version on `main` at merge time. PS-3C assigns Project-Atreides 1.4.0. If that number is still free when the first Atreides code PR merges, this order uses 1.4.0 there, 1.4.0 for L.C., and 1.3.0 for aureon. If PS-3C has taken a number, Phase B moves this order's changelog heading to the next minor. List the tag commands for Bill. Do not tag or release.

The report is `_reports/PS-3D-report-<date>.md`. It carries the baseline commits, each part's evidence, the rule 7 gate-input list, PR links and merge commits, and the headings Blocked and Unverified. A claim without a merge commit plus file and line, or a command and quoted output, goes under Unverified.
