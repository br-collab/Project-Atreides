"""Load one identified, versioned and integrity-checked SIM-1 calibration pack."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_CLASSES = frozenset({"SYNTHETIC", "A", "B"})
FORBIDDEN_HOSTS = frozenset(
    {"fred.stlouisfed.org", "alfred.stlouisfed.org", "api.stlouisfed.org"}
)
IDENTIFIER_NAME = re.compile(r"(?:^|_)(?:cusip|figi|ticker)(?:$|_)", re.IGNORECASE)
DEFAULT_PACK = "synthetic/1"
PACKS_ROOT = Path(__file__).with_name("packs")


@dataclass(frozen=True, slots=True)
class CalibrationInput:
    input_id: str
    license_class: str
    source_url: str
    citation: str
    ny_fed_notice: str | None
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CalibrationPack:
    pack_id: str
    version: str
    manifest_digest: str
    inputs: tuple[CalibrationInput, ...]

    @property
    def classes_used(self) -> tuple[str, ...]:
        return tuple(sorted({item.license_class for item in self.inputs}))

    @property
    def notices(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.ny_fed_notice for item in self.inputs if item.ny_fed_notice)
        )

    def value(self, input_id: str, key: str) -> Any:
        item = next(
            (candidate for candidate in self.inputs if candidate.input_id == input_id), None
        )
        if item is None or key not in item.values:
            raise KeyError(f"calibration value absent: {input_id}.{key}")
        return item.values[key]


def _pack_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("CFMA_DATA_URI must address one local pack; network schemes are refused")
    if parsed.scheme == "file":
        path = Path(parsed.path)
    else:
        supplied = Path(uri)
        path = supplied if supplied.is_absolute() else PACKS_ROOT / supplied
    if path.name in {"", ".", ".."}:
        raise ValueError("CFMA_DATA_URI must address one pack, not a store root")
    return path.resolve()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identifier_scan(value: object, trail: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if IDENTIFIER_NAME.search(str(key)):
                raise ValueError(f"forbidden identifier-shaped column {trail}.{key}")
            _identifier_scan(child, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _identifier_scan(child, f"{trail}[{index}]")


def load_calibration_pack(uri: str | None = None) -> CalibrationPack:
    """Load every calibration input; simulator call sites never open calibration files."""
    selected_uri = uri or os.getenv("CFMA_DATA_URI") or DEFAULT_PACK
    pack_path = _pack_path(selected_uri)
    manifest_path = pack_path / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {"schema_version", "pack_id", "version", "files"}:
        raise ValueError("calibration manifest has unknown or missing fields")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("calibration manifest files must be a non-empty object")
    payloads: list[dict[str, object]] = []
    for name, expected in files.items():
        if Path(name).name != name or name == "manifest.json":
            raise ValueError(f"manifest file is outside its pack: {name}")
        path = pack_path / name
        actual = _digest(path)
        if actual != expected:
            raise ValueError(f"calibration integrity mismatch: {name}")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict):
            raise ValueError(f"calibration file must contain an object: {name}")
        payloads.append(document)
    inputs: list[CalibrationInput] = []
    for document in payloads:
        rows = document.get("inputs")
        if not isinstance(rows, list):
            raise ValueError("calibration file requires an inputs list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("calibration input must be an object")
            required = {"input_id", "source_url", "citation", "license_class", "values"}
            if not required <= row.keys():
                raise ValueError("calibration input lacks provenance or class")
            license_class = str(row["license_class"])
            if license_class not in ALLOWED_CLASSES:
                raise ValueError(f"calibration class refused: {license_class}")
            source_url = str(row["source_url"])
            if (urlparse(source_url).hostname or "").lower() in FORBIDDEN_HOSTS:
                raise ValueError(f"FRED source refused: {source_url}")
            notice = row.get("ny_fed_notice")
            if license_class == "B" and not isinstance(notice, str):
                raise ValueError("class B calibration requires the NY Fed notice")
            values = row["values"]
            if not isinstance(values, dict):
                raise ValueError("calibration values must be an object")
            _identifier_scan(values, str(row["input_id"]))
            if str(row["input_id"]) == "aggregate_fail_rate" and license_class != "A":
                raise ValueError("aggregate fail rate must be admitted class A")
            inputs.append(
                CalibrationInput(
                    input_id=str(row["input_id"]),
                    license_class=license_class,
                    source_url=source_url,
                    citation=str(row["citation"]),
                    ny_fed_notice=notice if isinstance(notice, str) else None,
                    values=values,
                )
            )
    return CalibrationPack(
        pack_id=str(manifest["pack_id"]),
        version=str(manifest["version"]),
        manifest_digest="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        inputs=tuple(inputs),
    )
