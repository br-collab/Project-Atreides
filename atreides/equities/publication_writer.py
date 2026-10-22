"""Write the deterministic EQ-1 Atreides publications."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from atreides.equities.scenario import build_equities_publications


def write_publications(directory: Path, *, taken_at: datetime) -> tuple[Path, ...]:
    documents = build_equities_publications(taken_at)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, payload in sorted(documents.items()):
        path = directory / name
        path.write_bytes(payload)
        paths.append(path)
    return tuple(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    write_publications(args.directory, taken_at=datetime.now(UTC))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
