"""Refuse fixture values shaped like common real personal or financial identifiers."""

import re
from pathlib import Path


def test_fixtures_do_not_contain_real_identifier_shapes() -> None:
    patterns = {
        "Social Security number": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
        "passport number": re.compile(r'(?i)passport[^\n]{0,24}["\': ]+[A-Z0-9]{6,9}'),
        "bank account number": re.compile(
            r'(?i)(?:bank|account)[_-]?number[^\n]{0,16}["\': ]+\d{8,17}'
        ),
    }
    fixture_roots = (Path("tests/fixtures"), Path("simulator/publication"))
    findings: list[str] = []
    for root in fixture_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for label, pattern in patterns.items():
                if pattern.search(text):
                    findings.append(f"{path}: value shaped like a real {label}")
    assert not findings, "\n".join(findings)
