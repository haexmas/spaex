"""Constitution publication: join the declared source files and rename-swap.

`haex install`'s constitution-side terminal step. Two duties:

- **Join**: when a molecule declares `atoms.constitution: [a.md, b.md, ...]`
  the tool concatenates those file bytes (in the resolver's declared order,
  newline-separated) into the single effective constitution written to
  `.spaex/constitution.md`. That splitting exists purely for authoring
  maintainability; there is still only ever ONE effective constitution per
  adopted molecule set (ADR 0010).
- **Atomic publish**: writes the joined constitution plus install.lock as
  one rename-swap generation with post-write verification.

Post-ADR-0010 the module is single-branch: the LLM merge subsystem is
gone. What remains is joining N files that belong to the same molecule and
publishing the generation.

The empty case is also legitimate: an operator who ran `haex remove` on
their last constitution-contributing molecule adopts the empty state. In
that case only `install.lock` is staged (with `molecules=()` after orphan
cleanup) and the pre-existing `constitution.md` disappears with the
rename-swap of `.spaex/` (delete-orphans via full-directory swap).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from stat import S_IMODE

from spaex.constitution.resolve import ResolvedConstitutionContribution
from spaex.constitution.safety import (
    validate_no_concealment_instructions,
    validate_no_plaintext_secrets,
)
from spaex.install.generation import allocate_generation_id
from spaex.io import atomic, transaction
from spaex.model.install_lock import InstallLock, MoleculeEntry
from spaex.util.errors import HaexError, PostWriteValidationError

CONSTITUTION_PATH = f"{transaction.SPAEX_DIR}/{transaction.CONSTITUTION_NAME}"


def _delete_orphaned_paths(
    repo_root: Path,
    previous_lock: InstallLock | None,
    current_lock: InstallLock,
) -> None:
    """Delete recorded files no longer owned by the newly published lock.

    Files are backed up in memory until the publication callback returns. If a
    later unlink fails, earlier deletions are restored before the exception
    reaches ``publish_generation``, which then rolls the generation back too.
    Symlinked targets and paths resolving outside ``repo_root`` are ignored.
    """
    if previous_lock is None:
        return
    resolved_root = repo_root.resolve()
    previous_paths = {
        path for molecule in previous_lock.molecules for path in molecule.paths
    }
    current_paths = {path for molecule in current_lock.molecules for path in molecule.paths}
    deleted: list[tuple[Path, bytes, int]] = []
    try:
        for path in sorted(previous_paths - current_paths):
            if path.startswith(f"{transaction.SPAEX_DIR}/"):
                continue
            target = resolved_root / path
            if target.is_symlink() or not target.exists():
                continue
            resolved_target = target.resolve()
            try:
                resolved_target.relative_to(resolved_root)
            except ValueError:
                continue
            mode = S_IMODE(target.stat().st_mode)
            deleted.append((target, target.read_bytes(), mode))
            target.unlink()
    except OSError:
        for target, data, mode in reversed(deleted):
            atomic.write_replace(target, data)
            target.chmod(mode)
        raise


def _read_existing_lock(repo_root: Path) -> InstallLock | None:
    """Read the existing install.lock if present, returning None on error or absence.

    Best-effort forward-compat preservation; corrupt locks are treated as absent.
    """
    lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        return None
    try:
        return InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        # Best-effort forward-compat preservation only; a corrupt or
        # schema-incompatible existing lock (e.g. a pre-amendment lock read
        # by the current reader) is simply replaced wholesale by the fresh
        # generation below.
        return None


def _publish_constitution(
    molecule: MoleculeEntry | None,
    body: bytes | None,
    repo_root: Path,
    *,
    state_root: Path | None = None,
) -> None:
    """Publish the effective constitution and install.lock atomically.

    Preserves unknown top-level lock fields from any existing lock and
    publishes every output file as one rename-swap generation with
    post-write verification.

    When ``molecule`` is ``None`` (empty state), ``body`` must also be
    ``None``: only ``install.lock`` is staged with ``molecules=()`` and
    any pre-existing ``constitution.md`` disappears with the rename-swap
    of ``.spaex/`` (delete-orphans via full-directory swap).

    Args:
        molecule: The installed molecule this generation records, or None
            for the empty state.
        body: Effective constitution content, or None for the empty state.
        repo_root: Repository root path.

    Raises:
        PostWriteValidationError: If the published files disagree.
    """
    if (molecule is None) != (body is None):
        raise ValueError("molecule and body must both be None or both be set")

    existing_lock = _read_existing_lock(repo_root)
    unknown_top_level = (
        dict(existing_lock.unknown_top_level) if existing_lock is not None else {}
    )

    existing_generation_id = existing_lock.generation_id if existing_lock is not None else None
    # For the empty state, allocate against an empty payload so the ID still
    # advances deterministically past any prior generation.
    generation_seed = body if body is not None else b""
    generation_id = allocate_generation_id(generation_seed, existing_generation_id)
    molecules_tuple: tuple[MoleculeEntry, ...] = (
        () if molecule is None else (molecule,)
    )
    lock = InstallLock(
        spaex_version="4",
        generation_id=generation_id,
        molecules=molecules_tuple,
        unknown_top_level=unknown_top_level,
    )
    lock_bytes = lock.to_json_bytes()
    # Validate the complete lock envelope before any staged bytes are published.
    InstallLock.from_json(lock_bytes)

    def post_write_verify() -> None:
        """Verify the published install.lock matches the assembled generation.

        Raises:
            PostWriteValidationError: If digest mismatch detected.
        """
        lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
        published_lock = InstallLock.from_json(lock_path.read_bytes())
        if (
            published_lock.generation_id != generation_id
            or published_lock.molecules != molecules_tuple
        ):
            raise PostWriteValidationError(
                message="published install.lock does not match the assembled generation",
            )
        _delete_orphaned_paths(repo_root, existing_lock, lock)

    staged_files: list[transaction.StagedFile] = []
    if body is not None:
        staged_files.append(transaction.StagedFile(transaction.CONSTITUTION_NAME, body))
    staged_files.append(transaction.StagedFile(transaction.INSTALL_LOCK_NAME, lock_bytes))

    live_dir = repo_root / transaction.SPAEX_DIR
    transaction.publish_generation(
        live_dir,
        staged_files,
        post_write_verify=post_write_verify,
        state_root=state_root,
        repo_root=repo_root,
    )


def publish_constitution(
    contributions: Sequence[ResolvedConstitutionContribution],
    repo_root: Path,
    *,
    state_root: Path | None = None,
) -> None:
    """Join all declared constitution files from one molecule and publish.

    The v3 ``atoms.constitution`` list may hold one file or several; when
    several, the tool concatenates them in the resolver's declared order
    (newline-separated) into the single effective constitution. The lock
    records that molecule once, with ``.spaex/constitution.md`` as
    its sole contributed path.

    When ``contributions`` is empty the empty state is published:
    ``install.lock`` alone with ``molecules=()`` and any pre-existing
    ``constitution.md`` disappears via the rename-swap of ``.spaex/``.
    """
    if not contributions:
        _publish_constitution(None, None, repo_root, state_root=state_root)
        return

    source = contributions[0].source
    if any(contribution.source != source for contribution in contributions[1:]):
        raise ValueError(
            "constitution publication received contributions from multiple molecules"
        )

    for contribution in contributions:
        validate_no_plaintext_secrets(
            contribution.body, location=f"constitution source {contribution.source.id}"
        )
        # Principle VIII (ADR 0010): retained even without an adapter-produced
        # candidate to police.
        validate_no_concealment_instructions(contribution.body)

    molecule = MoleculeEntry(
        id=source.id,
        source=source.source,
        revision=source.revision,
        paths=(CONSTITUTION_PATH,),
    )
    _publish_constitution(
        molecule,
        b"\n".join(contribution.body for contribution in contributions),
        repo_root,
        state_root=state_root,
    )
