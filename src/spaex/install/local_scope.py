"""Local (per-developer) molecule scope (Spec 029, ADR 0027).

Molecules adopted with `spaex add --local` are recorded in the uncommitted
overlay `.spaex/local/manifest.json` and installed on top of project scope.
Everything local scope writes stays out of git:

* files under `.spaex/local/` via the self-ignoring `.spaex/local/.gitignore`;
* repo-root files, hook- and Spec-Kit-created files via this worktree's block
  in git's `info/exclude` (`spaex.install.git_exclude`).

Project scope always wins: shadowed molecules contribute nothing, and local
writes to project-owned or git-tracked paths are refused before anything is
written. Local scope publishes its own `.spaex` generation that re-stages
every project file byte-for-byte, so a local-only change never rewrites the
committed `.spaex/install.lock` (research.md R2, R4).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from spaex.behavior.orchestrate import record_declares_behavior
from spaex.constitution.publish import CONSTITUTION_PATH, delete_orphaned_paths
from spaex.constitution.resolve import ResolvedMolecule, resolve_install_inputs
from spaex.install import git_exclude
from spaex.install.generation import allocate_generation_id
from spaex.install.generic_atoms import (
    DeliveredFile,
    collect_exclusive_atoms,
    content_hash,
    restore_delivered_targets,
    snapshot_delivered_targets,
    write_delivered_files,
)
from spaex.install.nix_packages import ComposedFile, collect_package_fragments, compose
from spaex.install.side_effects import RepoSideEffectGuard
from spaex.integrations.speckit import emit_results, prepare_install
from spaex.io import transaction
from spaex.model.consumer_manifest import ConsumerManifest, flatten_compound_pins
from spaex.model.install_lock import (
    HookStatus,
    InstallLock,
    MoleculeEntry,
    SpeckitLockRecord,
)
from spaex.model.local_manifest import LocalManifest
from spaex.paths import (
    LOCAL_CONSTITUTION_RELATIVE_PATH,
    LOCAL_DIRNAME,
    LOCAL_MANIFEST_RELATIVE_PATH,
    LOCAL_RELATIVE_DIR,
    SPAEX_DIRNAME,
    local_dir,
    local_lock_path,
    local_manifest_path,
)
from spaex.util.errors import (
    HaexError,
    LocalManifestInvalidError,
    LocalPathConflictError,
    SpeckitDeclarationConflictError,
)

LOCAL_GITIGNORE = b"*\n"
LOCAL_GENERATED_PACKAGES_PATH = f"{LOCAL_RELATIVE_DIR}/generated/nix-packages.json"
LOCAL_PREAMBLE = (
    "> These rules apply only to this checkout and only for this developer. "
    "They supplement `.spaex/constitution.md`; where they conflict, the project "
    "constitution prevails.\n"
)
HOOK_WARNING = (
    "warning: {molecule_id} runs an install hook; repository side effects are checked, "
    "but files written outside the repository are not covered by local-scope exclusions\n"
)

# Files under `.spaex/local/` that every local publish writes fresh; every
# other file there (behavior outputs) is carried over verbatim.
_REGENERATED = frozenset({"manifest.json", ".gitignore", transaction.INSTALL_LOCK_NAME})

RunHooks = Callable[..., dict[str, HookStatus]]


def load_overlay(repo_root: Path) -> LocalManifest | None:
    """Read the local overlay; `None` when this checkout has none."""
    path = local_manifest_path(repo_root)
    if not path.is_file():
        return None
    try:
        return LocalManifest.from_json(path.read_bytes())
    except (ValueError, KeyError) as exc:
        raise LocalManifestInvalidError(
            message=f"{LOCAL_MANIFEST_RELATIVE_PATH} is not a valid local manifest: {exc}",
            context={"path": LOCAL_MANIFEST_RELATIVE_PATH},
        ) from exc


def read_local_lock(repo_root: Path) -> InstallLock | None:
    """Read the local install record, treating a corrupt one as absent."""
    path = local_lock_path(repo_root)
    if not path.is_file():
        return None
    try:
        return InstallLock.from_json(path.read_bytes())
    except (OSError, ValueError, HaexError):
        return None


def is_active(repo_root: Path) -> bool:
    """Whether this checkout has, or had, local scope (filesystem check only)."""
    return local_dir(repo_root).exists()


def exclusion_paths(lock: InstallLock | None) -> tuple[str, ...]:
    """Repo paths a local lock records outside `.spaex/` (those need `info/exclude`)."""
    if lock is None:
        return ()
    return tuple(
        sorted(
            {
                path
                for molecule in lock.molecules
                for path in molecule.paths
                if path.split("/", 1)[0] != SPAEX_DIRNAME
            }
        )
    )


def reconcile_exclusions(repo_root: Path) -> None:
    """Re-derive this worktree's exclusion block from the published local lock.

    Repairs a crash between the `.spaex` swap and the exclude-file rename.
    """
    if is_active(repo_root):
        git_exclude.reconcile(repo_root, exclusion_paths(read_local_lock(repo_root)))


@dataclass(frozen=True)
class LocalResolution:
    resolved: tuple[ResolvedMolecule, ...] = ()
    shadowed: tuple[str, ...] = ()


def resolve(
    manifest: ConsumerManifest, overlay: LocalManifest | None, state_root: Path
) -> LocalResolution:
    """Resolve overlay molecules, dropping those project scope already adopts."""
    if overlay is None or not overlay.compounds:
        return LocalResolution()
    project_ids = set(flatten_compound_pins(manifest))
    contributions, resolved = resolve_install_inputs(
        overlay.as_consumer_manifest(manifest.identity), state_root
    )
    legacy = sorted({c.source.id for c in contributions} - project_ids)
    if legacy:
        raise LocalPathConflictError(
            message=(
                f"local scope cannot adopt {', '.join(legacy)}: legacy `atoms.constitution` "
                f"writes the project-owned {CONSTITUTION_PATH}"
            ),
            context={"molecules": ",".join(legacy)},
        )
    return LocalResolution(
        resolved=tuple(r for r in resolved if r.molecule_id not in project_ids),
        shadowed=tuple(sorted({r.molecule_id for r in resolved} & project_ids)),
    )


def tracked_paths(repo_root: Path, paths: Iterable[str]) -> frozenset[str]:
    """The subset of `paths` git tracks; empty outside a git repository."""
    candidates = sorted(set(paths))
    if not candidates:
        return frozenset()
    proc = subprocess.run(
        ["git", "--literal-pathspecs", "-C", str(repo_root), "ls-files", "-z", "--", *candidates],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return frozenset()
    return frozenset(token.decode("utf-8") for token in proc.stdout.split(b"\0") if token)


def _declares_speckit(resolved: Sequence[ResolvedMolecule]) -> tuple[str, ...]:
    return tuple(
        r.molecule_id
        for r in resolved
        if r.molecule_manifest is not None and r.molecule_manifest.speckit is not None
    )


def preflight(
    repo_root: Path,
    *,
    local: Sequence[ResolvedMolecule],
    project: Sequence[ResolvedMolecule],
    project_owned: Iterable[str],
) -> tuple[DeliveredFile, ...]:
    """Refuse every local write that would change team-owned state (FR-006, FR-013)."""
    project_speckit, local_speckit = _declares_speckit(project), _declares_speckit(local)
    if project_speckit and local_speckit:
        raise SpeckitDeclarationConflictError(
            message=(
                "Spec Kit is already declared in project scope; local molecule(s) "
                f"{', '.join(local_speckit)} cannot declare a second Spec Kit policy"
            ),
            context={"molecules": ",".join((*project_speckit, *local_speckit))},
        )
    delivered = tuple(collect_exclusive_atoms(list(local), repo_root=repo_root))
    owned = set(project_owned)
    conflicts = {
        f.path: (f.owning_molecule_id, "project-owned") for f in delivered if f.path in owned
    }
    unowned = [f for f in delivered if f.path not in conflicts]
    for path in tracked_paths(repo_root, (f.path for f in unowned)):
        owner = next(f.owning_molecule_id for f in unowned if f.path == path)
        conflicts[path] = (owner, "tracked by git")
    if conflicts:
        details = ", ".join(
            f"{path} ({why}; from {owner})" for path, (owner, why) in sorted(conflicts.items())
        )
        raise LocalPathConflictError(
            message=f"local scope would overwrite {details}",
            context={"paths": ",".join(sorted(conflicts))},
        )
    return delivered


@dataclass(frozen=True)
class LocalPlan:
    """Everything one install will publish for local scope."""

    active: bool = False
    overlay_bytes: bytes | None = None
    resolution: LocalResolution = field(default_factory=LocalResolution)
    records: tuple[MoleculeEntry, ...] = ()
    content_hashes: Mapping[str, str] = field(default_factory=dict)
    delivered: tuple[DeliveredFile, ...] = ()
    packages: ComposedFile | None = None
    previous_lock: InstallLock | None = None
    on_disk_packages: bytes | None = None
    delivered_on_disk: bool = False

    @property
    def packages_bytes(self) -> bytes | None:
        return self.packages.to_json_bytes() if self.packages is not None else None

    @property
    def is_no_op(self) -> bool:
        """True when publishing would not change any local file."""
        if not self.active:
            return True
        if self.overlay_bytes is None:
            # Local scope was emptied (or never completed): publish its removal.
            return False
        previous = self.previous_lock
        return (
            previous is not None
            and previous.molecules == self.records
            and dict(previous.content_hashes) == dict(self.content_hashes)
            and self.packages_bytes == self.on_disk_packages
            and self.delivered_on_disk
        )


def prepare(
    repo_root: Path,
    *,
    manifest: ConsumerManifest,
    state_root: Path,
    project_resolved: Sequence[ResolvedMolecule],
    project_delivered: Sequence[DeliveredFile],
    project_lock: InstallLock | None,
    run_hooks: RunHooks,
    skip_hooks: bool,
    speckit_selection: str | None,
    speckit_disabled: bool,
) -> LocalPlan:
    """Validate, run local hooks and Spec Kit, and assemble the local publication.

    Runs before any project publication, so every refusal leaves the
    checkout untouched.
    """
    if not is_active(repo_root):
        return LocalPlan()
    overlay = load_overlay(repo_root)
    previous = read_local_lock(repo_root)
    resolution = resolve(manifest, overlay, state_root)
    for molecule_id in resolution.shadowed:
        sys.stdout.write(
            f"shadowed: {molecule_id} (adopted in project scope; local entry ignored, "
            f"run 'spaex remove --local {molecule_id}')\n"
        )
    local = resolution.resolved
    project_owned = {
        *(path for m in (project_lock.molecules if project_lock else ()) for path in m.paths),
        *(f.path for f in project_delivered),
    }
    delivered = preflight(
        repo_root, local=local, project=project_resolved, project_owned=project_owned
    )
    packages = compose(collect_package_fragments(list(local)))

    protected = sorted(p for p in project_owned if p.split("/", 1)[0] != SPAEX_DIRNAME)
    guards: list[tuple[str, RepoSideEffectGuard]] = []

    def observe(record: ResolvedMolecule) -> AbstractContextManager[RepoSideEffectGuard]:
        guard = RepoSideEffectGuard(
            repo_root, actor=f"local install hook of {record.molecule_id}", protected=protected
        )
        guards.append((record.molecule_id, guard))
        return guard

    hook_status = run_hooks(
        list(local),
        repo_root=repo_root,
        state_root=state_root,
        skip_hooks=skip_hooks,
        scope="local",
        observe=observe,
    )
    speckit: Mapping[str, SpeckitLockRecord] = {}
    speckit_ids = _declares_speckit(local)
    if speckit_ids:
        with RepoSideEffectGuard(repo_root, actor="local Spec Kit", protected=protected) as guard:
            records = prepare_install(
                list(local),
                repo_root=repo_root,
                existing_lock=previous,
                explicit_selection=speckit_selection,
                disabled=speckit_disabled,
            )
        emit_results(records)
        speckit = records.publication_records
        guards.append((speckit_ids[0], guard))
    created: dict[str, set[str]] = {}
    for molecule_id, guard in guards:
        created.setdefault(molecule_id, set()).update(guard.created)

    entries, hashes = _build_records(
        repo_root,
        local=local,
        delivered=delivered,
        packages=packages,
        hook_status=hook_status,
        speckit=speckit,
        created=created,
        previous=previous,
    )
    generated = repo_root / LOCAL_GENERATED_PACKAGES_PATH
    return LocalPlan(
        active=True,
        overlay_bytes=(
            local_manifest_path(repo_root).read_bytes()
            if overlay is not None and overlay.compounds
            else None
        ),
        resolution=resolution,
        records=entries,
        content_hashes=hashes,
        delivered=delivered,
        packages=packages,
        previous_lock=previous,
        on_disk_packages=generated.read_bytes() if generated.is_file() else None,
        # A crash after the swap but before root files were written leaves the
        # lock current and the files missing; rewrite them on the next install.
        delivered_on_disk=all(
            (repo_root / f.path).is_file() and (repo_root / f.path).read_bytes() == f.content
            for f in delivered
        ),
    )


def _build_records(
    repo_root: Path,
    *,
    local: Sequence[ResolvedMolecule],
    delivered: Sequence[DeliveredFile],
    packages: ComposedFile | None,
    hook_status: Mapping[str, HookStatus],
    speckit: Mapping[str, SpeckitLockRecord],
    created: Mapping[str, set[str]],
    previous: InstallLock | None,
) -> tuple[tuple[MoleculeEntry, ...], dict[str, str]]:
    """One lock entry per local molecule plus content hashes for every root file.

    Files a hook or Spec Kit created in an earlier install are carried over
    while they still exist, so they stay excluded and are deleted on removal.
    """
    hashes = {f.path: content_hash(f.content) for f in delivered}
    previous_paths = {
        m.id: m.paths for m in (previous.molecules if previous is not None else ())
    }
    previous_hashes = dict(previous.content_hashes) if previous is not None else {}
    entries: list[MoleculeEntry] = []
    for record in local:
        planned = {f.path for f in delivered if f.owning_molecule_id == record.molecule_id}
        if record_declares_behavior(record):
            planned.add(LOCAL_CONSTITUTION_RELATIVE_PATH)
        if packages is not None and record.molecule_id in packages.contributing_molecule_ids:
            planned.add(LOCAL_GENERATED_PACKAGES_PATH)
        carried = {
            path
            for path in previous_paths.get(record.molecule_id, ())
            if path.split("/", 1)[0] != SPAEX_DIRNAME
            and path not in planned
            and (repo_root / path).is_file()
        }
        fresh = created.get(record.molecule_id, set()) - planned
        for path in carried:
            if path in previous_hashes:
                hashes[path] = previous_hashes[path]
        for path in fresh - carried:
            hashes[path] = content_hash((repo_root / path).read_bytes())
        entries.append(
            MoleculeEntry(
                id=record.molecule_id,
                source=record.source_url,
                revision=record.revision,
                paths=tuple(sorted(planned | carried | fresh)),
                hook_status=hook_status.get(record.molecule_id),
                speckit=speckit.get(record.molecule_id),
            )
        )
    entries.sort(key=lambda m: (m.id, m.source, m.revision, m.paths))
    return tuple(entries), hashes


def _project_paths(live: Path) -> frozenset[str]:
    """Paths the published project lock owns; local orphan cleanup must keep them."""
    path = live / transaction.INSTALL_LOCK_NAME
    if not path.is_file():
        return frozenset()
    lock = InstallLock.from_json(path.read_bytes())
    return frozenset(p for molecule in lock.molecules for p in molecule.paths)


def publish(repo_root: Path, plan: LocalPlan, *, state_root: Path) -> None:
    """Publish local scope as its own `.spaex` generation.

    Every live project file is re-staged byte-for-byte, so the committed tree
    is unchanged. Root files are written, orphans deleted and the exclusion
    block reconciled inside `post_write_verify`: a failure there restores the
    root files and rolls the whole generation back.
    """
    live = repo_root / transaction.SPAEX_DIR
    staged = [
        transaction.StagedFile(path.relative_to(live).as_posix(), path.read_bytes())
        for path in sorted(live.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and path.relative_to(live).parts[0] != LOCAL_DIRNAME
    ]
    new_lock: InstallLock | None = None
    # Kept while the overlay lists anything, even when every entry is shadowed:
    # spaex never drops the developer's adoption record on its own (R9).
    if plan.overlay_bytes is not None:
        existing = live / LOCAL_DIRNAME
        # Carried-over files are behavior outputs; drop them once no local
        # molecule declares behavior any more.
        if existing.is_dir() and any(map(record_declares_behavior, plan.resolution.resolved)):
            for path in sorted(existing.rglob("*")):
                relative = path.relative_to(existing)
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and relative.as_posix() not in _REGENERATED
                    and relative.parts[0] != "generated"
                ):
                    staged.append(
                        transaction.StagedFile(
                            f"{LOCAL_DIRNAME}/{relative.as_posix()}", path.read_bytes()
                        )
                    )
        previous_id = plan.previous_lock.generation_id if plan.previous_lock else None
        new_lock = InstallLock(
            spaex_version="4",
            generation_id=allocate_generation_id(plan.overlay_bytes, previous_id),
            molecules=plan.records,
            content_hashes=dict(plan.content_hashes),
        )
        staged += [
            transaction.StagedFile(f"{LOCAL_DIRNAME}/manifest.json", plan.overlay_bytes),
            transaction.StagedFile(f"{LOCAL_DIRNAME}/.gitignore", LOCAL_GITIGNORE),
            transaction.StagedFile(
                f"{LOCAL_DIRNAME}/{transaction.INSTALL_LOCK_NAME}", new_lock.to_json_bytes()
            ),
        ]
        if plan.packages_bytes is not None:
            staged.append(
                transaction.StagedFile(
                    LOCAL_GENERATED_PACKAGES_PATH.removeprefix(f"{SPAEX_DIRNAME}/"),
                    plan.packages_bytes,
                )
            )
    empty_lock = InstallLock(
        spaex_version="4", generation_id="g_19700101T000000Z_0000", molecules=()
    )

    def post_write_verify() -> None:
        snapshot = snapshot_delivered_targets(plan.delivered, repo_root=repo_root)
        try:
            write_delivered_files(plan.delivered, repo_root=repo_root)
            delete_orphaned_paths(
                repo_root,
                plan.previous_lock,
                new_lock or empty_lock,
                keep=_project_paths(live),
            )
            git_exclude.reconcile(repo_root, exclusion_paths(new_lock))
        except (OSError, HaexError):
            restore_delivered_targets(snapshot)
            raise

    transaction.publish_generation(
        live,
        staged,
        post_write_verify=post_write_verify,
        state_root=state_root,
        repo_root=repo_root,
    )
