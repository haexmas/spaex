"""Atomic manifest write + in-process install with rollback — Spec 013 T072.

Runs under a caller-held ``ManifestLockContext``:

1. Snapshot the active manifest bytes (or record its absence).
2. Write the new manifest via an in-directory temporary file + rename.
3. Call ``haex install`` in-process with the same lock context held.
4. On ANY install failure, restore the previous manifest bytes atomically
   and re-raise as ``InstallTransactionFailedError``.

A rollback failure surfaces as ``ManifestRollbackFailedError`` with a
recovery-path hint; the lock stays held (the context manager releases it
on caller exit).

Spec 013 has NO post-install ``constitution-review-pending`` exception per
the 2026-09-04 clarification: any install failure rolls back the edit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from spaex.install.manifest_lock import ManifestLockContext
from spaex.io import atomic
from spaex.paths import manifest_path
from spaex.util.errors import (
    HaexError,
    InstallTransactionFailedError,
    ManifestRollbackFailedError,
)


def _atomic_delete(target: Path) -> None:
    if target.exists():
        target.unlink()


def write_and_reinstall(
    repo_root: Path,
    new_manifest_bytes: bytes,
    held_manifest_lock: ManifestLockContext,
    *,
    skip_hooks: bool = False,
    abort_on_behavior_contradiction: bool = True,
) -> int:
    """Publish the mutated manifest and delegate to ``haex install`` in-process.

    ``abort_on_behavior_contradiction=False`` (passed by `spaex add`/`spaex
    remove`, Spec 023 FR-024a) requests the add-time plausibility check: a
    Composer cross-molecule semantic contradiction warns and marks
    `.spaex/.stale` instead of aborting the install this call triggers.
    """
    from spaex.cli import install as install_cli

    manifest_target = manifest_path(repo_root)
    previous_bytes: bytes | None = (
        manifest_target.read_bytes() if manifest_target.exists() else None
    )

    try:
        atomic.write_replace(manifest_target, new_manifest_bytes)
        return install_cli.run(
            argparse.Namespace(
                repo_root=str(repo_root),
                skip_hooks=skip_hooks,
                abort_on_behavior_contradiction=abort_on_behavior_contradiction,
            ),
            held_manifest_lock=held_manifest_lock,
        )
    except BaseException as exc:
        try:
            if previous_bytes is None:
                _atomic_delete(manifest_target)
            else:
                atomic.write_replace(manifest_target, previous_bytes)
        except OSError as rollback_exc:
            raise ManifestRollbackFailedError(
                message=(
                    "manifest rollback failed after install failure: "
                    f"{rollback_exc}"
                ),
                context={"manifest_path": str(manifest_target)},
            ) from rollback_exc
        if not isinstance(exc, HaexError):
            raise
        raise InstallTransactionFailedError(
            message=f"`haex install` failed after manifest edit: {exc.message}",
            context={
                "install_key": exc.diagnostic_key,
                "install_exit_code": str(exc.exit_code),
            },
        ) from exc
