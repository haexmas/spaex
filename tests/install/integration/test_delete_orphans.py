"""Regression coverage for the retired multi-source publication path."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_install(repo_root: Path, *, state_root: Path) -> subprocess.CompletedProcess[str]:
    """Run install against a fixture with an isolated state directory."""
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), "install"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_multi_source_install_refuses_without_deleting_existing_outputs(
    multi_source_constitution_fixture: dict,
) -> None:
    """A refused multi-source install must not delete a previous generation."""
    consumer: Path = multi_source_constitution_fixture["consumer"]
    state_root: Path = multi_source_constitution_fixture["state_root"]
    live = consumer / ".spaex"
    live.mkdir()
    constitution = live / "constitution.md"
    constitution.write_bytes(b"existing\n")

    refused = _run_install(consumer, state_root=state_root)

    assert refused.returncode == 2, refused.stderr
    assert "key=constitution-already-adopted" in refused.stderr
    assert constitution.read_bytes() == b"existing\n"
