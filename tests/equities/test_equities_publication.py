from datetime import UTC, datetime

from atreides.equities.publication_writer import write_publications


def test_publication_writes_all_documents(tmp_path) -> None:
    paths = write_publications(tmp_path, taken_at=datetime(2026, 10, 22, 14, tzinfo=UTC))
    assert len(paths) == 5
    assert all(path.read_bytes().endswith(b"\n") for path in paths)


def test_ci_publishes_only_after_all_gates() -> None:
    workflow = open(".github/workflows/ci.yml", encoding="utf-8").read()
    action = open(".github/actions/publish-equities-snapshot/action.yml", encoding="utf-8").read()
    assert "needs: [test, lint, typecheck, probes]" in workflow
    assert "equities-snapshot" in action
