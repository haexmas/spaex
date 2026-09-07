"""`git show <sha>:<path>` capturing raw stdout bytes.

Callers pass the exact typed error class to raise on a non-zero exit — the
distinction between "clone missing", "SHA missing", and "path missing at that
SHA" is made in the caller (see spec-007 `haex-constitution-assemble.cli.md`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from spaex.util.errors import HaexError


def show_bytes(
    repo_dir: Path,
    sha: str,
    path: str,
    *,
    not_found_error: type[HaexError],
) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "show", f"{sha}:{path}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise not_found_error(
            message=f"git show {sha}:{path} failed in {repo_dir}",
            context={"path": path, "sha_short": sha[:12]},
        )
    return proc.stdout
