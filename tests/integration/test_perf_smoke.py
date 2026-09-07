"""T068/T069 — SC-004 / SC-007 performance smokes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary required"),
]


def _run_haex(
    repo_root: Path, *args: str, state_root: Path, timeout: float
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), *args],
        capture_output=True,
        env=env,
        timeout=timeout,
    )


def test_migrate_dry_run_completes_under_5s(self_migration_fixture: dict, tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    shutil.copytree(self_migration_fixture["publisher"], consumer)
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "1",
                "identity": "github.com/haexmas/haex-hive",
                "harness_sources": [
                    {
                        "role": "constitution",
                        "repository": "self",
                        "revision": self_migration_fixture["commit_a"],
                        "path": ".specify/memory/constitution.md",
                    }
                ],
            },
            indent=2,
        )
    )

    start = time.monotonic()
    proc = _run_haex(
        consumer,
        "migrate",
        "--dry-run",
        state_root=self_migration_fixture["state_root"],
        timeout=5.0,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, proc.stderr.decode()
    assert elapsed < 5.0, f"haex migrate --dry-run took {elapsed:.2f}s, want < 5s"


def test_install_refuses_multi_source_under_1s(multi_source_constitution_fixture: dict) -> None:
    consumer = multi_source_constitution_fixture["consumer"]
    state_root = multi_source_constitution_fixture["state_root"]

    start = time.monotonic()
    proc = _run_haex(
        consumer,
        "install",
        state_root=state_root,
        timeout=1.0,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 2
    assert b"key=constitution-already-adopted" in proc.stderr
    assert elapsed < 1.0, f"refusal took {elapsed:.2f}s, want < 1s"
