"""Spec 029 preflight: one Spec Kit policy per checkout (FR-013)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.install import local_scope
from spaex.util.errors import SpeckitDeclarationConflictError


def _record(molecule_id: str, *, speckit: bool) -> SimpleNamespace:
    return SimpleNamespace(
        molecule_id=molecule_id,
        molecule_manifest=SimpleNamespace(speckit=object() if speckit else None, atoms={}),
    )


def test_local_speckit_is_refused_when_project_declares_one(tmp_path: Path) -> None:
    with pytest.raises(SpeckitDeclarationConflictError, match="com.example.local"):
        local_scope.preflight(
            tmp_path,
            local=[_record("com.example.local", speckit=True)],  # type: ignore[list-item]
            project=[_record("com.example.project", speckit=True)],  # type: ignore[list-item]
            project_owned=(),
        )


def test_exclusion_paths_skip_spaex_files() -> None:
    lock = SimpleNamespace(
        molecules=(
            SimpleNamespace(paths=(".spaex/local/constitution.md", "mine.txt")),
            SimpleNamespace(paths=("generated/out.txt",)),
        )
    )
    assert local_scope.exclusion_paths(lock) == ("generated/out.txt", "mine.txt")  # type: ignore[arg-type]
