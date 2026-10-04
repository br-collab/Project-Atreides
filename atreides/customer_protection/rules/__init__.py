"""Versioned rule table for the customer protection engines (ORDER SC-2, WP-1).

EXPERIMENTAL (charter section 18.6). ``sources/`` holds the rule text exactly as
fetched, each file with a SHA-256 sidecar and retrieval metadata. ``table.json``
holds one row per figure or category an engine reads. :func:`load_rule_table`
checks every row against its source and leaves out any row that does not check.
"""

from atreides.customer_protection.rules.loader import load_rule_table, normalize_text, parse_figure
from atreides.customer_protection.rules.model import (
    CLAIM_LABEL,
    RejectedItem,
    RuleItem,
    RuleKind,
    RuleSource,
    RuleTable,
    RuleVersion,
    SourceLabel,
)

__all__ = [
    "CLAIM_LABEL",
    "RejectedItem",
    "RuleItem",
    "RuleKind",
    "RuleSource",
    "RuleTable",
    "RuleVersion",
    "SourceLabel",
    "load_rule_table",
    "normalize_text",
    "parse_figure",
]
