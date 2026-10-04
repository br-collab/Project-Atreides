"""Static checks over the source of ``atreides.customer_protection``.

- No float anywhere: no float annotation, no float literal, no use of the ``float`` builtin.
- No regulatory figure outside the rule table: no numeric literal other than 0 and 1
  in any engine module, and no ``Decimal("...")`` built from a string, which would
  be the same figure in disguise.
- No import of aureon or L.C. (Legiones Cannenses), and no network library.

Every module is scanned except :mod:`atreides.customer_protection.rules.loader`
for the literal check only: it converts units (per hundred, twelve months a year,
number words), which are arithmetic rather than regulation. It is still scanned
for floats and imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import atreides.customer_protection as package

PACKAGE = Path(package.__file__).resolve().parent
MODULES = sorted(PACKAGE.rglob("*.py"))
LITERAL_EXEMPT = {PACKAGE / "rules" / "loader.py"}
FORBIDDEN_IMPORTS = ("aureon", "lc", "legiones_cannenses", "harness_c2")
NETWORK_IMPORTS = ("urllib", "http", "socket", "requests", "httpx", "aiohttp", "ssl")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(PACKAGE)) for p in paths]


def test_the_scan_sees_the_package() -> None:
    assert PACKAGE / "rules" / "loader.py" in MODULES
    assert PACKAGE / "common.py" in MODULES


def float_uses(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            found.append(f"float literal {node.value!r} at line {node.lineno}")
        elif isinstance(node, ast.Name) and node.id == "float":
            found.append(f"float builtin at line {node.lineno}")
        elif isinstance(node, ast.Attribute) and node.attr == "float":
            found.append(f"float attribute at line {node.lineno}")
        elif isinstance(node, ast.Constant) and node.value == "float":
            found.append(f"float in a string annotation at line {node.lineno}")
    return found


def figure_literals(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | complex)
            and not isinstance(node.value, bool)
            and node.value not in (0, 1)
        ):
            found.append(f"numeric literal {node.value!r} at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Decimal"
            and any(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args)
        ):
            found.append(f"Decimal built from a string at line {node.lineno}")
    return found


def imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("path", MODULES, ids=_ids(MODULES))
def test_no_float(path: Path) -> None:
    assert float_uses(_tree(path)) == []


@pytest.mark.parametrize(
    "path", [p for p in MODULES if p not in LITERAL_EXEMPT], ids=_ids(
        [p for p in MODULES if p not in LITERAL_EXEMPT]
    )
)
def test_no_regulatory_figure_outside_the_table(path: Path) -> None:
    assert figure_literals(_tree(path)) == []


@pytest.mark.parametrize("path", MODULES, ids=_ids(MODULES))
def test_no_import_of_aureon_lc_or_the_network(path: Path) -> None:
    for name in imports(_tree(path)):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_IMPORTS, f"{path.name} imports {name}"
        assert root not in NETWORK_IMPORTS, f"{path.name} imports {name}"


def test_no_module_imports_the_dsor_record_union() -> None:
    """The DSOR (Decision System of Record) imports this package, never the reverse."""
    for path in MODULES:
        assert "atreides.dsor.record" not in imports(_tree(path)), path.name
        assert "atreides.dsor" not in imports(_tree(path)), path.name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x: float = 0", 1),
        ("x = 0.5", 1),
        ("import numpy\nx = numpy.float", 1),
        ("x: 'float'", 1),
        ("x = 1", 0),
    ],
)
def test_the_float_scan_catches_what_it_claims(source: str, expected: int) -> None:
    assert len(float_uses(ast.parse(source))) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = 250000", 1),
        ("x = Decimal('0.03')", 1),
        ("x = Decimal(0) + Decimal(1)", 0),
        ("x = True", 0),
        ("x = y[0]", 0),
    ],
)
def test_the_literal_scan_catches_what_it_claims(source: str, expected: int) -> None:
    assert len(figure_literals(ast.parse(source))) == expected


def test_the_import_scan_sees_both_import_forms() -> None:
    assert imports(ast.parse("import aureon.x\nfrom lc import y\nfrom . import z")) == [
        "aureon.x",
        "lc",
    ]
