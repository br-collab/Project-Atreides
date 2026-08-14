"""Emit ``docs/DATA-DICTIONARY.md`` from the models and the actual DDL.

Generated rather than written, and the reason is the same reason every
registry in this framework flags rather than defaults: **a hand-maintained
data dictionary drifts silently, and a data dictionary nobody can trust is
worse than none at all.** A reviewer who finds one stale field stops
believing the other four hundred.

So the source of truth is the code. Field names, types, optionality and
descriptions come from the Pydantic models. The persistence section reads
the DDL constants out of ``atreides.dsor.store`` rather than restating them.
``tests/test_data_dictionary.py`` regenerates and compares, so a model change
that is not reflected here fails the build.

Run: ``python3 tools/gen_data_dictionary.py``
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import re
import sys
import textwrap
from enum import Enum
from typing import Any

from pydantic import BaseModel

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUTPUT = REPO / "docs" / "DATA-DICTIONARY.md"

#: Modules surveyed, grouped as a reviewer would want to read them.
SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Decision of record",
        "The append-only lineage record and the union of agent outputs it "
        "wraps. This is the only thing that persists.",
        ("atreides.dsor.record",),
    ),
    (
        "Settlement rails",
        "How money and securities actually move, and what the framework is "
        "willing to assert about each.",
        (
            "atreides.rails.finality",
            "atreides.rails.cato_f",
            "atreides.rails.funding_state",
            "atreides.rails.determination",
            "atreides.rails.cns",
        ),
    ),
    (
        "Contracts",
        "The typed substrate for custody operations, and the economic "
        "attributes attached to a break.",
        (
            "atreides.contracts.asset_class",
            "atreides.contracts.custody_object",
            "atreides.contracts.failure_mode",
            "atreides.contracts.margin_impact",
            "atreides.contracts.margin_profile",
            "atreides.contracts.quorum",
        ),
    ),
    (
        "Messaging",
        "The canonical instruction, the emitted artifact, and the venue's "
        "answer coming back.",
        (
            "atreides.messaging.canonical",
            "atreides.messaging.profile",
            "atreides.messaging.emit",
            "atreides.messaging.readback",
        ),
    ),
)


def _is_local(obj: Any, module_name: str) -> bool:
    return getattr(obj, "__module__", None) == module_name


def _member_docs(enum_cls: type[Enum]) -> dict[str, str]:
    """Recover enum member docstrings from source.

    Python discards a string expression following a member assignment, so
    ``Member.__doc__`` falls back to the class docstring and the per-member
    prose - which is the most valuable content in this framework's enums,
    because that is where the reasoning for each disposition lives - is
    invisible at runtime. Reading the AST is the only way to get it, and
    losing it would make this document a list of names.
    """
    try:
        source = inspect.getsource(enum_cls)
    except (OSError, TypeError):  # pragma: no cover
        return {}

    tree = ast.parse(textwrap.dedent(source))
    class_def = tree.body[0]
    if not isinstance(class_def, ast.ClassDef):  # pragma: no cover
        return {}

    # Two documentation styles are in use across the codebase: a string
    # expression after the assignment, and a run of `#:` comment lines
    # before it. Both are read, because picking one would silently drop
    # half the enums.
    docs: dict[str, str] = {}
    lines = textwrap.dedent(source).splitlines()
    buffer: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("#:"):
            buffer.append(stripped[2:].strip())
            continue
        match = re.match(r"^([A-Z_][A-Z0-9_]*)\s*[:=]", stripped)
        if match and buffer:
            docs[match.group(1)] = " ".join(buffer)
        buffer = []

    pending: str | None = None
    for node in class_def.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            pending = node.targets[0].id
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and pending is not None
        ):
            docs[pending] = node.value.value
            pending = None
        else:
            pending = None
    return docs


def _enum_rows(enum_cls: type[Enum]) -> str:
    docs = _member_docs(enum_cls)
    lines = ["| Value | Meaning |", "| --- | --- |"]
    for member in enum_cls:
        doc = docs.get(member.name, "")
        if not doc:
            # A member with no docstring of its own inherits the class
            # docstring; that is noise here and is dropped rather than
            # repeated on every row.
            runtime = (member.__doc__ or "").strip()
            if runtime != (enum_cls.__doc__ or "").strip():
                doc = runtime
        lines.append(f"| `{member.value}` | {_flatten(doc)} |")
    return "\n".join(lines)


def _flatten(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _model_rows(model: type[BaseModel]) -> str:
    lines = ["| Field | Type | Required | Notes |", "| --- | --- | --- | --- |"]
    for name, info in model.model_fields.items():
        annotation = info.annotation
        type_name = getattr(annotation, "__name__", None) or _flatten(str(annotation))
        type_name = type_name.replace("atreides.", "")
        required = "yes" if info.is_required() else "no"
        note = _flatten(info.description or "")
        lines.append(f"| `{name}` | `{type_name}` | {required} | {note} |")
    return "\n".join(lines)


def _dataclass_rows(cls: type) -> str:
    lines = ["| Field | Type | Default |", "| --- | --- | --- |"]
    for name, f in cls.__dataclass_fields__.items():  # type: ignore[attr-defined]
        type_name = _flatten(str(f.type)).replace("atreides.", "")
        has_default = f.default is not inspect.Parameter.empty and repr(
            f.default
        ) not in ("<dataclasses._MISSING_TYPE object>",)
        default = f"`{f.default!r}`" if has_default else "required"
        if "_MISSING_TYPE" in default:
            default = "required"
        lines.append(f"| `{name}` | `{type_name}` | {default} |")
    return "\n".join(lines)


def _render_module(module_name: str) -> str:
    module = importlib.import_module(module_name)
    out: list[str] = []
    exported = getattr(module, "__all__", None)

    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        if exported is not None and name not in exported:
            continue
        obj = getattr(module, name)
        if not inspect.isclass(obj) or not _is_local(obj, module_name):
            continue

        doc = _flatten((obj.__doc__ or "").split("\n\n")[0])

        if issubclass(obj, Enum):
            out.append(f"#### `{name}` (enumeration)\n\n{doc}\n\n{_enum_rows(obj)}\n")
        elif issubclass(obj, BaseModel):
            out.append(f"#### `{name}`\n\n{doc}\n\n{_model_rows(obj)}\n")
        elif hasattr(obj, "__dataclass_fields__"):
            out.append(f"#### `{name}`\n\n{doc}\n\n{_dataclass_rows(obj)}\n")

    return "\n".join(out)


def _persistence_section() -> str:
    # Local: `atreides` is not importable until the sys.path bootstrap above
    # has run, which happens after the module-level import block.
    from atreides.dsor import store

    ddl = store._CREATE_TABLE.strip()
    index = store._CREATE_PARTIAL_INDEX.strip()
    return f"""## Persistence

