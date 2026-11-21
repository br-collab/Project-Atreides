"""Refuse fixture values shaped like common real personal or financial identifiers."""

import re
from pathlib import Path


def scan_real_identifier_shapes(roots: tuple[Path, ...]) -> tuple[str, ...]:
    patterns = {
        "Social Security number": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
        "passport number": re.compile(r'(?i)passport[^\n]{0,24}["\': ]+[A-Z0-9]{6,9}'),
        "bank account number": re.compile(
            r'(?i)(?:bank|account)[_-]?number[^\n]{0,16}["\': ]+\d{8,17}'
        ),
    }
    findings: list[str] = []
    for root in roots:
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
    return tuple(findings)


def test_fixtures_do_not_contain_real_identifier_shapes() -> None:
    findings = scan_real_identifier_shapes(
        (Path("tests/fixtures"), Path("simulator/publication"))
    )
    assert not findings, "\n".join(findings)


def test_fixture_check_refuses_social_security_number_shape(tmp_path: Path) -> None:
    fixture = tmp_path / "synthetic-attack.json"
    fixture.write_text('{"tax_token":"' + "123" + "-" + "45" + "-" + "6789" + '"}')
    findings = scan_real_identifier_shapes((tmp_path,))
    assert len(findings) == 1
    assert findings[0].endswith("value shaped like a real Social Security number")
