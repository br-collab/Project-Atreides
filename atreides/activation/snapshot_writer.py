"""Write one current agent-activation snapshot for the Common Operating Picture.

The command runs the existing Phase A runners once and writes the resulting
value.  It does not start a server or a long-lived agent process; scheduling and
publication belong to the caller.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from atreides.activation.runners import default_runners
from atreides.activation.snapshot import ActivationSnapshot, build_snapshot
from atreides.activation.supervisor import AgentSupervisor


def take_snapshot(*, taken_at: datetime) -> ActivationSnapshot:
    """Run one advisory tick and return the value observed at ``taken_at``."""
    supervisor = AgentSupervisor(runners=default_runners())
    state = supervisor.tick(taken_at)
    return build_snapshot(state, taken_at=taken_at)


def write_snapshot(path: Path, *, taken_at: datetime) -> ActivationSnapshot:
    """Write a snapshot as JSON and return the value that was written."""
    snapshot = take_snapshot(taken_at=taken_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the current Atreides agent-activation snapshot as JSON."
    )
    parser.add_argument("path", type=Path, help="output JSON path")
    args = parser.parse_args(argv)
    write_snapshot(args.path, taken_at=datetime.now(UTC))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
