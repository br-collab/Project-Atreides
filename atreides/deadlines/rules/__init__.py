"""Offline loader and committed parameter table for deadline engines."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from atreides.deadlines.model import DeadlineRule, DeadlineRuleTable, RuleSource

RULES_DIR = Path(__file__).parent
DEFAULT_TABLE_PATH = RULES_DIR / "table.json"
DEFAULT_SOURCES_DIR = RULES_DIR / "sources"


def load_rule_table(
    table_path: Path = DEFAULT_TABLE_PATH,
    sources_dir: Path = DEFAULT_SOURCES_DIR,
    *,
    as_of: date | None = None,
) -> DeadlineRuleTable:
    """Load cited parameters whose pinned source bytes and quotes still match."""
    document: dict[str, Any] = json.loads(table_path.read_bytes())
    sources: dict[str, RuleSource] = {}
    source_text: dict[str, str] = {}
    rejected: list[str] = []
    for raw in document["sources"]:
        try:
            source = RuleSource.model_validate_json(json.dumps(raw))
            data = (sources_dir / source.filename).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if actual != source.sha256:
                raise ValueError("source digest mismatch")
            if source.expires_at is not None and as_of is None:
                raise ValueError("currency date required for versioned source")
            if source.expires_at is not None and as_of is not None and as_of > source.expires_at:
                raise ValueError("source version expired")
            if source.source_id in sources:
                raise ValueError("duplicate source_id")
            sources[source.source_id] = source
            source_text[source.source_id] = data.decode("utf-8")
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            rejected.append(f"source:{raw.get('source_id', '<missing>')}: {exc}")

    rules: list[DeadlineRule] = []
    seen: set[str] = set()
    for raw in document["rules"]:
        rule_id = str(raw.get("rule_id", "<missing>"))
        try:
            rule = DeadlineRule.model_validate_json(json.dumps(raw))
            if rule.rule_id in seen:
                raise ValueError("duplicate rule_id")
            seen.add(rule.rule_id)
            loaded_source = sources.get(rule.source_id)
            if loaded_source is None:
                raise ValueError("source is not loaded")
            if rule.source_sha256 != loaded_source.sha256:
                raise ValueError("rule is pinned to different source bytes")
            if rule.quote not in source_text[rule.source_id]:
                raise ValueError("quote is absent from source bytes")
            rules.append(rule)
        except (ValueError, ValidationError) as exc:
            rejected.append(f"rule:{rule_id}: {exc}")
    return DeadlineRuleTable(
        schema_version=document["schema_version"],
        table_version=document["table_version"],
        sources=tuple(sources.values()),
        rules=tuple(rules),
        rejected=tuple(rejected),
    )
