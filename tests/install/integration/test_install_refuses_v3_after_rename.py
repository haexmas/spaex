"""T045 - `spaex install` refuses v3-shaped consumer manifests after the rename (Spec 014).

The v4 read gate must reject both the legacy ``haex_hive_version`` key and
``spaex_version: "3"`` with the ``spaex-version-unsupported`` diagnostic and
a ``spaex migrate`` hint, and must not create any ``.spaex/`` state.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_install(repo_root: Path, state_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), "install"],
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_v3_refusal(proc: subprocess.CompletedProcess, consumer: Path) -> None:
    assert proc.returncode != 0
    assert "key=spaex-version-unsupported" in proc.stderr
    assert "spaex migrate" in proc.stderr
    assert not (consumer / ".spaex").exists()


def test_legacy_haex_hive_version_in_spaex_json_refuses(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.example.consumer",
                "compounds": [],
            }
        )
    )

    _assert_v3_refusal(_run_install(consumer, tmp_path / "state"), consumer)


def test_spaex_version_three_refuses(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "3",
                "identity": "com.example.consumer",
                "compounds": [],
            }
        )
    )

    _assert_v3_refusal(_run_install(consumer, tmp_path / "state"), consumer)
