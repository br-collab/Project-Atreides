"""DEADLINE-1 WP-1 acceptance tests for rule loading and fail-closed status."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cannae_kernel.disposition import Disposition
from pydantic import ValidationError

from atreides.deadlines import DeadlineRule, DeadlineRuleTable, RuleUnit, assess, load_rule_table


def _write_table(tmp_path: Path, *, citation: str = "17 CFR 999.1") -> DeadlineRuleTable:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = b"A report is due within seven business days."
    digest = hashlib.sha256(source).hexdigest()
    (sources / "rule.txt").write_bytes(source)
    table = {
        "schema_version": 1,
        "table_version": "test/1",
        "sources": [
            {
                "source_id": "rule",
                "citation": "17 CFR 999.1",
                "url": "https://example.invalid/rule",
                "filename": "rule.txt",
                "sha256": digest,
                "retrieval_dtg": "202610090900",
                "effective_date": "2026-10-09",
                "expires_at": None,
            }
        ],
        "rules": [
            {
                "rule_id": "difference_recording",
                "citation": citation,
                "source_id": "rule",
                "source_sha256": digest,
                "quote": "due within seven business days",
                "figure": "seven business days",
                "applicability": "difference recorded after a quarterly count",
                "value": "7",
                "unit": "BUSINESS_DAYS",
            }
        ],
    }
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    return load_rule_table(table_path, sources)


def test_committed_table_loads_without_refusals() -> None:
    table = load_rule_table()
    assert table.table_version == "deadline-rules/0.2-rule-204"
    assert len(table.sources) == 1
    assert len(table.rules) == 4
    assert table.rejected == ()


def test_cited_hash_pinned_number_loads(tmp_path: Path) -> None:
    table = _write_table(tmp_path)
    rule = table.get("difference_recording")
    assert rule is not None
    assert rule.value == 7
    assert rule.unit is RuleUnit.BUSINESS_DAYS
    assert table.rejected == ()


def test_a_number_without_a_citation_fails_validation() -> None:
    with pytest.raises(ValidationError):
        DeadlineRule(
            rule_id="uncited",
            citation="",
            source_id="rule",
            source_sha256="a" * 64,
            quote="seven business days",
            figure="seven business days",
            applicability="test case",
            value=Decimal(7),
            unit=RuleUnit.BUSINESS_DAYS,
        )


def test_changed_source_bytes_refuse_the_number(tmp_path: Path) -> None:
    table = _write_table(tmp_path)
    assert table.rules
    (tmp_path / "sources" / "rule.txt").write_text("changed", encoding="utf-8")
    refused = load_rule_table(tmp_path / "table.json", tmp_path / "sources")
    assert refused.rules == ()
    assert any("digest mismatch" in reason for reason in refused.rejected)


def test_versioned_source_requires_currency_date(tmp_path: Path) -> None:
    _write_table(tmp_path)
    document = json.loads((tmp_path / "table.json").read_text(encoding="utf-8"))
    document["sources"][0]["expires_at"] = "2026-10-09"
    (tmp_path / "table.json").write_text(json.dumps(document), encoding="utf-8")

    undated = load_rule_table(tmp_path / "table.json", tmp_path / "sources")
    assert undated.rules == ()
    assert any("currency date required" in reason for reason in undated.rejected)

    expired = load_rule_table(
        tmp_path / "table.json", tmp_path / "sources", as_of=date(2026, 10, 10)
    )
    assert expired.rules == ()
    assert any("source version expired" in reason for reason in expired.rejected)

    current = load_rule_table(
        tmp_path / "table.json", tmp_path / "sources", as_of=date(2026, 10, 9)
    )
    assert current.get("difference_recording") is not None


def test_unloaded_item_is_indeterminate() -> None:
    result = assess(
        evaluated_at=datetime(2026, 10, 9, 9, tzinfo=UTC),
        missing_rules=("rule-204.short",),
    )
    assert result.disposition is Disposition.INDETERMINATE
    assert result.enforcement_status == "ADVISORY_ONLY"
    assert result.claim_label == "EXPERIMENTAL"


def test_missing_calendar_is_hold() -> None:
    result = assess(
        evaluated_at=datetime(2026, 10, 9, 9, tzinfo=UTC),
        missing_inputs=("calendar",),
    )
    assert result.disposition is Disposition.HOLD


def test_no_missing_evidence_or_breach_is_pass_but_not_a_compliance_claim() -> None:
    result = assess(evaluated_at=datetime(2026, 10, 9, 9, tzinfo=UTC))
    assert result.disposition is Disposition.PASS
    assert result.enforcement_status == "ADVISORY_ONLY"


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(ValidationError):
        assess(evaluated_at=datetime(2026, 10, 9, 9))


def test_deadline_package_has_no_cross_domain_or_enforcement_imports() -> None:
    package = Path(__file__).parents[2] / "atreides" / "deadlines"
    prohibited = {"aureon", "cop", "enforcement"}
    for source_file in package.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert roots.isdisjoint(prohibited), source_file
