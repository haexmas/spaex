"""Unit tests for the v1→v2 transform (T039)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.migrate.transform import migrate_v1_to_v2
from spaex.util.errors import (
    IdentityMismatchError,
    PermissionOnlyEntryError,
    PlaintextSecretDetectedError,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def test_rejects_non_github_non_reverse_dns_identity() -> None:
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "SomeGarbage!!",
            "harness_sources": [],
        }
    ).encode("utf-8")
    with pytest.raises((IdentityMismatchError, PermissionOnlyEntryError, ValueError)):
        migrate_v1_to_v2(raw, Path("."), Path("."))


def test_rejects_permission_only_entry(self_migration_fixture: dict, tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(
        ["git", "-C", str(consumer), "init", "-q"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(consumer), "remote", "add", "origin",
         "https://github.com/haexmas/haex-hive"],
        check=True,
        capture_output=True,
    )
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "github.com/haexmas/haex-hive",
            "harness_sources": [{"repository": "self"}],
        }
    ).encode("utf-8")
    with pytest.raises(PermissionOnlyEntryError):
        migrate_v1_to_v2(raw, consumer, self_migration_fixture["state_root"])


def test_refuses_plaintext_secret_in_input() -> None:
    raw = json.dumps(
        {
            "haex_hive_version": "1",
            "identity": "com.example.project",
            "harness_sources": [],
            "identity_note": "password=hunter22verylongvalue",
        }
    ).encode("utf-8")
    with pytest.raises(PlaintextSecretDetectedError):
        migrate_v1_to_v2(raw, Path("."), Path("."))


def test_transforms_self_reference_end_to_end(
    self_migration_fixture: dict, tmp_path: Path
) -> None:
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
                    "revision": self_migration_fixture["commit_a"][:12],
                    "path": ".specify/memory/constitution.md",
                }
            ],
            "groups": [],
            "active_feature": None,
        }
    ).encode("utf-8")

    v2 = migrate_v1_to_v2(raw, consumer, self_migration_fixture["state_root"])
    data = json.loads(v2.decode("utf-8"))
    assert data["haex_hive_version"] == "2"
    assert data["identity"] == "com.github.haexmas.haex-hive"
    assert data["atoms"] == [
        {
            "source": "https://github.com/haexmas/haex-hive",
            "revision": self_migration_fixture["commit_a"],
            "includes": ["com.github.haexmas.haex-hive.constitution"],
        }
    ]


def test_deterministic_output(self_migration_fixture: dict, tmp_path: Path) -> None:
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
    first = migrate_v1_to_v2(raw, consumer, self_migration_fixture["state_root"])
    second = migrate_v1_to_v2(raw, consumer, self_migration_fixture["state_root"])
    assert first == second
