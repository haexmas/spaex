"""Spec 029 FR-014: local hook side effects are checked at the repository boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import install as install_cli
from spaex.install import git_exclude
from spaex.util.errors import InstallTransactionFailedError

_CREATES_ID = "com.example.publisher.creates"
_EDITS_ID = "com.example.publisher.edits"

_CREATES_HOOK = """import os, pathlib
target = pathlib.Path("generated/out.txt")
target.parent.mkdir(exist_ok=True)
target.write_text(os.environ["SPAEX_SCOPE"])
"""
_EDITS_HOOK = """import pathlib
pathlib.Path("README.md").write_text("hijacked\\n")
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hook_molecule(path: str, script: str) -> dict:
    return {
        "path": path,
        "version": "1.0.0",
        "atoms": {},
        "manifest_extra": {
            "install_hook": {"interpreter": "python3", "script": "hook.py", "on_failure": "warn"}
        },
        "files": {"hook.py": script},
    }


@pytest.fixture
def scene(tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str) -> SimpleNamespace:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CREATES_ID: _hook_molecule("creates", _CREATES_HOOK),
            _EDITS_ID: _hook_molecule("edits", _EDITS_HOOK),
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    (consumer / "README.md").write_text("team readme\n")
    (consumer / ".gitignore").write_text(".spaex/manifest.json.lock\n")
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    assert install_cli.run(SimpleNamespace(repo_root=str(consumer))) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "init")

    def add(ids: str) -> int:
        return haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical, revision=head, molecule_ids=ids, local=True,
        )

    def remove(ids: str) -> int:
        return haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, ids, local=True)

    return SimpleNamespace(consumer=consumer, add=add, remove=remove)


def test_hook_created_file_is_recorded_excluded_and_removed(scene: SimpleNamespace) -> None:
    consumer = scene.consumer

    assert scene.add(_CREATES_ID) == 0

    assert (consumer / "generated/out.txt").read_text() == "local"
    lock = json.loads((consumer / ".spaex/local/install.lock").read_text())
    assert lock["molecules"][0]["paths"] == ["generated/out.txt"]
    assert git_exclude.block_paths(consumer) == ("/generated/out.txt",)
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""

    assert scene.remove(_CREATES_ID) == 0
    assert not (consumer / "generated/out.txt").exists()


def test_hook_editing_a_tracked_file_is_reverted_and_refused(scene: SimpleNamespace) -> None:
    consumer = scene.consumer

    with pytest.raises(InstallTransactionFailedError) as caught:
        scene.add(_EDITS_ID)

    assert caught.value.context["install_key"] == "local-hook-side-effect"
    assert (consumer / "README.md").read_text() == "team readme\n"
    assert not (consumer / ".spaex/local").exists()
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""
