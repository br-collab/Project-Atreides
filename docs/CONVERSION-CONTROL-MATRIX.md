# Self-clearing conversion control matrix

This matrix describes a synthetic control rehearsal. It is not a legal conclusion, membership application, filing, or production conversion plan.

| Control | Governing source | Evidence and disposition | Executable node |
|---|---|---|---|
| Introducing status and bank notification | 17 CFR 240.15c3-3(k)(2)(ii), (f) | Pinned verbatim provisions; absent written notification is `None` and holds G1 | `tests/test_conversion_scenario.py::test_conversion_rule_quotes_are_verbatim_in_pinned_source` |
| Statement-to-book conservation (I10) | Synthetic prior-clearer statement; balanced Atreides journal | Account/issue quantity and account cash must match exactly, including cents | `tests/test_conversion_scenario.py::test_i10_generated_migrations_conserve_quantity_and_cash` |
| Possession or control | 17 CFR 240.15c3-3(b), (c) | Prior clearer remains an unknown location; the real engine becomes PASS only after synthetic DTC control | `tests/test_conversion_scenario.py::test_prior_clearer_location_is_unknown_until_transfer` |
| Conversion readiness (I9) | 17 CFR 240.15c3-3(f), (e)(5), (c); 17 CFR 240.15c3-1(a)(2)(i) | G1–G4 and all real engine results gate the conversion; six variants exercise the named holds | `tests/test_conversion_scenario.py::test_all_six_variants_drive_expected_holds_and_recovery` |
| Adversarial mutations | CONV-1 order WP4 | Dropped account, one-cent cash change, quantity change, and gate bypass must fail I10 or I9 | `tests/test_conversion_scenario.py::test_four_mutations_are_caught_by_i9_or_i10` |
| Human-readable publication | CONV-1 order WP6 | Four artifacts state D disposition, I9/I10, deposit, and the explicit non-claims | `tests/test_conversion_scenario.py::test_publication_has_four_files_and_explicit_non_claims` |

The scenario additionally does not model the paragraph (b)(2) temporary-lag allowance, infer fully-paid/excess-margin status from debit balances, use a bank-holiday calendar, or use real customer data. No component submits, authorizes, releases, or holds credentials.
