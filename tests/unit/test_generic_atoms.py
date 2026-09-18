"""Unit tests for `spaex.install.generic_atoms` (Spec 027 CodeRabbit fixes).

Covers the three module-level invariants a full `spaex add`/`spaex remove`
integration test cannot easily isolate: snapshot/restore rollback semantics,
path-shape rejection for install.lock round-tripping, and collision
detection keyed by canonical (not declared-text) destination.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.install.generic_atoms import (
    DeliveredFile,
    collect_exclusive_atoms,
    restore_delivered_targets,
    snapshot_delivered_targets,
    write_delivered_files,
)
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.util.errors import (
    ExclusiveAtomPathCollisionError,
    ExclusiveAtomPathUnsupportedShapeError,
)


def _resolved(
    molecule_id: str, *, atoms: dict[str, list[str]], cache_dir: Path
) -> ResolvedMolecule:
    """Build a minimal `ResolvedMolecule` for these unit tests."""
    manifest = MoleculeManifest(
        spaex_version="4",
        id=molecule_id,
        version="1.0.0",
        priority=100,
        atoms={category: tuple(paths) for category, paths in atoms.items()},
    )
    return ResolvedMolecule(
        molecule_id=molecule_id,
        source_url="https://example.com/publisher",
        revision="0" * 40,
        repo_dir=cache_dir,
        molecule_path="mol",
        install_hook=None,
        effective_priority=100,
        molecule_manifest=manifest,
        cache_dir=cache_dir,
    )


def test_write_delivered_files_then_restore_snapshot_reverts_changes(
    tmp_path: Path,
) -> None:
    """`restore_delivered_targets` undoes exactly what `write_delivered_files` did.

    This is the mechanism `spaex.constitution.publish`'s `post_write_verify`
    relies on to keep the repository free of a mix of files from two
    generations when a later step in the same publish fails —
    `transaction.publish_generation`'s swap-rollback only covers `.spaex/`
    itself (ADR 0026).
    """
    (tmp_path / "flake.nix").write_text("old content\n")
    delivered = (
        DeliveredFile(path="flake.nix", owning_molecule_id="x", content=b"new content\n"),
        DeliveredFile(path="new-file.txt", owning_molecule_id="x", content=b"created\n"),
    )

    snapshot = snapshot_delivered_targets(delivered, repo_root=tmp_path)
    write_delivered_files(delivered, repo_root=tmp_path)
    assert (tmp_path / "flake.nix").read_text() == "new content\n"
    assert (tmp_path / "new-file.txt").exists()

    restore_delivered_targets(snapshot)
    assert (tmp_path / "flake.nix").read_text() == "old content\n"
    assert not (tmp_path / "new-file.txt").exists()


def test_collect_exclusive_atoms_rejects_nested_path_without_dot_segment(
    tmp_path: Path,
) -> None:
    """A nested exclusive path lacking a leading dot-segment cannot round-trip
    through install.lock's schema (only a bare filename or a dot-segment-
    prefixed nested path is accepted), so it must be refused at collection
    time rather than fail on the next `install.lock` read.
    """
    cache_dir = tmp_path / "cache"
    (cache_dir / "config").mkdir(parents=True)
    (cache_dir / "config" / "tool.toml").write_text("# config\n")
    resolved = [
        _resolved(
            "com.example.a", atoms={"dev_environment": ["config/tool.toml"]}, cache_dir=cache_dir
        )
    ]
    with pytest.raises(ExclusiveAtomPathUnsupportedShapeError):
        collect_exclusive_atoms(resolved, repo_root=tmp_path / "repo")


def test_collect_exclusive_atoms_accepts_dot_segment_nested_path(tmp_path: Path) -> None:
    """A dot-prefixed nested path remains a legitimate exclusive-atom shape."""
    cache_dir = tmp_path / "cache"
    (cache_dir / ".codex").mkdir(parents=True)
    (cache_dir / ".codex" / "foo.md").write_text("# foo\n")
    resolved = [
        _resolved(
            "com.example.a", atoms={"dev_environment": [".codex/foo.md"]}, cache_dir=cache_dir
        )
    ]
    delivered = collect_exclusive_atoms(resolved, repo_root=tmp_path / "repo")
    assert [d.path for d in delivered] == [".codex/foo.md"]


def test_collect_exclusive_atoms_detects_collision_via_symlinked_destination(
    tmp_path: Path,
) -> None:
    """Two declared paths that resolve to the same real file must collide.

    `foo` and `bar` are different declared strings, but if `bar` is a
    symlink to `foo`, both writes would land on the same canonical file —
    collision detection keyed only on declared text would miss this and let
    the second write silently clobber the first molecule's content.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    os.symlink(repo_root / "foo", repo_root / "bar")

    cache_a = tmp_path / "cache-a"
    cache_a.mkdir()
    (cache_a / "foo").write_text("# a\n")
    cache_b = tmp_path / "cache-b"
    cache_b.mkdir()
    (cache_b / "bar").write_text("# b\n")

    resolved = [
        _resolved("com.example.a", atoms={"dev_environment": ["foo"]}, cache_dir=cache_a),
        _resolved("com.example.b", atoms={"dev_environment": ["bar"]}, cache_dir=cache_b),
    ]
    with pytest.raises(ExclusiveAtomPathCollisionError):
        collect_exclusive_atoms(resolved, repo_root=repo_root)


def test_collect_exclusive_atoms_allows_distinct_unrelated_paths(tmp_path: Path) -> None:
    """Sanity check: unrelated declared paths never spuriously collide."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    cache_a = tmp_path / "cache-a"
    cache_a.mkdir()
    (cache_a / "foo").write_text("# a\n")
    cache_b = tmp_path / "cache-b"
    cache_b.mkdir()
    (cache_b / "bar").write_text("# b\n")

    resolved = [
        _resolved("com.example.a", atoms={"dev_environment": ["foo"]}, cache_dir=cache_a),
        _resolved("com.example.b", atoms={"dev_environment": ["bar"]}, cache_dir=cache_b),
    ]
    delivered = collect_exclusive_atoms(resolved, repo_root=repo_root)
    assert sorted(d.path for d in delivered) == ["bar", "foo"]
