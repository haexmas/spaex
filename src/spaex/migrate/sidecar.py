"""Sidecar publication for `haex migrate` (FR-014-FR-016).

Under Spec 014 the target v4 filename is ``.spaex.json``, so the consumer
sidecar becomes ``.spaex.json.migrated``. The legacy ``.haex-hive.json.migrated``
name is invalidated defensively so a stale sidecar from a prior v2/v3 run
does not shadow the fresh v4 proposal.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from spaex.io import atomic

SIDECAR_SUFFIX = ".migrated"


def sidecar_path(repo_root: Path) -> Path:
    """Return the current consumer sidecar path (v4 target: .spaex.json.migrated)."""
    return repo_root / (".spaex.json" + SIDECAR_SUFFIX)


def legacy_sidecar_path(repo_root: Path) -> Path:
    return repo_root / (".haex-hive.json" + SIDECAR_SUFFIX)


def invalidate_stale_sidecar(repo_root: Path) -> None:
    for candidate in (sidecar_path(repo_root), legacy_sidecar_path(repo_root)):
        with suppress(FileNotFoundError):
            candidate.unlink()


def publish_sidecar(repo_root: Path, proposal_bytes: bytes) -> None:
    atomic.write_replace(sidecar_path(repo_root), proposal_bytes)
