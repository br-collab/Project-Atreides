# PS-3 evidence plan

Date: 2026-11-18. Owner of the committed copy: Project-Atreides. Canonical copy: workspace `_reports/PS-3-evidence-plan.md`.

This plan is the closure checklist for ORDER PS-3. For every row, the final report must quote both rule 6 evidence that the named test failed before the control existed and rule 14 evidence that the named test failed after the stated one-line deliberate break. A passing test without both failure demonstrations does not close the row.

| ID | Control | Named test | One-line deliberate break |
|---|---|---|---|
| P0-01 | Every planted reconciliation break is assigned its own ranked cause from timing, missing instruction, quantity difference, or unknown. | `test_planted_breaks_receive_ranked_causes` | Return `UNKNOWN` before evaluating the break facts. |
| P0-02 | KYC chain integrity is checked independently of stored-payload equality. | `test_kyc_broken_digest_with_same_payload_fails_chain_check_only` | Remove the chain-verification refusal in `resolve_kyc`. |
| P0-03 | The stored KYC payload must equal the resolved record independently of chain integrity. | `test_kyc_resealed_different_record_fails_payload_check_only` | Remove the stored-payload equality refusal in `resolve_kyc`. |
| WSP-01 | The versioned WSP register has one complete row for every golden-path gate and every row names an existing test. | `test_wsp_register_covers_every_gate_with_an_existing_test` | Delete the confirmation gate row. |
| WSP-02 | Every WSP row names a synthetic registered-principal role, review frequency, evidence, escalation path, rule, control, and test. | `test_wsp_rows_have_complete_supervisory_fields` | Blank one row's `supervisor_role`. |
| WSP-03 | Every golden-path gate decision produces a review record with reviewer, decision, outcome, and time. | `test_golden_path_produces_review_record_for_every_gate` | Skip the reserve gate while building review records. |
| WSP-04 | A reviewer cannot review a decision made by the same actor. | `test_supervisory_review_refuses_self_review` | Remove the reviewer-equals-decider refusal. |
| SC-01 | A Rule 3120 run executes every WSP row's named test and reports tests, exceptions, and remediation owners to synthetic senior management. | `test_3120_run_executes_and_reports_every_wsp_test` | Stop recording executed test names. |
| SC-02 | A missing or unrun WSP test is a Rule 3120 exception, never a pass. | `test_3120_missing_test_is_one_exception` | Treat a missing test as passed. |
| SC-03 | The Rule 3130 artifact is an unsigned draft that cites the Rule 3120 report. | `test_3130_is_unsigned_draft_citing_3120_report` | Mark the certification as signed. |
| CAT-01 | CAT records are built in L.C. from evidence-chain events, never request values. | `test_cat_builder_reads_evidence_chain_not_request` | Replace the evidence-chain symbol with a conflicting request symbol. |
| CAT-02 | The CAT event set contains the required new-order, route, and post-trade-allocation events, while execution remains the synthetic exchange's event. | `test_cat_event_set_and_exchange_execution_boundary` | Emit a firm execution event. |
| CAT-03 | An FDID is derived and can never equal the account number. | `test_cat_refuses_fdid_equal_to_account_number` | Remove the FDID/account-number equality refusal. |
| CAT-04 | Customer fields follow the reduced post-2025 CAIS requirements and record a rule basis for every sent or withheld field. | `test_cat_customer_fields_have_reduced_cais_basis` | Add an account holder name without a basis. |
| CAT-05 | The local CAT validator checks required fields, types, linkage keys, and specification timestamp precision. | `test_cat_validator_checks_schema_linkage_and_time_precision` | Skip parent linkage validation. |
| CAT-06 | A route without its parent new-order event is refused. | `test_cat_route_without_parent_is_refused` | Accept an unknown `parent_event_id`. |
| CAT-07 | Rejected CAT records produce feedback and a T+3 correction deadline. | `test_cat_rejection_feedback_has_t_plus_3_deadline` | Set the correction deadline to T+4. |
| CAT-08 | A rejected CAT record appears on the COP exceptions panel with its computed correction deadline. | `test_cat_rejection_appears_on_cop_exceptions` | Filter CAT feedback out of the exceptions panel. |
| CAT-09 | Aureon's CAT stub never labels arbitrary input `READY`; it returns the documented non-validation disposition. | `test_aureon_cat_stub_never_returns_ready` | Restore the constant `READY` result. |
| AML-01 | Ongoing monitoring reads books and the instruction log, not caller-supplied scenario values. | `test_aml_monitor_reads_books_and_instruction_log` | Use the caller's transfer amount instead of the instruction log. |
| AML-02 | Deposit then withdrawal without trading fires only for the planted customer and not the golden-path customer. | `test_aml_deposit_withdrawal_scenario` | Disable the deposit-withdrawal detector. |
| AML-03 | Transfers between unrelated accounts fire only for the planted customer and not the golden-path customer. | `test_aml_unrelated_accounts_scenario` | Treat unrelated owners as related. |
| AML-04 | Deposit of securities followed by a fast sale fires only for the planted customer and not the golden-path customer. | `test_aml_fast_sale_scenario` | Ignore the security-deposit event. |
| AML-05 | Declared thresholds are policy data and a monitoring alert opens a case. | `test_aml_alert_opens_case_using_policy_thresholds` | Return an alert without creating its case. |
| AML-06 | Aureon can draft an advisory case narrative but cannot decide a case. | `test_aml_agent_output_is_advisory_without_decision` | Let the advisory set a final decision. |
| AML-07 | Only a named human AML officer can record a SAR or no-SAR decision with a reason, and a case cannot close without it. | `test_aml_case_close_requires_named_human_decision` | Permit closure with no human decision. |
| AML-08 | The SAR clock starts at initial detection, applies the defined extension condition, and a missed 30-day deadline becomes a supervisory exception. | `test_aml_missed_30_day_clock_is_supervisory_exception` | Start the clock at case creation instead of detection. |
| AML-09 | A file decision produces a draft SAR record and never files it. | `test_aml_file_decision_produces_unfiled_draft` | Mark the draft as filed. |
| AML-10 | No public COP, customer statement, customer communication, or externally published pack contains SAR data or the case identifier. | `test_sar_confidentiality_across_every_published_artifact` | Add the case identifier to the public AML summary. |
| SURV-01 | A planted same-beneficial-owner wash pair is flagged and routed to a human. | `test_equities_wash_pair_is_flagged_for_human` | Ignore equal beneficial-owner identifiers. |
| SURV-02 | Marking-the-close activity is detected from the run's orders and fills. | `test_equities_marking_close_is_flagged` | Disable the close-window price check. |
| SURV-03 | Missing required scenario data produces `DATA_INCOMPLETE`, never clear. | `test_surveillance_missing_beneficial_owner_is_data_incomplete` | Map missing beneficial owner to clear. |
| PUB-01 | The pack and COP derive WSP, 3120, CAT, AML-alert, and surveillance numbers from engine results. | `test_cop_and_pack_counts_equal_engine_results` | Hard-code the CAT validated count. |
| PUB-02 | Customer confirmation and statement remain unchanged and contain no supervisory, AML, or surveillance data. | `test_customer_artifacts_unchanged_and_free_of_ps3_data` | Add a supervisory status field to the statement. |

## Required source and gate-input evidence

The final report must identify the pinned primary source used by each regulated control and quote the pin or checksum. It must also list every input and its source for the review record, Rule 3120 run, CAT validator, each AML scenario, SAR decision, and each surveillance scenario. Any substantive input supplied by a caller instead of read from the named system of record is a defect.
