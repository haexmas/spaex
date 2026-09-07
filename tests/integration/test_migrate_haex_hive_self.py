"""T042 — FR-023 self-migration fixture (A/B/C) via the same code path."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.migrate.transform import migrate_v1_to_v2

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_migrating_commit_b_yields_commit_c_pinned_to_a(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    consumer = tmp_path / "consumer"
    shutil.copytree(self_migration_fixture["publisher"], consumer)
    commit_a = self_migration_fixture["commit_a"]

    v1_at_b = {
        "haex_hive_version": "1",
        "identity": "github.com/haexmas/haex-hive",
        "harness_sources": [
            {
                "role": "constitution",
                "repository": "self",
                "revision": commit_a,
                "path": ".specify/memory/constitution.md",
            }
        ],
        "groups": [],
        "active_feature": None,
    }
    raw_b = json.dumps(v1_at_b, indent=2).encode("utf-8")

    v2 = migrate_v1_to_v2(raw_b, consumer, self_migration_fixture["state_root"])
    data = json.loads(v2.decode("utf-8"))
    assert data["haex_hive_version"] == "2"
    assert data["atoms"][0]["revision"] == commit_a
    assert data["atoms"][0]["includes"] == ["com.github.haexmas.haex-hive.constitution"]
