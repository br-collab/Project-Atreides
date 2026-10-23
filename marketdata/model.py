from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    url: str
    license_class: str
    kind: str
    citation: str
    ny_fed_notice: str | None = None


@dataclass(frozen=True, slots=True)
class StorePaths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "00_raw"

    @property
    def normalized(self) -> Path:
        return self.root / "10_normalized"

    @property
    def packs(self) -> Path:
        return self.root / "20_curated" / "packs"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    @property
    def catalog(self) -> Path:
        return self.root / "catalog"

    @property
    def runs(self) -> Path:
        return self.root / "40_runs"

    def create(self) -> None:
        for path in (
            self.raw,
            self.normalized,
            self.packs,
            self.quarantine,
            self.catalog,
            self.runs,
        ):
            path.mkdir(parents=True, exist_ok=True)
