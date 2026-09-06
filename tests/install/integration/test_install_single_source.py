"""End-to-end `haex install` refusal + single-source publication tests.

Migrated from `tests/integration/test_assemble_single_source.py` when
`haex constitution assemble` was retired in favour of `haex install`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from haex_hive.io.state import transaction_paths
from haex_hive.io.writer_lock import ConstitutionWriterLock

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_haex(repo_root: Path, *args: str, state_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HAEX_HIVE_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "haex_hive", "--repo-root", str(repo_root),
         "install", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_successful_straight_copy(single_source_constitution_fixture: dict) -> None:
    """Publish a constitution using the device-local transaction journal."""
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]

    proc = _run_haex(consumer, state_root=state_root)
    assert proc.returncode == 0, proc.stderr

    constitution = consumer / ".haex-hive" / "constitution.md"
    lock = consumer / ".haex-hive" / "install.lock"
    assert constitution.read_bytes() == b"# Example Constitution\n\nBe kind.\n"
    assert not (consumer / ".haex-hive" / "visibility.json").exists()

    lock_data = json.loads(lock.read_text())
    assert lock_data["haex_hive_version"] == "3"
    assert lock_data["molecules"] == [
        {
            "id": single_source_constitution_fixture["atom_id"],
            "source": single_source_constitution_fixture["canonical"],
            "revision": single_source_constitution_fixture["commit_sha"],
            "paths": [".haex-hive/constitution.md"],
        }
    ]
    assert lock_data["generation_id"]
def test_active_writer_is_excluded(
    single_source_constitution_fixture: dict,
) -> None:
    """Refuse assembly while another writer holds the device-local mutex."""
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]
    mutex = transaction_paths(consumer, state_root).mutex

    with ConstitutionWriterLock(mutex):
        proc = _run_haex(consumer, state_root=state_root)

    assert proc.returncode == 9
    assert "key=constitution-writer-busy" in proc.stderr


def test_unavailable_pinned_sha_refuses_untouched(single_source_constitution_fixture: dict) -> None:
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]

    manifest_path = consumer / ".haex-hive.json"
    data = json.loads(manifest_path.read_text())
    data["compounds"][0]["revision"] = "deadbeef" * 5
    manifest_path.write_text(json.dumps(data))

    proc = _run_haex(consumer, state_root=state_root)
    assert proc.returncode == 3
    assert "key=pinned-revision-not-found" in proc.stderr
    assert not (consumer / ".haex-hive" / "constitution.md").exists()
    assert not (consumer / ".haex-hive" / "install.lock").exists()


def test_contribution_file_absent_refuses(tmp_path: Path, git_binary: str) -> None:
    def _git(repo: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        )
        return proc.stdout.strip()

    canonical = "https://github.com/example/broken-publisher"
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _git(publisher, "init", "-q")
    _git(publisher, "config", "user.email", "haex-test@example.com")
    _git(publisher, "config", "user.name", "haex-test")
    _git(publisher, "config", "commit.gpgsign", "false")
    _git(publisher, "remote", "add", "origin", canonical)

    atom_id = "com.github.example.broken-publisher.constitution"
    (publisher / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "publisher": "com.github.example.broken-publisher",
                "molecules": {atom_id: {"path": "c", "version": "1.0.0"}},
            }
        )
    )
    (publisher / "c").mkdir()
    (publisher / "c" / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "id": atom_id,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["missing.md"]},
            }
        )
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "declare missing contribution")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    from haex_hive.migrate.transform import clone_dir

    clone_target = clone_dir(state_root, canonical)
    clone_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, clone_target)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.github.example.consumer",
                "compounds": [{"source": canonical, "revision": sha, "molecules": [atom_id]}],
            }
        )
    )

    proc = _run_haex(consumer, state_root=state_root)
    assert proc.returncode == 3
    assert "key=contribution-file-not-found" in proc.stderr
    assert not (consumer / ".haex-hive" / "constitution.md").exists()


def test_empty_compounds_publishes_empty_generation(tmp_path: Path) -> None:
    """An empty consumer publishes an empty install.lock instead of refusing.

    Post-`haex remove` recovery: the operator is allowed to retract every
    molecule and land in the empty state without a follow-up install failure.
    """
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.github.example.consumer",
                "compounds": [],
            }
        )
    )
    proc = _run_haex(consumer, state_root=tmp_path / "state")
    assert proc.returncode == 0, proc.stderr
    assert "installed empty generation" in proc.stdout
    assert not (consumer / ".haex-hive" / "constitution.md").exists()

    lock_bytes = (consumer / ".haex-hive" / "install.lock").read_bytes()
    lock_data = json.loads(lock_bytes)
    assert lock_data["molecules"] == []

    # Re-invocation is a no-op.
    proc2 = _run_haex(consumer, state_root=tmp_path / "state")
    assert proc2.returncode == 0
    assert "no changes" in proc2.stdout
    assert (consumer / ".haex-hive" / "install.lock").read_bytes() == lock_bytes
