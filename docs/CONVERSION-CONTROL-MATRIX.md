# Self-clearing conversion control matrix

This is a synthetic control rehearsal, not a legal conclusion, membership application, filing, or production conversion plan. Owner roles are illustrative.

| Control | Owner role (illustrative) | Governing source | Evidence and disposition | What is not tested | Executable node |
|---|---|---|---|---|---|
| Introducing status and bank notification | FINOP | 17 CFR 240.15c3-3(k)(2)(ii), (f) | Pinned provisions and declared evidence; absent notification is `None` and holds G1 | Delivery, retention, legal sufficiency | `tests/test_conversion_scenario.py::test_conversion_rule_quotes_are_verbatim_in_pinned_source` |
| Statement-to-book conservation (I10) | Conversion operations | Synthetic prior-clearer statement; balanced Atreides journal | Account/issue quantity and account cash match exactly, including cents | ACATS, bulk-transfer messaging, real customer data | `tests/test_conversion_scenario.py::test_i10_generated_migrations_conserve_quantity_and_cash` |
| Possession or control | Stock-record operations | 17 CFR 240.15c3-3(b), (c) | Prior clearer stays unknown; the real engine passes only after the declared transfer | Paragraph (b)(2) lag allowance; DTC membership | `tests/test_conversion_scenario.py::test_prior_clearer_location_is_unknown_until_transfer` |
| Conversion readiness (I9) | Conversion manager | 17 CFR 240.15c3-3(f), (e)(3), (e)(5), (c); 17 CFR 240.15c3-1(a)(2)(i) | Independent declarations and dates derive required result; pipeline output is compared separately | Legal approval, FINRA CMA, filing or notice submission | `tests/test_conversion_scenario.py::test_all_seven_variants_have_honest_i9_and_expected_holds` |
| Adversarial mutations | Independent controls testing | CONV-1B scope | Six end-to-end mutations must turn I9 or I10 false | Exhaustive fault injection or production data | `tests/test_conversion_scenario.py::test_six_end_to_end_mutations_each_fail_i9_or_i10` |
| Human-readable publication | Operations reporting | CONV-1/CONV-1B publication requirements | Four artifacts show required and produced D–D+3 results and deposit evidence | Production correctness or external publication delivery | `tests/test_conversion_scenario.py::test_publication_has_four_files_and_explicit_non_claims` |

The scenario also does not infer fully-paid or excess-margin status from account debits, use a bank-holiday calendar, or use real identifiers. No component submits, authorizes, releases, or holds credentials.
