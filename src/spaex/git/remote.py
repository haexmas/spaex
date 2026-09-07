"""`git remote get-url origin` → repo URL string."""

from __future__ import annotations

import subprocess
from pathlib import Path

from spaex.util.errors import MissingRemoteOriginError


def origin_url(repo_dir: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
        capture_output=True,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise MissingRemoteOriginError(
            message="git remote get-url origin failed",
            context={"repo_dir": str(repo_dir)},
        )
    return proc.stdout.strip()
