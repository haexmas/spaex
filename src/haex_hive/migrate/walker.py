"""Enumerate v2 manifests present in a repository (Spec 013 T053).

Yields ``MigrationInput`` records for:

- ``.haex-hive.json`` at repo root (consumer)
- ``manifest.json`` at repo root, if it looks like a publisher root
- Every per-molecule ``manifest.json`` under paths declared by the publisher
  root.

Every yielded record names the local filesystem source path and the
proposal path per contracts/haex-migrate.v2-to-v3.md's placement table.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haex_hive.model.repo_relative_path import RepoRelativePath
from haex_hive.util.errors import (
    MigrationManifestInvalidError,
    MigrationPathOutsideRepositoryError,
)


@dataclass(frozen=True)
class MigrationInput:
    """One manifest to migrate + where its ``.migrated`` proposal lands."""

    kind: str  # "consumer" | "publisher-root" | "molecule"
    source: Path
    proposal: Path
    raw: bytes


def _sibling_proposal(path: Path) -> Path:
    return path.with_name(path.name + ".migrated")


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _publisher_molecules(publisher_data: dict[str, Any]) -> dict[str, Any]:
    """Return the v2 molecule map or refuse a structurally malformed value."""
    molecules = publisher_data.get("molecules") or publisher_data.get("atoms") or {}
    if not isinstance(molecules, dict):
        raise MigrationManifestInvalidError(
            message="publisher manifest molecules/atoms must be an object",
            context={"path": "manifest.json"},
        )
    return molecules


def _molecule_dir(repo_root: Path, path_value: str) -> Path:
    """Resolve a declared molecule directory without leaving ``repo_root``."""
    try:
        RepoRelativePath.validate(path_value)
    except ValueError as exc:
        raise MigrationPathOutsideRepositoryError(
            message=f"molecule path {path_value!r} is not repository-relative",
            context={"path": path_value},
        ) from exc

    root = repo_root.resolve()
    candidate = (root / path_value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MigrationPathOutsideRepositoryError(
            message=f"molecule path {path_value!r} resolves outside the repository",
            context={"path": path_value},
        ) from exc
    return candidate


def walk_local_manifests(repo_root: Path) -> Iterator[MigrationInput]:
    """Yield every local manifest that could be a migration input."""
    consumer = repo_root / ".haex-hive.json"
    if consumer.exists():
        yield MigrationInput(
            kind="consumer",
            source=consumer,
            proposal=_sibling_proposal(consumer),
            raw=consumer.read_bytes(),
        )

    publisher_root = repo_root / "manifest.json"
    publisher_data = _load_json_object(publisher_root) if publisher_root.exists() else None
    if publisher_data is not None and "publisher" in publisher_data:
        molecule_entries: list[tuple[Path, bytes]] = []
        molecules = _publisher_molecules(publisher_data)
        for entry in molecules.values():
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            molecule_manifest = _molecule_dir(repo_root, path_value) / "manifest.json"
            if molecule_manifest.exists():
                molecule_entries.append(
                    (molecule_manifest, molecule_manifest.read_bytes())
                )

        yield MigrationInput(
            kind="publisher-root",
            source=publisher_root,
            proposal=_sibling_proposal(publisher_root),
            raw=publisher_root.read_bytes(),
        )
        for molecule_manifest, raw in molecule_entries:
            yield MigrationInput(
                kind="molecule",
                source=molecule_manifest,
                proposal=_sibling_proposal(molecule_manifest),
                raw=raw,
            )
