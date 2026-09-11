"""`haex install` handler (Spec 008, US1 MVP).

Resolves `.spaex.json`'s adopted atoms and publishes a new generation
via the rename-swap primitive. Idempotent: a re-invocation with an
unchanged effective input set is a no-op and reports "no changes" without
allocating a new generation ID or touching disk.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.constitution.publish import (
    CONSTITUTION_PATH,
    publish_constitution,
    stage_constitution,
)
from spaex.constitution.resolve import (
    ResolvedConstitutionContribution,
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
from spaex.model.install_lock import HookStatus, InstallLock, MoleculeEntry
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


def _is_no_op(
    repo_root: Path,
    expected_body: bytes | None,
    expected_records: Sequence[MoleculeEntry],
) -> bool:
    """True when the published state already matches the desired body + molecule map.

    Compares the constitution body byte-for-byte AND the complete molecule
    list (contributor plus hook-only records with their ``hook_status``)
    against what is currently on disk. Fields under transaction metadata
    (generation_id, written_at) are ignored: they change on every
    publication and are the whole reason for having a no-op path.

    Body semantics:

    * ``expected_body`` is ``bytes``: ``constitution.md`` must exist with
      matching bytes.
    * ``expected_body`` is ``None``: empty-constitution state,
      ``constitution.md`` must NOT exist.

    Molecule map: ``expected_records`` is sorted with the same key that
    ``_publish_constitution`` uses, so equality is a direct tuple compare
    against the on-disk lock's already-sorted ``molecules`` field. This
    covers FR-025's "atom bytes unchanged, hook_status map unchanged"
    clean no-op case for arbitrary molecule counts (contributor +
    hook-only), not just the single-source MVP shape.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    constitution_path = live_root / transaction.CONSTITUTION_NAME
    lock_path = live_root / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        return False
    if expected_body is None:
        if constitution_path.exists():
            return False
    else:
        if not constitution_path.exists():
            return False
        if constitution_path.read_bytes() != expected_body:
            return False
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return False
    expected_sorted = tuple(
        sorted(
            expected_records,
            key=lambda m: (m.id, m.source, m.revision, m.paths),
        )
    )
    return lock.molecules == expected_sorted


