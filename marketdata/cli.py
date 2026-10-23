from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from marketdata.catalog import CATALOG_PATH
from marketdata.guard import check_repository
from marketdata.normalize import normalize
from marketdata.packs import build_pack, verify_pack, write_pack_lock
from marketdata.store import DEFAULT_ROOT, ingest, initialize
from marketdata.sync import sync_to_bucket, sync_to_ssd

PACK_LOCKS = Path(__file__).with_name("pack-locks.json")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m marketdata")
    result.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = result.add_subparsers(dest="command", required=True)
    ingest_command = commands.add_parser("ingest")
    ingest_command.add_argument("source_id")
    normalize_command = commands.add_parser("normalize")
    normalize_command.add_argument("source_id")
    build = commands.add_parser("build-pack")
    build.add_argument("pack_id")
    build.add_argument("version")
    build.add_argument("inputs", type=Path, nargs="+")
    build.add_argument("--start", type=date.fromisoformat)
    build.add_argument("--end", type=date.fromisoformat)
    verify = commands.add_parser("verify")
    verify.add_argument("pack", type=Path)
    lock = commands.add_parser("pack-lock")
    lock.add_argument("pack", type=Path)
    sync = commands.add_parser("sync")
    sync.add_argument("--to", choices=("ssd", "bucket"), required=True)
    sync.add_argument("source", type=Path)
    sync.add_argument("destination")
    sync.add_argument("--endpoint-url")
    sync.add_argument("--prune", action="store_true")
    guard = commands.add_parser("guard")
    guard.add_argument("repository", type=Path, nargs="?", default=Path.cwd())
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = initialize(args.root)
    if args.command == "ingest":
        print(ingest(args.source_id, root=args.root))
    elif args.command == "normalize":
        print(normalize(args.source_id, root=args.root))
    elif args.command == "build-pack":
        print(
            build_pack(
                args.pack_id,
                args.version,
                args.inputs,
                root=args.root,
                start=args.start,
                end=args.end,
            )
        )
    elif args.command == "verify":
        print(verify_pack(args.pack, store=paths))
    elif args.command == "pack-lock":
        print(write_pack_lock(args.pack, PACK_LOCKS))
    elif args.command == "sync" and args.to == "ssd":
        print(
            sync_to_ssd(
                args.source, Path(args.destination), curated_root=paths.packs, prune=args.prune
            )
        )
    elif args.command == "sync":
        print(
            sync_to_bucket(
                args.source,
                args.destination,
                curated_root=paths.packs,
                endpoint_url=args.endpoint_url,
                prune=args.prune,
            )
        )
    elif args.command == "guard":
        offenders = check_repository(args.repository)
        if offenders:
            raise SystemExit("repository contains forbidden DATA-1 paths: " + ", ".join(offenders))
        print(f"guard clean; catalog {CATALOG_PATH.name}")
    return 0
