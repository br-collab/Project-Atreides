"""Validate and publish only full-run requirement traceability evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from atreides.traceability.emitter import (
    RunScope,
    TraceabilityDocument,
    traceability_digest,
    write_traceability,
)

__all__ = ["publication_bytes", "write_publication"]


def publication_bytes(source: Path) -> bytes:
    """Return normalized bytes only for intact evidence from a full test run."""
    document = TraceabilityDocument.model_validate_json(source.read_bytes())
    if document.run_scope is not RunScope.FULL:
        raise ValueError("partial test run cannot be published as requirement coverage")
    if document.digest != traceability_digest(document):
        raise ValueError("traceability digest does not match the document content")
    return (document.model_dump_json(indent=2) + "\n").encode()


def write_publication(source: Path, destination: Path) -> TraceabilityDocument:
    """Validate the complete source before creating or replacing the destination."""
    raw = publication_bytes(source)
    document = TraceabilityDocument.model_validate_json(raw)
    write_traceability(destination, document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish full-run traceability evidence as JSON.")
    parser.add_argument("source", type=Path, help="full-run traceability JSON")
    parser.add_argument("destination", type=Path, help="validated publication JSON")
    args = parser.parse_args(argv)
    write_publication(args.source, args.destination)
    return 0


if __name__ == "__main__":  # pragma: no cover, exercised through main
    raise SystemExit(main())
