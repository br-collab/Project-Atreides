"""Rule 31: implementation and test cite the same pinned paragraphs."""

import pytest

from atreides.books.projections import EXHIBIT_A_PARAGRAPHS
from atreides.deadlines.rule_204 import RULE_204_PARAGRAPH
from atreides.margin.engine import (
    FINRA_4210_MAINTENANCE_PARAGRAPH,
    REG_T_INITIAL_MARGIN_PARAGRAPH,
)


@pytest.mark.parametrize(
    ("rule_id", "scope_words"),
    [
        ("15c3-3a.item.01", "customers' security accounts"),
        ("15c3-3a.item.04", "Customers' securities failed to receive"),
        ("15c3-3a.item.10", "customers' cash and margin accounts"),
        ("15c3-3a.item.11", "short sales by customers"),
        ("15c3-3a.item.12", "not older than 30 calendar days"),
    ],
)
def test_exhibit_a_projection_cites_each_pinned_paragraph(rule_id: str, scope_words: str) -> None:
    assert scope_words in EXHIBIT_A_PARAGRAPHS[rule_id]


def test_reg_t_initial_margin_cites_the_pinned_paragraph() -> None:
    assert "fifty per cent of its current market value" in REG_T_INITIAL_MARGIN_PARAGRAPH


def test_finra_4210_maintenance_cites_the_pinned_paragraph() -> None:
    assert FINRA_4210_MAINTENANCE_PARAGRAPH.startswith("25 percent")


def test_rule_204_close_out_cites_the_pinned_paragraph() -> None:
    assert "beginning of regular trading hours" in RULE_204_PARAGRAPH
    assert "borrowing or purchasing securities of like kind and quantity" in RULE_204_PARAGRAPH
