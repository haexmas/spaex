"""`spaex install` handler (Spec 008, US1 MVP).

Resolves `.spaex/manifest.json`'s adopted atoms and publishes a new generation
via the rename-swap primitive. Idempotent: a re-invocation with an
unchanged effective input set is a no-op and reports "no changes" without
allocating a new generation ID or touching disk.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from types import TracebackType
from typing import Literal

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.invoke import COMPOSER_LOG_ENV, DEFAULT_COMPOSER_LOG
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.materialize import project_local_from_config
from spaex.behavior.stale import STALE_FILENAME, StaleMarker, read_stale
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
from spaex.install.generic_atoms import DeliveredFile, collect_exclusive_atoms
from spaex.install.hook_runner import HookOutcomeKind, run_install_hook
from spaex.install.lock import OwnerToken
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ManifestLockContext,
    active_manifest_lock_path,
)
from spaex.install.nix_packages import (
    GENERATED_PACKAGES_PATH,
    ComposedFile,
    collect_package_fragments,
)
from spaex.install.nix_packages import compose as compose_nix_packages
from spaex.integrations.speckit import emit_results, prepare_install
from spaex.io import transaction
from spaex.io.state import default_state_root, transaction_paths
from spaex.io.writer_lock import ConstitutionWriterLock
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import (
    HookStatus,
    InstallLock,
    MoleculeEntry,
    SpeckitLockRecord,
)
from spaex.paths import (
    MANIFEST_RELATIVE_PATH,
    composed_constitution_path,
    manifest_path,
)
from spaex.skills.installer import pending_external_skill_molecules
from spaex.util import exit_codes
from spaex.util.errors import ConstitutionAlreadyAdoptedError, HaexError


def _load_consumer_manifest(repo_root: Path) -> ConsumerManifest:
    """Load and validate the consumer's v4 harness manifest."""
    path = manifest_path(repo_root)
    if not path.exists():
        raise HaexError(
            message=f"{MANIFEST_RELATIVE_PATH} not found",
            context={"path": str(path)},
            diagnostic_key="spaex-json-missing",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint=(
                "Create `.spaex/manifest.json` and retry."
            ),
        )
    raw = path.read_bytes()
    try:
        return ConsumerManifest.from_json(raw)
    except (ValueError, KeyError) as exc:
        raise HaexError(
            message=f"{MANIFEST_RELATIVE_PATH} is not a valid v4 manifest: {exc}",
            diagnostic_key="spaex-manifest-invalid",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint=(
                "Repair `.spaex/manifest.json` and retry."
            ),
        ) from exc


