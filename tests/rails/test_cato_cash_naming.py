"""The cash gate has one public identity: Cato Cash (``cato_cash``)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cato_cash_is_the_only_operational_identity() -> None:
    retired_module = "cato" + "_f"
    retired_class = "Cato" + "FDecision"
    retired_label = "CATO" + "-F"
    excluded = {ROOT / "CHANGELOG.md"}
    excluded.update((ROOT / "doctrine").glob("**/*"))

    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        ignored_parts = {".git", ".venv", ".uv-cache"}
        if not path.is_file() or path in excluded or ignored_parts & set(path.parts):
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(name in text for name in (retired_module, retired_class, retired_label)):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], f"retired cash-gate identity remains in: {offenders}"
    assert (ROOT / "atreides/rails/cato_cash.py").is_file()
    assert not (ROOT / f"atreides/rails/{retired_module}.py").exists()
