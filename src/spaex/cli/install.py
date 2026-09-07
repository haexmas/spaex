"""`haex install` handler (Spec 008, US1 MVP).

Resolves `.spaex.json`'s adopted atoms and publishes a new generation
via the rename-swap primitive. Idempotent: a re-invocation with an
unchanged effective input set is a no-op and reports "no changes" without
allocating a new generation ID or touching disk.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spaex.constitution.publish import CONSTITUTION_PATH, publish_constitution
from spaex.constitution.resolve import resolve_constitution_contributions
from spaex.install import inflight
from spaex.install.lock import OwnerToken
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    MANIFEST_LOCK_NAME,
    MANIFEST_NAME,
    ManifestLockContext,
)
from spaex.io import transaction
from spaex.io.state import default_state_root, transaction_paths
from spaex.io.writer_lock import ConstitutionWriterLock
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import InstallLock
from spaex.util import exit_codes
from spaex.util.errors import ConstitutionAlreadyAdoptedError, HaexError


def _load_consumer_manifest(repo_root: Path) -> ConsumerManifest:
    """Load and validate the consumer's v4 harness manifest."""
    manifest_path = repo_root / MANIFEST_NAME
    if not manifest_path.exists():
        raise HaexError(
            message=".spaex.json not found",
            context={"path": str(manifest_path)},
            diagnostic_key="spaex-json-missing",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint=(
                "Run `spaex migrate`, review `.spaex.json.migrated`, and adopt "
                "it as `.spaex.json`."
            ),
        )
    raw = manifest_path.read_bytes()
    try:
        return ConsumerManifest.from_json(raw)
    except (ValueError, KeyError) as exc:
        raise HaexError(
            message=f".spaex.json is not a valid v4 manifest: {exc}",
            diagnostic_key="spaex-json-invalid",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint=(
                "Run `spaex migrate`, review `.spaex.json.migrated`, and adopt "
                "it as `.spaex.json`."
            ),
        ) from exc


def _live_generation_id(repo_root: Path) -> str | None:
    """Return the currently published generation ID, if one is available."""
    lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        return None
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return None
    return lock.generation_id


def _is_no_op_single_source(
    repo_root: Path,
    body: bytes,
    source_id: str,
    source_revision: str,
    source_url: str,
) -> bool:
    """True when on-disk publication already matches the single-source candidate.

    Compares the constitution body byte-for-byte and the recorded source
    identity, source URL, and revision. Fields under transaction metadata
    (generation_id, written_at) are ignored — those change on every
    publication and are the whole reason for having a no-op path.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    constitution_path = live_root / transaction.CONSTITUTION_NAME
    lock_path = live_root / transaction.INSTALL_LOCK_NAME
    if not (constitution_path.exists() and lock_path.exists()):
        return False
    if constitution_path.read_bytes() != body:
        return False
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return False
    if len(lock.molecules) != 1:
        return False
    recorded = lock.molecules[0]
    if (
        recorded.id != source_id
        or recorded.revision != source_revision
        or recorded.source != source_url
    ):
        return False
    return recorded.paths == (CONSTITUTION_PATH,)


def _is_no_op_empty(repo_root: Path) -> bool:
    """True when the on-disk state is already the empty-constitution state.

    Empty state on disk means: no constitution.md file present AND an
    install.lock whose molecules list is empty. Either condition failing
    means publication is required to reach the empty state.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    constitution_path = live_root / transaction.CONSTITUTION_NAME
    lock_path = live_root / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists() or constitution_path.exists():
        return False
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return False
    return len(lock.molecules) == 0


def run(
    args: argparse.Namespace,
    *,
    held_manifest_lock: ManifestLockContext | None = None,
) -> int:
    """`haex install` — US1 MVP: publish resolved atoms as a new generation.

    When ``held_manifest_lock`` is passed, install reuses the caller's
    acquired manifest lock via reference counting (Spec 013 T071). Standalone
    invocations acquire the manifest lock themselves before reading
    ``.spaex.json``; the install mutex is acquired second per FR-026.
    """
    repo_root = Path(args.repo_root).resolve()
    state_root = default_state_root()
    timeout_seconds = getattr(args, "lock_timeout", DEFAULT_LOCK_TIMEOUT_SECONDS)
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_LOCK_TIMEOUT_SECONDS
    manifest_lock = (
        held_manifest_lock
        if held_manifest_lock is not None
        else ManifestLockContext(
            repo_root / MANIFEST_LOCK_NAME,
            timeout_seconds=timeout_seconds,
        )
    )

    try:
        paths = transaction_paths(repo_root, state_root)
        with manifest_lock, ConstitutionWriterLock(paths.mutex, OwnerToken.emit()):
            live_root = repo_root / transaction.SPAEX_DIR
            # A missing live tree with a retained previous generation is the
            # one recovery step that must precede resolution: a failed retry
            # must not leave the repository without its last good generation.
            inflight.restore_previous_generation(live_root)
            inflight.clean_stale_siblings(live_root)

            manifest = _load_consumer_manifest(repo_root)
            contributions = resolve_constitution_contributions(manifest, state_root)

            if not contributions:
                # Empty-constitution state: valid post-`haex remove` outcome.
                # If the on-disk state is already empty, skip publication;
                # otherwise publish install.lock alone so orphan-cleanup via
                # the rename-swap removes any stale constitution.md.
                if _is_no_op_empty(repo_root):
                    inflight.clean_stale_siblings(
                        repo_root / transaction.SPAEX_DIR,
                        remove_prev=True,
                    )
                    sys.stdout.write("no changes\n")
                    return exit_codes.SUCCESS
                publish_constitution([], repo_root, state_root=state_root)
                new_generation_id = _live_generation_id(repo_root)
                sys.stdout.write(
                    f"installed empty generation {new_generation_id}\n"
                )
                return exit_codes.SUCCESS

            molecule_ids = sorted(
                {contribution.source.id for contribution in contributions}
            )
            if len(molecule_ids) != 1:
                raise ConstitutionAlreadyAdoptedError(
                    message=(
                        "multiple constitution contributions are not supported; "
                        f"currently resolved molecules: {', '.join(molecule_ids)}"
                    ),
                    context={"molecules": ",".join(molecule_ids)},
                )

            contribution = contributions[0]
            assembled_body = b"\n".join(
                contribution.body for contribution in contributions
            )
            if _is_no_op_single_source(
                repo_root,
                assembled_body,
                contribution.source.id,
                contribution.source.revision,
                contribution.source.source,
            ):
                inflight.clean_stale_siblings(
                    repo_root / transaction.SPAEX_DIR,
                    remove_prev=True,
                )
                sys.stdout.write("no changes\n")
                return exit_codes.SUCCESS

            publish_constitution(
                contributions,
                repo_root,
                state_root=state_root,
            )
            new_generation_id = _live_generation_id(repo_root)
            sys.stdout.write(f"installed generation {new_generation_id}\n")
            return exit_codes.SUCCESS
    except HaexError:
        raise
    except (OSError, ValueError) as exc:
        raise HaexError(
            message=f"install failed: {exc}",
            diagnostic_key="install-failed",
            exit_code=exit_codes.INPUT_REFUSE,
        ) from exc
