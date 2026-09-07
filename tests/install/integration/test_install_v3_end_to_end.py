"""T024 — `haex install` against a fully v3 consumer + publisher (Spec 013)."""

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
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), "install"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_v3_consumer_and_publisher_produce_byte_identical_lock_across_runs(
    single_source_constitution_fixture: dict,
) -> None:
    """Installing a v3 consumer against a v3 publisher is v3-shaped and idempotent."""
    consumer: Path = single_source_constitution_fixture["consumer"]
    state_root: Path = single_source_constitution_fixture["state_root"]

    manifest = json.loads((consumer / ".spaex.json").read_text())
    assert manifest["spaex_version"] == "4"
    assert "compounds" in manifest

    first = _run_install(consumer, state_root)
    assert first.returncode == 0, first.stderr

    lock_path = consumer / ".spaex" / "install.lock"
    lock_data = json.loads(lock_path.read_text())
    assert lock_data["spaex_version"] == "4"
    assert lock_data["molecules"] == [
        {
            "id": single_source_constitution_fixture["atom_id"],
            "source": single_source_constitution_fixture["canonical"],
            "revision": single_source_constitution_fixture["commit_sha"],
            "paths": [".spaex/constitution.md"],
        }
    ]

    first_bytes = lock_path.read_bytes()
    second = _run_install(consumer, state_root)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "no changes"
    assert lock_path.read_bytes() == first_bytes
