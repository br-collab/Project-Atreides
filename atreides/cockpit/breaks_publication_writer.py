"""Write the complete synthetic break snapshot for the display-only COP."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from atreides.cockpit.break_scenarios import REQUIRED_BREAK_IDS, build_synthetic_records
from atreides.cockpit.breaks import BreakRecord
from atreides.cockpit.breaks_publication import BreaksPublication, records_digest

JSON_INDENT = len("  ")


def build_publication(records: tuple[BreakRecord, ...], *, taken_at: datetime) -> BreaksPublication:
    """Refuse a partial scenario set and return the validated publication."""
    actual = {record.break_id for record in records}
    if actual != REQUIRED_BREAK_IDS:
        missing = ", ".join(sorted(REQUIRED_BREAK_IDS - actual)) or "none"
        unexpected = ", ".join(sorted(actual - REQUIRED_BREAK_IDS)) or "none"
        raise ValueError(
            f"break snapshot is partial or unexpected, missing: {missing}; unexpected: {unexpected}"
        )
    return BreaksPublication(
        taken_at=taken_at,
        input_digest=records_digest(records),
        records=records,
    )


def publication_bytes(taken_at: datetime) -> bytes:
    publication = build_publication(build_synthetic_records(), taken_at=taken_at)
    return (publication.model_dump_json(indent=JSON_INDENT) + "\n").encode()


def write_publication(path: Path, *, taken_at: datetime) -> BreaksPublication:
    """Validate the complete document before creating or replacing the path."""
    raw = publication_bytes(taken_at)
    publication = BreaksPublication.model_validate_json(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return publication


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write synthetic break records as JSON.")
    parser.add_argument("path", type=Path, help="output JSON path")
    args = parser.parse_args(argv)
    write_publication(args.path, taken_at=datetime.now(UTC))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
