from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from marketdata.packs import verify_pack
from marketdata.store import digest_file, initialize


def _pack_files(curated_root: Path) -> list[Path]:
    files: list[Path] = []
    for manifest in curated_root.rglob("manifest.json"):
        verify_pack(manifest.parent)
        files.extend(sorted(path for path in manifest.parent.iterdir() if path.is_file()))
    return sorted(set(files))


def _assert_curated(source: Path, curated_root: Path) -> None:
    try:
        source.resolve().relative_to(curated_root.resolve())
    except ValueError as error:
        raise ValueError("sync refuses anything outside 20_curated") from error


def sync_to_ssd(
    source: Path,
    destination: Path,
    *,
    curated_root: Path,
    prune: bool = False,
) -> int:
    _assert_curated(source, curated_root)
    copied = 0
    expected: set[Path] = set()
    for path in _pack_files(source):
        relative = path.relative_to(source)
        target = destination / relative
        expected.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and digest_file(target) == digest_file(path):
            continue
        shutil.copy2(path, target)
        if digest_file(target) != digest_file(path):
            raise ValueError(f"post-copy digest mismatch: {relative}")
        copied += 1
    deleted: list[str] = []
    if prune:
        for path in destination.rglob("*"):
            if path.is_file() and path not in expected:
                deleted.append(path.relative_to(destination).as_posix())
                path.unlink()
    paths = initialize(curated_root.parents[1])
    with (paths.runs / "sync.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "destination": str(destination),
                    "copied": copied,
                    "prune": prune,
                    "deleted": deleted,
                },
                sort_keys=True,
            )
            + "\n"
        )
    return copied


def sync_to_bucket(
    source: Path,
    destination: str,
    *,
    curated_root: Path,
    endpoint_url: str | None = None,
    prune: bool = False,
) -> int:
    _assert_curated(source, curated_root)
    parsed = urlparse(destination)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("bucket destination must be s3://bucket[/prefix]")
    endpoint = endpoint_url or os.getenv("CFMA_S3_ENDPOINT")
    local_endpoint = endpoint is not None and urlparse(endpoint).hostname in {
        "127.0.0.1",
        "localhost",
    }
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        config=Config(signature_version=UNSIGNED) if local_endpoint else None,
    )
    prefix = parsed.path.strip("/")
    uploaded = 0
    expected: set[str] = set()
    for path in _pack_files(source):
        relative = path.relative_to(source).as_posix()
        key = "/".join(part for part in (prefix, relative) if part)
        expected.add(key)
        digest = digest_file(path)
        try:
            response = client.head_object(Bucket=parsed.netloc, Key=key)
            if response.get("Metadata", {}).get("sha256") == digest:
                continue
        except client.exceptions.ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
        client.upload_file(
            str(path), parsed.netloc, key, ExtraArgs={"Metadata": {"sha256": digest}}
        )
        response = client.head_object(Bucket=parsed.netloc, Key=key)
        if response.get("Metadata", {}).get("sha256") != digest:
            raise ValueError(f"post-upload digest mismatch: {key}")
        uploaded += 1
    deleted: list[str] = []
    if prune:
        listing = client.list_objects_v2(Bucket=parsed.netloc, Prefix=prefix)
        for item in listing.get("Contents", []):
            key = item["Key"]
            if key not in expected:
                client.delete_object(Bucket=parsed.netloc, Key=key)
                deleted.append(key)
    paths = initialize(curated_root.parents[1])
    with (paths.runs / "sync.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "destination": destination,
                    "uploaded": uploaded,
                    "prune": prune,
                    "deleted": deleted,
                },
                sort_keys=True,
            )
            + "\n"
        )
    return uploaded
