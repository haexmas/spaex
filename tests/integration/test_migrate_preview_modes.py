"""T041 — FR-018 preview vs. write-mode sidecar semantics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _run_haex(repo_root: Path, *args: str, state_root: Path):
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _prepare_consumer(fixture: dict, tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    shutil.copytree(fixture["publisher"], consumer)
    (consumer / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "1",
                "identity": "github.com/haexmas/haex-hive",
                "harness_sources": [
                    {
                        "role": "constitution",
                        "repository": "self",
                        "revision": fixture["commit_a"],
                        "path": ".specify/memory/constitution.md",
                    }
                ],
            },
            indent=2,
        )
    )
    return consumer


def test_dry_run_and_check_produce_identical_stdout(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    dry = _run_haex(consumer, "migrate", "--dry-run",
                    state_root=self_migration_fixture["state_root"])
    chk = _run_haex(consumer, "migrate", "--check",
                    state_root=self_migration_fixture["state_root"])
    assert dry.returncode == 0
    assert chk.returncode == 0
    assert dry.stdout == chk.stdout


def test_write_mode_invalidates_stale_sidecar(self_migration_fixture: dict, tmp_path: Path) -> None:
    """Write mode invalidates BOTH the legacy .haex-hive.json.migrated and any
    existing .spaex.json.migrated sidecars, then writes a fresh v4 proposal at
    .spaex.json.migrated (Spec 014)."""
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    legacy_stale = consumer / ".haex-hive.json.migrated"
    new_stale = consumer / ".spaex.json.migrated"
    legacy_stale.write_bytes(b"{}")
    new_stale.write_bytes(b"{\"stale\": true}")
    proc = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 0
    assert not legacy_stale.exists()
    assert new_stale.exists()
    assert new_stale.read_bytes() != b"{\"stale\": true}"


def test_preview_mode_preserves_existing_sidecar(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    stale = consumer / ".haex-hive.json.migrated"
    stale.write_bytes(b"{\"preserved\": true}")
    proc = _run_haex(consumer, "migrate", "--dry-run",
                    state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 0
    assert stale.read_bytes() == b"{\"preserved\": true}"