def _report_pending_external_skills(resolved: Sequence[ResolvedMolecule]) -> None:
    """FR-011: report `external_skills` as pending; never install them here."""
    pending = pending_external_skill_molecules(resolved)
    if not pending:
        return
    count = 0
    for record in pending:
        assert record.molecule_manifest is not None
        count += len(record.molecule_manifest.external_skills)
    sys.stdout.write(
        f"{count} external skill reference(s) pending across {len(pending)} molecule(s); "
        "run `spaex skills install` to install them\n"
    )


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
    *,
    allow_existing_behavior_artifact: bool = False,
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
    * ``expected_body`` is ``None``: no classic constitution contribution;
      ``constitution.md`` must not exist unless
      ``allow_existing_behavior_artifact`` is enabled for active behavior or
      project-local fragments.

    Molecule map: ``expected_records`` is sorted with the same key that
    ``_publish_constitution`` uses, so equality is a direct tuple compare
    against the on-disk lock's already-sorted ``molecules`` field. This
    covers FR-025's "atom bytes unchanged, hook_status map unchanged"
    clean no-op case for arbitrary molecule counts (contributor +
    hook-only), not just the single-source MVP shape.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    constitution_path = composed_constitution_path(repo_root)
    lock_path = live_root / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        return False
    try:
        lock = InstallLock.from_json(lock_path.read_bytes())
    except (OSError, ValueError, HaexError):
        return False
    if expected_body is None:
        # Behavior-only manifests also use `.spaex/constitution.md`. Their
        # molecule records now identify that shared output, so an existing
        # behavior artifact is valid even though there is no classic
        # atoms.constitution body in this install generation.
        if constitution_path.exists() and not allow_existing_behavior_artifact:
            return False
    else:
        if not constitution_path.exists():
            return False
        if constitution_path.read_bytes() != expected_body:
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
    ``.spaex/manifest.json``; the install mutex is acquired second per FR-026.
    """
    repo_root = Path(args.repo_root).resolve()
    state_root = default_state_root()
    skip_hooks = bool(getattr(args, "skip_hooks", False))
    abort_on_contradiction = bool(
        getattr(args, "abort_on_behavior_contradiction", True)
    )
    # T054/FR-010a: a real `spaex install` invocation (never an internal
    # add/remove-triggered one, which runs with abort_on_contradiction=False)
    # announces a pending FR-024a stale marker before the behavior pipeline
    # re-invokes the Composer and routes it through the reconciliation
    # prompt.
    if abort_on_contradiction:
        stale_marker = read_stale(repo_root / ".spaex" / STALE_FILENAME)
        if stale_marker is not None:
            _announce_stale_contradiction(stale_marker)
    timeout_seconds = getattr(args, "lock_timeout", DEFAULT_LOCK_TIMEOUT_SECONDS)
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_LOCK_TIMEOUT_SECONDS
    manifest_lock = (
        held_manifest_lock
        if held_manifest_lock is not None
        else ManifestLockContext(
            active_manifest_lock_path(repo_root),
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
            project_local = project_local_from_config(
                getattr(manifest, "local_fragments", ()), repo_root=repo_root
            )
            preserved_project_local_files = _preserved_project_local_files(
                repo_root, getattr(manifest, "local_fragments", ())
            )
            contributions, resolved = resolve_install_inputs(manifest, state_root)
            _report_pending_external_skills(resolved)
            delivered_files = collect_exclusive_atoms(resolved, repo_root=repo_root)
            composed_packages = compose_nix_packages(collect_package_fragments(resolved))
            extra_spaex_files = (
                (transaction.StagedFile(
                    GENERATED_PACKAGES_PATH.removeprefix(f"{transaction.SPAEX_DIR}/"),
                    composed_packages.to_json_bytes(),
                ),)
                if composed_packages is not None
                else ()
            )
            preserved_behavior_files = (
                _preserved_behavior_files(repo_root)
                if project_local or _has_behavior_fragments(resolved)
                else ()
            )
            preserved_files = (
                *preserved_project_local_files,
                *preserved_behavior_files,
            )
            contributing_ids = {contribution.source.id for contribution in contributions}
            existing_lock = _read_live_lock(repo_root)

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
                speckit_records = prepare_install(
                    resolved,
                    repo_root=repo_root,
                    existing_lock=existing_lock,
                    explicit_selection=getattr(args, "speckit_agents", None),
                    disabled=bool(getattr(args, "no_speckit_integrations", False)),
                )
                emit_results(speckit_records)
                hook_only_records = _hook_only_records(
                    resolved,
                    contributing_ids=contributing_ids,
                    hook_status=hook_status,
                    speckit_records=speckit_records,
                )
                hook_only_records = _augment_records_with_generic_atoms(
                    hook_only_records,
                    resolved=resolved,
                    delivered_files=delivered_files,
                    composed_packages=composed_packages,
                )
                # FR-025: publish only when the complete post-hook state
                # (empty constitution + molecule map with hook_status)
                # differs from disk. A hook-only re-install with an
                # identical hook_status map is a clean no-op.
                if _is_no_op(
                    repo_root,
                    None,
                    hook_only_records,
                    allow_existing_behavior_artifact=(
                        bool(project_local) or _has_behavior_fragments(resolved)
                    ),
                ):
                    inflight.clean_stale_siblings(
                        repo_root / transaction.SPAEX_DIR,
                        remove_prev=True,
                    )
                    sys.stdout.write("no changes\n")
                    _run_behavior_pipeline(
                        repo_root=repo_root,
                        state_root=state_root,
                        resolved=resolved,
                        project_local=project_local,
                        abort_on_contradiction=abort_on_contradiction,
                    )
                    return exit_codes.SUCCESS
                generation_context = _preserve_generation_for_behavior(
                    repo_root, resolved, project_local
                )
                stale_bytes_to_restore: bytes | None = None
                with generation_context:
                    if speckit_records:
                        publish_constitution(
                            [],
                            repo_root,
                            state_root=state_root,
                            hook_only_records=tuple(hook_only_records),
                            speckit_records=speckit_records.publication_records,
                            preserved_files=preserved_files,
                            extra_spaex_files=extra_spaex_files,
                            delivered_files=delivered_files,
                        )
                    else:
                        publish_constitution(
                            [],
                            repo_root,
                            state_root=state_root,
                            hook_only_records=tuple(hook_only_records),
                            preserved_files=preserved_files,
                            extra_spaex_files=extra_spaex_files,
                            delivered_files=delivered_files,
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
                    outcome = _run_behavior_pipeline(
                        repo_root=repo_root,
                        state_root=state_root,
                        resolved=resolved,
                        project_local=project_local,
                        abort_on_contradiction=abort_on_contradiction,
                    )
                    if (
                        not abort_on_contradiction
                        and _behavior_publication_deferred(outcome, resolved, project_local)
                    ):
                        stale_bytes_to_restore = _read_stale_bytes(repo_root)
                        rollback = getattr(generation_context, "rollback", None)
                        if rollback is not None:
                            rollback()
                if stale_bytes_to_restore is not None:
                    (repo_root / ".spaex" / STALE_FILENAME).write_bytes(
                        stale_bytes_to_restore
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
                stage_constitution(
                    contributions,
                    repo_root,
                    state_root=state_root,
                    preserved_files=preserved_files,
                )
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

            speckit_records = prepare_install(
                resolved,
                repo_root=repo_root,
                existing_lock=existing_lock,
                explicit_selection=getattr(args, "speckit_agents", None),
                disabled=bool(getattr(args, "no_speckit_integrations", False)),
            )
            emit_results(speckit_records)

            hook_only_records = _hook_only_records(
                resolved,
                contributing_ids=contributing_ids,
                hook_status=hook_status,
                speckit_records=speckit_records,
            )
            hook_only_records = _augment_records_with_generic_atoms(
                hook_only_records,
                resolved=resolved,
                delivered_files=delivered_files,
                composed_packages=composed_packages,
                exclude_ids=frozenset(contributing_ids),
            )
            # The constitution contributor's own record is built separately
            # (below and inside `publish_constitution`, not via
            # `_augment_records_with_generic_atoms`, which is why it is
            # excluded above): fold in any generic-atom paths *this same*
            # molecule also owns, so a molecule declaring both
            # `atoms.constitution` and a Spec 027 category gets every path
            # it contributed recorded against its one `install.lock` entry.
            contributor_extra_paths = _generic_atom_paths_for_molecule(
                contribution.source.id,
                delivered_files=delivered_files,
                composed_packages=composed_packages,
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
                    paths=tuple(sorted({CONSTITUTION_PATH, *contributor_extra_paths})),
                    hook_status=hook_status.get(contribution.source.id),
                    speckit=speckit_records.get(contribution.source.id),
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
                    project_local=project_local,
                    abort_on_contradiction=abort_on_contradiction,
                )
                return exit_codes.SUCCESS

            generation_context = _preserve_generation_for_behavior(
                repo_root, resolved, project_local
            )
            stale_bytes_to_restore = None
            with generation_context:
                if speckit_records:
                    publish_constitution(
                        contributions,
                        repo_root,
                        state_root=state_root,
                        hook_status=hook_status.get(contribution.source.id),
                        hook_only_records=tuple(hook_only_records),
                        speckit_records=speckit_records.publication_records,
                        preserved_files=preserved_files,
                        extra_spaex_files=extra_spaex_files,
                        delivered_files=delivered_files,
                        contributor_extra_paths=contributor_extra_paths,
                    )
                else:
                    publish_constitution(
                        contributions,
                        repo_root,
                        state_root=state_root,
                        hook_status=hook_status.get(contribution.source.id),
                        hook_only_records=tuple(hook_only_records),
                        preserved_files=preserved_files,
                        extra_spaex_files=extra_spaex_files,
                        delivered_files=delivered_files,
                        contributor_extra_paths=contributor_extra_paths,
                    )
                new_generation_id = _live_generation_id(repo_root)
                sys.stdout.write(f"installed generation {new_generation_id}\n")
                outcome = _run_behavior_pipeline(
                    repo_root=repo_root,
                    state_root=state_root,
                    resolved=resolved,
                    project_local=project_local,
                    abort_on_contradiction=abort_on_contradiction,
                )
                if (
                    not abort_on_contradiction
                    and _behavior_publication_deferred(outcome, resolved, project_local)
                ):
                    stale_bytes_to_restore = _read_stale_bytes(repo_root)
                    rollback = getattr(generation_context, "rollback", None)
                    if rollback is not None:
                        rollback()
            if stale_bytes_to_restore is not None:
                (repo_root / ".spaex" / STALE_FILENAME).write_bytes(
                    stale_bytes_to_restore
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


def _preserve_generation_for_behavior(
    repo_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment] = (),
) -> AbstractContextManager[None]:
    """Keep a copy of the live generation until behavior orchestration passes."""
    live = repo_root / transaction.SPAEX_DIR
    if not project_local and not _has_behavior_fragments(resolved):
        return nullcontext()

    backup_root = Path(
        tempfile.mkdtemp(prefix=".spaex-install-rollback-", dir=repo_root.parent)
    )
    backup_live = backup_root / transaction.SPAEX_DIR
    had_live = live.exists()
    if had_live:
        shutil.copytree(live, backup_live, symlinks=True)

    class _GenerationRollback(AbstractContextManager[None]):
        _rollback_requested = False

        def __enter__(self) -> None:
            return None

        def rollback(self) -> None:
            """Request restoration while allowing the caller to finish cleanly."""
            self._rollback_requested = True

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> Literal[False]:
            try:
                if exc_type is not None or self._rollback_requested:
                    raw_log_path = os.environ.get(COMPOSER_LOG_ENV)
                    composer_log = (
                        Path(raw_log_path)
                        if raw_log_path
                        else repo_root / DEFAULT_COMPOSER_LOG
                    )
                    if raw_log_path and not composer_log.is_absolute():
                        composer_log = Path.cwd() / composer_log
                    try:
                        preserved_log = (
                            composer_log.read_bytes() if composer_log.is_file() else None
                        )
                    except OSError:
                        preserved_log = None
                    if live.exists():
                        shutil.rmtree(live)
                    if had_live:
                        backup_live.rename(live)
                    if preserved_log is not None:
                        # The failure that triggered this rollback is what wrote
                        # the log (it postdates the backup snapshot), and the
                        # invalid-output hint sends the operator here to inspect
                        # it. Restoring the old generation must not erase it.
                        try:
                            composer_log.parent.mkdir(parents=True, exist_ok=True)
                            composer_log.write_bytes(preserved_log)
                        except OSError:
                            pass
            finally:
                shutil.rmtree(backup_root, ignore_errors=True)
            return False

    return _GenerationRollback()


def _preserved_project_local_files(
    repo_root: Path,
    entries: Sequence[Mapping[str, object]],
) -> tuple[transaction.StagedFile, ...]:
    """Snapshot the manifest and configured local files inside `.spaex`.

    The manifest is now part of the repository-local `.spaex/` tree. Since
    install publication swaps that directory as a whole, it must be carried
    into every generation alongside configured local fragment sources.
    """
    root = repo_root.resolve()
    preserved: dict[str, transaction.StagedFile] = {}
    manifest = manifest_path(root)
    if manifest.is_file():
        preserved["manifest.json"] = transaction.StagedFile(
            "manifest.json", manifest.read_bytes()
        )
    manifest_lock = manifest.parent / "manifest.json.lock"
    if manifest_lock.is_file():
        preserved["manifest.json.lock"] = transaction.StagedFile(
            "manifest.json.lock", manifest_lock.read_bytes()
        )
    for entry in entries:
        if "file" not in entry:
            continue
        configured = Path(os.path.normpath(str(root / str(entry["file"]))))
        try:
            relative = configured.relative_to(root)
            spaex_relative = relative.relative_to(transaction.SPAEX_DIR)
        except ValueError:
            continue
        relative_name = spaex_relative.as_posix()
        preserved[relative_name] = transaction.StagedFile(
            relative_name, configured.read_bytes()
        )
    return tuple(preserved.values())


def _read_live_lock(repo_root: Path) -> InstallLock | None:
    """Read the current lock for Spec Kit idempotence without blocking install."""
    path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
    if not path.exists():
        return None
    try:
        return InstallLock.from_json(path.read_bytes())
    except (OSError, ValueError, HaexError):
        return None


def _has_behavior_fragments(resolved: Sequence[ResolvedMolecule]) -> bool:
    """Return whether the resolved set can trigger behavior orchestration."""
    return any(
        record.molecule_manifest is not None
        and (
            bool(record.molecule_manifest.atoms.get("behavior"))
            or bool(record.molecule_manifest.constitution_fragments)
        )
        for record in resolved
    )


def _preserved_behavior_files(repo_root: Path) -> tuple[transaction.StagedFile, ...]:
    """Carry behavior inputs and outputs through the install directory swap.

    The behavior pipeline owns these files, but the install transaction also
    swaps the complete ``.spaex/`` directory while updating ``install.lock``.
    Preserve the current behavior tree so a lock-only update cannot erase the
    composed artifact, prompt override, clarifications, or stale marker before
    orchestration gets a chance to reconcile them.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    if not live_root.exists():
        return ()

    preserved_names = {
        transaction.CONSTITUTION_NAME,
        "clarifications.json",
        "composer-prompt.md",
        ".stale",
    }
    preserved: list[transaction.StagedFile] = []
    for path in live_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(live_root)
        if (
            relative.parts[0] != "constitution.d"
            and relative.as_posix() not in preserved_names
        ):
            continue
        preserved.append(
            transaction.StagedFile(relative.as_posix(), path.read_bytes())
        )
    return tuple(preserved)


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
    ``.spaex/manifest.json`` restore. A non-OK outcome under ``on_failure="warn"``
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


