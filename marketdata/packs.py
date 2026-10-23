from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from marketdata.catalog import classify_url
from marketdata.model import StorePaths
from marketdata.normalize import validate_rows
from marketdata.store import digest_file, initialize
from simulator.calibration.identifiers import refuse_identifiers
from simulator.calibration.loader import DEFAULT_PACK, load_calibration_pack


def _metadata(path: Path) -> dict[str, Any]:
    metadata_path = path.with_suffix(".metadata.json")
    if not metadata_path.exists():
        raise ValueError(f"normalized metadata absent: {path.name}")
    return cast(dict[str, Any], json.loads(metadata_path.read_text()))


def build_pack(
    pack_id: str,
    version: str,
    inputs: list[Path],
    *,
    root: Path | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Path:
    paths = initialize(root)
    if not inputs:
        raise ValueError("build-pack requires at least one normalized input")
    synthetic = load_calibration_pack(DEFAULT_PACK)
    calibration_inputs: list[dict[str, object]] = [
        {
            "input_id": item.input_id,
            "source_url": item.source_url,
            "citation": item.citation,
            "license_class": item.license_class,
            **({"ny_fed_notice": item.ny_fed_notice} if item.ny_fed_notice else {}),
            "values": item.values,
        }
        for item in synthetic.inputs
    ]
    for path in inputs:
        metadata = _metadata(path)
        source = classify_url(str(metadata.get("source_url", "")))
        mismatches = {
            "source_id": (metadata.get("source_id"), source.source_id),
            "license_class": (metadata.get("license_class"), source.license_class),
            "ny_fed_notice": (metadata.get("ny_fed_notice"), source.ny_fed_notice),
        }
        wrong = [name for name, (sidecar, catalog) in mismatches.items() if sidecar != catalog]
        if wrong:
            raise ValueError(
                f"build-pack sidecar/catalog mismatch for {path.name}: {', '.join(wrong)}"
            )
        table = pq.read_table(path)
        rows = table.to_pylist()
        refuse_identifiers(rows, path.name)
        selected = sorted(
            (
                row
                for row in rows
                if (start is None or date.fromisoformat(str(row["date"])) >= start)
                and (end is None or date.fromisoformat(str(row["date"])) <= end)
            ),
            key=lambda row: (str(row["date"]), str(row["metric"])),
        )
        if not selected:
            raise ValueError(f"build-pack date window has no rows: {path.name}")
        validation_errors = validate_rows(selected)
        if validation_errors:
            raise ValueError(
                f"build-pack revalidation failed for {path.name}: " + "; ".join(validation_errors)
            )
        source_id = source.source_id
        calibration_inputs.append(
            {
                "input_id": source_id,
                "source_url": source.url,
                "citation": f"{source_id}; raw sha256:{metadata['raw_sha256']}",
                "license_class": source.license_class,
                **({"ny_fed_notice": source.ny_fed_notice} if source.ny_fed_notice else {}),
                "values": {
                    "observations": [
                        {
                            "date": str(row["date"]),
                            "metric": str(row["metric"]),
                            "value": str(row["value"]),
                            "unit": str(row["unit"]),
                        }
                        for row in selected
                    ]
                },
            }
        )
    destination = paths.packs / pack_id / version
    if destination.exists():
        raise ValueError(f"pack is immutable and already exists: {pack_id}/{version}")
    destination.mkdir(parents=True)
    calibration_path = destination / "calibration.json"
    calibration_path.write_text(
        json.dumps({"inputs": calibration_inputs}, indent=2, sort_keys=True) + "\n"
    )
    manifest = {
        "schema_version": "cfma.calibration-manifest/1",
        "pack_id": pack_id,
        "version": version,
        "files": {"calibration.json": digest_file(calibration_path)},
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return destination


def verify_pack(pack: Path, *, store: StorePaths | None = None) -> str:
    manifest_path = pack / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") != "cfma.calibration-manifest/1":
        raise ValueError("unsupported pack manifest schema")
    for name, expected in manifest.get("files", {}).items():
        if Path(name).name != name:
            raise ValueError(f"pack file escapes pack directory: {name}")
        path = pack / name
        actual = digest_file(path)
        if actual != expected:
            if store is not None:
                quarantine = store.quarantine / f"corrupt-{pack.parent.name}-{pack.name}-{name}"
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, quarantine)
                quarantine.with_suffix(quarantine.suffix + ".reason.json").write_text(
                    json.dumps(
                        {"reason": "digest mismatch", "expected": expected, "actual": actual},
                        indent=2,
                    )
                    + "\n"
                )
            raise ValueError(f"pack digest mismatch: {name}")
    return "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()


def write_pack_lock(pack: Path, lock_file: Path) -> str:
    digest = verify_pack(pack)
    manifest = json.loads((pack / "manifest.json").read_text())
    document = json.loads(lock_file.read_text())
    key = f"{manifest['pack_id']}/{manifest['version']}"
    existing = document["packs"].get(key)
    if existing is not None and existing != digest:
        raise ValueError(f"pack lock refuses changed immutable pack: {key}")
    document["packs"][key] = digest
    lock_file.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return digest
