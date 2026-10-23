"""Refuse real instrument identifiers at the calibration boundary."""

from __future__ import annotations

import re

IDENTIFIER_NAME = re.compile(
    r"(?:^|_)(?:cusip|figi|ticker|issuer(?:_name)?)(?:$|_)", re.IGNORECASE
)
FIGI_VALUE = re.compile(r"^BBG[0-9A-Z]{9}$")
TICKER_VALUE = re.compile(r"^(?:ticker\s*[:=]\s*|\$)[A-Z][A-Z0-9.\-]{0,9}$", re.IGNORECASE)
_CUSIP_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*@#"


def _is_cusip(value: str) -> bool:
    text = value.upper()
    if len(text) != 9 or any(character not in _CUSIP_CHARS for character in text):
        return False
    total = 0
    for index, character in enumerate(text[:8]):
        number = _CUSIP_CHARS.index(character)
        if index % 2:
            number *= 2
        total += number // 10 + number % 10
    return text[8].isdigit() and (10 - total % 10) % 10 == int(text[8])


def identifier_kind(value: str) -> str | None:
    """Return the identifier shape carried by ``value``, if any."""
    text = value.strip()
    if _is_cusip(text):
        return "CUSIP"
    if FIGI_VALUE.fullmatch(text.upper()):
        return "FIGI"
    if TICKER_VALUE.fullmatch(text):
        return "ticker"
    return None


def refuse_identifiers(value: object, trail: str = "input") -> None:
    """Scan keys and values recursively; names alone are not sufficient evidence."""
    if isinstance(value, dict):
        for key, child in value.items():
            if IDENTIFIER_NAME.search(str(key)):
                raise ValueError(f"forbidden identifier-shaped key {trail}.{key}")
            kind = identifier_kind(str(key))
            if kind:
                raise ValueError(f"forbidden {kind}-shaped key {trail}.{key}")
            refuse_identifiers(child, f"{trail}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            refuse_identifiers(child, f"{trail}[{index}]")
    elif isinstance(value, str):
        kind = identifier_kind(value)
        if kind:
            raise ValueError(f"forbidden {kind}-shaped value at {trail}")
