from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_PATH = re.compile(
    r"(^|/)(?:00_raw|10_normalized|20_curated|40_runs|quarantine|cfma-data)(?:/|$)"
)
SECRET_PATH = re.compile(r"(^|/)(?:\.env[^/]*|.*\.(?:pem|key))$", re.I)


def check_repository(root: Path) -> list[str]:
    tracked = (
        subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    return sorted(
        path
        for path in tracked
        if path and (FORBIDDEN_PATH.search(path) or SECRET_PATH.search(path))
    )