def _announce_stale_contradiction(marker: StaleMarker) -> None:
    """T054/FR-010a: surface a pending FR-024a stale marker at install start.

    The behavior pipeline below always re-invokes the Composer in this case
    (the fragment set changed since the marker was written, so the
    reproducibility fast-path in `orchestrate.run` cannot match), routing the
    same contradiction through the interactive reconciliation prompt (or an
    immediate refusal on a non-interactive terminal) before the composed
    Constitution is
    rewritten.
    """
    sys.stdout.write(
        "NOTE: a previous `spaex add`/`spaex remove` left the composed "
        f"constitution stale, unresolved (recorded {marker.detected_at}); "
        "re-running the Composer now to reconcile it:\n"
    )
    for question in marker.questions:
        provenance = ", ".join(
            f"{cited.get('molecule_id')}/{cited.get('fragment_id')}"
            for cited in question.cited_fragments
        )
        sys.stdout.write(f"  [{question.kind}] {question.question} ({provenance})\n")
    sys.stdout.flush()


def _run_behavior_pipeline(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: list[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment] = (),
    abort_on_contradiction: bool = True,
) -> behavior_orchestrate.BehaviorOutcome:
    """Spec 023 behavior-harness pass.

    Runs after the Spec 008 `.spaex/` rename-swap so behavior-authored
    files (`.spaex/constitution.d/`, `.spaex/constitution.md`, `.spaex/clarifications.json`)
    survive the swap. Fast-path exits when no molecule declares behavior
    fragments and no project-local fragment is configured (plan.md
    behavior-harness contract). Composer + emit failures surface as typed
    HaexError with exit codes 20-22 / 30-34.

    `abort_on_contradiction=False` (set only by the internal install that
    `spaex add`/`spaex remove` trigger via `write_and_reinstall`) requests
    the FR-024a add-time plausibility check: a Composer Shape B response
    prints a WARN and writes `.spaex/.stale` instead of aborting.
    """
    outcome = behavior_orchestrate.run(
        repo_root=repo_root,
        state_root=state_root,
        resolved=resolved,
        project_local=project_local,
        abort_on_contradiction=abort_on_contradiction,
    )
    if outcome.published and not outcome.skipped_composer:
        sys.stdout.write(
            f"composed .spaex/constitution.md ({outcome.fragment_count} fragment(s))\n"
        )
    elif outcome.skipped_composer:
        sys.stdout.write(
            f"reused .spaex/constitution.md ({outcome.fragment_count} fragment(s), "
            "source_hash/build_input_hash unchanged)\n"
        )
    elif outcome.removed_constitution:
        sys.stdout.write("removed .spaex/constitution.md (no active fragments)\n")
    elif outcome.stale:
        sys.stdout.write(
            f"add-time plausibility check found a cross-molecule "
            f"contradiction ({outcome.fragment_count} fragment(s)); "
            ".spaex/constitution.md left unchanged, marked stale (see .spaex/.stale)\n"
        )
    if outcome.published or outcome.skipped_composer:
        # T036: nudge the operator to run `spaex install --global` when no
        # runtime has the bootstrap block yet, so `.spaex/constitution.md` gets picked up.
        from spaex.cli import behavior_commands  # local import to avoid cycles

        behavior_commands.maybe_emit_no_bootstrap_hint()
    return outcome


