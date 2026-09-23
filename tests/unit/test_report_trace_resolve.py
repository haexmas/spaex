"""Unit tests for `resolve_trace_query` (Spec 028 T026, research.md R2)."""

from __future__ import annotations

import json
from pathlib import Path

from spaex.model.install_lock import InstallLock, MoleculeEntry
from spaex.report.trace import resolve_trace_query

_SOURCE = "https://github.com/example/atoms"
_REV_A = "1" * 40
_REV_B = "2" * 40


def _write_manifest(repo: Path) -> None:
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.trace-consumer",
                "compounds": [],
            }
        ),
        encoding="utf-8",
    )


def _write_lock(repo: Path, molecules: tuple[MoleculeEntry, ...]) -> None:
    lock = InstallLock("4", "g_20260101T000000Z_0000", molecules)
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())


def test_single_owner_file(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _write_lock(
        tmp_path,
        (
            MoleculeEntry(
                id="com.example.atoms.nix-python",
                source=_SOURCE,
                revision=_REV_A,
                paths=("flake.nix",),
            ),
        ),
    )

    result = resolve_trace_query(tmp_path, "flake.nix")

    assert result.kind == "file"
    assert result.error is None
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.path == "flake.nix"
    assert match.constitution_trace_hint is False
    assert len(match.owners) == 1
    owner = match.owners[0]
    assert owner.molecule_id == "com.example.atoms.nix-python"
    assert owner.source == _SOURCE
    assert owner.revision == _REV_A


def test_shared_owner_path_and_constitution_hint(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _write_lock(
        tmp_path,
        (
            MoleculeEntry(
                id="com.example.atoms.ast-grep",
                source=_SOURCE,
                revision=_REV_B,
                paths=(".spaex/constitution.md",),
            ),
            MoleculeEntry(
                id="com.example.atoms.general-coding",
                source=_SOURCE,
                revision=_REV_A,
                paths=(".spaex/constitution.md",),
            ),
        ),
    )

    result = resolve_trace_query(tmp_path, ".spaex/constitution.md")

    assert result.kind == "file"
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.constitution_trace_hint is True
    owner_ids = {owner.molecule_id for owner in match.owners}
    assert owner_ids == {"com.example.atoms.general-coding", "com.example.atoms.ast-grep"}


def test_directory_prefix_match(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _write_lock(
        tmp_path,
        (
            MoleculeEntry(
                id="com.example.atoms.docs",
                source=_SOURCE,
                revision=_REV_A,
                paths=(".spaex/docs/one.md", ".spaex/docs/two.md", "README.md"),
            ),
        ),
    )

    result = resolve_trace_query(tmp_path, ".spaex/docs")

    assert result.kind == "directory"
    assert result.error is None
    assert [m.path for m in result.matches] == [".spaex/docs/one.md", ".spaex/docs/two.md"]


def test_no_match(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _write_lock(tmp_path, ())

    result = resolve_trace_query(tmp_path, "README.md")

    assert result.matches == ()
    assert result.error == "no molecule is recorded for README.md"


def test_constitution_hint_false_for_other_shared_paths(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _write_lock(
        tmp_path,
        (
            MoleculeEntry(
                id="com.example.atoms.nix-python",
                source=_SOURCE,
                revision=_REV_A,
                paths=(".spaex/generated/nix-packages.json",),
            ),
            MoleculeEntry(
                id="com.example.atoms.nix-rust",
                source=_SOURCE,
                revision=_REV_B,
                paths=(".spaex/generated/nix-packages.json",),
            ),
        ),
    )

    result = resolve_trace_query(tmp_path, ".spaex/generated/nix-packages.json")

    assert len(result.matches) == 1
    assert result.matches[0].constitution_trace_hint is False
