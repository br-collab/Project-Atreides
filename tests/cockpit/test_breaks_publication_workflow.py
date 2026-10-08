"""Acceptance tests for publishing the synthetic break document."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/publish-breaks-snapshot/action.yml"
ACTION_USE = "uses: ./.github/actions/publish-breaks-snapshot"


def test_breaks_action_writes_and_publishes_only_changed_bytes() -> None:
    action = ACTION.read_text(encoding="utf-8")
    assert "atreides.cockpit.breaks_publication_writer" in action
    assert "breaks-snapshot" in action
    assert "breaks.json" in action
    assert "diff --cached --quiet" in action


def test_push_publication_waits_for_every_required_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "publish-breaks-snapshot:" in workflow
    assert "needs: [test, lint, typecheck, probes]" in workflow
    assert "group: breaks-snapshot-publication" in workflow
    assert ACTION_USE in workflow


def test_nightly_publication_waits_for_deep_properties() -> None:
    workflow = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    assert "publish-breaks-snapshot:" in workflow
    assert "needs: [deep-properties]" in workflow
    assert "group: breaks-snapshot-publication" in workflow
    assert ACTION_USE in workflow
