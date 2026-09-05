"""T040 — end-to-end `haex migrate` integration coverage for US1."""

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


def _run_haex(repo_root: Path, *args: str, state_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HAEX_HIVE_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "haex_hive", "--repo-root", str(repo_root), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _prepare_consumer(fixture: dict, tmp_path: Path, extra: dict | None = None) -> Path:
    consumer = tmp_path / "consumer"
    shutil.copytree(fixture["publisher"], consumer)
    v1 = {
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
    }
    if extra:
        v1.update(extra)
    (consumer / ".haex-hive.json").write_text(json.dumps(v1, indent=2))
    return consumer


def test_dry_run_prints_diff_no_sidecar(self_migration_fixture: dict, tmp_path: Path) -> None:
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    proc = _run_haex(
        consumer, "migrate", "--dry-run", state_root=self_migration_fixture["state_root"]
    )
    assert proc.returncode == 0, proc.stderr
    assert "@@" in proc.stdout
    assert not (consumer / ".haex-hive.json.migrated").exists()


def test_write_mode_creates_sidecar(self_migration_fixture: dict, tmp_path: Path) -> None:
    """v1 input chains v1→v2→v3; the sidecar lands as the final v3 proposal."""
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    proc = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 0, proc.stderr
    sidecar = consumer / ".haex-hive.json.migrated"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["haex_hive_version"] == "3"
    assert data["identity"] == "com.github.haexmas.haex-hive"
    # v2's `atoms[]` has been renamed to `compounds[]` per Spec 013.
    assert "compounds" in data
    assert "atoms" not in data


def test_already_v3_is_noop(self_migration_fixture: dict, tmp_path: Path) -> None:
    """A repo whose manifests are all already v3 emits no proposals."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.github.haexmas.haex-hive",
                "compounds": [],
            },
            indent=2,
        )
    )
    proc = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 0
    assert "already at v3" in proc.stderr
    assert not (consumer / ".haex-hive.json.migrated").exists()


def test_v2_consumer_chains_to_v3(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    """A v2 consumer emits a v3 proposal via the v2→v3 leg of the chain."""
    consumer = tmp_path / "consumer"
    shutil.copytree(self_migration_fixture["publisher"], consumer)
    (consumer / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "identity": "com.github.haexmas.haex-hive",
                "atoms": [
                    {
                        "source": "https://github.com/haexmas/haex-hive",
                        "revision": self_migration_fixture["commit_a"],
                        "includes": [
                            "com.github.haexmas.haex-hive.constitution"
                        ],
                    }
                ],
            },
            indent=2,
        )
    )
    proc = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 0, proc.stderr
    sidecar = consumer / ".haex-hive.json.migrated"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["haex_hive_version"] == "3"
    assert data["compounds"][0]["molecules"] == [
        "com.github.haexmas.haex-hive.constitution"
    ]


def test_dry_run_and_check_conflict_is_usage_error(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    consumer = _prepare_consumer(self_migration_fixture, tmp_path)
    proc = _run_haex(consumer, "migrate", "--dry-run", "--check",
                      state_root=self_migration_fixture["state_root"])
    assert proc.returncode == 64
