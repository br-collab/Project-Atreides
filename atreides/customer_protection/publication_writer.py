"""Write the current synthetic advisory publication for the display-only COP."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from cannae_kernel.disposition import Disposition

from atreides.customer_protection.publication import AdvisoryPublication
from atreides.customer_protection.scenarios import build_publication

REQUIRED_DISPOSITIONS = frozenset(
    {Disposition.PASS, Disposition.HOLD, Disposition.INDETERMINATE}
)


def publication_bytes(taken_at: datetime) -> bytes:
    """Return deterministic bytes after proving all required outcomes exist."""
    publication = build_publication(taken_at)
    actual = {
        advisory.disposition
        for scenario in publication.scenarios
        for advisory in scenario.advisories
    }
    if not REQUIRED_DISPOSITIONS <= actual:
        missing = ", ".join(sorted(item.value for item in REQUIRED_DISPOSITIONS - actual))
        raise ValueError(f"synthetic scenarios did not yield required dispositions: {missing}")
    return (publication.model_dump_json(indent=2) + "\n").encode()


def write_publication(path: Path, *, taken_at: datetime) -> AdvisoryPublication:
    """Validate the document completely before creating or replacing ``path``."""
    raw = publication_bytes(taken_at)
    publication = AdvisoryPublication.model_validate_json(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return publication


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write synthetic customer protection advisories as JSON."
    )
    parser.add_argument("path", type=Path, help="output JSON path")
    args = parser.parse_args(argv)
    write_publication(args.path, taken_at=datetime.now(UTC))
    return 0


if __name__ == "__main__":  # pragma: no cover, exercised through main
    raise SystemExit(main())
