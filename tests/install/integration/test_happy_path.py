"""T021 — `haex install` happy path (US1 MVP, Spec 008).

A single-source constitution atom lands under `.spaex/` as two files
(constitution.md, install.lock) published atomically by the rename-swap
primitive. The lock's `molecules[]` records the atom's `(id, source,
revision, paths)` and the lock's own top-level `generation_id` (install.lock
is the sole publication record; there is no separate visibility.json,
generated_by, constitution block, or participating_roots since the
2026-09-03 install.lock amendment).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_install(repo_root: Path, state_root: Path) -> subprocess.CompletedProcess:
    """Run `haex install` against a fixture repository."""
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "spaex",
            "--repo-root",
            str(repo_root),
            "install",
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_happy_path_single_source_publishes_both_files(
    single_source_constitution_fixture: dict,
) -> None:
    """Install a single source and verify all published generation files."""
    consumer: Path = single_source_constitution_fixture["consumer"]
    state_root: Path = single_source_constitution_fixture["state_root"]
    atom_id = single_source_constitution_fixture["atom_id"]
    commit_sha = single_source_constitution_fixture["commit_sha"]
    canonical = single_source_constitution_fixture["canonical"]

    proc = _run_install(consumer, state_root)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("installed generation g_")

    live = consumer / ".spaex"
    constitution = live / "constitution.md"
    lock_path = live / "install.lock"

    assert constitution.read_bytes() == b"# Example Constitution\n\nBe kind.\n"
    assert not (live / "visibility.json").exists()

    lock = json.loads(lock_path.read_text())
    assert lock["spaex_version"] == "4"
    assert lock["molecules"] == [
        {
            "id": atom_id,
            "source": canonical,
            "revision": commit_sha,
            "paths": [".spaex/constitution.md"],
        }
    ]
    assert proc.stdout.strip().endswith(lock["generation_id"])