def _behavior_publication_deferred(
    outcome: behavior_orchestrate.BehaviorOutcome,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment],
) -> bool:
    """Return whether an internal add/remove must retain the old generation."""
    if not project_local and not _has_behavior_fragments(resolved):
        return False
    return not (
        outcome.published or outcome.skipped_composer or outcome.removed_constitution
    )


def _read_stale_bytes(repo_root: Path) -> bytes | None:
    """Snapshot the add-time stale marker before rolling back the generation."""
    path = repo_root / transaction.SPAEX_DIR / STALE_FILENAME
    try:
        return path.read_bytes() if path.exists() else None
    except OSError:
        return None


def _hook_only_records(
    resolved: list[ResolvedMolecule],
    *,
    contributing_ids: set[str],
    hook_status: dict[str, HookStatus],
    speckit_records: Mapping[str, SpeckitLockRecord] | None = None,
) -> list[MoleculeEntry]:
    """Build install.lock records without a classic constitution contribution.

    Behavior molecules use the shared composed constitution as their
    publication path, so they are recorded alongside hook-only molecules
    during every successful install. A rejected or deferred Composer result
    is rolled back by the surrounding generation transaction, so it cannot
    replace the last valid published behavior generation. This keeps
    install.lock's molecule list useful for both the legacy
    ``atoms.constitution`` path and the canonical ``atoms.behavior`` path.
    Hook-only records still use ``paths=()``. Records only appear here for
    molecules whose hook reached a status, whose Spec Kit integration was
    selected, or which contributed behavior fragments.
    """
    speckit_records = speckit_records or {}
    records: list[MoleculeEntry] = []
    for record in resolved:
        if record.molecule_id in contributing_ids:
            continue
        has_behavior = _has_behavior_fragments((record,))
        has_hook_or_speckit = (
            record.install_hook is not None or record.molecule_id in speckit_records
        )
        has_recorded_hook_or_speckit = (
            record.molecule_id in hook_status or record.molecule_id in speckit_records
        )
        if not has_behavior and (
            not has_hook_or_speckit or not has_recorded_hook_or_speckit
        ):
            continue
        records.append(
            MoleculeEntry(
                id=record.molecule_id,
                source=record.source_url,
                revision=record.revision,
                paths=(CONSTITUTION_PATH,) if has_behavior else (),
                hook_status=hook_status.get(record.molecule_id),
                speckit=speckit_records.get(record.molecule_id),
            )
        )
    return records