def _constitution_contributor_matches_disk(
    repo_root: Path,
    contribution: ResolvedConstitutionContribution,
) -> bool:
    """Return whether disk records the current constitution contributor."""
    lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        return False
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return False

    source = contribution.source
    return any(
        record.id == source.id
        and record.source == source.source
        and record.revision == source.revision
        and record.paths == (CONSTITUTION_PATH,)
        for record in lock.molecules
    )


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
    skip_hooks = bool(getattr(args, "skip_hooks", False))
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

            if not contributions:
                # Empty-constitution state: valid post-`haex remove` outcome
                # OR a set of hook-only molecules (no atoms.constitution).
                # Hook-only molecules must still see their install_hook run
                # and land a per-molecule hook_status record in install.lock
                # (Spec 016 FR-007, FR-021).
                hook_status = _run_hooks(
                    resolved,
                    repo_root=repo_root,
                    state_root=state_root,
                    skip_hooks=skip_hooks,
                )
                hook_only_records = _hook_only_records(
                    resolved,
                    contributing_ids=contributing_ids,
                    hook_status=hook_status,
                )
                # FR-025: publish only when the complete post-hook state
                # (empty constitution + molecule map with hook_status)
                # differs from disk. A hook-only re-install with an
                # identical hook_status map is a clean no-op.
                if _is_no_op(repo_root, None, hook_only_records):
                    inflight.clean_stale_siblings(
                        repo_root / transaction.SPAEX_DIR,
                        remove_prev=True,
                    )
                    sys.stdout.write("no changes\n")
                    _run_behavior_pipeline(
                        repo_root=repo_root,
                        state_root=state_root,
                        resolved=resolved,
                    )
                    return exit_codes.SUCCESS
                publish_constitution(
                    [],
                    repo_root,
                    state_root=state_root,
                    hook_only_records=tuple(hook_only_records),
                )
                new_generation_id = _live_generation_id(repo_root)
                if hook_only_records:
                    sys.stdout.write(
                        f"installed generation {new_generation_id}\n"
                    )
                else:
                    sys.stdout.write(
                        f"installed empty generation {new_generation_id}\n"
                    )
                _run_behavior_pipeline(
                    repo_root=repo_root,
                    state_root=state_root,
                    resolved=resolved,
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

            # Hooks MUST run on every invocation per FR-024. Stage a
            # candidate constitution first ONLY when atom bytes differ
            # from what's published so the hook sees the incoming
            # constitution; if the body is unchanged, the hook already
            # sees the correct constitution on disk. The full no-op
            # decision (FR-025) is made AFTER hooks run, based on the
            # complete hook_status map.
            hook_present = any(
                record.install_hook is not None for record in resolved
            )
            hook_enabled = hook_present and not skip_hooks
            constitution_path = live_root / transaction.CONSTITUTION_NAME
            body_matches_disk = (
                constitution_path.exists()
                and constitution_path.read_bytes() == assembled_body
            )
            contributor_matches_disk = (
                body_matches_disk
                and _constitution_contributor_matches_disk(repo_root, contribution)
            )
            stage_context = (
                stage_constitution(contributions, repo_root, state_root=state_root)
                if hook_enabled and not contributor_matches_disk
                else nullcontext()
            )
            with stage_context:
                hook_status = _run_hooks(
                    resolved,
                    repo_root=repo_root,
                    state_root=state_root,
                    skip_hooks=skip_hooks,
                )

            hook_only_records = _hook_only_records(
                resolved,
                contributing_ids=contributing_ids,
                hook_status=hook_status,
            )
            # FR-025: no-op iff the complete post-hook state (atom bytes
            # AND every molecule's hook_status, contributor + hook-only)
            # matches disk. A hook_status delta with unchanged atom bytes
            # still publishes a new generation carrying only that delta.
            expected_records: list[MoleculeEntry] = [
                MoleculeEntry(
                    id=contribution.source.id,
                    source=contribution.source.source,
                    revision=contribution.source.revision,
                    paths=(CONSTITUTION_PATH,),
                    hook_status=hook_status.get(contribution.source.id),
                ),
                *hook_only_records,
            ]
            if _is_no_op(repo_root, assembled_body, expected_records):
                inflight.clean_stale_siblings(
                    repo_root / transaction.SPAEX_DIR,
                    remove_prev=True,
                )
                sys.stdout.write("no changes\n")
                _run_behavior_pipeline(
                    repo_root=repo_root,
                    state_root=state_root,
                    resolved=resolved,
                )
                return exit_codes.SUCCESS

            publish_constitution(
                contributions,
                repo_root,
                state_root=state_root,
                hook_status=hook_status.get(contribution.source.id),
                hook_only_records=tuple(hook_only_records),
            )
            new_generation_id = _live_generation_id(repo_root)
            sys.stdout.write(f"installed generation {new_generation_id}\n")
            _run_behavior_pipeline(
                repo_root=repo_root,
                state_root=state_root,
                resolved=resolved,
            )
            return exit_codes.SUCCESS
    except HaexError:
        raise
    except (OSError, ValueError) as exc:
        raise HaexError(
            message=f"install failed: {exc}",
            diagnostic_key="install-failed",
            exit_code=exit_codes.INPUT_REFUSE,
        ) from exc


def _run_hooks(
    resolved: list[ResolvedMolecule],
    *,
    repo_root: Path,
    state_root: Path,
    skip_hooks: bool = False,
) -> dict[str, HookStatus]:
    """Hook orchestration with per-molecule on_failure policy.

    Iterates ``resolved`` in the resolver's canonical order (the sort
    key ``(effective_priority, molecule_id.encode("utf-8"))`` applied
    ascending in `resolve_install_inputs`), satisfying FR-010. Every
    declared install_hook is invoked, whether the molecule contributes
    to the constitution or is hook-only (FR-007).

    A non-OK outcome under ``on_failure="abort"`` raises ``install-failed``
    with ``molecule_id`` + ``hook_failure`` context (FR-016, FR-017),
    which trips the Spec-008 stage-generation rollback via the enclosing
    ``stage_constitution`` context and, upstream, ``write_and_reinstall``'s
    ``.spaex.json`` restore. A non-OK outcome under ``on_failure="warn"``
    records ``hook_status="failed"``, emits ONE ``WARN:`` line on stderr
    naming the molecule id and failure reason (after the hook subprocess
    has exited so its inherited stderr is never prefixed, FR-019), and
    continues with the next molecule (FR-018, FR-022).

    When ``skip_hooks`` is true (Spec 016 FR-026), no hook subprocess is
    launched; every resolved molecule declaring ``install_hook`` is
    recorded as ``hook_status="skipped"`` (FR-023, FR-028).
    """
    statuses: dict[str, HookStatus] = {}
    for record in resolved:
        if record.install_hook is None:
            continue
        if skip_hooks:
            statuses[record.molecule_id] = "skipped"
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


def _run_behavior_pipeline(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: list[ResolvedMolecule],
) -> None:
    """Spec 023 behavior-harness pass.

    Runs after the Spec 008 `.spaex/` rename-swap so behavior-authored
    files (`.spaex/constitution.d/`, `.spaex.md`, `.spaex/clarifications.json`)
    survive the swap. Fast-path exits when no molecule declares behavior
    fragments (plan.md §Backward compatibility). Composer + emit
    failures surface as typed HaexError with exit codes 20-22 / 30-34.
    """
    outcome = behavior_orchestrate.run(
        repo_root=repo_root,
        state_root=state_root,
        resolved=resolved,
    )
    if outcome.published and not outcome.skipped_composer:
        sys.stdout.write(
            f"composed .spaex.md ({outcome.fragment_count} fragment(s))\n"
        )
    elif outcome.skipped_composer:
        sys.stdout.write(
            f"reused .spaex.md ({outcome.fragment_count} fragment(s), "
            "source_hash/build_input_hash unchanged)\n"
        )
    elif outcome.removed_spaex_md:
        sys.stdout.write("removed .spaex.md (no active fragments)\n")
    if outcome.published or outcome.skipped_composer:
        # T036: nudge the operator to run `spaex install --global` when no
        # runtime has the bootstrap block yet, so `.spaex.md` gets picked up.
        from spaex.cli import behavior_commands  # local import to avoid cycles

        behavior_commands.maybe_emit_no_bootstrap_hint()


def _hook_only_records(
    resolved: list[ResolvedMolecule],
    *,
    contributing_ids: set[str],
    hook_status: dict[str, HookStatus],
) -> list[MoleculeEntry]:
    """Build install.lock records for hook-only molecules (paths=()).

    A record is emitted for every resolved molecule that declares
    ``install_hook`` and does NOT contribute an ``atoms.constitution``
    file. The constitution-contributing molecule's record is created
    elsewhere by ``publish_constitution``. Records only appear here for
    molecules whose hook actually reached a status in ``hook_status``
    (i.e. skipped by the caller when a preceding abort short-circuited
    later hooks).
    """
    return [
        MoleculeEntry(
            id=record.molecule_id,
            source=record.source_url,
            revision=record.revision,
            paths=(),
            hook_status=hook_status.get(record.molecule_id),
        )
        for record in resolved
        if record.install_hook is not None
        and record.molecule_id not in contributing_ids
        and record.molecule_id in hook_status
    ]
