"""Structural guardrails for simulator evidence required by PHASE-2 rule zero."""

from __future__ import annotations

import ast
from pathlib import Path

SIMULATOR = Path(__file__).parents[2] / "simulator"


def _functions() -> list[ast.FunctionDef]:
    functions: list[ast.FunctionDef] = []
    for path in SIMULATOR.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        functions.extend(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    return functions


def test_attacks_and_mutations_rerun_the_target() -> None:
    candidates = [
        function
        for function in _functions()
        if function.name.startswith(("attack_", "mutate_"))
    ]
    assert candidates
    for function in candidates:
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        target = function.name.removeprefix("attack_").removeprefix("mutate_")
        target = target.removesuffix("_run")
        assert f"run_{target}" in calls, function.name


def test_invariant_expressions_are_not_relabelled_copies() -> None:
    invariant_dicts: list[ast.Dict] = []
    for function in _functions():
        invariant_dicts.extend(
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Dict)
            and any(
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value.startswith("I")
                for key in node.keys
            )
        )
    assert invariant_dicts
    for mapping in invariant_dicts:
        expressions = [
            ast.dump(value, include_attributes=False)
            for key, value in zip(mapping.keys, mapping.values, strict=True)
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and key.value.startswith("I")
        ]
        assert len(expressions) == len(set(expressions))