def _generic_atom_paths_for_molecule(
    molecule_id: str,
    *,
    delivered_files: Sequence[DeliveredFile],
    composed_packages: ComposedFile | None,
) -> tuple[str, ...]:
    """Every Spec 027 generic-atom path `molecule_id` owns this generation.

    Used to fold the classic constitution contributor's own generic-atom
    paths into its dedicated `install.lock` entry (built separately by
    `publish_constitution`, not by `_augment_records_with_generic_atoms`).
    """
    paths = {file.path for file in delivered_files if file.owning_molecule_id == molecule_id}
    if composed_packages is not None and molecule_id in composed_packages.contributing_molecule_ids:
        paths.add(GENERATED_PACKAGES_PATH)
    return tuple(sorted(paths))


def _augment_records_with_generic_atoms(
    records: Sequence[MoleculeEntry],
    *,
    resolved: Sequence[ResolvedMolecule],
    delivered_files: Sequence[DeliveredFile],
    composed_packages: ComposedFile | None,
    exclude_ids: frozenset[str] = frozenset(),
) -> list[MoleculeEntry]:
    """Fold Spec 027 exclusive/composable generic-atom paths into install.lock.

    Extends whatever record ``_hook_only_records`` already built for each
    molecule with its exclusive-category paths, plus the shared
    composed-packages path for every one of its contributing molecules.
    Creates a fresh record for a molecule that contributes *only* generic
    atoms and therefore has no existing entry (no behavior fragments, no
    install_hook, no Spec Kit selection) — without this, such a molecule's
    delivered files would have nowhere to be recorded.

    ``exclude_ids`` (the legacy ``atoms.constitution`` contributor, built
    and appended separately by the caller) is never folded in nor given a
    fresh entry here, even if it also happens to declare a generic atom —
    avoiding a duplicate ``molecules[]`` entry for the same id. The caller
    instead folds that molecule's generic-atom paths into its own dedicated
    entry via ``_generic_atom_paths_for_molecule`` and
    ``publish_constitution``'s ``contributor_extra_paths``.
    """
    paths_by_molecule: dict[str, list[str]] = {}
    for file in delivered_files:
        if file.owning_molecule_id in exclude_ids:
            continue
        paths_by_molecule.setdefault(file.owning_molecule_id, []).append(file.path)
    composed_owner_ids = (
        set(composed_packages.contributing_molecule_ids) - exclude_ids
        if composed_packages is not None
        else set()
    )

    result: list[MoleculeEntry] = []
    seen: set[str] = set()
    for record in records:
        extra = tuple(paths_by_molecule.get(record.id, ()))
        if record.id in composed_owner_ids:
            extra = (*extra, GENERATED_PACKAGES_PATH)
        if extra:
            record = MoleculeEntry(
                id=record.id,
                source=record.source,
                revision=record.revision,
                paths=tuple(sorted(set(record.paths) | set(extra))),
                hook_status=record.hook_status,
                speckit=record.speckit,
            )
        result.append(record)
        seen.add(record.id)

    remaining_ids = (set(paths_by_molecule) | composed_owner_ids) - seen
    resolved_by_id = {rm.molecule_id: rm for rm in resolved}
    for molecule_id in sorted(remaining_ids):
        extra = tuple(paths_by_molecule.get(molecule_id, ()))
        if molecule_id in composed_owner_ids:
            extra = (*extra, GENERATED_PACKAGES_PATH)
        rm = resolved_by_id[molecule_id]
        result.append(
            MoleculeEntry(
                id=molecule_id,
                source=rm.source_url,
                revision=rm.revision,
                paths=tuple(sorted(extra)),
            )
        )
    return result
