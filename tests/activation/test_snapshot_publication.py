"""The activation snapshot is published from both ordered CI cadences."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
ACTION = "uses: ./.github/actions/publish-agents-snapshot"


def test_main_push_publishes_only_after_every_ci_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "github.event_name == 'push'" in workflow
    assert "needs: [test, lint, typecheck, probes]" in workflow
    assert ACTION in workflow


def test_nightly_publishes_only_after_the_deep_property_run() -> None:
    workflow = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    assert "needs: [deep-properties]" in workflow
    assert ACTION in workflow


def test_publication_uses_one_stable_generated_branch() -> None:
    action = (ROOT / ".github/actions/publish-agents-snapshot/action.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m atreides.activation.snapshot_writer" in action
    assert "HEAD:agents-snapshot" in action
    assert 'cp "$RUNNER_TEMP/agents.json" "$publish_dir/agents.json"' in action
