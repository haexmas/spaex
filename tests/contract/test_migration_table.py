"""T038 — migration table contract test (canonical v1 shapes)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.migrate.transform import migrate_v1_to_v2
from spaex.util.errors import (
    CredentialInUrlError,
    IdentityMismatchError,
    PermissionOnlyEntryError,
    PlaintextSecretDetectedError,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _consumer_repo(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    subprocess.run(["git", "init", "-q", str(consumer)], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "remote", "add", "origin",
         "https://github.com/haexmas/haex-hive"],
        check=True,
    )
    return consumer


def test_role_constitution_self(self_migration_fixture: dict, tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    shutil.copytree(self_migration_fixture["publisher"], consumer)
    raw = json.dumps(
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
        }
    ).encode("utf-8")
    v2 = migrate_v1_to_v2(raw, consumer, self_migration_fixture["state_root"])
    data = json.loads(v2.decode("utf-8"))
    assert data["atoms"][0]["includes"] == ["com.github.haexmas.haex-hive.constitution"]


def test_permission_only_bare_repository_refused(tmp_path: Path) -> None:
    consumer = _consumer_repo(tmp_path)
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "github.com/haexmas/haex-hive",
            "harness_sources": [{"repository": "self"}],
        }
    ).encode("utf-8")
    with pytest.raises(PermissionOnlyEntryError):
        migrate_v1_to_v2(raw, consumer, tmp_path / "state")


def test_credential_url_refused(tmp_path: Path) -> None:
    consumer = _consumer_repo(tmp_path)
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "github.com/haexmas/haex-hive",
            "harness_sources": [
                {
                    "role": "constitution",
                    "repository": "https://user:pass@github.com/x/y",
                    "revision": "0" * 40,
                    "path": "constitution.md",
                }
            ],
        }
    ).encode("utf-8")
    with pytest.raises((CredentialInUrlError, PlaintextSecretDetectedError)):
        migrate_v1_to_v2(raw, consumer, tmp_path / "state")


def test_non_github_identity_refused(tmp_path: Path) -> None:
    consumer = _consumer_repo(tmp_path)
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "gitlab.com/example/project",
            "harness_sources": [],
        }
    ).encode("utf-8")
    with pytest.raises(IdentityMismatchError):
        migrate_v1_to_v2(raw, consumer, tmp_path / "state")
