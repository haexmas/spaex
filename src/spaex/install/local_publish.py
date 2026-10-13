"""Publication of local (per-developer) scope (Spec 029, ADR 0027).

Local scope publishes its own `.spaex` generation after any project
publication: every live project file is re-staged byte-for-byte and only
`.spaex/local/` is replaced, so the committed tree never changes. Planning,
validation and hooks live in `spaex.install.local_scope`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.orchestrate import record_declares_behavior
from spaex.constitution.publish import delete_orphaned_paths
from spaex.install import git_exclude
from spaex.install.generation import allocate_generation_id
from spaex.install.generic_atoms import (
    restore_delivered_targets,
    snapshot_delivered_targets,
    write_delivered_files,
)
from spaex.install.local_scope import (
    LOCAL_GENERATED_PACKAGES_PATH,
    LOCAL_PREAMBLE,
    LocalPlan,
    exclusion_paths,
)
from spaex.io import transaction
from spaex.model.install_lock import InstallLock
from spaex.paths import (
    LOCAL_CONSTITUTION_RELATIVE_PATH,
    LOCAL_DIRNAME,
    SPAEX_DIRNAME,
    local_dir,
)
from spaex.util.errors import HaexError

LOCAL_GITIGNORE = b"*\n"

# Files under `.spaex/local/` that every local publish writes fresh; every
# other file there (behavior outputs) is carried over verbatim.
_REGENERATED = frozenset({"manifest.json", ".gitignore", transaction.INSTALL_LOCK_NAME})


def preserved_files(repo_root: Path) -> tuple[transaction.StagedFile, ...]:
    """Carry `.spaex/local/**` verbatim through a project publication (Spec 029).

    A project publish never changes local scope; the local publish that may
    follow replaces these files itself.
    """
    live_root = repo_root / transaction.SPAEX_DIR
    local_root = local_dir(repo_root)
    if not local_root.is_dir():
        return ()
    return tuple(
        transaction.StagedFile(path.relative_to(live_root).as_posix(), path.read_bytes())
        for path in sorted(local_root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    )


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


def compose_local_behavior(
    *,
    repo_root: Path,
    state_root: Path,
    local_plan: LocalPlan,
    abort_on_contradiction: bool,
) -> None:
    """Spec 029: compose local behavior fragments into `.spaex/local/constitution.md`.

    The project constitution is never recomposed for local changes; the local
    document carries a preamble stating that project rules prevail.
    """
    outcome = behavior_orchestrate.run(
        repo_root=repo_root,
        state_root=state_root,
        resolved=list(local_plan.resolution.resolved),
        abort_on_contradiction=abort_on_contradiction,
        spaex_dir=local_dir(repo_root),
        preamble=LOCAL_PREAMBLE,
    )
    path = LOCAL_CONSTITUTION_RELATIVE_PATH
    if outcome.published and not outcome.skipped_composer:
        sys.stdout.write(f"composed {path} ({outcome.fragment_count} fragment(s))\n")
    elif outcome.skipped_composer:
        sys.stdout.write(f"reused {path} ({outcome.fragment_count} fragment(s))\n")
    elif outcome.stale:
        sys.stdout.write(
            f"local fragments contradict each other; {path} left unchanged, "
            "marked stale (see .spaex/local/.stale)\n"
        )
    if outcome.published or outcome.skipped_composer:
        from spaex.cli import behavior_commands  # local import to avoid cycles

        behavior_commands.maybe_emit_local_bootstrap_hint()
