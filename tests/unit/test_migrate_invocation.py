"""T043 — invocation-level behavior for chained `haex migrate` (Spec 013)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from haex_hive.cli import migrate as migrate_cli
from haex_hive.migrate.registry import ProposalRegistry


def _make_v3_consumer(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.example.project",
                "compounds": [],
            },
            indent=2,
        )
    )


def _make_v2_consumer_and_molecules(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "identity": "com.example.project",
                "atoms": [
                    {
                        "source": "https://example.com/publisher",
                        "revision": "a" * 40,
                        "includes": ["com.example.publisher.hello"],
                    }
                ],
            },
            indent=2,
        )
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "publisher": "com.example.publisher",
                "atoms": {
                    "com.example.publisher.hello": {
                        "path": "hello",
                        "version": "1.0.0",
                    }
                },
            },
            indent=2,
        )
    )
    mol_dir = root / "hello"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "id": "com.example.publisher.hello",
                "version": "1.0.0",
                "contributes": {"constitution": "constitution.md"},
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text("# hi\n")


def _run_migrate(repo_root: Path, *, dry_run: bool = False, check: bool = False) -> int:
    ns = SimpleNamespace(repo_root=str(repo_root), dry_run=dry_run, check=check)
    return migrate_cli.run(ns)


def test_idempotency_on_all_v3_inputs(tmp_path: Path) -> None:
    _make_v3_consumer(tmp_path / "repo")
    rc = _run_migrate(tmp_path / "repo")
    assert rc == 0
    assert not (tmp_path / "repo" / ".haex-hive.json.migrated").exists()


def test_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    _make_v2_consumer_and_molecules(tmp_path / "repo")
    rc = _run_migrate(tmp_path / "repo", dry_run=True)
    assert rc == 0
    assert not any(tmp_path.rglob("*.migrated"))


def test_check_does_not_touch_filesystem(tmp_path: Path) -> None:
    _make_v2_consumer_and_molecules(tmp_path / "repo")
    rc = _run_migrate(tmp_path / "repo", check=True)
    assert rc == 0
    assert not any(tmp_path.rglob("*.migrated"))


def test_write_mode_emits_all_proposals(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _make_v2_consumer_and_molecules(repo)
    rc = _run_migrate(repo)
    assert rc == 0
    assert (repo / ".haex-hive.json.migrated").exists()
    assert (repo / "manifest.json.migrated").exists()
    assert (repo / "hello" / "manifest.json.migrated").exists()


def test_registry_rollback_removes_registered_files(tmp_path: Path) -> None:
    """Every path registered before a failure is unlinked on rollback."""
    registry = ProposalRegistry()
    a = tmp_path / "a.migrated"
    b = tmp_path / "b.migrated"
    registry.emit(a, b"a\n")
    registry.emit(b, b"b\n")
    assert a.exists() and b.exists()
    registry.rollback()
    assert not a.exists()
    assert not b.exists()


def test_registry_commit_keeps_files(tmp_path: Path) -> None:
    registry = ProposalRegistry()
    p = tmp_path / "p.migrated"
    registry.emit(p, b"payload\n")
    registry.commit()
    assert p.exists()
    # commit clears the internal list but does not delete the file.
    assert registry.registered == ()


def test_dry_run_and_check_mutually_exclusive(tmp_path: Path) -> None:
    _make_v2_consumer_and_molecules(tmp_path / "repo")
    from haex_hive.util import exit_codes

    rc = _run_migrate(tmp_path / "repo", dry_run=True, check=True)
    assert rc == exit_codes.USAGE
