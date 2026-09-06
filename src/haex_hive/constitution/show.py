"""Constitution show (US4): read-only, integrity-verified inspection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO

from haex_hive.constitution.publish import CONSTITUTION_PATH
from haex_hive.io import transaction
from haex_hive.model.install_lock import InstallLock, MoleculeEntry
from haex_hive.util.errors import (
    ConstitutionNotAssembledError,
    InstallLockMissingError,
)


def _constitution_molecules(lock: InstallLock) -> tuple[MoleculeEntry, ...]:
    """Molecules whose contribution includes the published constitution file.

    Constitution provenance is derived from `molecules[]` rather than
    tracked in a separate lock section (2026-09-03 install.lock amendment).
    """
    return tuple(molecule for molecule in lock.molecules if CONSTITUTION_PATH in molecule.paths)


def _render_preface(molecules: tuple[MoleculeEntry, ...]) -> bytes:
    lines = "".join(f"- {m.id} @ {m.revision[:7]} ({m.source})\n" for m in molecules)
    return f"# Assembled from\n{lines}\n---\n\n".encode()


def show(
    repo_root: Path,
    *,
    no_preface: bool,
    out: BinaryIO | None = None,
    state_root: Path | None = None,
) -> None:
    """Render the currently published constitution without modifying state."""
    hive_dir = repo_root / transaction.HAEX_HIVE_DIR
    del state_root  # show is read-only; stale-sibling cleanup is a writer concern.

    constitution_path = hive_dir / transaction.CONSTITUTION_NAME
    if not constitution_path.exists():
        raise ConstitutionNotAssembledError(
            message=".haex-hive/constitution.md does not exist",
        )

    lock_path = hive_dir / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        raise InstallLockMissingError(
            message=".haex-hive/install.lock does not exist",
        )

    lock = InstallLock.from_json(lock_path.read_bytes())
    constitution_molecules = _constitution_molecules(lock)
    if not constitution_molecules:
        raise InstallLockMissingError(
            message="install.lock has no constitution-contributing molecule",
        )

    body = constitution_path.read_bytes()

    stream = out if out is not None else sys.stdout.buffer
    if not no_preface:
        stream.write(_render_preface(constitution_molecules))
    stream.write(body)