One table. Everything else in this document describes objects that live in
memory for the duration of a decision and are then serialised into
`payload`.

```sql
{ddl}
```

```sql
{index}
```

**Read this before designing anything downstream.** The partial index is the
append-only guarantee: at most one non-correction record may exist per
`operation_id`, and a correction is a *new row* carrying `correction_of`
rather than an update. Nothing in the store issues an `UPDATE` or a `DELETE`.

**And read this before promising anyone a query.** `payload` is a JSON
document, not a normalised schema, so `dsor_records` is queryable by
`record_id`, `operation_id`, `dtg`, `kind` and correction lineage, and by
nothing else without unpacking JSON. That is a deliberate trade and it is
worth stating plainly rather than discovering: replay fidelity was chosen
over queryability, because a lineage record that has been decomposed into
columns can no longer be proved byte-for-byte identical to the output it
recorded, and byte-for-byte replay is the property the whole framework is
sold on.

The consequence for a data engineer is that analytics belong in a
**projection** built from this table, never in this table. A projection may
be rebuilt from the lineage at any time; the lineage may never be rebuilt
from a projection.
"""


def _coverage() -> tuple[int, int, list[str]]:
    """Count enum members that state what they mean, and name those that do not.

    Emitted rather than hidden. A blank cell in a generated table reads as a
    tooling failure; a counted gap reads as work. And the gap is real: an
    enum member with no stated meaning is a value a downstream consumer has
    to guess at, which is the same defect as an unattributed registry entry.
    """
    documented = total = 0
    missing: list[str] = []
    for _title, _blurb, modules in SECTIONS:
        for module_name in modules:
            module = importlib.import_module(module_name)
            exported = getattr(module, "__all__", None)
            for name in sorted(dir(module)):
                if name.startswith("_"):
                    continue
                if exported is not None and name not in exported:
                    continue
                obj = getattr(module, name)
                if not (
                    inspect.isclass(obj)
                    and _is_local(obj, module_name)
                    and issubclass(obj, Enum)
                ):
                    continue
                docs = _member_docs(obj)
                for member in obj:
                    total += 1
                    if docs.get(member.name):
                        documented += 1
                    else:
                        missing.append(f"{module_name.split('.')[-1]}.{name}.{member.name}")
    return documented, total, missing


def render() -> str:
    documented, total, missing = _coverage()
    pct = round(100 * documented / total) if total else 0
    missing_block = "\n".join(f"- `{m}`" for m in missing)

    coverage_section = f"""## Documentation coverage

**{documented} of {total} enumeration values ({pct}%) state what they mean in
source.** The remainder are listed below rather than rendered as blank cells,
because a blank cell in a generated table reads as a tooling failure and a
counted gap reads as work.

The gap is not cosmetic. An enumeration value with no stated meaning is a
value a downstream consumer has to guess at, which is the same defect as an
unattributed registry entry - and the guess will be made by whoever is
furthest from the decision.

<details>
<summary>Values with no stated meaning ({len(missing)})</summary>

{missing_block}

</details>
"""

    parts: list[str] = [
        "# Data Dictionary",
        "",
        "*Generated by `tools/gen_data_dictionary.py`. Do not edit by hand -*",
        "*`tests/test_data_dictionary.py` fails when this file drifts from the*",
        "*models it describes.*",
        "",
        "Written for a reviewer who has not read the code: every persisted and",
        "in-memory structure, its fields, and what each one is for. Terminology",
        "is defined in [`GLOSSARY.md`](GLOSSARY.md).",
        "",
        "---",
        "",
        coverage_section,
        "---",
        "",
        _persistence_section(),
        "---",
        "",
    ]

    for title, blurb, modules in SECTIONS:
        parts.append(f"## {title}\n\n{blurb}\n")
        for module_name in modules:
            rendered = _render_module(module_name)
            if not rendered.strip():
                continue
            parts.append(f"### `{module_name}`\n")
            parts.append(rendered)
        parts.append("---\n")

    return "\n".join(parts).rstrip() + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
