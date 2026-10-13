"""Constitution show (US4): read-only, integrity-verified inspection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO

from spaex.constitution.publish import CONSTITUTION_PATH
from spaex.io import transaction
from spaex.model.install_lock import InstallLock, MoleculeEntry
from spaex.paths import local_constitution_path
from spaex.util.errors import (
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


LOCAL_SECTION_HEADING = b"## Local (this checkout only)\n\n"


def show(
    repo_root: Path,
    *,
    no_preface: bool,
    out: BinaryIO | None = None,
    state_root: Path | None = None,
) -> None:
    """Render the currently published constitution without modifying state.

    Spec 029: the checkout's local behavior document follows under its own
    heading when present.
    """
    hive_dir = repo_root / transaction.SPAEX_DIR
    del state_root  # show is read-only; stale-sibling cleanup is a writer concern.

    constitution_path = hive_dir / transaction.CONSTITUTION_NAME
    local_path = local_constitution_path(repo_root)
    stream = out if out is not None else sys.stdout.buffer
    if not constitution_path.exists():
        if local_path.exists():
            stream.write(LOCAL_SECTION_HEADING + local_path.read_bytes())
            return
        raise ConstitutionNotAssembledError(
            message=".spaex/constitution.md does not exist",
        )

    lock_path = hive_dir / transaction.INSTALL_LOCK_NAME
    if not lock_path.exists():
        raise InstallLockMissingError(
            message=".spaex/install.lock does not exist",
        )

    lock = InstallLock.from_json(lock_path.read_bytes())
    constitution_molecules = _constitution_molecules(lock)
    body = constitution_path.read_bytes()

    if not no_preface:
        stream.write(_render_preface(constitution_molecules))
    stream.write(body)
    if local_path.exists():
        stream.write(b"\n" + LOCAL_SECTION_HEADING + local_path.read_bytes())
