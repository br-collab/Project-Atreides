"""The data dictionary must match the code that generates it.

A hand-maintained data dictionary drifts silently, and a data dictionary
nobody can trust is worse than none at all: a reviewer who finds one stale
field stops believing the other four hundred. So the document is generated,
and this test is what makes "generated" mean something - add a field, change
a description, or add an enumeration value without regenerating, and the
build fails.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import gen_data_dictionary  # noqa: E402

from atreides.dsor import store  # noqa: E402


def test_committed_data_dictionary_matches_the_models() -> None:
    committed = gen_data_dictionary.OUTPUT.read_text(encoding="utf-8")
    regenerated = gen_data_dictionary.render()
    assert committed == regenerated, (
        "docs/DATA-DICTIONARY.md is stale. Run "
        "`python3 tools/gen_data_dictionary.py` and commit the result."
    )


def test_the_dictionary_reports_the_real_ddl_rather_than_restating_it() -> None:
    """The persistence section reads the DDL constants out of the store.

    Restating the schema in prose is how a document ends up describing a
    table that no longer exists.
    """
    text = gen_data_dictionary.OUTPUT.read_text(encoding="utf-8")
    assert store._CREATE_TABLE.strip() in text
    assert store._CREATE_PARTIAL_INDEX.strip() in text


def test_undocumented_enumeration_values_are_counted_not_hidden() -> None:
    """A blank cell reads as a tooling failure; a counted gap reads as work."""
    documented, total, missing = gen_data_dictionary._coverage()
    assert total > 0
    assert documented + len(missing) == total
    text = gen_data_dictionary.OUTPUT.read_text(encoding="utf-8")
    assert f"{documented} of {total} enumeration values" in text


def test_enum_member_prose_survives_generation() -> None:
    """Python discards a string expression after a member assignment, so the
    reasoning that lives on each disposition is invisible at runtime and has
    to be read from source. If that ever silently stops working, the document
    degrades to a list of names and this test is the only thing that would
    notice.
    """
    text = gen_data_dictionary.OUTPUT.read_text(encoding="utf-8")
    assert "Obligation-level only" in text
    assert "The venue has the instruction" in text
    assert "The ordinary case in a netted system" in text
