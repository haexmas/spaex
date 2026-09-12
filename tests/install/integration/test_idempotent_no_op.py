"""T022 — `haex install` idempotence (US1 MVP, Spec 008 SC-003).

A second invocation with unchanged effective inputs is a no-op: no file
is rewritten, no generation ID is allocated, and the run reports "no
changes". The trust-git amendment's byte-comparison detection replaces
the earlier snapshot-digest scaffolding.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from spaex.git.cache import clone_dir

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


def test_second_install_is_a_no_op(
    single_source_constitution_fixture: dict,
) -> None:
    """Verify unchanged inputs leave the published generation untouched."""
    consumer: Path = single_source_constitution_fixture["consumer"]
    state_root: Path = single_source_constitution_fixture["state_root"]

    first = _run_install(consumer, state_root)
    assert first.returncode == 0, first.stderr
    assert first.stdout.startswith("installed generation g_")

    live = consumer / ".spaex"
    constitution_bytes = (live / "constitution.md").read_bytes()
    lock_bytes = (live / "install.lock").read_bytes()
    stat_before = {
        p.name: p.stat().st_mtime_ns
        for p in (live / "constitution.md", live / "install.lock")
    }

    second = _run_install(consumer, state_root)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "no changes"

    assert (live / "constitution.md").read_bytes() == constitution_bytes
    assert (live / "install.lock").read_bytes() == lock_bytes

    stat_after = {
        p.name: p.stat().st_mtime_ns
        for p in (live / "constitution.md", live / "install.lock")
    }
    assert stat_after == stat_before, "no-op path must not touch on-disk files"


def test_changed_source_url_republishes_lock(
    single_source_constitution_fixture: dict,
) -> None:
    """Verify a changed source URL creates a generation with updated metadata."""
    consumer: Path = single_source_constitution_fixture["consumer"]
    state_root: Path = single_source_constitution_fixture["state_root"]
    new_source = "https://github.com/example/renamed-publisher"

    first = _run_install(consumer, state_root)
    assert first.returncode == 0, first.stderr
    assert first.stdout.startswith("installed generation g_")
    first_generation_id = first.stdout.strip().removeprefix("installed generation ")

    old_clone = clone_dir(state_root, single_source_constitution_fixture["canonical"])
    new_clone = clone_dir(state_root, new_source)
    shutil.copytree(old_clone, new_clone)

    manifest_path = consumer / ".spaex/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["compounds"][0]["source"] = new_source
    manifest_path.write_text(json.dumps(manifest, indent=2))

    second = _run_install(consumer, state_root)
    assert second.returncode == 0, second.stderr
    assert second.stdout.startswith("installed generation g_")
    second_generation_id = second.stdout.strip().removeprefix("installed generation ")
    assert second_generation_id != first_generation_id

    lock = json.loads((consumer / ".spaex" / "install.lock").read_text())
    assert lock["molecules"][0]["source"] == new_source
