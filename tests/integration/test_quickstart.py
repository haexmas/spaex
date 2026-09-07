"""T066 — end-to-end quickstart.md Path 1-4 walkthrough (SC-001..SC-003)."""

from __future__ import annotations

import json
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
    stdin_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-m", "spaex", "--repo-root", str(repo_root), *args],
        input=stdin_bytes if stdin_bytes is not None else b"",
        capture_output=True,
        env=env,
    )


def test_path1_migrate_produces_schema_valid_v4(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
    """quickstart.md Path 1 - SC-001. Under Spec 014 the chain reaches v4
    and the consumer sidecar lives at `.spaex.json.migrated`."""
    consumer = tmp_path / "consumer"
    shutil.copytree(self_migration_fixture["publisher"], consumer)
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "1",
                "identity": "github.com/haexmas/haex-hive",
                "harness_sources": [
                    {
                        "role": "constitution",
                        "repository": "self",
                        "revision": self_migration_fixture["commit_a"],
                        "path": ".specify/memory/constitution.md",
                    }
                ],
            },
            indent=2,
        )
    )

    dry_run = _run_haex(
        consumer, "migrate", "--dry-run", state_root=self_migration_fixture["state_root"]
    )
    assert dry_run.returncode == 0, dry_run.stderr.decode()
    assert b"@@" in dry_run.stdout

    write = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert write.returncode == 0, write.stderr.decode()
    sidecar = consumer / ".spaex.json.migrated"
    assert sidecar.exists()

    data = json.loads(sidecar.read_text())
    assert data["spaex_version"] == "4"
    assert "haex_hive_version" not in data

    # Adopt every proposal (consumer becomes .spaex.json + delete .spaex.json;
    # publisher-root + per-molecule manifest.json.migrated overwrite their
    # originals). Only after all `.migrated` siblings replace their originals
    # does the rerun report "already at v4".
    for migrated in list(consumer.rglob("*.migrated")):
        if migrated.name == ".spaex.json.migrated":
            (consumer / ".spaex.json").unlink(missing_ok=True)
            migrated.replace(consumer / ".spaex.json")
        else:
            migrated.replace(migrated.with_name(migrated.name[: -len(".migrated")]))
    rerun = _run_haex(consumer, "migrate", state_root=self_migration_fixture["state_root"])
    assert rerun.returncode == 0
    assert b"already at v4" in rerun.stderr
    assert not sidecar.exists()


def test_path2_single_source_assemble_and_show(
    single_source_constitution_fixture: dict,
) -> None:
    """quickstart.md Path 2 + Path 4 — SC-002."""
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]

    first = _run_haex(consumer, "install", state_root=state_root)
    assert first.returncode == 0, first.stderr.decode()

    source_body = (
        single_source_constitution_fixture["publisher"] / "constitution" / "constitution.md"
    ).read_bytes()
    constitution = (consumer / ".spaex" / "constitution.md").read_bytes()
    assert constitution == source_body
    lock_data_1 = json.loads((consumer / ".spaex" / "install.lock").read_bytes())

    second = _run_haex(consumer, "install", state_root=state_root)
    assert second.returncode == 0
    assert second.stdout.decode().strip() == "no changes"
    assert (consumer / ".spaex" / "constitution.md").read_bytes() == constitution
    lock_data_2 = json.loads((consumer / ".spaex" / "install.lock").read_bytes())
    assert lock_data_1 == lock_data_2, "no-op re-install must leave install.lock untouched"

    show = _run_haex(consumer, "constitution", "show", state_root=state_root)
    assert show.returncode == 0, show.stderr.decode()
    assert show.stdout.endswith(constitution)
    assert b"# Assembled from" in show.stdout

    no_preface = _run_haex(consumer, "constitution", "show", "--no-preface", state_root=state_root)
    assert no_preface.returncode == 0
    assert no_preface.stdout == constitution


def test_path3_multi_source_refuses_before_writing(
    multi_source_constitution_fixture: dict,
) -> None:
    """Multiple constitution sources are refused before publication."""
    consumer = multi_source_constitution_fixture["consumer"]
    state_root = multi_source_constitution_fixture["state_root"]

    proc = _run_haex(consumer, "install", state_root=state_root)
    assert proc.returncode == 2
    assert b"key=constitution-already-adopted" in proc.stderr
    assert not (consumer / ".spaex" / "constitution.md").exists()
