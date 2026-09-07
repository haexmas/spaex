"""`git rev-parse <ref>^{commit}` → full 40-char SHA."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from spaex.util.errors import PinnedRevisionNotFoundError

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def full_sha(repo_dir: Path, maybe_short: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", f"{maybe_short}^{{commit}}"],
        capture_output=True,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise PinnedRevisionNotFoundError(
            message=f"could not resolve revision {maybe_short!r}",
            context={"revision": maybe_short, "repo_dir": str(repo_dir)},
        )
    sha = proc.stdout.strip()
    if not _SHA40_RE.match(sha):
        raise PinnedRevisionNotFoundError(
            message=f"git rev-parse returned unexpected value: {sha!r}",
            context={"revision": maybe_short},
        )
    return sha
