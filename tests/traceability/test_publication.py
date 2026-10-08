"""Acceptance tests for publishing only complete traceability evidence."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from atreides.traceability import RunScope, build_traceability, load_register
from atreides.traceability.publication_writer import write_publication

ROOT = Path(__file__).resolve().parents[2]
REGISTER_PATH = ROOT / "docs/requirements/register.json"
ACTION = ROOT / ".github/actions/publish-traceability-snapshot/action.yml"


def _source(path: Path, scope: RunScope) -> Path:
    document = build_traceability(
        load_register(REGISTER_PATH),
        {},
        {},
        run_scope=scope,
        run_commit_sha="a" * 40,
        run_timestamp="2026-10-08T12:00:00+00:00",
    )
    path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def test_partial_run_is_refused_without_replacing_the_destination(tmp_path: Path) -> None:
    destination = tmp_path / "published.json"
    destination.write_text("previous good snapshot\n", encoding="utf-8")
    with pytest.raises(ValueError, match="partial test run"):
        write_publication(_source(tmp_path / "partial.json", RunScope.PARTIAL), destination)
    assert destination.read_text(encoding="utf-8") == "previous good snapshot\n"


def test_full_run_is_published_with_advisory_labels(tmp_path: Path) -> None:
    destination = tmp_path / "published.json"
    document = write_publication(_source(tmp_path / "full.json", RunScope.FULL), destination)
    assert document.synthetic is True
    assert document.enforcement_status == "ADVISORY_ONLY"
    assert document.claim_label == "EXPERIMENTAL"
    assert destination.is_file()


def test_tampered_traceability_digest_is_refused(tmp_path: Path) -> None:
    source = _source(tmp_path / "tampered.json", RunScope.FULL)
    source.write_text(source.read_text(encoding="utf-8").replace("BR-01", "BR-99", 1))
    with pytest.raises(ValueError, match="digest"):
        write_publication(source, tmp_path / "published.json")


def test_action_publishes_the_ci_artifact_to_the_stable_branch() -> None:
    action = ACTION.read_text(encoding="utf-8")
    assert "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333" in action
    assert "atreides.traceability.publication_writer" in action
    assert "traceability-snapshot" in action
    assert "traceability.json" in action
    assert "diff --cached --quiet" in action


def test_main_publication_waits_for_every_required_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "publish-traceability-snapshot:" in workflow
    assert "needs: [test, lint, typecheck, probes]" in workflow
    assert "group: traceability-snapshot-publication" in workflow
    assert "uses: ./.github/actions/publish-traceability-snapshot" in workflow


def test_publication_runtime_does_not_require_the_pytest_development_extra() -> None:
    script = """
import builtins
original_import = builtins.__import__
def without_pytest(name, *args, **kwargs):
    if name == "pytest" or name.startswith("pytest."):
        raise ModuleNotFoundError("pytest deliberately unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_pytest
import atreides.traceability.publication_writer
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
