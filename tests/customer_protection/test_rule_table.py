"""WP-1 acceptance: the rule table loads only figures that check against pinned rule text.

Acceptance criteria (ORDER SC-2, WP-1):

- No regulatory figure exists outside the table: see ``test_package_source.py``.
- A test fails if a number has no citation: ``test_a_row_without_a_citation_is_refused``
  and ``test_every_loaded_item_is_cited_quoted_and_hashed``.
- An unloaded item returns INDETERMINATE: ``test_an_unloaded_item_is_indeterminate``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cannae_kernel.disposition import Disposition

from atreides.customer_protection.common import RuleReader, decide
from atreides.customer_protection.rules import (
    RuleKind,
    RuleTable,
    SourceLabel,
    load_rule_table,
    normalize_text,
    parse_figure,
)
from atreides.customer_protection.rules.loader import DEFAULT_SOURCES_DIR, FigureError
from atreides.customer_protection.rules.model import RuleItemSpec
from tests.customer_protection.conftest import TableEditor, without

RULE_SOURCES = {
    "17cfr240.15c3-1": "17 CFR 240.15c3-1",
    "17cfr240.15c3-3": "17 CFR 240.15c3-3",
    "17cfr240.15c3-3a": "17 CFR 240.15c3-3a",
    "17cfr240.17a-11": "17 CFR 240.17a-11",
}


def _row(document: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(row for row in document["items"] if row["id"] == rule_id)


# --- the committed table -------------------------------------------------------------


def test_the_committed_table_loads_with_nothing_refused(table: RuleTable) -> None:
    assert table.rejected == ()
    assert len(table.items) == 86
    assert table.table_version == "sc2-rules/0.1"


def test_every_rule_section_the_order_names_is_loaded(table: RuleTable) -> None:
    loaded = {s.source_id: s for s in table.sources}
    for source_id, citation in RULE_SOURCES.items():
        assert loaded[source_id].citation == citation
        assert loaded[source_id].label is SourceLabel.RULE
        assert loaded[source_id].ecfr_up_to_date_as_of is not None
    assert loaded["sec-faq-15c3-3-daily"].label is SourceLabel.GUIDANCE


def test_every_loaded_item_is_cited_quoted_and_hashed(table: RuleTable) -> None:
    sources = {s.source_id: s for s in table.sources}
    for item in table.items:
        source = sources[item.source_id]
        text = normalize_text((DEFAULT_SOURCES_DIR / source.filename).read_bytes())
        assert item.citation.startswith(source.citation), item.id
        assert item.quote in text, item.id
        assert item.sha256 == source.sha256 == hashlib.sha256(
            (DEFAULT_SOURCES_DIR / source.filename).read_bytes()
        ).hexdigest()
        assert item.retrieval_dtg == source.retrieval_dtg
        assert item.source_label is SourceLabel.RULE, "guidance is never computed from"
        assert (item.value is not None) is item.kind.has_value, item.id


def test_no_item_is_read_from_guidance(table: RuleTable) -> None:
    assert all(item.source_id != "sec-faq-15c3-3-daily" for item in table.items)


def test_the_daily_items_carry_the_compliance_date_from_guidance(table: RuleTable) -> None:
    for rule_id in ("15c3-3.e3iB1.daily_threshold", "15c3-1.a1iiA.daily_debit_reduction"):
        item = table.get(rule_id)
        assert item is not None
        assert str(item.compliance_date) == "2026-06-30"


@pytest.mark.parametrize(
    ("rule_id", "value"),
    [
        # The facts the order states in section 2, here read back from the loaded text.
        ("15c3-1.a2i.minimum.carrying", Decimal("250000")),
        ("15c3-1.a1ii.alternative_floor", Decimal("250000")),
        ("15c3-1.a1ii.alternative_debit_percent", Decimal("0.02")),
        ("15c3-1.a1iiA.weekly_debit_reduction", Decimal("0.03")),
        ("15c3-1.a1iiA.daily_debit_reduction", Decimal("0.02")),
        ("15c3-3.e3iB1.daily_threshold", Decimal("500000000")),
    ],
)
def test_the_order_s_stated_figures_match_the_loaded_text(
    table: RuleTable, rule_id: str, value: Decimal
) -> None:
    item = table.get(rule_id)
    assert item is not None and item.value == value


def test_every_sidecar_hash_matches_its_file() -> None:
    for sidecar in DEFAULT_SOURCES_DIR.glob("*.sha256"):
        digest, name = sidecar.read_text(encoding="utf-8").split()
        assert hashlib.sha256((DEFAULT_SOURCES_DIR / name).read_bytes()).hexdigest() == digest
        meta = json.loads((DEFAULT_SOURCES_DIR / f"{name}.meta.json").read_text(encoding="utf-8"))
        assert meta["sha256"] == digest
        assert len(meta["retrieval_dtg"]) == 12 and meta["retrieval_dtg"].isdigit()


# --- unloaded items --------------------------------------------------------------------


def test_an_unloaded_item_is_indeterminate(edited_table: TableEditor) -> None:
    rule_id = "15c3-1.a1ii.alternative_floor"
    table = edited_table(without(rule_id))
    reader = RuleReader(table)
    assert reader.value(rule_id) is None
    assert reader.missing == (rule_id,)
    assert decide(reader.missing, (), ()) is Disposition.INDETERMINATE


def test_missing_inputs_hold_and_nothing_found_passes(table: RuleTable) -> None:
    reader = RuleReader(table)
    assert reader.value("15c3-1.a1ii.alternative_floor") == Decimal("250000")
    assert reader.present("15c3-3.control.c5")
    assert reader.missing == ()
    assert [ref.rule_id for ref in reader.used] == [
        "15c3-1.a1ii.alternative_floor",
        "15c3-3.control.c5",
    ]
    assert decide((), ("credits",), ()) is Disposition.HOLD
    assert decide((), (), ("shortfall",)) is Disposition.HOLD
    assert decide((), (), ()) is Disposition.PASS


# --- refusals ----------------------------------------------------------------------------


def test_a_row_without_a_citation_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-1.a1ii.alternative_debit_percent"
    table = edited_table(lambda d: _row(d, rule_id).pop("citation"))
    assert table.get(rule_id) is None
    assert [r.id for r in table.rejected] == [rule_id]


def test_a_figure_that_does_not_read_as_its_value_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-1.a1iiA.weekly_debit_reduction"
    table = edited_table(lambda d: _row(d, rule_id).update(value="0.025"))
    assert table.get(rule_id) is None
    assert "reads 0.03" in table.rejected[0].reason


def test_a_quote_not_in_the_source_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-1.a2i.minimum.carrying"
    table = edited_table(
        lambda d: _row(d, rule_id).update(
            quote="shall maintain net capital of not less than $300,000", figure="$300,000",
            value="300000",
        )
    )
    assert table.get(rule_id) is None
    assert "quote not found" in table.rejected[0].reason


def test_an_item_pinned_to_other_text_is_refused(edited_table: TableEditor) -> None:
    rule_id = "17a-11.b3.minimum_warning"
    table = edited_table(lambda d: _row(d, rule_id).update(sha256="0" * 64))
    assert table.get(rule_id) is None
    assert "re-pin" in table.rejected[0].reason


def test_a_rule_item_read_from_guidance_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-3.e3iB1.daily_threshold"
    faq = "sec-faq-15c3-3-daily"

    def edit(document: dict[str, Any]) -> None:
        row = _row(document, rule_id)
        source = next(s for s in load_rule_table().sources if s.source_id == faq)
        row.update(source_id=faq, sha256=source.sha256)

    table = edited_table(edit)
    assert table.get(rule_id) is None
    assert "not rule text" in table.rejected[0].reason


def test_a_compliance_date_whose_quote_is_absent_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-3.e3iB1.daily_threshold"
    table = edited_table(lambda d: _row(d, rule_id).update(compliance_quote="June 30, 2027"))
    assert table.get(rule_id) is None


def test_a_compliance_date_citing_an_unloaded_source_is_refused(edited_table: TableEditor) -> None:
    rule_id = "15c3-3.e3iB1.daily_threshold"
    table = edited_table(lambda d: _row(d, rule_id).update(compliance_source_id="nowhere"))
    assert table.get(rule_id) is None


def test_a_duplicate_id_is_refused(edited_table: TableEditor) -> None:
    rule_id = "17a-11.b1.ai_warning"
    table = edited_table(lambda d: d["items"].append(dict(_row(d, rule_id))))
    assert table.get(rule_id) is not None
    assert [r.reason for r in table.rejected] == ["duplicate id"]


def test_an_item_whose_source_is_not_listed_is_refused(edited_table: TableEditor) -> None:
    rule_id = "17a-11.b1.ai_warning"
    table = edited_table(lambda d: _row(d, rule_id).update(source_id="nowhere"))
    assert table.get(rule_id) is None


def test_a_tampered_source_refuses_every_item_read_from_it(tmp_path: Path) -> None:
    import shutil

    sources = tmp_path / "sources"
    shutil.copytree(DEFAULT_SOURCES_DIR, sources)
    path = sources / "17-CFR-240.17a-11.xml"
    path.write_bytes(path.read_bytes().replace(b"1,200 percent", b"1,500 percent"))
    table = load_rule_table(sources_dir=sources)
    assert table.get("17a-11.b1.ai_warning") is None
    assert table.version_of("17cfr240.17a-11") is None
    assert "source:17cfr240.17a-11" in {r.id for r in table.rejected}
    assert table.get("15c3-1.a1ii.alternative_floor") is not None


def test_metadata_that_describes_another_file_is_refused(tmp_path: Path) -> None:
    import shutil

    sources = tmp_path / "sources"
    shutil.copytree(DEFAULT_SOURCES_DIR, sources)
    meta = sources / "17-CFR-240.17a-11.xml.meta.json"
    document = json.loads(meta.read_text(encoding="utf-8"))
    document["source_id"] = "17cfr240.15c3-1"
    meta.write_text(json.dumps(document), encoding="utf-8")
    assert load_rule_table(sources_dir=sources).version_of("17cfr240.17a-11") is None


def test_a_missing_source_file_is_refused(tmp_path: Path) -> None:
    import shutil

    sources = tmp_path / "sources"
    shutil.copytree(DEFAULT_SOURCES_DIR, sources)
    (sources / "17-CFR-240.17a-11.xml").unlink()
    table = load_rule_table(sources_dir=sources)
    assert table.get("17a-11.b2.alternative_warning") is None


def test_version_of_names_the_pinned_text(table: RuleTable) -> None:
    version = table.version_of("17cfr240.15c3-3a")
    assert version is not None and version.citation == "17 CFR 240.15c3-3a"
    assert table.version_of("not-a-source") is None


# --- the row model -----------------------------------------------------------------------


def _spec(**changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "x", "kind": "PERCENT", "citation": "c", "source_id": "s", "sha256": "a" * 64,
        "quote": "by 3%", "figure": "3%", "value": "0.03",
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(
    "changes",
    [
        {"figure": None},
        {"value": None},
        {"kind": "CONTROL_LOCATION"},
        {"figure": "4%"},
        {"compliance_date": "2026-06-30"},
    ],
)
def test_the_row_model_refuses_inconsistent_rows(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RuleItemSpec.model_validate(_spec(**changes))


def test_the_row_model_refuses_a_non_finite_value() -> None:
    with pytest.raises(ValueError):
        RuleItemSpec.model_validate(_spec(value="NaN"))


# --- figures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "figure", "value"),
    [
        (RuleKind.PERCENT, "1500 percent", "15"),
        (RuleKind.PERCENT, "1,200 percent", "12"),
        (RuleKind.PERCENT, "3%", "0.03"),
        (RuleKind.PERCENT, "0 percent", "0"),
        (RuleKind.PERCENT, "1/2 of 1 percent", "0.005"),
        (RuleKind.PERCENT, "3/4 of 1 percent", "0.0075"),
        (RuleKind.PERCENT, "1 1/2 percent", "0.015"),
        (RuleKind.PERCENT, "4 1/2 %", "0.045"),
        (RuleKind.USD, "$250,000", "250000"),
        (RuleKind.USD, "$500 million", "500000000"),
        (RuleKind.USD, "$5 billion", "5000000000"),
        (RuleKind.MONTHS, "3 months", "3"),
        (RuleKind.MONTHS, "1 year", "12"),
        (RuleKind.MONTHS, "25 years", "300"),
        (RuleKind.CALENDAR_DAYS, "30 calendar days", "30"),
        (RuleKind.BUSINESS_DAYS, "two business days", "2"),
        (RuleKind.BUSINESS_DAYS, "5 business days", "5"),
    ],
)
def test_figures_read_exactly(kind: RuleKind, figure: str, value: str) -> None:
    assert parse_figure(kind, figure) == Decimal(value)


@pytest.mark.parametrize(
    ("kind", "figure"),
    [
        (RuleKind.PERCENT, "percent"),
        (RuleKind.PERCENT, "three percent"),
        (RuleKind.USD, "250,000"),
        (RuleKind.MONTHS, "3 weeks"),
        (RuleKind.CALENDAR_DAYS, "30 business days"),
        (RuleKind.BUSINESS_DAYS, "many business days"),
        (RuleKind.CONTROL_LOCATION, "anything"),
    ],
)
def test_figures_that_do_not_read_are_refused(kind: RuleKind, figure: str) -> None:
    with pytest.raises(FigureError):
        parse_figure(kind, figure)


def test_normalized_text_joins_split_fractions_and_drops_markup() -> None:
    raw = b"<P>maturity\xe2\x80\x941 <FR>1/2</FR> percent.&#160;<script>x=1</script></P>"
    assert normalize_text(raw) == "maturity—1 1/2 percent."
