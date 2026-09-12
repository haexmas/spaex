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

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from stat import S_IMODE

from spaex.constitution.resolve import ResolvedConstitutionContribution
from spaex.constitution.safety import (
    validate_no_concealment_instructions,
    validate_no_plaintext_secrets,
)
from spaex.install.generation import allocate_generation_id
from spaex.io import atomic, transaction
from spaex.model.install_lock import HookStatus, InstallLock, MoleculeEntry
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
        # schema-incompatible existing lock is simply replaced wholesale by the fresh
        # generation below.
        return None


def _publish_constitution(
    molecules: Sequence[MoleculeEntry],
    body: bytes | None,
    repo_root: Path,
    *,
    state_root: Path | None = None,
    preserved_files: Sequence[transaction.StagedFile] = (),
) -> None:
    """Publish the effective constitution and install.lock atomically.

    Preserves unknown top-level lock fields from any existing lock and
    publishes every output file as one rename-swap generation with
    post-write verification.

    When ``body`` is ``None`` (no constitution to publish), only
    ``install.lock`` is staged and any pre-existing ``constitution.md``
    disappears with the rename-swap of ``.spaex/`` (delete-orphans via
    full-directory swap). Hook-only molecule records (paths=()) may still
    be present in ``molecules`` alongside the empty-body case.

    Args:
        molecules: Every molecule record to write to install.lock: the
            constitution contributor (if any) plus hook-only molecule
            records. Sorted canonically before publication.
        body: Effective constitution content, or None when no molecule
            contributes an ``atoms.constitution`` file this generation.
        repo_root: Repository root path.

    Raises:
        PostWriteValidationError: If the published files disagree.

    ``preserved_files`` contains source files inside the live `.spaex` tree
    that must survive the full-directory rename-swap.
    """
    existing_lock = _read_existing_lock(repo_root)
    unknown_top_level = (
        dict(existing_lock.unknown_top_level) if existing_lock is not None else {}
    )

    existing_generation_id = existing_lock.generation_id if existing_lock is not None else None
    # For the empty state, allocate against an empty payload so the ID still
    # advances deterministically past any prior generation.
    generation_seed = body if body is not None else b""
    generation_id = allocate_generation_id(generation_seed, existing_generation_id)
    molecules_tuple: tuple[MoleculeEntry, ...] = tuple(
        sorted(
            molecules,
            key=lambda m: (m.id, m.source, m.revision, m.paths),
        )
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

    staged_files: list[transaction.StagedFile] = list(preserved_files)
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
    hook_status: HookStatus | None = None,
    hook_only_records: Sequence[MoleculeEntry] = (),
    preserved_files: Sequence[transaction.StagedFile] = (),
) -> None:
    """Join all declared constitution files from one molecule and publish.

    The v3 ``atoms.constitution`` list may hold one file or several; when
    several, the tool concatenates them in the resolver's declared order
    (newline-separated) into the single effective constitution. The lock
    records that molecule once, with ``.spaex/constitution.md`` as
    its sole contributed path.

    When ``contributions`` is empty the empty-constitution state is
    published: ``install.lock`` with only the ``hook_only_records`` (if
    any) and any pre-existing ``constitution.md`` disappears via the
    rename-swap of ``.spaex/``.

    Optional ``hook_status`` records the Spec 016 install_hook outcome on
    the contributing molecule's install.lock entry. Pass ``None`` when the
    molecule declared no install_hook; the writer omits the field then.

    Optional ``hook_only_records`` carries per-molecule install.lock
    entries for hook-only molecules (paths=()) whose install_hook ran
    during this generation. They are merged into the sorted molecules
    array alongside the constitution contributor's record.

    ``preserved_files`` carries configured project-local source files through
    the full-directory rename-swap.
    """
    if not contributions:
        _publish_constitution(
            tuple(hook_only_records),
            None,
            repo_root,
            state_root=state_root,
            preserved_files=preserved_files,
        )
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
        hook_status=hook_status,
    )
    _publish_constitution(
        (molecule, *hook_only_records),
        b"\n".join(contribution.body for contribution in contributions),
        repo_root,
        state_root=state_root,
        preserved_files=preserved_files,
    )


@contextmanager
def stage_constitution(
    contributions: Sequence[ResolvedConstitutionContribution],
    repo_root: Path,
    *,
    state_root: Path | None = None,
    preserved_files: Sequence[transaction.StagedFile] = (),
) -> Iterator[None]:
    """Temporarily activate a candidate constitution for install hooks.

    The candidate contains the constitution and an install lock without hook
    status. It is atomically made visible before the context body runs and is
    rolled back if a hook raises. Successful callers must still invoke
    ``publish_constitution`` to write the final hook status. Any
    ``preserved_files`` are included in the temporary candidate as well.
    """
    if not contributions:
        raise ValueError("cannot stage an empty constitution")

    source = contributions[0].source
    if any(contribution.source != source for contribution in contributions[1:]):
        raise ValueError(
            "constitution staging received contributions from multiple molecules"
        )
    for contribution in contributions:
        validate_no_plaintext_secrets(
            contribution.body, location=f"constitution source {contribution.source.id}"
        )
        validate_no_concealment_instructions(contribution.body)

    existing_lock = _read_existing_lock(repo_root)
    existing_generation_id = (
        existing_lock.generation_id if existing_lock is not None else None
    )
    body = b"\n".join(contribution.body for contribution in contributions)
    generation_id = allocate_generation_id(body, existing_generation_id)
    lock = InstallLock(
        spaex_version="4",
        generation_id=generation_id,
        molecules=(
            MoleculeEntry(
                id=source.id,
                source=source.source,
                revision=source.revision,
                paths=(CONSTITUTION_PATH,),
            ),
        ),
        unknown_top_level=(
            dict(existing_lock.unknown_top_level) if existing_lock is not None else {}
        ),
    )
    lock_bytes = lock.to_json_bytes()
    InstallLock.from_json(lock_bytes)

    with transaction.stage_generation(
        repo_root / transaction.SPAEX_DIR,
        [
            *preserved_files,
            transaction.StagedFile(transaction.CONSTITUTION_NAME, body),
            transaction.StagedFile(transaction.INSTALL_LOCK_NAME, lock_bytes),
        ],
        state_root=state_root,
        repo_root=repo_root,
    ):
        yield
