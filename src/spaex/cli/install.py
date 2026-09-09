"""`haex install` handler (Spec 008, US1 MVP).

Resolves `.spaex.json`'s adopted atoms and publishes a new generation
via the rename-swap primitive. Idempotent: a re-invocation with an
unchanged effective input set is a no-op and reports "no changes" without
allocating a new generation ID or touching disk.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from pathlib import Path

from spaex.constitution.publish import (
    CONSTITUTION_PATH,
    publish_constitution,
    stage_constitution,
)
from spaex.constitution.resolve import (
    ResolvedMolecule,
    resolve_install_inputs,
)
from spaex.install import inflight
from spaex.install.hook_runner import HookOutcomeKind, run_install_hook
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
from spaex.model.install_lock import HookStatus, InstallLock
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
    hook_status: HookStatus | None = None,
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
    return (
        recorded.paths == (CONSTITUTION_PATH,)
        and recorded.hook_status == hook_status
    )


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
            contributions, resolved = resolve_install_inputs(manifest, state_root)
            contributing_ids = {contribution.source.id for contribution in contributions}
            _refuse_hook_only_in_mvp(
                resolved,
                contributing_ids=contributing_ids,
            )

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

            # Hooks MUST run on every invocation per FR-024. Execute them
            # before the no-op check so a re-install still exercises each
            # declared hook idempotently. Hook-only-transaction (FR-025) is
            # deferred to T039; MVP happy path publishes when the body
            # differs and skips otherwise, matching pre-Spec-016 idempotency.
            hook_enabled = any(
                record.molecule_id in contributing_ids and record.install_hook is not None
                for record in resolved
            )
            candidate_matches = _is_no_op_single_source(
                repo_root,
                assembled_body,
                contribution.source.id,
                contribution.source.revision,
                contribution.source.source,
                hook_status="ok" if hook_enabled else None,
            )
            stage_context = (
                stage_constitution(contributions, repo_root, state_root=state_root)
                if hook_enabled and not candidate_matches
                else nullcontext()
            )
            with stage_context:
                hook_status = _run_hooks_for_mvp(
                    resolved,
                    contributing_ids=contributing_ids,
                    repo_root=repo_root,
                    state_root=state_root,
                )

            if _is_no_op_single_source(
                repo_root,
                assembled_body,
                contribution.source.id,
                contribution.source.revision,
                contribution.source.source,
                hook_status=hook_status.get(contribution.source.id),
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
                hook_status=hook_status.get(contribution.source.id),
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


def _refuse_hook_only_in_mvp(
    resolved: list[ResolvedMolecule], *, contributing_ids: set[str]
) -> None:
    """MVP (US1) does not support molecules with install_hook and no constitution.

    Refusing early avoids silently dropping a hook-only molecule when it is
    selected alongside a constitution-contributing molecule. Support for
    running hook-only molecules lands with User Story 4 (T035-T038).
    """
    for record in resolved:
        if (
            record.install_hook is not None
            and record.molecule_id not in contributing_ids
        ):
            raise HaexError(
                message=(
                    f"molecule {record.molecule_id!r} declares install_hook but "
                    "no atoms.constitution; hook-only molecules are out of scope "
                    "for the Spec 016 MVP (US1)"
                ),
                context={"molecule_id": record.molecule_id},
                diagnostic_key="install-failed",
                exit_code=exit_codes.INPUT_REFUSE,
            )


def _run_hooks_for_mvp(
    resolved: list[ResolvedMolecule],
    *,
    contributing_ids: set[str],
    repo_root: Path,
    state_root: Path,
) -> dict[str, HookStatus]:
    """Hook orchestration with per-molecule on_failure policy.

    Iterates resolved molecules in resolver order (ascending effective
    priority, ties broken by UTF-8 molecule id) and runs each declared
    install_hook. A non-OK outcome under ``on_failure="abort"`` raises
    ``install-failed`` with ``molecule_id`` + ``hook_failure`` context
    (FR-016, FR-017), which trips the Spec-008 stage-generation rollback
    via the enclosing ``stage_constitution`` context and, upstream,
    ``write_and_reinstall``'s ``.spaex.json`` restore. A non-OK outcome
    under ``on_failure="warn"`` records ``hook_status="failed"``, emits
    ONE ``WARN:`` line on stderr naming the molecule id and failure
    reason (after the hook subprocess has exited so its inherited stderr
    is never prefixed, FR-019), and continues with the next molecule
    (FR-018, FR-022).
    """
    statuses: dict[str, HookStatus] = {}
    for record in resolved:
        if record.molecule_id not in contributing_ids or record.install_hook is None:
            continue
        outcome = run_install_hook(
            record, consumer_repo_root=repo_root, state_root=state_root
        )
        if outcome.kind is HookOutcomeKind.OK:
            statuses[record.molecule_id] = "ok"
            continue
        reason = outcome.reason or (
            f"exit_{outcome.exit_code}"
            if outcome.exit_code is not None
            else outcome.kind.name.lower()
        )
        if record.install_hook.on_failure == "warn":
            statuses[record.molecule_id] = "failed"
            sys.stderr.write(
                f"WARN: molecule {record.molecule_id} install_hook failed "
                f"({reason})\n"
            )
            sys.stderr.flush()
            continue
        raise HaexError(
            message=(
                f"install_hook for molecule {record.molecule_id!r} failed: {reason}"
            ),
            context={
                "molecule_id": record.molecule_id,
                "hook_failure": reason,
            },
            diagnostic_key="install-failed",
            exit_code=exit_codes.INPUT_REFUSE,
        )
    return statuses
