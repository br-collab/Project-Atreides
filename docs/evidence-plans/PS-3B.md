# PS-3B evidence plan

Date: 2026-11-18. Owner of committed copy: Project-Atreides. Canonical copy: workspace `_reports/PS-3B-evidence-plan.md`.

This is the closure checklist for ORDER PS-3B. Every row requires: a baseline run that fails before the fix, a passing run after the fix, and a rule 14 one-line deliberate break that makes the named test fail for the named control. For reconciliation, supervision, CAT, anti-money laundering, surveillance, publication, and customer artifact controls, the test must execute the golden path or five-day firm run. A direct unit call is supporting evidence only.

| ID | Control | Run-level test | One-line deliberate break |
|---|---|---|---|
| RUN-01 | Clean five-day small firm run reports all six reconciliations RAN with zero breaks each day. | `test_clean_five_day_small_firm_has_six_zero_break_reconciliations_daily` | Restore the negative sign in `book_location_balances`. |
| RUN-02 | A one-share depository-feed difference creates exactly one securities-count break through the firm run. | `test_firm_run_one_share_depository_difference_is_one_break` | Ignore the planted depository delta in the run adapter. |
| RUN-03 | An issued CNS money instruction that books never post creates exactly one break through the firm run. | `test_firm_run_unposted_cns_instruction_is_one_break` | Rebuild the outside CNS statement from posted books. |
| RUN-04 | A reserve deposit that the bank never receives creates exactly one break through the firm run. | `test_firm_run_missing_reserve_bank_receipt_is_one_break` | Rebuild the bank statement from reserve books. |
| RUN-05 | Stock-record rows use `reconcile`, including calendar owner and derived status. | `test_firm_run_street_rows_derive_status_owner_and_breaks` | Write `COMPLETED` into one street row. |
| RUN-06 | Instruction log records CNS money, customer deposit, and reserve instructions when issued, never from books. | `test_firm_run_instruction_log_has_three_issued_source_kinds` | Skip appending the customer deposit instruction. |
| KYC-01 | The KYC chain is sealed once at decision time, stored with unique event IDs, and replayed by resolvers. | `test_golden_path_kyc_chain_is_stored_at_decision_time` | Restore the fixed `evt_...0001` identifier. |
| KYC-02 | A chain stored for record A is refused when offered for record B through onboarding. | `test_golden_path_refuses_kyc_chain_for_other_record` | Remove the stored payload equality refusal. |
| APR-01 | Approval actor kind and provenance are enforced in `accept_intent` and come from the producing record. | `test_golden_path_approval_provenance_matches_record` | Force `ActorKind.HUMAN` in the acceptance path. |
| APR-02 | Market-access limits come from a pinned policy independent of generator bounds. | `test_firm_run_market_access_limits_equal_pinned_policy` | Set the limit from the generator maximum draw. |
| APR-03 | A market-access refusal becomes a refused order without aborting the firm run. | `test_firm_run_records_refused_order_and_continues` | Raise on the first refused order. |
| APR-04 | Margin result digest binds a computed margin result or is absent. | `test_golden_path_margin_digest_binds_computed_result` | Reuse the journal digest as the margin digest. |
| WSP-03 | Golden path emits one review record for each gate decision actually made, using decision ID, decider, and named WSP principal. | `test_golden_path_emits_review_for_every_actual_gate` | Skip the reserve decision when emitting reviews. |
| SC-01 | Rule 3120 reads executed tests from JUnit XML produced by the same run. | `test_golden_path_3120_reads_same_run_junit_xml` | Accept a caller-supplied executed-test set. |
| SC-02 | A WSP test absent from that JUnit XML is exactly one exception. | `test_golden_path_3120_missing_junit_test_is_exception` | Treat an absent JUnit test as PASS. |
| CAT-01 | Golden path evidence chain produces L.C. CAT records and rejected feedback appears in live COP. | `test_golden_path_cat_records_and_rejection_reach_live_cop` | Drop CAT exceptions before rendering the COP. |
| CAT-02 | FDID is compared with raw account number before account fields are removed. | `test_golden_path_cat_rejects_raw_account_as_fdid` | Strip the account number before the FDID comparison. |
| CAT-03 | CAIS field bases are validated against a pinned rule table with checksum. | `test_golden_path_cat_cais_bases_match_pinned_table` | Change one sent or withheld action without changing the pin. |
| CAT-04 | Timestamp precision matches the pinned CAT specification. | `test_golden_path_cat_timestamp_precision_matches_pin` | Render timestamps without required fractional precision. |
| CAT-05 | T+3 uses the US equities holiday calendar, including 26 November 2026. | `test_golden_path_cat_t_plus_3_skips_thanksgiving` | Count 26 November 2026 as a business day. |
| CAT-06 | CAT specification metadata carries a verified checksum. | `test_golden_path_cat_specification_checksum_matches` | Change one checksum hex digit. |
| AML-01 | Golden path and five-day firm run invoke monitoring over books plus instruction log; golden customer is clean and three planted customers alert. | `test_firm_run_aml_scenarios_and_clean_golden_customer` | Skip the instruction-log source in the run adapter. |
| AML-08 | SAR clock starts at initial detection, including the defined extension condition, in a real run. | `test_firm_run_missed_sar_clock_is_supervisory_exception` | Start the clock at case creation. |
| AML-10 | Every publication file and rendered COP page excludes SAR data and case identifiers. | `test_real_publication_tree_contains_no_sar_or_case_identifier` | Add a case identifier to the published pack. |
| SAR-01 | SAR officer, outcome, reason, and date are read from a signed verified-human attestation. | `test_firm_run_sar_decision_reads_signed_officer_attestation` | Read the outcome from a caller argument. |
| PUB-01 | `build_public_summary` feeds the dated pack and live COP with engine-derived counts. | `test_live_pack_and_cop_counts_equal_run_engines` | Hard-code one CAT count in the renderer. |
| PUB-02 | Customer confirmation and statement amounts remain unchanged and contain no supervisory or AML data. | `test_golden_path_customer_artifacts_unchanged_and_clean` | Add supervisory status to the statement renderer. |
| SURV-01 | Surveillance reads L.C. run records through an adapter, never caller tuples. | `test_golden_path_surveillance_reads_lc_run_adapter` | Read a caller-provided record tuple. |
| SURV-02 | Wash match requires same symbol, opposite sides, overlapping time, and matching quantity. | `test_golden_path_wash_match_uses_all_four_predicates` | Remove the matching-quantity predicate. |
| SURV-03 | Marking-the-close uses the America/New_York market calendar close. | `test_golden_path_marking_close_uses_market_calendar` | Replace calendar close with `hour=16` on record timezone. |
| SURV-04 | Empty surveillance input is DATA_INCOMPLETE and CFTC Part 45 is NOT_VALIDATED. | `test_golden_path_empty_surveillance_and_cftc_are_not_clear_or_ready` | Return CLEAR or READY for one empty or unvalidated path. |
| HYG-01 | aureon migrates real 11c9db2 tombstones and evicts by age. | `test_real_11c9db2_tombstone_fixture_migrates_and_evicts_by_age` | Sort tombstones by UUID instead of age. |
| HYG-02 | L.C. strict typing pins aureon ref and CI uses the correct pull-request label. | `test_ci_workflows_pin_aureon_and_use_correct_pr_label` | Remove the aureon ref. |
| HYG-03 | New changelog entries retract named overclaims and pack digest recorded times reflect writes. | `test_changelog_retractions_and_pack_digest_write_times` | Restore a constant recorded time. |
| HYG-04 | Lot-election deadline follows pinned 26 CFR 1.1012-1(c)(8), including settlement failure. | `test_golden_path_lot_election_deadline_follows_pinned_text` | Use contractual settlement after settlement failure. |
| HYG-05 | Confirmation quantity is signed and sale confirmation is negative. | `test_golden_path_sale_confirmation_quantity_is_negative` | Apply `abs` to confirmation quantity. |
| HYG-06 | Old SIM-1 runner packs are listed in `SUPERSEDED.md` after the baseline rerun. | `test_superseded_lists_old_sim1_runner_packs` | Remove one runner-pack entry. |
| SEC-01 | aureon SECURITY.md records the development-audit decision and 2027-03-31 expiry. | `test_security_md_records_audit_expiry` | Remove the expiry date. |

## Required baseline and restoration evidence

For every row the report must quote:

1. the named test failing at the baseline commit for the defect it describes;
2. the named test passing after the implementation;
3. the named test failing after the stated one-line deliberate break through its required real run;
4. the named test passing after the exact source restoration.

The report must identify every gate input and show it is read from a run artifact, signed attestation, or pinned file. Anything else blocks acceptance.

