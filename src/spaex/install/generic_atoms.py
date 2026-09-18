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
written. That rollback only covers `.spaex/` itself (ADR 0026), though —
these root files live outside it — so `publish.py` additionally snapshots
every delivered target via `snapshot_delivered_targets` before writing and
restores that snapshot (`restore_delivered_targets`) if anything in the same
`post_write_verify` call fails afterward, including the orphan-cleanup step
that runs after these writes. Root-file deletion for a retracted molecule
reuses the existing `_delete_orphaned_paths` orphan-cleanup mechanism
(extended for FR-007's content-hash check), since it already deletes any
path no longer present in `install.lock` once a generation publishes
successfully.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from stat import S_IMODE

from spaex.constitution.resolve import ResolvedMolecule
from spaex.io import atomic
from spaex.model.atom_category import is_exclusive
from spaex.util.errors import (
    ExclusiveAtomPathCollisionError,
    ExclusiveAtomPathEscapesRepoError,
    ExclusiveAtomPathUnsupportedShapeError,
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


def _is_lock_compatible_path(rel_path: str) -> bool:
    """Whether `rel_path` matches one of install.lock's two accepted shapes.

    `install-lock.v4.schema.json`'s `paths` items only accept a bare
    single-segment filename or a path whose first segment starts with a
    literal dot (data-model.md's `InstallLock extension`). A molecule
    manifest's own path validation (`RepoRelativePath.validate`, already run
    at manifest-parse time) is looser — it only forbids absolute paths,
    backslashes, control characters, and `.`/`..` segments — so a nested
    non-dot-prefixed path like `config/tool.toml` would otherwise pass
    manifest parsing yet fail the very next `install.lock` read. Only the
    segment-shape check remains here; character-safety is already covered.
    """
    if "/" not in rel_path:
        return True
    first_segment = rel_path.split("/", 1)[0]
    return first_segment.startswith(".")


def collect_exclusive_atoms(
    resolved: Sequence[ResolvedMolecule], *, repo_root: Path
) -> tuple[DeliveredFile, ...]:
    """Resolve every exclusive-category file each molecule declares.

    Refuses (`exclusive-atom-path-unsupported-shape`) when a declared path
    cannot round-trip through install.lock's schema — see
    `_is_lock_compatible_path`.

    Refuses (FR-003) when two *different* currently-resolved molecules
    declare the same destination path under an exclusive category — new
    cross-molecule enforcement; unlike `atoms-category-overlap` (one
    molecule's own manifest, checked at parse time), this can only be
    checked once every adopted molecule's manifest is known together.
    Ownership is tracked by each path's *canonical* destination (FR-010's
    symlink resolution), not its declared text: two distinct declared paths
    that resolve to the same real file (one a symlink to the other) must
    still be refused as a collision, since only one of the two writes could
    ever actually land. Molecules are visited in `molecule_id` order so
    which one is reported as the pre-existing owner in a collision is
    deterministic.

    Returns entries sorted by `path`, so a caller building deterministic
    output (install.lock's molecule map, `write_delivered_files`'s write
    order) never depends on resolver iteration order.
    """
    owner_by_destination: dict[Path, str] = {}
    delivered: list[DeliveredFile] = []
    for record in sorted(resolved, key=lambda r: r.molecule_id):
        manifest = record.molecule_manifest
        if manifest is None or record.cache_dir is None:
            continue
        for category, rel_paths in manifest.atoms.items():
            if not is_exclusive(category):
                continue
            for rel_path in rel_paths:
                if not _is_lock_compatible_path(rel_path):
                    raise ExclusiveAtomPathUnsupportedShapeError(
                        message=(
                            f"exclusive atom path {rel_path!r} declared by "
                            f"{record.molecule_id!r} is not a bare root-level "
                            "filename or a dot-segment-prefixed nested path"
                        ),
                        context={"path": rel_path, "molecule_id": record.molecule_id},
                    )
                destination = _canonical_destination(rel_path, repo_root=repo_root)
                existing_owner = owner_by_destination.get(destination)
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
                owner_by_destination[destination] = record.molecule_id
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
    fold into install.lock's `content_hashes` map. Does not itself roll back
    on partial failure: a caller publishing through `post_write_verify`
    (`spaex.constitution.publish`) snapshots every target first via
    `snapshot_delivered_targets` and restores that snapshot
    (`restore_delivered_targets`) if this call or a step after it fails,
    since `transaction.publish_generation`'s swap-rollback only covers
    `.spaex/` itself (ADR 0026), not these root-level targets.
    """
    hashes: dict[str, str] = {}
    for file in delivered:
        target = _canonical_destination(file.path, repo_root=repo_root)
        atomic.write_replace(target, file.content)
        hashes[file.path] = content_hash(file.content)
    return hashes


@dataclass(frozen=True)
class _DeliveredTargetSnapshot:
    """A delivered file's destination content just before `write_delivered_files`."""

    target: Path
    previous_content: bytes | None
    previous_mode: int | None


def snapshot_delivered_targets(
    delivered: Sequence[DeliveredFile], *, repo_root: Path
) -> tuple[_DeliveredTargetSnapshot, ...]:
    """Capture every delivered file's destination content before any writes.

    `None` content records that the target did not exist (or was a symlink,
    left untouched the same way `_delete_orphaned_paths` leaves symlinks
    alone) prior to this generation, so `restore_delivered_targets` knows to
    delete it rather than rewrite it during rollback.
    """
    snapshot: list[_DeliveredTargetSnapshot] = []
    for file in delivered:
        target = _canonical_destination(file.path, repo_root=repo_root)
        if target.exists() and not target.is_symlink():
            previous_content: bytes | None = target.read_bytes()
            previous_mode: int | None = S_IMODE(target.stat().st_mode)
        else:
            previous_content = None
            previous_mode = None
        snapshot.append(_DeliveredTargetSnapshot(target, previous_content, previous_mode))
    return tuple(snapshot)


def restore_delivered_targets(snapshot: Sequence[_DeliveredTargetSnapshot]) -> None:
    """Undo `write_delivered_files` using a `snapshot_delivered_targets` result.

    Restores in reverse write order. A target with no prior content is
    deleted; a target that had content is rewritten atomically to its prior
    bytes and permission bits.
    """
    for entry in reversed(snapshot):
        if entry.previous_content is None:
            entry.target.unlink(missing_ok=True)
        else:
            atomic.write_replace(entry.target, entry.previous_content)
            if entry.previous_mode is not None:
                entry.target.chmod(entry.previous_mode)


__all__ = [
    "DeliveredFile",
    "collect_exclusive_atoms",
    "content_hash",
    "restore_delivered_targets",
    "snapshot_delivered_targets",
    "write_delivered_files",
]
