"""Materialize exclusive generic atom-category files (Spec 027).

Exclusive categories (any `atoms` key other than `behavior`, `skill`,
`skills`, and the composable `nix_packages` category — see
`spaex.model.atom_category`) are delivered verbatim to a repo-root-relative
destination, one owning molecule per path (FR-001/FR-003), overwriting any
pre-existing file spaex does not already own (FR-006).

Writing happens inside the existing `.spaex/` publish transaction's
`post_write_verify` callback (see `spaex.constitution.publish`), not before
it: a write failure there rolls the whole generation back via
`transaction.publish_generation`'s existing swap-rollback path, so a failed
write never leaves `install.lock` claiming a file that was not actually
written. Root-file deletion for a retracted molecule reuses the existing
`_delete_orphaned_paths` orphan-cleanup mechanism (extended for FR-007's
content-hash check), since it already deletes any path no longer present in
`install.lock` once a generation publishes successfully.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spaex.constitution.resolve import ResolvedMolecule
from spaex.io import atomic
from spaex.model.atom_category import is_exclusive
from spaex.util.errors import (
    ExclusiveAtomPathCollisionError,
    ExclusiveAtomPathEscapesRepoError,
)


def content_hash(data: bytes) -> str:
    """Return the `sha256:<hex>` digest install.lock's `content_hashes` records."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass(frozen=True)
class DeliveredFile:
    """One exclusive-category file to materialize at the consumer repo root."""

    path: str
    owning_molecule_id: str
    content: bytes


def collect_exclusive_atoms(
    resolved: Sequence[ResolvedMolecule],
) -> tuple[DeliveredFile, ...]:
    """Resolve every exclusive-category file each molecule declares.

    Refuses (FR-003) when two *different* currently-resolved molecules
    declare the same destination path under an exclusive category — new
    cross-molecule enforcement; unlike `atoms-category-overlap` (one
    molecule's own manifest, checked at parse time), this can only be
    checked once every adopted molecule's manifest is known together.
    Molecules are visited in `molecule_id` order so which one is reported
    as the pre-existing owner in a collision is deterministic.

    Returns entries sorted by `path`, so a caller building deterministic
    output (install.lock's molecule map, `write_delivered_files`'s write
    order) never depends on resolver iteration order.
    """
    owner_by_path: dict[str, str] = {}
    delivered: list[DeliveredFile] = []
    for record in sorted(resolved, key=lambda r: r.molecule_id):
        manifest = record.molecule_manifest
        if manifest is None or record.cache_dir is None:
            continue
        for category, rel_paths in manifest.atoms.items():
            if not is_exclusive(category):
                continue
            for rel_path in rel_paths:
                existing_owner = owner_by_path.get(rel_path)
                if existing_owner is not None and existing_owner != record.molecule_id:
                    raise ExclusiveAtomPathCollisionError(
                        message=(
                            f"path {rel_path!r} is declared as an exclusive atom by "
                            f"both {existing_owner!r} and {record.molecule_id!r}"
                        ),
                        context={
                            "path": rel_path,
                            "molecule_a": existing_owner,
                            "molecule_b": record.molecule_id,
                        },
                    )
                owner_by_path[rel_path] = record.molecule_id
                source = record.cache_dir / rel_path
                delivered.append(
                    DeliveredFile(
                        path=rel_path,
                        owning_molecule_id=record.molecule_id,
                        content=source.read_bytes(),
                    )
                )
    return tuple(sorted(delivered, key=lambda d: d.path))


def _canonical_destination(rel_path: str, *, repo_root: Path) -> Path:
    """Resolve `rel_path` against `repo_root`, refusing an escape (FR-010).

    `Path.resolve()` resolves symlinks in every *existing* ancestor
    component even when the leaf itself does not exist yet, so this catches
    a symlinked ancestor directory redirecting the write outside the repo —
    not just a lexically unsafe path string (already rejected earlier, at
    manifest-parse time, by `RepoRelativePath.validate`).
    """
    resolved_root = repo_root.resolve()
    candidate = (resolved_root / rel_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise ExclusiveAtomPathEscapesRepoError(
            message=(
                f"exclusive atom destination {rel_path!r} resolves outside the "
                "repository root"
            ),
            context={"path": rel_path},
        ) from None
    return candidate


def write_delivered_files(
    delivered: Sequence[DeliveredFile], *, repo_root: Path
) -> dict[str, str]:
    """Write every delivered file atomically (FR-011), overwriting per FR-006.

    Returns `{path: content_hash}` for every path written, for the caller to
    fold into install.lock's `content_hashes` map.
    """
    hashes: dict[str, str] = {}
    for file in delivered:
        target = _canonical_destination(file.path, repo_root=repo_root)
        atomic.write_replace(target, file.content)
        hashes[file.path] = content_hash(file.content)
    return hashes


__all__ = [
    "DeliveredFile",
    "collect_exclusive_atoms",
    "content_hash",
    "write_delivered_files",
]
