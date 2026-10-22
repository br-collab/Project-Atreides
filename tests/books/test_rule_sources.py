"""Integrity checks for the cited books-and-records source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "atreides" / "books" / "rules"


def test_rule_17a_3_source_matches_the_pinned_digest() -> None:
    table = json.loads((RULES / "table.json").read_text(encoding="utf-8"))
    record = table["rules"][0]
    source = (RULES / record["source_file"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == record["source_sha256"]
    text = source.decode("utf-8")
    assert "17 CFR 240.17a-3(a)(1)-(5)" in text
    assert "showing the location of all securities long" in text
