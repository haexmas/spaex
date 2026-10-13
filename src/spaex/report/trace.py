"""Builds `FileAttribution` for `spaex trace` (data-model.md, Spec 028)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from spaex.cli.install import _load_consumer_manifest
from spaex.install import local_scope
from spaex.model.install_lock import InstallLock, read_with_consistent_generation
from spaex.paths import COMPOSED_CONSTITUTION_RELATIVE_PATH
from spaex.util.errors import UsageError


@dataclass(frozen=True)
class MoleculeOwner:
    """One molecule's identity for a `PathOwnership` entry."""

    molecule_id: str
    source: str
    revision: str
    scope: Literal["project", "local"] = "project"


@dataclass(frozen=True)
class PathOwnership:
    """One recorded path and every molecule that owns it (data-model.md)."""

    path: str
    owners: tuple[MoleculeOwner, ...]
    constitution_trace_hint: bool


@dataclass(frozen=True)
class FileAttribution:
    """Result of one `spaex trace` invocation (data-model.md)."""

    query: str
    kind: Literal["file", "directory"]
    matches: tuple[PathOwnership, ...]
    error: str | None


def normalize_query(repo_root: Path, raw: str) -> str:
    """Normalize a `spaex trace` path argument to repo-relative POSIX form (FR-011).

    Accepts a repo-relative path, an absolute path inside the repository, a
    `./`-prefixed path, and a trailing slash — all resolve to the same
    answer. Raises `UsageError` when `raw` resolves outside `repo_root`.
    """
    root = repo_root.resolve()
    resolved = (root / raw).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise UsageError(
            message=f"{raw!r} resolves outside the repository",
            context={"path": raw},
        ) from None
    return relative.as_posix()


def _owners_by_path(
    project: InstallLock, local: InstallLock | None
) -> dict[str, tuple[MoleculeOwner, ...]]:
    """Every recorded path with its owners, project scope first (Spec 029)."""
    owners: dict[str, list[MoleculeOwner]] = {}
    scoped: list[tuple[Literal["project", "local"], InstallLock]] = [("project", project)]
    if local is not None:
        scoped.append(("local", local))
    for scope, lock in scoped:
        for molecule in lock.molecules:
            for path in molecule.paths:
                owners.setdefault(path, []).append(
                    MoleculeOwner(molecule.id, molecule.source, molecule.revision, scope)
                )
    return {path: tuple(entries) for path, entries in owners.items()}


def resolve_trace_query(repo_root: Path, query: str) -> FileAttribution:
    """Resolve a `spaex trace` query against the install lock's recorded paths (research.md R2)."""
    normalized = normalize_query(repo_root, query)

    def _build(lock: InstallLock) -> FileAttribution:
        _load_consumer_manifest(repo_root)  # gate only: propagates its HaexError

        owners_map = _owners_by_path(lock, local_scope.read_local_lock(repo_root))

        if normalized in owners_map:
            kind: Literal["file", "directory"] = "file"
            matched_paths = [normalized]
        else:
            prefix = "" if normalized == "." else f"{normalized}/"
            matched_paths = sorted(p for p in owners_map if p.startswith(prefix))
            kind = "directory" if matched_paths else "file"

        if not matched_paths:
            return FileAttribution(
                query=normalized,
                kind=kind,
                matches=(),
                error=f"no molecule is recorded for {normalized}",
            )

        matches = tuple(
            PathOwnership(
                path=path,
                owners=owners_map[path],
                constitution_trace_hint=(path == COMPOSED_CONSTITUTION_RELATIVE_PATH),
            )
            for path in matched_paths
        )
        return FileAttribution(query=normalized, kind=kind, matches=matches, error=None)

    return read_with_consistent_generation(repo_root, _build)
