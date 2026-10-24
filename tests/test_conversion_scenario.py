from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from atreides.customer_protection.rules import normalize_text
from simulator.conversion import (
    SEED,
    VARIANTS,
    StatementLine,
    migration_books,
    migration_conserved,
    publish_conversion,
    run_conversion_variant,
)


def test_conversion_rule_quotes_are_verbatim_in_pinned_source() -> None:
    table = json.loads(Path("atreides/customer_protection/rules/table.json").read_text())
    source = normalize_text(
        Path("atreides/customer_protection/rules/sources/17-CFR-240.15c3-3.xml").read_bytes()
    )
    ids = {"15c3-3.k2ii.introducing_exemption", "15c3-3.f.bank_written_notification"}
    rows = [row for row in table["items"] if row["id"] in ids]
    assert {row["id"] for row in rows} == ids
    assert all(row["quote"] in source for row in rows)


@seed(SEED)
@settings(max_examples=200, database=None, deadline=None)
@given(
    quantities=st.lists(
        st.decimals(min_value="0.01", max_value="100000", places=3), min_size=1, max_size=8
    ),
    cash=st.lists(
        st.decimals(min_value="0.01", max_value="10000000", places=2), min_size=1, max_size=8
    ),
)
def test_i10_generated_migrations_conserve_quantity_and_cash(
    quantities: list[Decimal], cash: list[Decimal]
) -> None:
    size = min(len(quantities), len(cash))
    lines = tuple(
        StatementLine(f"SYN-CUST-{i}", f"SYN-ISSUE-{i}", quantities[i], cash[i])
        for i in range(size)
    )
    assert migration_conserved(migration_books(lines, date(2027, 1, 6), transferred=False), lines)


def test_prior_clearer_location_is_unknown_until_transfer() -> None:
    run = run_conversion_variant("clean")
    assert run["closes"][2]["control"]["disposition"] == "INDETERMINATE"
    assert run["closes"][3]["control"]["disposition"] == "PASS"


def test_all_seven_variants_have_honest_i9_and_expected_holds() -> None:
    runs = {variant: run_conversion_variant(variant) for variant in VARIANTS}
    assert all(run["all_invariants_pass"] for run in runs.values())
    assert runs["clean"]["closes"][3]["conversion_disposition"] == "PASS"
    assert "reserve shortfall" in runs["short-first-deposit"]["closes"][2]["conversion_reasons"]
    assert "reserve shortfall" in runs["late-first-deposit"]["closes"][2]["conversion_reasons"]
    assert runs["late-transfer"]["closes"][4]["conversion_disposition"] == "HOLD"
    assert any(
        "G1:" in reason for reason in runs["missing-f-letter"]["closes"][3]["conversion_reasons"]
    )
    assert any(
        "G2:" in reason for reason in runs["affiliated-bank"]["closes"][3]["conversion_reasons"]
    )
    assert any(
        "G3:" in reason for reason in runs["capital-short"]["closes"][3]["conversion_reasons"]
    )


def test_six_end_to_end_mutations_each_fail_i9_or_i10() -> None:
    cases = (
        ("clean", "forced-hold-funded"),
        ("short-first-deposit", "forced-pass-short"),
        ("clean", "cleared-gate-let-through"),
        ("affiliated-bank", "affiliated-counted-eligible"),
        ("clean", "prior-clearer-as-control"),
        ("clean", "drop-one-share"),
    )
    for variant, mutation in cases:
        run = run_conversion_variant(variant, mutation=mutation)
        assert not run["all_invariants_pass"], (variant, mutation)


def test_publication_has_four_files_and_explicit_non_claims(tmp_path: Path) -> None:
    output = tmp_path / "clean"
    publish_conversion(run_conversion_variant("clean"), output)
    assert {path.name for path in output.iterdir()} == {
        "run-summary.json",
        "daily-close.json",
        "trend.json",
        "SUMMARY.md",
    }
    summary = (output / "SUMMARY.md").read_text()
    assert "ACATS or bulk transfer" in summary
    assert "I9 conversion gated" in summary


def test_control_matrix_node_ids_exist() -> None:
    text = Path("docs/CONVERSION-CONTROL-MATRIX.md").read_text()
    required = {
        "test_conversion_rule_quotes_are_verbatim_in_pinned_source",
        "test_i10_generated_migrations_conserve_quantity_and_cash",
        "test_prior_clearer_location_is_unknown_until_transfer",
        "test_all_seven_variants_have_honest_i9_and_expected_holds",
        "test_six_end_to_end_mutations_each_fail_i9_or_i10",
        "test_publication_has_four_files_and_explicit_non_claims",
    }
    assert all(f"tests/test_conversion_scenario.py::{name}" in text for name in required)
