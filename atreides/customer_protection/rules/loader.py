"""Load the rule table, checking every item against the pinned rule text.

EXPERIMENTAL (charter section 18.6). No network. The files read here were
written by ``tools/fetch_customer_protection_rules.py`` and committed.

WHAT A CHECK FAILURE DOES
-------------------------
It does not raise. A refused item is left out of the table and listed in
:attr:`~.model.RuleTable.rejected` with the reason, so its id resolves to
nothing, and an engine that needs it returns INDETERMINATE naming it. A table
that raised on one bad row would take every computation down with it; a table
that loaded the row anyway would compute from a figure nobody can stand behind.

An item is refused when:

- its source file is missing, or its bytes do not hash to the sidecar's SHA-256,
- the item's pinned SHA-256 is not the source's (the text changed after the item
  was written, so a person has to read the new text and re-pin it),
- its ``quote`` is not in the normalized source text,
- its ``figure`` does not parse to exactly its ``value``,
- its compliance date's quote is not in the source it cites,
- a RULE item cites a GUIDANCE source. Guidance is recorded, never computed from.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from atreides.customer_protection.rules.model import (
    RejectedItem,
    RuleItem,
    RuleItemSpec,
    RuleKind,
    RuleSource,
    RuleTable,
    SourceLabel,
)

__all__ = [
    "DEFAULT_SOURCES_DIR",
    "DEFAULT_TABLE_PATH",
    "FigureError",
    "load_rule_table",
    "normalize_text",
    "parse_figure",
]

RULES_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCES_DIR = RULES_DIR / "sources"
DEFAULT_TABLE_PATH = RULES_DIR / "table.json"

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_SPACE = re.compile(r"\s+")

# Unit conversions. These are arithmetic facts, not regulatory figures, which
# is why they live here and not in an engine: "percent" means per hundred and a
# year has twelve months whatever the rule says.
_PER_HUNDRED = Decimal(100)
_MONTHS_PER_YEAR = Decimal(12)
_SCALE = {"million": Decimal(10) ** 6, "billion": Decimal(10) ** 9}
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_NUMBER = r"(?P<whole>\d[\d,]*)?(?:\s*(?P<num>\d+)/(?P<den>\d+))?"
_PERCENT = re.compile(rf"^{_NUMBER}\s*(?:percent|%)$")
_FRACTION_OF_ONE = re.compile(r"^(?P<num>\d+)/(?P<den>\d+) of 1\s*(?:percent|%)$")
_USD = re.compile(r"^\$(?P<amount>\d[\d,]*)(?:\s+(?P<scale>million|billion))?$")
_DURATION = re.compile(rf"^{_NUMBER}\s+(?P<unit>months?|years?)$")
_DAYS = re.compile(r"^(?P<count>\d+|[a-z]+)\s+(?P<unit>calendar|business) days$")


class FigureError(ValueError):
    """A figure that does not read as its kind."""


def normalize_text(raw: bytes) -> str:
    """The text a quote is checked against: tags removed, entities decoded, spaces collapsed.

    Every tag becomes a space, so ``1<FR>1/2</FR>`` reads ``1 1/2``. Quotes in the
    table are written against this function's output, not against the raw markup.
    """
    text = raw.decode("utf-8")
    text = _SCRIPT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return _SPACE.sub(" ", text).strip()


def _number(match: re.Match[str]) -> Decimal:
    whole, num, den = match.group("whole"), match.group("num"), match.group("den")
    if whole is None and num is None:
        raise FigureError("no number")
    value = Fraction(int(whole.replace(",", ""))) if whole else Fraction(0)
    if num is not None and den is not None:
        value += Fraction(int(num), int(den))
    return Decimal(value.numerator) / Decimal(value.denominator)


def parse_figure(kind: RuleKind, figure: str) -> Decimal:
    """Read ``figure`` as ``kind``. Raises :class:`FigureError` if it does not read."""
    text = figure.strip()
    if kind is RuleKind.PERCENT:
        if match := _FRACTION_OF_ONE.match(text):
            return Decimal(int(match["num"])) / Decimal(int(match["den"])) / _PER_HUNDRED
        if match := _PERCENT.match(text):
            return _number(match) / _PER_HUNDRED
    elif kind is RuleKind.USD:
        if match := _USD.match(text):
            amount = Decimal(match["amount"].replace(",", ""))
            return amount * _SCALE[match["scale"]] if match["scale"] else amount
    elif kind is RuleKind.MONTHS:
        if match := _DURATION.match(text):
            count = _number(match)
            return count * _MONTHS_PER_YEAR if match["unit"].startswith("year") else count
    elif kind in (RuleKind.CALENDAR_DAYS, RuleKind.BUSINESS_DAYS):
        if (match := _DAYS.match(text)) and match["unit"] == kind.value.split("_")[0].lower():
            days: str = match["count"]
            if days.isdigit():
                return Decimal(int(days))
            if days in _WORDS:
                return Decimal(_WORDS[days])
    raise FigureError(f"{figure!r} does not read as {kind}")


def _load_source(sources_dir: Path, source_id: str, filename: str) -> tuple[RuleSource, str]:
    path = sources_dir / filename
    raw = path.read_bytes()
    sidecar = (sources_dir / f"{filename}.sha256").read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sidecar:
        raise ValueError(f"{filename}: bytes hash to {actual}, sidecar says {sidecar}")
    meta: dict[str, Any] = json.loads(
        (sources_dir / f"{filename}.meta.json").read_text(encoding="utf-8")
    )
    if meta["sha256"] != actual or meta["source_id"] != source_id:
        raise ValueError(f"{filename}: metadata does not describe this file")
    source = RuleSource(
        source_id=source_id,
        citation=meta["citation"],
        label=SourceLabel(meta["label"]),
        filename=filename,
        url=meta["url"],
        sha256=actual,
        retrieval_dtg=meta["retrieval_dtg"],
        ecfr_up_to_date_as_of=meta["ecfr_up_to_date_as_of"],
        latest_amendment_date=meta["latest_amendment_date"],
    )
    return source, normalize_text(raw)


def _check(
    spec: RuleItemSpec,
    sources: dict[str, tuple[RuleSource, str]],
) -> RuleItem:
    if spec.source_id not in sources:
        raise ValueError(f"source {spec.source_id} is not loaded")
    source, text = sources[spec.source_id]
    if source.label is not SourceLabel.RULE:
        raise ValueError(f"source {spec.source_id} is {source.label}, not rule text")
    if spec.sha256 != source.sha256:
        raise ValueError(
            f"pinned to {spec.sha256[:12]}, source is now {source.sha256[:12]}; "
            "re-read the text and re-pin"
        )
    if spec.quote not in text:
        raise ValueError(f"quote not found in {source.filename}: {spec.quote!r}")
    if spec.figure is not None and spec.value is not None:
        parsed = parse_figure(spec.kind, spec.figure)
        if parsed != spec.value:
            raise ValueError(f"figure {spec.figure!r} reads {parsed}, table says {spec.value}")
    if spec.compliance_source_id is not None:
        if spec.compliance_source_id not in sources:
            raise ValueError(f"compliance source {spec.compliance_source_id} is not loaded")
        _, compliance_text = sources[spec.compliance_source_id]
        if spec.compliance_quote is None or spec.compliance_quote not in compliance_text:
            raise ValueError(f"compliance quote not found: {spec.compliance_quote!r}")
    return RuleItem(
        id=spec.id,
        kind=spec.kind,
        citation=spec.citation,
        source_id=spec.source_id,
        source_file=source.filename,
        source_label=source.label,
        sha256=source.sha256,
        retrieval_dtg=source.retrieval_dtg,
        effective_date=source.latest_amendment_date,
        compliance_date=spec.compliance_date,
        quote=spec.quote,
        value=spec.value,
    )


def load_rule_table(
    table_path: Path = DEFAULT_TABLE_PATH,
    sources_dir: Path = DEFAULT_SOURCES_DIR,
) -> RuleTable:
    """Load and check the committed table. Never raises on a bad item; see the module docstring."""
    table_bytes = table_path.read_bytes()
    document: dict[str, Any] = json.loads(table_bytes)

    sources: dict[str, tuple[RuleSource, str]] = {}
    rejected: list[RejectedItem] = []
    for entry in document["sources"]:
        try:
            sources[entry["source_id"]] = _load_source(
                sources_dir, entry["source_id"], entry["filename"]
            )
        except (OSError, ValueError, KeyError) as exc:
            rejected.append(RejectedItem(id=f"source:{entry['source_id']}", reason=str(exc)))

    items: list[RuleItem] = []
    seen: set[str] = set()
    for row in document["items"]:
        rule_id = str(row.get("id", "<no id>"))
        try:
            spec = RuleItemSpec.model_validate(row)
            if spec.id in seen:
                raise ValueError("duplicate id")
            seen.add(spec.id)
            items.append(_check(spec, sources))
        except ValueError as exc:
            rejected.append(RejectedItem(id=rule_id, reason=str(exc)))

    return RuleTable(
        table_version=document["table_version"],
        table_digest="sha256:" + hashlib.sha256(table_bytes).hexdigest(),
        sources=tuple(source for source, _ in sources.values()),
        items=tuple(items),
        rejected=tuple(rejected),
    )
