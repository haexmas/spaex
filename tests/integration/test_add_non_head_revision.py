"""T064 — pinning `--revision=<SHA>` at a non-HEAD commit (Spec 013 research D3)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_HELLO_ID = "com.example.publisher.hello"


def _remove_read_only(func, path, exc_info) -> None:
    """Retry removal after clearing Git's read-only bit on Windows."""
    if not isinstance(exc_info[1], PermissionError):
        raise exc_info[1]
    os.chmod(path, stat.S_IWRITE)
    func(path)

def test_add_pins_non_head_revision_via_fetched_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, haex_add_helpers
) -> None:
    """A pinned non-HEAD SHA must resolve against the fetched object, not HEAD."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    bare = haex_add_helpers["clone_dir"](state_root, canonical)
    advance = tmp_path / "advance-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(advance)], check=True)
    haex_add_helpers["git"](advance, "config", "user.email", "t@e")
    haex_add_helpers["git"](advance, "config", "user.name", "t")
    haex_add_helpers["git"](advance, "config", "commit.gpgsign", "false")
    (advance / "hello" / "constitution.md").write_text("# v2\n")
    haex_add_helpers["git"](advance, "commit", "-q", "-am", "advance to v2")
    haex_add_helpers["git"](advance, "push", "-q", "origin", "HEAD:main")
    new_head = haex_add_helpers["git"](advance, "rev-parse", "HEAD")
    assert new_head != head

    # The cached clone was the push target above, so remove it to force
    # `ensure_object` through its initialization and fetch path. The working
    # copy remains the reachable source for the test's canonical URL.
    shutil.rmtree(bare, onerror=_remove_read_only)
    from spaex.git import publisher_fetch

    original_run_git = publisher_fetch._run_git

    def run_git_with_local_test_remote(*args, cwd=None, capture=True, timeout=None):
        mapped_args = tuple(str(advance) if arg == canonical else arg for arg in args)
        return original_run_git(
            *mapped_args, cwd=cwd, capture=capture, timeout=timeout
        )

    monkeypatch.setattr(publisher_fetch, "_run_git", run_git_with_local_test_remote)

    consumer = haex_add_helpers["make_consumer"](tmp_path)
    rc = haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head,
    )
    assert rc == 0
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"][0]["revision"] == head
    published = (consumer / ".spaex" / "constitution.md").read_bytes()
    assert b"hello constitution constitution.md" in published
