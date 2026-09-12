"""Paths for the device-local publisher clone cache."""

from __future__ import annotations

import hashlib
from pathlib import Path


def clone_dir(state_root: Path, canonical_source: str) -> Path:
    """Return the device-local clone directory for a source URL."""
    digest = hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()[:16]
    return state_root / "repos" / digest


__all__ = ["clone_dir"]
