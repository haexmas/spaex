"""Atomic manifest write + in-process install with rollback — Spec 013 T072.

Runs under a caller-held ``ManifestLockContext``:

1. Snapshot the current `.spaex.json` bytes (or record its absence).
2. Write the new manifest via ``.spaex.json.tmp`` + rename.
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

from spaex.install.manifest_lock import MANIFEST_NAME, ManifestLockContext
from spaex.io import atomic
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
) -> int:
    """Publish the mutated manifest and delegate to ``haex install`` in-process."""
    from spaex.cli import install as install_cli

    manifest_path = repo_root / MANIFEST_NAME
    previous_bytes: bytes | None = (
        manifest_path.read_bytes() if manifest_path.exists() else None
    )

    try:
        atomic.write_replace(manifest_path, new_manifest_bytes)
        return install_cli.run(
            argparse.Namespace(repo_root=str(repo_root)),
            held_manifest_lock=held_manifest_lock,
        )
    except BaseException as exc:
        try:
            if previous_bytes is None:
                _atomic_delete(manifest_path)
            else:
                atomic.write_replace(manifest_path, previous_bytes)
        except OSError as rollback_exc:
            raise ManifestRollbackFailedError(
                message=(
                    "manifest rollback failed after install failure: "
                    f"{rollback_exc}"
                ),
                context={"manifest_path": str(manifest_path)},
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
