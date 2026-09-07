"""T025 — `haex install` refuses v2 input with a `haex migrate` hint (Spec 013)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _run_install(repo_root: Path, state_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), "install"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_v2_consumer_refuses_with_unavailable_migration_hint(tmp_path: Path) -> None:
    """A v2 consumer is refused because v2-to-v3 migration is not available yet."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "identity": "com.example.consumer",
                "atoms": [],
            }
        )
    )

    proc = _run_install(consumer, tmp_path / "state")
    assert proc.returncode != 0
    assert "v2-to-v3 migration is not available yet" in proc.stderr
    assert not (consumer / ".spaex").exists()


def test_v3_consumer_against_v2_publisher_refuses_without_writing(
    tmp_path: Path, git_binary: str
) -> None:
    """A v2 publisher is the publisher's own migration debt, not the operator's."""
    canonical = "https://github.com/example/stale-publisher"
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _git(publisher, "init", "-q")
    _git(publisher, "config", "user.email", "haex-test@example.com")
    _git(publisher, "config", "user.name", "haex-test")
    _git(publisher, "config", "commit.gpgsign", "false")
    _git(publisher, "remote", "add", "origin", canonical)

    molecule_id = "com.github.example.stale-publisher.constitution"
    (publisher / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "publisher": "com.github.example.stale-publisher",
                "atoms": {molecule_id: {"path": "c", "version": "1.0.0"}},
            }
        )
    )
    (publisher / "c").mkdir()
    (publisher / "c" / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "id": molecule_id,
                "version": "1.0.0",
                "contributes": {"constitution": "constitution.md"},
            }
        )
    )
    (publisher / "c" / "constitution.md").write_bytes(b"# Stale\n")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "v2 publisher")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    from spaex.migrate.transform import clone_dir

    clone_target = clone_dir(state_root, canonical)
    clone_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, clone_target)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.github.example.consumer",
                "compounds": [{"source": canonical, "revision": sha, "molecules": [molecule_id]}],
            }
        )
    )

    proc = _run_install(consumer, state_root)
    assert proc.returncode != 0
    assert not (consumer / ".spaex").exists()
