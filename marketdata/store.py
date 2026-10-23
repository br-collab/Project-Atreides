from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from marketdata.catalog import ADMITTED_HOSTS, classify_url, resolve_source
from marketdata.model import Source, StorePaths

DEFAULT_ROOT = Path.home() / "Data" / "cfma-data"
CHUNK_SIZE = 1024 * 1024
MINIMUM_FREE_FRACTION = 0.10
_RAW_NAME = re.compile(r"^[0-9a-f]{64}\.[A-Za-z0-9.]+(?:\.metadata\.json)?$")


class _AdmittedRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: IO[bytes],
        code: int,
        message: str,
        headers: HTTPMessage,
        new_url: str,
    ) -> Request | None:
        parsed = urlparse(new_url)
        host = (parsed.hostname or "").lower()
        if host not in ADMITTED_HOSTS or (
            host == "www.sec.gov" and "/edgar/" in parsed.path.lower()
        ):
            raise ValueError(f"redirect host refused before fetch: {host or '<missing>'}")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


_OPENER = build_opener(_AdmittedRedirect())


def _open(request: Request, timeout: int) -> Any:
    return _OPENER.open(request, timeout=timeout)


def store_paths(root: Path | None = None) -> StorePaths:
    return StorePaths((root or Path(os.getenv("CFMA_DATA_ROOT", DEFAULT_ROOT))).resolve())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _log(paths: StorePaths, event: dict[str, object]) -> None:
    paths.runs.mkdir(parents=True, exist_ok=True)
    target = paths.runs / "events.jsonl"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def _quarantine_interrupted_raw(paths: StorePaths) -> None:
    """Move interrupted/foreign raw names aside before any run can count or use them."""
    for path in sorted(candidate for candidate in paths.raw.rglob("*") if candidate.is_file()):
        relative = path.relative_to(paths.raw)
        valid = len(relative.parts) == 2 and bool(_RAW_NAME.fullmatch(relative.name))
        if valid:
            continue
        digest = hashlib.sha256(str(relative).encode()).hexdigest()[:12]
        destination = paths.quarantine / f"raw-startup-{digest}-{path.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, destination)
        _log(
            paths,
            {
                "event": "raw_startup_quarantine",
                "path": str(relative),
                "reason": "raw name is not <source-id>/<digest>.<suffix> or its metadata",
                "at": datetime.now(UTC).isoformat(),
            },
        )


def store_usage(paths: StorePaths) -> dict[str, object]:
    """Return auditable store bytes by zone and raw source."""
    zones = {
        name: sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
        for name, directory in {
            "00_raw": paths.raw,
            "10_normalized": paths.normalized,
            "20_curated": paths.packs.parent,
            "quarantine": paths.quarantine,
            "catalog": paths.catalog,
            "40_runs": paths.runs,
        }.items()
    }
    sources = {
        directory.name: sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
        for directory in sorted(paths.raw.iterdir())
        if directory.is_dir()
    }
    return {"zones": zones, "raw_sources": sources}


def _ensure_free_space(paths: StorePaths, incoming_bytes: int) -> None:
    usage = shutil.disk_usage(paths.root)
    minimum_free = int(usage.total * MINIMUM_FREE_FRACTION)
    if usage.free - incoming_bytes < minimum_free:
        raise ValueError(
            "ingest refused: fetch would leave the volume below 10 percent free "
            f"(free={usage.free}, incoming={incoming_bytes}, required_free={minimum_free})"
        )


def initialize(root: Path | None = None) -> StorePaths:
    paths = store_paths(root)
    paths.create()
    _quarantine_interrupted_raw(paths)
    package_root = Path(__file__).parent
    catalog_files = [package_root / "sources.yaml", package_root / "pack-locks.json"]
    catalog_files.extend(sorted((package_root / "schemas").glob("*.json")))
    manifest: dict[str, str] = {}
    for source in catalog_files:
        target = paths.catalog / source.name
        shutil.copy2(source, target)
        manifest[source.name] = _sha256(target)
    (paths.catalog / "manifest.json").write_text(
        json.dumps(
            {"schema_version": "cfma.catalog-manifest/1", "files": manifest},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _log(
        paths,
        {
            "event": "store_status",
            "at": datetime.now(UTC).isoformat(),
            **store_usage(paths),
        },
    )
    return paths


def ingest(
    source_id: str,
    *,
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> Path:
    paths = initialize(root)
    _ensure_free_space(paths, 0)
    try:
        source = (
            resolve_source(source_id)
            if catalog_path is None
            else resolve_source(source_id, catalog_path=catalog_path)
        )
        # Reclassification by the exact URL makes file-supplied class claims irrelevant.
        classify_url(source.url) if catalog_path is None else classify_url(
            source.url, catalog_path=catalog_path
        )
    except Exception as error:
        _log(
            paths,
            {
                "event": "ingest_refused",
                "source_id": source_id,
                "reason": str(error),
                "at": datetime.now(UTC).isoformat(),
            },
        )
        raise
    request = Request(source.url, headers={"User-Agent": "CFMA-DATA-1/1.0 public-data research"})
    temporary: Path | None = None
    try:
        with _open(request, timeout=60) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                _ensure_free_space(paths, int(declared))
            with tempfile.NamedTemporaryFile(dir=paths.raw, delete=False) as target:
                temporary = Path(target.name)
                total = 0
                while chunk := response.read(CHUNK_SIZE):
                    total += len(chunk)
                    _ensure_free_space(paths, total)
                    target.write(chunk)
        digest = _sha256(temporary)
        suffix = Path(source.url.split("?", 1)[0]).suffix or ".bin"
        destination = paths.raw / source.source_id / f"{digest}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary.unlink()
        else:
            temporary.replace(destination)
        metadata = {
            "schema_version": "cfma.raw/1",
            "source_id": source.source_id,
            "source_url": source.url,
            "citation": source.citation,
            "license_class": source.license_class,
            "ny_fed_notice": source.ny_fed_notice,
            "sha256": digest,
            "bytes": destination.stat().st_size,
            "fetched_at": datetime.now(UTC).isoformat(),
            "validation_status": "raw",
        }
        metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
        if not metadata_path.exists():
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        _log(paths, {"event": "ingest", **metadata})
        return destination
    except Exception as error:
        if temporary is not None and temporary.exists():
            quarantine = paths.quarantine / f"ingest-{source_id}-{temporary.name}.failed"
            shutil.move(temporary, quarantine)
        _log(
            paths,
            {
                "event": "ingest_refused",
                "source_id": source_id,
                "reason": str(error),
                "at": datetime.now(UTC).isoformat(),
            },
        )
        raise


def latest_raw(source: Source, paths: StorePaths) -> Path:
    candidates = sorted(
        path
        for path in (paths.raw / source.source_id).glob("*")
        if not path.name.endswith(".metadata.json")
    )
    if not candidates:
        raise ValueError(f"no raw file for source: {source.source_id}")
    return candidates[-1]


def digest_file(path: Path) -> str:
    return _sha256(path)
