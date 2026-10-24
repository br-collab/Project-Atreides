#!/usr/bin/env python3
"""Regenerate every published dated spike artifact from its locked local pack.

CLOSE-1 WP4.1: "Add a local regenerate command that rebuilds every published
spike artifact from its locked pack at the current commit and records that
commit. It runs on the Mac (CI has no store)."
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from marketdata.packs import verify_pack
from marketdata.store import DEFAULT_ROOT
from simulator.runner import publish_run, run_simulation

REPOSITORY_ROOT = Path(__file__).parents[1]
PACK_LOCKS = REPOSITORY_ROOT / "marketdata/pack-locks.json"
PUBLICATION_ROOT = REPOSITORY_ROOT / "simulator/publication"
OUTPUT_NAMES = frozenset({"SUMMARY.md", "daily-close.json", "run-summary.json", "trend.json"})


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    pack_id: str
    start: date
    end: date
    seed: int


ARTIFACTS = (
    ArtifactSpec(
        "spike-2019", "repo-spike-2019", date(2019, 8, 19), date(2019, 9, 17), 20261023
    ),
    ArtifactSpec(
        "stress-2020-03", "stress-2020-03", date(2020, 2, 10), date(2020, 3, 31), 20261024
    ),
    ArtifactSpec(
        "stress-2023-03", "stress-2023-03", date(2023, 2, 9), date(2023, 3, 24), 20261024
    ),
)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _current_commit() -> str:
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("regeneration requires a clean committed tree")
    return _git("rev-parse", "HEAD")


def _locked_pack(spec: ArtifactSpec, data_root: Path) -> Path:
    locks = json.loads(PACK_LOCKS.read_text())
    version = locks["current"].get(spec.pack_id)
    if not isinstance(version, str):
        raise ValueError(f"no current locked version for {spec.pack_id}")
    key = f"{spec.pack_id}/{version}"
    expected = locks["packs"].get(key)
    if expected is None:
        raise ValueError(f"no digest lock for {key}")
    pack = data_root / "20_curated/packs" / spec.pack_id / version
    actual = verify_pack(pack)
    if actual != expected:
        raise ValueError(f"local pack does not match lock for {key}: {actual} != {expected}")
    return pack


def regenerate(
    *,
    data_root: Path,
    output_root: Path,
    repository_shas: dict[str, str],
) -> tuple[Path, ...]:
    current = _current_commit()
    supplied = repository_shas.get("atreides")
    if supplied is not None and supplied != current:
        raise ValueError(f"atreides source commit must be current HEAD {current}, not {supplied}")
    shas = {**repository_shas, "atreides": current}
    outputs: list[Path] = []
    for spec in ARTIFACTS:
        pack = _locked_pack(spec, data_root)
        target = output_root / spec.name
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ValueError(f"publication target is not a real directory: {target}")
        if target.exists():
            shutil.rmtree(target)
        publish_run(
            run_simulation(
                seed=spec.seed,
                days=None,
                start=spec.start,
                end=spec.end,
                calibration_uri=pack.as_uri(),
                repository_shas=shas,
                require_explicit_dated_window=True,
            ),
            target,
        )
        names = {path.name for path in target.iterdir()}
        if names != OUTPUT_NAMES:
            raise ValueError(f"artifact is not output-only: {spec.name}: {sorted(names)}")
        outputs.append(target)
    return tuple(outputs)


def label_summary_freshness(
    summary: Path,
    *,
    source_commit: str,
    current_commit: str,
    is_ancestor: Callable[[str, str], bool],
) -> None:
    marker = "- Artifact freshness:"
    lines = [line for line in summary.read_text().splitlines() if not line.startswith(marker)]
    if source_commit != current_commit:
        if not is_ancestor(source_commit, current_commit):
            raise ValueError(
                f"artifact source {source_commit} is not an ancestor of current {current_commit}"
            )
        lines.extend(
            (
                "",
                f"{marker} `STALE`; source commit `{source_commit}` is behind current main "
                f"`{current_commit}`.",
            )
        )
    summary.write_text("\n".join(lines) + "\n")


def label_stale_artifacts(publication_root: Path, current_commit: str) -> None:
    def is_ancestor(older: str, newer: str) -> bool:
        result = subprocess.run(
            ("git", "merge-base", "--is-ancestor", older, newer),
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        return result.returncode == 0

    for spec in ARTIFACTS:
        artifact = publication_root / spec.name
        run = json.loads((artifact / "run-summary.json").read_text())
        source_commit = run.get("repository_shas", {}).get("atreides")
        if not isinstance(source_commit, str) or not source_commit:
            raise ValueError(f"artifact has no Atreides source commit: {spec.name}")
        label_summary_freshness(
            artifact / "SUMMARY.md",
            source_commit=source_commit,
            current_commit=current_commit,
            is_ancestor=is_ancestor,
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    regenerate_command = commands.add_parser("regenerate")
    regenerate_command.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    regenerate_command.add_argument("--output", type=Path, default=PUBLICATION_ROOT)
    regenerate_command.add_argument("--repository-sha", action="append", default=[])
    label_command = commands.add_parser("label-stale")
    label_command.add_argument("publication_root", type=Path)
    label_command.add_argument("current_commit")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "label-stale":
        label_stale_artifacts(args.publication_root, args.current_commit)
        return 0
    repository_shas = dict(value.split("=", 1) for value in args.repository_sha)
    for output in regenerate(
        data_root=args.root,
        output_root=args.output,
        repository_shas=repository_shas,
    ):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
