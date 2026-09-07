"""End-to-end refusal tests for multiple constitution contributions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_haex(
    repo_root: Path,
    *args: str,
    state_root: Path,
) -> subprocess.CompletedProcess:
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
            *args,
        ],
        input=b"",
        capture_output=True,
        env=env,
    )


def test_multi_source_constitution_refuses_before_writing(
    multi_source_constitution_fixture: dict,
) -> None:
    """Refuse multiple constitution sources without creating publication state."""
    consumer = multi_source_constitution_fixture["consumer"]
    state_root = multi_source_constitution_fixture["state_root"]

    proc = _run_haex(consumer, state_root=state_root)

    assert proc.returncode == 2, proc.stderr.decode()
    assert b"key=constitution-already-adopted" in proc.stderr
    assert not (consumer / ".spaex" / "constitution.md").exists()
    assert not (consumer / ".spaex" / "install.lock").exists()


def test_retired_merge_flags_are_not_install_options(
    multi_source_constitution_fixture: dict,
) -> None:
    """The retired LLM merge flags are no longer part of the install CLI."""
    consumer = multi_source_constitution_fixture["consumer"]
    state_root = multi_source_constitution_fixture["state_root"]

    proc = _run_haex(consumer, "--llm=none", state_root=state_root)

    assert proc.returncode == 2
    assert b"unrecognized arguments" in proc.stderr
