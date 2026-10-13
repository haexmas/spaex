"""Spec 029 FR-016: a crash inside the local publication converges on reinstall."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spaex.install import git_exclude

pytestmark = [pytest.mark.slow]

_PROJECT_ID = "com.example.publisher.proj"
_MINE_ID = "com.example.publisher.mine"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _install(consumer: Path, state_root: Path, crash_after: str | None) -> int:
    env = {**os.environ, "SPAEX_STATE": str(state_root)}
    env.pop("SPAEX_CRASH_AFTER", None)
    if crash_after is not None:
        env["SPAEX_CRASH_AFTER"] = crash_after
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(consumer), "install"],
        capture_output=True,
        env=env,
        check=False,
    ).returncode


@pytest.mark.parametrize("crash_point", ["pre_swap", "rename_a", "rename_b"])
def test_crash_during_local_publish_converges(
    tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str, crash_point: str
) -> None:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _PROJECT_ID: {"path": "proj", "version": "1.0.0", "atoms": {"tools": ["project.txt"]}},
            _MINE_ID: {"path": "mine", "version": "1.0.0", "atoms": {"tools": ["mine.txt"]}},
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    (consumer / ".gitignore").write_text(".spaex/manifest.json.lock\n")
    assert haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, revision=head, molecule_ids=_PROJECT_ID,
    ) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "project scope")
    project_lock = (consumer / ".spaex/install.lock").read_bytes()
    overlay = consumer / ".spaex/local/manifest.json"
    overlay.parent.mkdir()
    overlay.write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "compounds": [{"source": canonical, "revision": head, "molecules": [_MINE_ID]}],
            }
        )
    )

    assert _install(consumer, state_root, crash_point) != 0
    assert _install(consumer, state_root, None) == 0

    assert (consumer / ".spaex/install.lock").read_bytes() == project_lock
    assert (consumer / ".spaex/local/install.lock").is_file()
    assert (consumer / "mine.txt").is_file()
    assert git_exclude.block_paths(consumer) == ("/mine.txt",)
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""
